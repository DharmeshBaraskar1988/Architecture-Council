# Talking faces for the council room

Each council member is a 3D cartoon portrait. After a session, MuseTalk 1.5 lip-syncs every spoken line onto
the speaker's portrait on this computer's GPU. The room plays the video in step with the line's Edge TTS audio,
and uses the illustrated face for any line whose video is not ready yet.

| File | What |
|---|---|
| `make_portraits.py` | Makes 4 portrait options per member with DreamShaper 8; `--pick member=N` chooses |
| `render.py` | Prepares each face once, then renders queued lines (`work`), one test line (`test`) or faces (`prepare`) |
| `download_models.py` | MuseTalk inference weights (~4.4 GB), resumes after dropped connections |
| `portraits/<member>.png` | The chosen portraits (copied to `frontend/public/avatars/`) |

Output: `data/avatars/clips/<clip id>.mp4` (silent, 256 × 256), where the clip id is the same as the line's audio
in `data/tts/`. Progress: `data/avatars/status/<run>.json`; log: `data/avatars/render.log`.

## Setup (once, Windows, NVIDIA GPU)

```powershell
py -3.12 -m venv avatar\.tools; avatar\.tools\Scripts\python -m pip install uv
avatar\.tools\Scripts\uv python install 3.10; avatar\.tools\Scripts\uv venv --python 3.10 avatar\.venv
git clone --depth 1 https://github.com/TMElyralab/MuseTalk avatar\MuseTalk
$py = "--python", "avatar\.venv\Scripts\python.exe"
avatar\.tools\Scripts\uv pip install @py torch==2.0.1 torchvision==0.15.2 torchaudio==2.0.2 --index-url https://download.pytorch.org/whl/cu118
avatar\.tools\Scripts\uv pip install @py diffusers==0.30.2 accelerate==0.28.0 numpy==1.23.5 opencv-python==4.9.0.80 soundfile==0.12.1 transformers==4.39.2 huggingface_hub==0.30.2 librosa==0.11.0 einops==0.8.1 omegaconf ffmpeg-python moviepy safetensors edge-tts hf_xet "setuptools<70"
avatar\.tools\Scripts\uv pip install @py mmengine "mmcv==2.0.1" -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.0/index.html
avatar\.tools\Scripts\uv pip install @py "mmdet==3.1.0" "mmpose==1.1.0"
avatar\.venv\Scripts\python avatar\download_models.py
avatar\.venv\Scripts\python avatar\make_portraits.py          # then look at avatar\portraits\options\sheet.png
```

ffmpeg must be on PATH.

## Everyday use

- Nothing to do: opening a finished session in the room queues its lines; the renderer starts in the background.
- Change a portrait: `avatar\.venv\Scripts\python avatar\make_portraits.py --pick critic=3`. That member's face
  is prepared again automatically; videos already made keep the old portrait until deleted from `data/avatars/clips`.
- Faster, slightly softer videos: set `COUNCIL_AVATAR_DECODER=taesd` for the frontend server (~1.3× real time
  instead of ~3× on an RTX 3050 4 GB).
- Stop rendering: end the `python ... render.py work` process; delete files in `data/avatars/queue` to drop
  sessions. It resumes where it left off next time a room is opened.

## Speed on an RTX 3050 Laptop (4 GB)

About 3× real time: a full session (25–30 minutes of speech, ~200 lines) takes roughly 1.5 hours.
Preparing a face takes about a minute, once per portrait. The 4 GB card is why models are loaded to RAM and
halved before moving to the GPU, why face preparation runs in its own process, and why the VAE decodes two
frames at a time: each of those, done MuseTalk's default way, overflows the card and runs many times slower.

## Licences

MuseTalk code MIT · Whisper MIT · DWPose Apache-2.0 · face-parsing MIT · **sd-vae-ft-mse and DreamShaper 8:
CreativeML OpenRAIL-M** (use restrictions apply; check before company use) · edge-tts LGPL-3.0, run as a
separate program; text is sent to Microsoft's speech service. All characters are fictional.
