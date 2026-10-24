"""Make 3D cartoon portrait options for each council member (DreamShaper 8, a Stable Diffusion 1.5 model).

    avatar\\.venv\\Scripts\\python.exe avatar\\make_portraits.py              # 4 options per member
    avatar\\.venv\\Scripts\\python.exe avatar\\make_portraits.py --pick critic=3 moderator=2

Options go to avatar/portraits/options/<member>-<n>.png with a contact sheet (sheet.png). Without --pick, option 1
of every member is used; --pick changes the chosen ones. Chosen portraits are copied to avatar/portraits/<member>.png
and to the frontend (public/avatars/), where the room shows them. MuseTalk animates these images.
All characters are fictional; the prompts describe looks only.
"""
import argparse
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPTIONS = HERE / "portraits" / "options"
CHOSEN = HERE / "portraits"
PUBLIC = HERE.parent / "frontend" / "public" / "avatars"
MODEL = "Lykon/dreamshaper-8"            # CreativeML OpenRAIL-M

STYLE = ("3d cartoon character portrait, pixar style animation, head and shoulders, facing the camera, looking at viewer, "
         "mouth closed, gentle smile, symmetrical face, soft studio lighting, plain soft grey background, centered, high detail")
NEGATIVE = ("open mouth, teeth, profile, side view, looking away, tilted head, hands, multiple people, text, watermark, logo, "
            "deformed, disfigured, blurry, lowres, cropped head, photo, realistic skin pores")

MEMBERS = {
    "moderator":     "a friendly woman in her thirties, dark brown bob haircut, wearing a thin black headset with a small microphone, grey blazer over white blouse",
    "strategist":    "a confident south asian woman, long straight black hair, small gold earrings, purple knit sweater",
    "architect":     "a thoughtful woman with a short auburn pixie haircut, round thin-rimmed glasses, green eyes, blue blazer",
    "platform_cost": "a calm south asian man, short black hair, neat full black beard, mustard yellow collared shirt",
    "critic":        "a sceptical man with spiky blond hair, blue eyes, light stubble, one eyebrow slightly raised, red collared shirt",
    "fact_checker":  "a sharp black woman with voluminous curly dark hair, warm brown eyes, green sweater",
    "you":           "a friendly person with short brown hair, teal hooded sweatshirt",
}


def download(patterns: list[str], tries: int = 30) -> str:
    """The model's files, resuming after dropped connections."""
    import time
    from huggingface_hub import snapshot_download

    for attempt in range(1, tries + 1):
        try:
            return snapshot_download(MODEL, allow_patterns=patterns, ignore_patterns=["*.ckpt", "*.onnx*"])
        except (OSError, ConnectionError) as e:
            if attempt == tries:
                raise
            print(f"  retry {attempt}: {str(e)[:120]}", flush=True)
            time.sleep(min(60, 5 * attempt))
    raise AssertionError("unreachable")


def generate(count: int) -> None:
    import torch
    from diffusers import DPMSolverMultistepScheduler, StableDiffusionPipeline

    try:                                  # half-precision files: half the download
        local = download(["*.json", "*.txt", "*.fp16.safetensors"])
        pipe = StableDiffusionPipeline.from_pretrained(local, torch_dtype=torch.float16, variant="fp16", safety_checker=None)
    except (OSError, ValueError):
        local = download(["*.json", "*.txt", "*.safetensors"])
        pipe = StableDiffusionPipeline.from_pretrained(local, torch_dtype=torch.float16, safety_checker=None)
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type="dpmsolver++", use_karras_sigmas=True)
    pipe = pipe.to("cuda")
    pipe.enable_attention_slicing()       # fits a 4 GB card
    OPTIONS.mkdir(parents=True, exist_ok=True)
    for who, looks in MEMBERS.items():
        for n in range(1, count + 1):
            g = torch.Generator("cuda").manual_seed(1000 * n + len(who))
            img = pipe(f"{looks}, {STYLE}", negative_prompt=NEGATIVE, width=512, height=512,
                       num_inference_steps=28, guidance_scale=7, generator=g).images[0]
            img.save(OPTIONS / f"{who}-{n}.png")
            print(f"{who}-{n}.png")
    sheet(count)


def sheet(count: int) -> None:
    """One image with every option, a row per member, so they can be compared at a glance."""
    from PIL import Image, ImageDraw

    size = 256
    out = Image.new("RGB", (size * count + 140, size * len(MEMBERS)), "white")
    draw = ImageDraw.Draw(out)
    for row, who in enumerate(MEMBERS):
        draw.text((8, row * size + size // 2), who, fill="black")
        for n in range(1, count + 1):
            p = OPTIONS / f"{who}-{n}.png"
            if p.exists():
                out.paste(Image.open(p).resize((size, size)), (140 + (n - 1) * size, row * size))
                draw.text((140 + (n - 1) * size + 6, row * size + 6), str(n), fill="white")
    out.save(OPTIONS / "sheet.png")


def choose(picks: dict[str, int]) -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    for who in MEMBERS:
        src = OPTIONS / f"{who}-{picks.get(who, 1)}.png"
        if not src.exists():
            print(f"missing {src.name}; {who} keeps its current portrait")
            continue
        shutil.copy(src, CHOSEN / f"{who}.png")
        shutil.copy(src, PUBLIC / f"{who}.png")
        print(f"{who}: option {picks.get(who, 1)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=4, help="options per member")
    ap.add_argument("--pick", nargs="*", default=None, metavar="MEMBER=N", help="choose options without generating")
    args = ap.parse_args()
    if args.pick is None:
        generate(args.count)
        choose({})
    else:
        choose({k: int(v) for k, v in (p.split("=") for p in args.pick)})
