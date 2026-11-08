# Design Ledger — Simple Empire Character Generator

The authoritative record of design decisions (D1–D33) plus empirically
validated findings from the prompt-test campaign. Provenance: handoff from an
earlier chat (`HANDOFF.md` in this repo) plus an iterative design session
between the owner and the planning agent.

Target environment (validated): Windows 11 + RTX 5080 16 GB, ComfyUI 0.27.0
under Pinokio at `C:\apps\pinokio\api\comfy.git\app`, torch 2.7.0+cu128,
checkpoint `flux1-schnell-fp8Checkpoint.safetensors` (Apache-2.0), API at
`http://127.0.0.1:8188`. Settings: steps 4, cfg 1.0, euler/simple, 1024×1024.

## Decision ledger

- **D1 — No resume logic needed.** Outputs are preserved (ComfyUI SaveImage
  appends counters, never overwrites) and seeds are deterministic, so an
  abort/restart only re-renders duplicates. Owner accepted the trade-off.
- **D2 — v1 combo math was wrong.** The factorial grid was 384 combos, not 96
  (4 nations × 4 ranks × 3 ages × 4 demeanors × 2 lighting). Superseded by D3.
- **D3 — Random-sampling design.** No factorial grid; the generator draws each
  attribute at random. Unique seeds guarantee no duplicates; `--master-seed`
  keeps runs reproducible; a JSONL manifest records every draw.
- **D4 — Abort-when-enough.** `--n` is an upper bound; the owner aborts when
  enough images exist. No pre-computed totals.
- **D5 — PySide6 (Qt6) GUI.** Keeps the validated Python pipeline unchanged;
  QThread for long-running batches with responsive Abort; model/view gallery
  for 19k+ thumbnails with per-axis filters; PyInstaller packaging.
  Architecture rule: core has zero GUI imports; CLI stays first-class. All
  ComfyUI HTTP in worker threads; UI updates via signals.
- **D6 — Civilians tab.** Parallel to Officers; same style core.
- **D7 — Gender & race axes; unified multi-select controls** (later refined by
  D11/D12/D19).
- **D8 — Age = dual-handle min/max slider** (30–70), uniform draw between
  handles; replaces per-rank age curves.
- **D9 — Name: "Simple Empire Character Generator"** (repo/code name
  AvatarGen). Architecture keeps room for later scope growth.
- **D10 — Civilians: generic formal attire only** for v1; attire/status-mark
  axes remain designed-in for later.
- **D11 — Race: always random**, drawn from a 9-bucket vocabulary; bucket keys
  (not phrases) stored in the manifest.
- **D12 — Gender: user selection** (male / female / mixed).
- **D13 — Nations & branches, composed not enumerated.** New axis branch
  (army/navy/air force, officers only). Insignia/uniform text is composed from
  nation motif + branch device + uniform cut, so nations × branches never
  explodes into per-nation tables. Two tiers: hand-written primary nations,
  pool-filled minor nations.
- **D14 — Personal-details axis: fully random.** 1–2 detail phrases per image
  from gender-appropriate pools (facial hair, hair, accessories). Motivated by
  observed male-variation collapse ("man in a suit" archetype gravity);
  equalizes descriptor density by construction.
- **D15 — Backdrop pools keyed by (subject type, uniform variant, lighting).**
  Validated combat-field look ("unit photographer just behind the lines").
  Pools: combat-outdoor (muddy field/tree line, ruined village, trench parapet,
  motor pool), formal-outdoor (residence steps, courtyard), civilian-outdoor
  (building facade, street), studio (canvas). 2–4 phrases per pool, random
  draw.
- **D16 — Race vocabulary signed off** (Black, white/European, East Asian,
  South Asian, Southeast Asian, Middle Eastern, Latino/Hispanic, Central
  Asian, Indigenous; Pacific Islander dropped). Revisit if problematic; bucket
  keys make wording revisions safe.
- **D17 — Occasion axis ("archival photo" model).** Owner goal: each image is
  the one surviving photo of a fictional person; occasions (academy
  graduation, promotion sitting, front-line candid, press photo, award
  ceremony) condition age band, uniform variant, composition, backdrop, and
  demeanor into authentic clusters. Civilians get a parallel occasion list
  (D26).
- **D18 — One photo per person.** No career-arc sets, no character identity
  management, no face consistency. Every output is an independent plate;
  volume = number of characters needed.
- **D19 — Maximize automation.** The system decides; user controls shrink to
  N, gender tri-state, and tab choice. Occasion is hidden and drawn
  automatically. Stylistic integrity is engineered in (occasion-conditioned
  bundles, validated pools, negative guards). The Gallery is the owner's
  steering tool — browse, abort, target re-runs.
- **D20 — Sides.** Nations group into alliances; each side owns a uniform
  family covering army/airforce/navy × formal/combat; nations contribute
  heraldic motifs (later demoted by D33) and palette accents. Draw chain:
  side → nation → branch → variant → occasion.
