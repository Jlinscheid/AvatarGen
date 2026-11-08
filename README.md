# AvatarGen — Simple Empire Character Generator

Batch-generates 1940s-style black-and-white military and civilian leader
portraits via a local ComfyUI (flux1-schnell), designed as an archival
"photo plate" source for a WWII-fantasy game: every image is meant to read
like the one surviving photograph of a fictional person.

**Product name:** Simple Empire Character Generator
**Code/repo name:** AvatarGen
**Status:** design phase complete (see `docs/DESIGN.md`), implementation pending.

## How it works

- Draws character attributes at random (side → nation → branch → rank →
  age → gender → race → demeanor → uniform variant → occasion → backdrop →
  personal details), assembles a prompt from validated phrase pools, and
  queues it to ComfyUI at `http://127.0.0.1:8188`.
- Unique random seeds guarantee no duplicate images; a master seed keeps
  runs reproducible; a JSONL manifest records every draw for filtering.
- Volume is a single `--n` upper bound — abort whenever you have enough
  (SaveImage never overwrites, so abort/restart is always safe).
- Ships as a cross-platform PySide6 GUI (Generate / Gallery / Settings /
  Post-process) over a GUI-free core; the headless CLI keeps working for
  automation and GPU boxes without a display.

## Model & licensing

- Checkpoint: `flux1-schnell` (FP8) — Apache-2.0, commercial-safe.
  Settings: steps 4, cfg 1.0, euler/simple, 1024×1024.
- All nations, insignia, and flags are fictional. Real-world national/party
  symbols are excluded via negative prompts and review (see DESIGN.md D24,
  D29, D32, D33).
- PySide6 is LGPL — used as a dependency, not bundled.

## Repository layout (planned)

```
docs/       design ledger, prompt pools, provenance
src/core/   draws, prompt assembly, ComfyUI client, postprocess (no GUI imports)
src/gui/    PySide6 shell (Generate / Gallery / Settings / Post-process)
cli/        headless batch script
assets/     side flags & badges (grayscale, for runtime overlay)
tests/      offline draw-logic tests
```

## Requirements

- Windows/macOS/Linux with Python 3.11+; GPU box runs ComfyUI (tested:
  ComfyUI 0.27.0 via Pinokio, RTX 5080 16 GB, torch 2.7.0+cu128).
- `pip install requests pillow` (CLI); `pip install PySide6` (GUI).

## Documentation

- `docs/DESIGN.md` — the full decision ledger (D1–D33) and test-validated
  findings from the design campaign.
- `docs/PROMPT_POOLS.md` — validated prompt phrase tables and the backdrop
  drafting standard.
