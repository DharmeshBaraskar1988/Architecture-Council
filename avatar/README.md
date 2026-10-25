# Council portraits

Each council member is shown as a 3D cartoon portrait: `frontend/public/avatars/<member>.png`. While a member
speaks, the room makes the portrait bob gently and its glow follows the loudness of their Edge TTS voice.
Members without a portrait keep the illustrated face drawn in the room.

| File | What |
|---|---|
| `make_portraits.py` | Makes 4 portrait options per member with DreamShaper 8; `--pick member=N` chooses |
| `portraits/<member>.png` | The chosen portraits (also copied to `frontend/public/avatars/`) |

The portraits are already made; nothing here is needed to run the room.

## Making new portraits (optional, NVIDIA GPU)

The environment is not installed (about 6 GB). To set it up again:

```powershell
py -3.12 -m venv avatar\.tools; avatar\.tools\Scripts\python -m pip install uv
avatar\.tools\Scripts\uv venv --python 3.10 avatar\.venv
$py = "--python", "avatar\.venv\Scripts\python.exe"
avatar\.tools\Scripts\uv pip install @py torch==2.0.1 torchvision==0.15.2 --index-url https://download.pytorch.org/whl/cu118
avatar\.tools\Scripts\uv pip install @py diffusers==0.30.2 transformers==4.39.2 accelerate==0.28.0 huggingface_hub==0.30.2 safetensors pillow
avatar\.venv\Scripts\python avatar\make_portraits.py          # then look at avatar\portraits\options\sheet.png
avatar\.venv\Scripts\python avatar\make_portraits.py --pick critic=3
```

The DreamShaper 8 weights (2.6 GB) are cached in `%USERPROFILE%\.cache\huggingface\hub` and are reused.

## Licences

DreamShaper 8: CreativeML OpenRAIL-M (use restrictions apply; check before company use). All characters are
fictional; the prompts describe looks only.
