# Handoff: Batch WWII-Fantasy Portrait Generation (ComfyUI, local RTX 5080)

Status: **solution validated end-to-end** — ComfyUI 0.27.0 running under Pinokio on
Windows 11, torch 2.7.0+cu128, RTX 5080 (16 GB) detected and sampling successfully.

---

## 1. Stack

| Layer | Choice | Why |
|---|---|---|
| UI/runtime | ComfyUI via Pinokio (`C:\apps\pinokio\api\comfy.git\app`) | Already installed and working |
| Model | `flux1-schnell-fp8Checkpoint.safetensors` | **Apache-2.0 (commercial-safe)**, native FP8, fits 16 GB, ~10–20 s/image @1024 on the 5080 |
| Fallback model | Photo-real SDXL checkpoint (Civitai "vintage photo" fine-tunes) | Faster (~2–4 s/img); different character |
| Models NOT to use | `flux1-dev-*` (incl. the bnb-nf4 we started with) | Non-commercial license. Also needs `bitsandbytes` or it OOM-allocates ~79 TB |
| Batch driver | `gen_avatars.py` (ComfyUI API mode, POST `/prompt`, poll `/history`) | Headless, resumable, deterministic seeds |

Known-good KSampler settings:

- **flux1-schnell**: steps **4**, cfg **1.0**, sampler `euler`, scheduler `simple`, denoise 1.0, 1024×1024
- SDXL (if swapped): steps 25–30, cfg 6.0, `dpmpp_2m` / `karras`

Optional env upgrades (nice for long batches): `pip install -U torch torchvision --index-url https://download.pytorch.org/whl/cu128` (ComfyUI 0.27 wants torch ≥ 2.8 for dynamic VRAM; works on 2.7).

---

## 2. Art direction

**Style**: 1940s black-and-white formal military portrait photography — head-and-chest
crop, centered formal composition, direct gaze; single soft key light (studio variant)
or flat overcast daylight (field variant); large-format film look, silver gelatin print,
film grain, dust/scratches; shallow depth of field.

**Insignia policy (decided)**: all nations and insignia are **fictional**. Real-world
national/party symbols are excluded — both by policy and to keep the game distributable
(Germany §86a StGB, Steam/store rules). Insignia reads as authentic through period
*shape vocabulary* (cap badges = wreath+device; collar tabs = bars/pips; medals =
cross pattée / star orders / ribbon bars) filled with invented motifs.

Fictional nations (defined in script):

| Nation | Motif | Reads as | Uniform vocabulary |
|---|---|---|---|
| Veldmark | bronze griffon-over-crossed-keys cap badge, griffon collar tabs | German field force | dark green wool greatcoat, leather strap, peaked cap |
| Ostrand | silver star-in-laurel-wreath, five-star rank boards | American | olive drab service tunic, officer peaked cap |
| Averne | lion-head-over-crown regimental badge, pip boards | British | khaki battledress, collar and tie, side cap/beret |
| Karsk | wheat-sheaf-in-star badge, red/gold rank boards | Soviet | brown tunic with shoulder boards, peaked cap |

Negative prompt (always): `color, sepia, illustration, digital art, cartoon, anime,
modern, smooth skin, watermark, text, low quality, swastika, nazi symbols`
(the last two terms guard against checkpoint hallucination of period symbols).

**Likeness rule**: prompts describe generic officers by age/rank/demeanor — never
real historical names. Do not feed reference photos of real people into img2img for
this set.

---

## 3. Prompt template (as assembled by the script)

```
1940s black and white formal military portrait photograph, head and shoulders,
large format film look, silver gelatin print, vintage film grain, slight dust and
scratches, shallow depth of field, direct gaze, centered formal composition,
a {AGE}-year-old {NATION_FLAVOR}, {DEMEANOR}, wearing a {UNIFORM}, {INSIGNIA},
{RANK} rank insignia, {LIGHTING}
```

