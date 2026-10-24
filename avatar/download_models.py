"""Download the weights the council room's avatars need (MuseTalk 1.5 inference only; ~2.5 GB).

Run with the avatar environment:  avatar\\.venv\\Scripts\\python.exe avatar\\download_models.py
Weights land in avatar/MuseTalk/models, laid out the way MuseTalk expects.
"""
import time
from pathlib import Path

from huggingface_hub import hf_hub_download

MODELS = Path(__file__).resolve().parent / "MuseTalk" / "models"

# (repo, file inside the repo, folder under models/)                         licence
FILES = [
    ("TMElyralab/MuseTalk", "musetalkV15/unet.pth", "."),                    # MIT
    ("TMElyralab/MuseTalk", "musetalkV15/musetalk.json", "."),
    ("stabilityai/sd-vae-ft-mse", "config.json", "sd-vae"),                  # CreativeML OpenRAIL-M
    ("stabilityai/sd-vae-ft-mse", "diffusion_pytorch_model.bin", "sd-vae"),
    ("openai/whisper-tiny", "config.json", "whisper"),                       # MIT
    ("openai/whisper-tiny", "pytorch_model.bin", "whisper"),
    ("openai/whisper-tiny", "preprocessor_config.json", "whisper"),
    ("yzd-v/DWPose", "dw-ll_ucoco_384.pth", "dwpose"),                       # Apache-2.0
    ("ManyOtherFunctions/face-parse-bisent", "79999_iter.pth", "face-parse-bisent"),         # MIT (face-parsing.PyTorch)
    ("ManyOtherFunctions/face-parse-bisent", "resnet18-5c106cde.pth", "face-parse-bisent"),  # BSD (torchvision)
]

def fetch(repo: str, name: str, target: Path, tries: int = 30) -> Path:
    """Download one file, resuming after dropped connections (large files rarely arrive in one go on home links)."""
    done = target / name
    if done.exists() and done.stat().st_size > 0:
        return done                                  # already here (for example fetched with curl -C -)
    for attempt in range(1, tries + 1):
        try:
            return Path(hf_hub_download(repo, name, local_dir=target))
        except (OSError, ConnectionError) as e:
            if attempt == tries:
                raise
            print(f"  retry {attempt} for {name}: {str(e)[:120]}", flush=True)
            time.sleep(min(60, 5 * attempt))
    raise AssertionError("unreachable")


if __name__ == "__main__":
    for repo, name, folder in FILES:
        target = MODELS / folder
        target.mkdir(parents=True, exist_ok=True)
        path = fetch(repo, name, target)
        print(f"{path.stat().st_size / 1e6:8.1f} MB  {path.relative_to(MODELS)}", flush=True)
