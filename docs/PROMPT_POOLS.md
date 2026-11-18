# Prompt Pools — validated phrase tables

Phrase tables the prompt assembler draws from. Every phrase marked ✓ has been
render-validated by the owner on flux1-schnell (B&W, steps 4, cfg 1.0,
euler/simple, 1024×1024). New phrases enter as drafts and get validated in
smoke tests before graduation.

## Global constants

**STYLE_CORE** (every prompt starts with this):
```
1940s black and white formal portrait photograph, head and shoulders,
large format film look, silver gelatin print, vintage film grain, slight dust
and scratches, shallow depth of field, direct gaze, centered formal composition
```
(Composition tail swaps for candid/group-crop occasions — see COMPOSITION.)

**NEGATIVE** (shared; drift terms appended as discovered per D23):
```
color, sepia, illustration, digital art, cartoon, anime, modern, smooth skin,
watermark, text, low quality, swastika, nazi symbols, fishing boat
```

## Race vocabulary (D11/D16 — signed off)

| Key | Phrase |
|---|---|
| black | a Black man / woman |
| white | a white (European) man / woman |
| east_asian | an East Asian man / woman |
| south_asian | a South Asian man / woman |
| southeast_asian | a Southeast Asian man / woman |
| middle_eastern | a Middle Eastern man / woman |
| latino | a Latino man / Latina woman |
| central_asian | a Central Asian man / woman |
| indigenous | an Indigenous man / woman |

Attach directly to the subject noun; never append at the end of the prompt.

## Personal details (D14 — random draw, 1–2 per image)

- facial hair (male only): clean shaven · neat mustache · full beard ·
  goatee · heavy stubble
- hair (male): receding grey · thick swept back · balding · short crop ·
  wavy unruly
- hair (female): 1940s roll · bobbed · pinned up
- accessories (all): round spectacles · pince-nez · pipe · pocket square ·
  string of pearls · signet ring · scar on left cheek · weathered sun-lined
  face

## Officers — uniform vocabulary by side/branch/variant (D13/D20/D25)

Structure per side: army/navy/airforce × formal/combat (+ women's formal).
Heraldry rule (D33): badges are generic shapes only — "a metal cap badge",
never a motif. Rank is ambiguous (D24): "officer rank insignia" / "rank boards
on the shoulders" / "rank stripes on the sleeve".

Veldmark-flavored drafts (to be re-authored per side at content time):
- army formal: dark green wool dress greatcoat with polished buttons, leather
  strap, peaked cap with a metal cap badge
- army combat: dark green field tunic under a wool greatcoat, mud-flecked
  shoulders, field cap, leather equipment straps ✓
- army combat (helmet variant): … flared steel helmet with a dull patina
  sitting low over the brow, chin strap fastened ✓
- navy formal: dark navy double-breasted reefer jacket with brass buttons,
  peaked cap with a metal cap badge on a navy blue cap band, rank stripes on
  the sleeve ✓
- airforce: olive drab service tunic under a leather flight jacket, side cap
  pushed back ✓ (flight-line candid)
- women's formal (draft): tailored period jacket, skirt/slacks, side cap or
  brimmed service hat

## Civilians (D10/D26)

- statesman: dark formal double-breasted suit, sash and a single medal order
  for ceremony occasions ✓
- scientist: white laboratory coat over a tweed suit and tie, round
  spectacles ✓
- industrialist: dark three-piece suit with a watch chain (draft, untested)

## Backdrop pools (D15/D23/D32)

Drafting standard (D23): name the subject class explicitly + a scale/function
cue. Generic nouns drift to the dominant training-data look.

- officer combat outdoor ✓: muddy field with a distant tree line · ruined
  village street · trench parapet · motor pool with vehicles
- officer formal outdoor (draft): official residence steps · courtyard
- civilian outdoor (draft): stone government building facade · street with
  crowds
- civilian statesman ceremonial: blurred stage drapery, plain curtains —
  NO banners, NO flags (D32) ✓ (drapery render validated)
- scientist indoor ✓: blurred laboratory chalkboard densely covered in
  handwritten equations and diagrams, out-of-focus glassware on shelving at
  the edge of frame
- industrialist (draft): factory floor with heavy industrial machinery and a
  long lathe line · shipyard with a huge grey ship under construction, giant
  cranes and scaffolding · office with window light
- naval (draft, D23 wording standard): deck of a large warship, heavy gun
  turret and rigging · naval dockyard with a huge grey battleship in drydock,
  giant cranes and scaffolding · moored heavy cruiser and dockyard cranes
- airforce (draft): airfield apron with dispersed propeller fighter aircraft
  and ground crew · hangar interior

## Composition (D17)

- formal portrait (default): direct gaze, centered ✓
- group-crop candid ✓: `candid shot of military officers in conversation,
  cropped close on one officer in the foreground, head and shoulders slightly
  off-center, looking toward another officer rather than the camera` + a
  partially visible out-of-focus companion at the frame edge. Low weight
  (~20–30% of candid occasions). Indoor variant validated for scientists ✓.

## Occasion conditioning (D17/D26)

Occasions are drawn first and condition the other axes (age band, uniform
variant, composition, backdrop, demeanor). Officers: academy graduation ·
promotion sitting · front-line candid · press photo · award ceremony.
Civilians: appointment/institute/owner portrait · candid at work · press
photo · award ceremony.

## Drift-term negatives discovered so far (D23)

- `fishing boat` — naval dockside scenes ✓ (owner-confirmed fix)
- expect per-branch additions during volume runs (one word each)