- **D21 — Playable vs. AI factions.** Major (playable) sides get hand-written
  tables (capped at ~2–3); minor (AI) nations cost one line each (name, side)
  and inherit the side's uniform family. Variety grows linearly. Draw
  weighting: majors ~60–70% of volume, minors split the rest.
- **D22 — Generic insignia for minors + runtime overlay.** Minors generate
  with blank insignia carriers (plain cap band, blank collar tabs, plain
  helmet); the game composites each nation's badge/flag at runtime. Manifest
  tags `insignia: blank`. Helmets become natural decal surfaces.
- **D23 — Backdrop drafting standard + drift-term negatives.** Every backdrop
  phrase names its subject class explicitly with a scale/function cue
  ("huge grey battleship in drydock, giant cranes and scaffolding", not
  "dockyard"). Empirically confirmed negatives ("fishing boat") join the
  shared NEGATIVE string; per-branch drift terms discovered in smoke tests.
- **D24 — Rank ambiguous in prompts.** Generic phrases only ("officer rank
  insignia"); real rank lives in the manifest/game. Kills confidently-wrong
  rank devices and the naval sleeve-stripe failure mode.
- **D25 — Women's uniforms: Option C hybrid.** Distinct women's FORMAL
  variants per side (tailored jacket, period skirt/slacks, women's headwear);
  combat draws reuse the shared combat vocabulary. 3 extra entries per side.
  Revisit after gallery review.
- **D26 — Civilian categories: statesman, scientist, industrialist.** Each has
  attire, backdrop pool, and occasion bundles (appointment/institute/owner
  portraits; press photos; candids with group-crop). Category replaces the
  title axis for v1.
- **D27 — Scientist chalkboard validated.** "Chalkboard densely covered in
  handwritten equations" renders well; blur-fallback noted. Watch item:
  spectacles archetype gravity (generic-Einstein collapse) — if confirmed,
  spectacles become weighted rather than near-certain.
- **D29 — Coincidental real-person likeness: observed; review-stage control.**
  Archetype gravity (elderly statesman, scientist, senior officer sittings)
  can land on recognizable real faces with no name in the prompt. No
  negative-prompt fix exists. Mitigations: "no recognizable real persons" is
  an explicit acceptance criterion in smoke/spot checks; rich D14 details
  decorrelate; high-risk cells reviewed with extra scrutiny; game never names
  a character after the person their photo resembles. Rejection is costless
  (D18).
- **D30 — Banner drift.** Invented heraldry is diffusion's weakest subject;
  banners rendered gibberish symbols/CJK-like script. See D32/D33 for the
  resolution.
- **D31 — Side-level flags.** Flags belong to sides. Deterministic overlay
  (design flag once as grayscale tone asset, composite in postprocess or at
  runtime) recommended over generation-time conditioning (img2img/IP-Adapter/
  Redux) — conditioning redraws and distorts motifs and cannot guarantee
  identical flags across images. Superseded for portraits by D32; side flags
  remain game/UI assets.
- **D32 — No flags in portrait backdrops.** State/ceremonial occasions use
  plain stage drapery. Side flags are game/UI assets only.
- **D33 — All heraldry handled outside the photo (final rule).** No invented
  symbols inside any portrait, any tier: badges render as generic shapes,
  rank is ambiguous, no banners. All symbols are game-side overlay assets
  (manifest tags `overlay: cap_badge` / `overlay: none`). In-image nation
  identity comes solely from the side's uniform family plus per-nation
  palette accents (cap band color, button metal, facing color) — those
  accents are now the differentiator between same-side nations.

## Validated prompt findings (test campaign)

| Test | Result | Action |
|---|---|---|
| Combat uniform, field backdrop | validated ("unit photographer" feel) | D15 pool locked |
| Group-crop candid (officers talking) | validated | composition option, low weight |
| Helmet (combat) | validated; erases cap badge | headwear sub-axis; insignia re-routes to boards |
| Naval formal, dockside | fishing-boat drift | "fishing boat" negative (D23) |
| Naval drydock | fishing-boat drift again | asset-class + scale wording standard (D23) |
| Scientist, chalkboard | chalkboard renders fine | D26 pool locked (D27) |
| Statesman, flag-draped stage | banner gibberish; coincidental likeness of a real person | D30/D32 (no banners); D29 (review control) |

## Risks

| Risk | Mitigation |
|---|---|
| Period-symbol hallucination | negative terms; human spot-check per nation × lighting |
| Insignia drift | eliminated for minors via overlay (D22); majors use generic shapes (D33) |
| Real-person likeness | review-stage control (D29) |
| Interrupted long runs | accepted (D1) |
| Non-commercial model creep | schnell (Apache-2.0) only unless a licensed SDXL fine-tune is vetted |

## Open items (content, non-blocking)

- Side count/names and nation membership (majors)
- Minor-nation roster (trivial to extend; one line each)
- Majors' badge overlay vs. generic-shape decision confirmed by D33; revert
  path documented
- Industrialist / air-force / award-ceremony backdrop pools await test renders
- Script/`core` implementation pending owner go-ahead