## 4. Option tables

| Axis | Values |
|---|---|
| nation | veldmark, ostrand, averne, karsk |
| rank | captain, major, colonel, general |
| age | 40, 50, 60 |
| demeanor | resolute / weary / stern / faint smile |
| lighting | studio (key light left, canvas backdrop, sharp) / field (overcast, blurred horizon) |
| seed | reproducible stream from seed 1234; 50 per combo by default |

Grid = 4×4×3×4×2 = **96 combos × N seeds**. Defaults: 50 seeds → **4,800 images ≈
1.5–2 days GPU time on the 5080** (schnell @ ~15–20 s/img incl. overhead). Scale
`--seeds-per-combo` (25 → 2,400; 100 → 9,600) or run `--max` for smoke tests.
Combos are deterministically shuffled and seeds randomized so early output already
spans the full option space.

Demeanor → prompt text mapping (texture words beat emotion words on photo models):

| demeanor | prompt text |
|---|---|
| resolute | resolute expression |
| weary | weary expression, heavy-lidded eyes |
| stern | stern hard stare |
| faint smile | faint knowing smile |

---

## 5. Workflow graph (API format, embedded in the script)

```
CheckpointLoaderSimple ─ MODEL ────────► KSampler.model
  (ckpt_name)          ─ CLIP ─► CLIPTextEncode(positive: style prompt)
                       ─ CLIP ─► CLIPTextEncode(negative)
                       ─ VAE  ────────► VAEDecode.vae
EmptyLatentImage(1024×1024, batch 1) ─► KSampler.latent_image
KSampler ─ LATENT ─► VAEDecode.samples ─ IMAGE ─► SaveImage(filename_prefix per image)
```

The script POSTs this JSON to `/prompt` per image with prompt/seed/prefix
substituted; no UI graph export needed. `filename_prefix` is
`wwii_portraits/{nation}_{rank}_{age}_{demeanor}_{lighting}_{seed:010d}`.

---

## 6. Running it

```bat
pip install requests pillow
python gen_avatars.py --max 20            :: smoke test (~5 min)
python gen_avatars.py                     :: full default batch
python gen_avatars.py --seeds-per-combo 25
python gen_avatars.py --nations veldmark  :: one faction only
python gen_avatars.py --postprocess       :: raw PNG -> 512px JPEG q85
```

- ComfyUI must be running (Pinokio) at `http://127.0.0.1:8188`.
- **Resume**: a job whose output file exists is skipped (file-prefix dedupe), so
  crashes/Ctrl+C are free to restart.
- Output lands in `C:\apps\pinokio\api\comfy.git\app\output\wwii_portraits\`.
- Post-process: 1024→512 LANCZOS, JPEG q85 ≈ 80–120 KB/portrait. Optional archival
  texture: re-encode at q70 or add grain in engine/pipeline.

---

## 7. Insignia consistency (team decision point)

Text prompts describe the fictional badges, but diffusion will drift the exact
heraldry between seeds. At 512px this is usually fine. If tight faction identity
matters, switch to the **composite** approach:

1. Generate portraits with plain cap band / blank collar tabs.
2. Design each nation's badge once (vector in Inkscape, or 5–10 img2img picks).
3. Composite onto the cap in-engine or with PIL (fixed ellipse + multiply blend —
   front-facing peaked caps put the badge in a predictable spot).

Strategy 2 also reuses the same emblems on unit markers/maps/UI.

## 8. Open items

- [ ] Approve nation names/motifs (table above) or swap
- [ ] Choose seeds-per-combo for target volume
- [ ] Decide plain-badge vs composite insignia pipeline
- [ ] If commercial: model is already Apache-2.0 (schnell) ✓; keep likeness rule
- [ ] Optional: LoRA fine-tune on ~30–50 CC/public-domain 1940s portraits
      (Bundesarchiv CC-BY-SA, National Archives) for stronger period texture
