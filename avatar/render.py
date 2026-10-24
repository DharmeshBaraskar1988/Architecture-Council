"""Talking-head videos for the council room: MuseTalk 1.5 lip-syncs each spoken line onto its member's portrait.

    avatar\\.venv\\Scripts\\python.exe avatar\\render.py work            # render queued sessions until the queue is empty
    avatar\\.venv\\Scripts\\python.exe avatar\\render.py test critic "Hello, I disagree with this design."

The room queues a session by writing data/avatars/queue/<run id>.json: [{"speaker", "voice", "text"}, ...].
Each line's audio is the room's own Edge TTS clip (data/tts/<sha1(voice\\ntext)>.mp3, made here if missing), and
its video is data/avatars/clips/<same sha1>.mp4: silent, 256x256, played in step with that audio. Progress for a
run is in data/avatars/status/<run id>.json. One renderer at a time (data/avatars/render.pid).

Each member is prepared once from avatar/portraits/<member>.png: a short idle loop (slight breathing and head
movement, so the face is not frozen), face box, latents and blending masks, cached in data/avatars/faces/<member>/.
"""
import asyncio
import hashlib
import json
import os
import pickle
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MUSETALK = HERE / "MuseTalk"
DATA = HERE.parent / "data"
TTS = DATA / "tts"
OUT = DATA / "avatars"
CLIPS, QUEUE, STATUS, FACES = OUT / "clips", OUT / "queue", OUT / "status", OUT / "faces"
PORTRAITS = HERE / "portraits"
PIDFILE = OUT / "render.pid"
VOICES = HERE.parent / "frontend" / "lib" / "voices.json"     # who speaks with which Edge voice (shared with the room)

FPS = 25
IDLE_FRAMES = 40          # one way; MuseTalk plays the loop forwards then backwards
BATCH = 8                 # frames per lip-sync batch; fits a 4 GB card in half precision
DECODE_CHUNK = 2          # frames per VAE decode: bigger chunks overflow a 4 GB card and run ~3x slower
DECODER = os.environ.get("COUNCIL_AVATAR_DECODER", "sd-vae")   # "taesd": tiny decoder, ~5x faster, a little softer
SIZE = 256                # output video size; the room shows it at most ~130 px


def clip_id(voice: str, text: str) -> str:
    """Same key as frontend/app/api/tts/route.ts, so the room's audio and these videos match."""
    return hashlib.sha1(f"{voice}\n{text}".encode("utf-8")).hexdigest()


def alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    except OSError:
        return False


def make_audio(voice: str, text: str, mp3: Path, tries: int = 3) -> None:
    """The line's Edge TTS clip. Times out instead of hanging when the connection drops."""
    import edge_tts

    TTS.mkdir(parents=True, exist_ok=True)
    tmp = mp3.with_suffix(f".{os.getpid()}.part")
    for attempt in range(1, tries + 1):
        try:
            asyncio.run(asyncio.wait_for(edge_tts.Communicate(text, voice).save(str(tmp)), timeout=60))
            os.replace(tmp, mp3)
            return
        except Exception:
            tmp.unlink(missing_ok=True)
            if attempt == tries:
                raise
            time.sleep(5 * attempt)


