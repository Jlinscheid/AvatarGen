# AvatarGen

Simple Empire Character Generator — batch avatar portraits via local ComfyUI.
Prototype; see the project plan (decision log D1–D45) for the spec.

## Run from source

```bash
python -m venv venv            # or your preferred env manager
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py
```

## Prerequisites

- ComfyUI (easiest via [Pinokio](https://pinokio.computer)), default endpoint
  `http://127.0.0.1:8188` — configurable in Options → Settings.
- A diffusion checkpoint (default: `flux1-schnell-fp8Checkpoint.safetensors`)
  placed in ComfyUI's `models/checkpoints/` folder.

## Layout

- `dictionaries.json` — default side/nation, subject, uniform, composition,
  ethnicity tables (user-editable data; GUI editing comes later).
- `avatargen/core.py` — prompt assembly, ComfyUI client, template I/O.
- `avatargen/gui.py` — PySide6 main window, template tab, settings dialog,
  render worker (abortable QThread).
- `userdata/templates/` — your templates (one JSON per template).
- `userdata/renders/<template-id>/` — saved renders + `manifest.jsonl`.