def take_lock() -> bool:
    """One renderer at a time: create render.pid atomically; take over only from a process that is gone."""
    for _ in range(2):
        try:
            fd = os.open(PIDFILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if alive(int(PIDFILE.read_text() or 0)):
                    return False
            except (OSError, ValueError):
                pass
            PIDFILE.unlink(missing_ok=True)                   # stale: its renderer has exited
    return False


class Renderer:
    def __init__(self):
        os.chdir(MUSETALK)                                   # MuseTalk loads its weights from ./models
        sys.path.insert(0, str(MUSETALK))
        import torch
        from transformers import WhisperModel
        from musetalk.utils.audio_processor import AudioProcessor
        from diffusers import UNet2DConditionModel
        from musetalk.models.unet import PositionalEncoding
        from musetalk.models.vae import VAE

        self.torch = torch
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        # MuseTalk's own loader puts the 3.4 GB UNet on the GPU in full precision before halving it, which does not
        # fit a 4 GB card (Windows then swaps video memory and it crawls). Load to RAM, halve, then move: ~1.7 GB.
        config = json.loads(Path("models", "musetalkV15", "musetalk.json").read_text("utf-8"))
        unet = UNet2DConditionModel(**config)
        unet.load_state_dict(torch.load(Path("models", "musetalkV15", "unet.pth"), map_location="cpu"))
        self.unet = type("Unet", (), {})()
        self.unet.model = unet.half().to(self.device).eval()
        self.vae = VAE(model_path=str(Path("models", "sd-vae")), use_float16=True)
        self.pe = PositionalEncoding(d_model=384).half().to(self.device)
        self.tiny = None
        if DECODER == "taesd":                               # madebyollin/taesd, MIT
            from diffusers import AutoencoderTiny
            self.tiny = AutoencoderTiny.from_pretrained("madebyollin/taesd", torch_dtype=torch.float16).to(self.device).eval()
        self.timesteps = torch.tensor([0], device=self.device)
        self.audio = AudioProcessor(feature_extractor_path="models/whisper")
        self.whisper = WhisperModel.from_pretrained("models/whisper").to(device=self.device, dtype=self.unet.model.dtype).eval()
        self.whisper.requires_grad_(False)
        self.faces: dict[str, dict] = {}

    # ---------- members ----------
    def face(self, who: str) -> dict:
        """The member's prepared face; prepared in a separate process the first time (see prepare_face)."""
        if who in self.faces:
            return self.faces[who]
        cache = face_cache(who)
        if not cache.exists():
            done = subprocess.run([sys.executable, str(HERE / "render.py"), "prepare", who], cwd=HERE)
            if done.returncode != 0 or not cache.exists():
                raise RuntimeError(f"could not prepare the face of {who}")
        data = pickle.loads(cache.read_bytes())
        data["latents"] = [l.to(self.device) for l in data["latents"]]
        self.faces[who] = data
        return data

    # ---------- one line ----------
    def render(self, who: str, mp3: Path, mp4: Path) -> float:
        import cv2
        import numpy as np
        from musetalk.utils.blending import get_image_blending
        from musetalk.utils.utils import datagen

        torch, face = self.torch, self.face(who)
        start = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp, "a.wav")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-ar", "16000", "-ac", "1", str(wav)], check=True)
            dtype = self.unet.model.dtype
            feats, length = self.audio.get_audio_feature(str(wav), weight_dtype=dtype)
            chunks = self.audio.get_whisper_chunk(feats, self.device, dtype, self.whisper, length, fps=FPS,
                                                  audio_padding_length_left=2, audio_padding_length_right=2)
        part = mp4.with_suffix(".part.mp4")
        enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{SIZE}x{SIZE}",
                                "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(part)], stdin=subprocess.PIPE)
        n = len(face["frames"])
        i = 0
        with torch.no_grad():
            for whisper_batch, latent_batch in datagen(chunks, face["latents"], BATCH, device=self.device):
                audio_feats = self.pe(whisper_batch.to(self.device))
                latent_batch = latent_batch.to(device=self.device, dtype=dtype)
                pred = self.unet.model(latent_batch, self.timesteps, encoder_hidden_states=audio_feats).sample
                for res in self.decode(pred):
                    x1, y1, x2, y2 = face["boxes"][i % n]
                    res = cv2.resize(res.astype(np.uint8), (x2 - x1, y2 - y1))
                    frame = get_image_blending(face["frames"][i % n].copy(), res, [x1, y1, x2, y2],
                                               face["masks"][i % n], face["mask_boxes"][i % n])
                    enc.stdin.write(cv2.resize(frame, (SIZE, SIZE), interpolation=cv2.INTER_AREA).tobytes())
                    i += 1
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("ffmpeg could not write the video")
        os.replace(part, mp4)
        return time.time() - start

    def decode(self, latents):
        """Latents to BGR uint8 frames, a few at a time (see DECODE_CHUNK)."""
        import numpy as np
        torch, out = self.torch, []
        for k in range(0, len(latents), DECODE_CHUNK):
            z = latents[k:k + DECODE_CHUNK]
            if self.tiny is not None:
                img = self.tiny.decode(z.to(self.tiny.dtype)).sample
            else:
                img = self.vae.vae.decode((z / self.vae.scaling_factor).to(self.vae.vae.dtype)).sample
            img = (img / 2 + 0.5).clamp(0, 1).permute(0, 2, 3, 1).float().cpu().numpy()
            out.extend((img * 255).round().astype(np.uint8)[..., ::-1])
        return out

    # ---------- the queue ----------
    def work(self) -> None:
        while True:
            jobs = sorted(QUEUE.glob("*.json"), key=lambda p: p.stat().st_mtime)
            if not jobs:
                return
            job = jobs[0]
            run = job.stem
            try:
                lines = json.loads(job.read_text("utf-8"))
            except (OSError, ValueError):
                job.unlink(missing_ok=True)
                continue
            status = {"total": len(lines), "done": 0, "failed": 0, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "errors": []}
            for line in lines:
                key = clip_id(line["voice"], line["text"])
                mp4 = CLIPS / f"{key}.mp4"
                try:
                    if not mp4.exists():
                        mp3 = TTS / f"{key}.mp3"
                        if not mp3.exists():
                            make_audio(line["voice"], line["text"], mp3)
                        took = self.render(line["speaker"], mp3, mp4)
                        print(f"{run} {status['done'] + status['failed'] + 1}/{len(lines)} {line['speaker']} {took:.1f}s", flush=True)
                    status["done"] += 1
                except Exception as e:                                # one bad line must not stop the session
                    status["failed"] += 1
                    status["errors"] = (status["errors"] + [f"{line['speaker']}: {e}"])[-5:]
                    print(f"{run} failed {line['speaker']}: {e}", flush=True)
                write_status(run, status)
            status["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            write_status(run, status)
            # a newer manifest for the same run (more lines) replaces this one; only remove what was rendered
            if json.loads(job.read_text("utf-8")) == lines:
                job.unlink(missing_ok=True)


def face_cache(who: str) -> Path:
    portrait = PORTRAITS / f"{who}.png"
    if not portrait.exists():
        raise FileNotFoundError(f"no portrait for {who}: run make_portraits.py")
    return FACES / who / f"{hashlib.sha1(portrait.read_bytes()).hexdigest()[:12]}.pkl"


def prepare_face(who: str) -> None:
    """Idle loop, face box, latents and blending masks for one member, cached on disk.

    Runs in its own process: the pose and face detectors MuseTalk uses here do not fit on a 4 GB card next to
    the lip-sync models, and Windows then swaps video memory and everything slows to a crawl.
    """
    import cv2
    os.chdir(MUSETALK)
    sys.path.insert(0, str(MUSETALK))
    from musetalk.models.vae import VAE
    from musetalk.utils.blending import get_image_prepare_material
    from musetalk.utils.face_parsing import FaceParsing
    from musetalk.utils.preprocessing import coord_placeholder, get_landmark_and_bbox

    cache = face_cache(who)
    vae = VAE(model_path=str(Path("models", "sd-vae")), use_float16=True)
    parser = FaceParsing(left_cheek_width=90, right_cheek_width=90)
    frames = idle_loop(cv2.imread(str(PORTRAITS / f"{who}.png")))
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for i, f in enumerate(frames):
            paths.append(str(Path(tmp, f"{i:08d}.png")))
            cv2.imwrite(paths[-1], f)
        coords, frames = get_landmark_and_bbox(paths, 0)
    if any(c == coord_placeholder for c in coords):
        raise RuntimeError(f"no face found in the portrait for {who}: pick another option")
    latents, boxes = [], []
    for (x1, y1, x2, y2), frame in zip(coords, frames):
        y2 = min(y2 + 10, frame.shape[0])                     # v1.5 extra margin under the chin
        boxes.append((x1, y1, x2, y2))
        crop = cv2.resize(frame[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
        latents.append(vae.get_latents_for_unet(crop).cpu())
    frames, boxes, latents = frames + frames[::-1], boxes + boxes[::-1], latents + latents[::-1]
    masks, mask_boxes = [], []
    for frame, box in zip(frames, boxes):
        mask, crop_box = get_image_prepare_material(frame, list(box), fp=parser, mode="jaw")
        masks.append(mask)
        mask_boxes.append(crop_box)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps({"frames": frames, "boxes": boxes, "latents": latents, "masks": masks, "mask_boxes": mask_boxes}))
    print(f"prepared {who}: face box {boxes[0]}", flush=True)


def write_status(run: str, status: dict) -> None:
    STATUS.mkdir(parents=True, exist_ok=True)
    tmp = STATUS / f"{run}.json.part"
    tmp.write_text(json.dumps(status), "utf-8")
    os.replace(tmp, STATUS / f"{run}.json")


def idle_loop(img):
    """IDLE_FRAMES of the portrait gently breathing: a slow zoom of about 1.5 % and a small nod."""
    import math
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    out = []
    for i in range(IDLE_FRAMES):
        t = 0.5 - 0.5 * math.cos(math.pi * i / (IDLE_FRAMES - 1))       # 0 → 1, easing at both ends
        m = cv2.getRotationMatrix2D((w / 2, h * 0.62), 0.6 * (t - 0.5), 1 + 0.015 * t)
        m[1, 2] += -2.0 * t
        out.append(cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.uint8))
    return out


def main() -> None:
    for d in (CLIPS, QUEUE, STATUS, FACES):
        d.mkdir(parents=True, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "work"
    if cmd == "prepare":
        for who in sys.argv[2:]:
            prepare_face(who)
        return
    if cmd == "test":
        who, text = sys.argv[2], sys.argv[3]
        voice = json.loads(VOICES.read_text("utf-8"))[who]
        mp3 = TTS / f"{clip_id(voice, text)}.mp3"
        if not mp3.exists():
            make_audio(voice, text, mp3)
        mp4 = CLIPS / f"{clip_id(voice, text)}.mp4"
        took = Renderer().render(who, mp3, mp4)
        print(f"{mp4} in {took:.1f}s")
        return
    if not take_lock():
        print("another renderer is running")
        return
    try:
        Renderer().work()
    finally:
        PIDFILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
