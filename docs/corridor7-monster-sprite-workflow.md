# Corridor 7 new-monster sprite workflow for AI agents

This is the production contract for turning a short monster idea into a complete,
palette-correct sprite set that can be loaded by EC7Wolf and placed in a custom
Corridor 7 level. It is deliberately written as an executable workflow: an AI
agent should be able to accept one or two sentences, make conservative design
assumptions, generate every required view and state, validate the result, and
deliver a companion mod without redistributing any retail game data.

The workflow is based on all sixteen CD-release alien families, their current
EC7Wolf actor states, the sprite-name map, and the enemy chapter on pages 68–81
of the official strategy guide. The guide establishes character, silhouette,
and combat role; the shipped sprite pages establish the art language; and the
current actor definitions establish what EC7Wolf actually displays. When those
sources disagree, runtime actor code wins for implementation.

## Completion contract

A monster is complete only when the delivery contains:

- a design brief derived from the user's short description, including all
  assumptions;
- a state-and-angle manifest made **before** final image generation;
- one final PNG for every manifest entry, with no missing rotation;
- exact Corridor 7 palette conformance, binary transparency, and a verified
  common anchor;
- a contact sheet, turntable, animation previews, and a palette-index report;
- a root `DECORATE` lump and sprite namespace (`sprites/` in a PK3 or
  `S_START`/`S_END` in a WAD) in a companion mod;
- a placement decision: replace an existing translated enemy slot, or document
  the required XLAT/editor extension for a genuinely new slot;
- an EC7Wolf test in normal, night-vision, and infrared modes at near and far
  distances.

Concept art, a single front view, a sheet with unsplit cells, or files that are
merely "close" to the game palette are not complete.

## Evidence and legal boundary

Use these sources in this order:

1. The user's description and explicit corrections.
2. The official strategy guide, especially its enemy chapter, for the intended
   personality, threat, movement, and recognizable features.
3. Sprite pages decoded from the user's legally owned Corridor 7 CD files for
   pixel treatment, scale, animation cadence, views, and palette use.
4. [`monsters.txt`](../wadsrc/static/actors/corridor7/monsters.txt) for the
   states that the current engine actually runs.
5. [`co7map.txt`](../wadsrc/static/co7map.txt) and
   [`r_sprites.cpp`](../src/r_sprites.cpp) for names and rotation rules.
6. [`corridor7.txt`](../wadsrc/static/xlat/corridor7.txt) for native map object
   translation and placement.

Retail sprites and guide scans are private reference material. Never add them,
contact sheets made from them, the extracted palette, or any other commercial
Corridor 7 data to this repository or a distributable mod. Commit only original
new-monster work and metadata.

To inspect the user's installation without writing a retail-art cache, run the
repository's in-memory asset browser:

```sh
python3 tools/c7assets.py --dir /path/to/CORR7CD
```

The directory must contain `CORR7CD.EXE` and `GFXTILES.CO7`; the complete browser
also uses the map and VGA files described in the main README. The browser does
not make the art distributable.

## What the stock monsters teach us

Corridor 7's monsters are designed for instant recognition in a dark,
low-resolution corridor. The common traits are a strong outer silhouette,
oversized heads/weapons/horns/eyes, dark outlines, bright color families,
clustered highlights, sparse single-pixel texture, and hard-edged pseudo-3D
shading. Organic bodies favor reds, purples, yellow-greens, and sickly gray;
technology favors steel gray with intense lamps or weapon accents. Fine detail
must support the silhouette, never compete with it.

The source artwork occupies a virtual 64×64 canvas. Shapes are often much
narrower than the canvas and the original column-post format crops empty space
at load time, but the logical pivot remains horizontally centered at the bottom
of that canvas. There is no soft alpha or smooth vector edge. A frame should
still read at 1× size, against black and against a mid-value wall.

### Complete CD bestiary reference

The page ranges below are the decoded `GFXTILES.CO7` sprite-page numbers, not
names to reuse for new art. "Rotated locomotion" means eight views for each
directional frame. The archive sometimes contains a fifth rotated frame while
the current actor uses A–D; generate from the target state manifest, not from a
blind maximum count.

| Family | Retail pages | Current visual topology | Guide-derived design lesson |
| --- | ---: | --- | --- |
| Alioprobe / Organic Eye | 75–123 | Rotated locomotion; front attack, pain, death | A dangling organic eye: a slow sentry whose readable eye/tissue silhouette matters more than weapon bulk. |
| Animated Probe | 239–289 | Rotated locomotion; front attack, pain, death | A tiny, extremely fast mechanical eye; keep its bright optic and compact flying profile readable. |
| Bandor | 124–184 | Four disguise/morph sequences, rotated revealed body, front combat/death | Furniture becomes a green armored gunner. The prop-to-body transition is part of the monster, not optional decoration. |
| Rodex | 185–238 | Rotated locomotion; front combat/death | A short green pack alien in a red suit; large color blocks preserve its scale and nervous movement. |
| Tenaj | 290–343 | Rotated locomotion; front combat/death | A quick, clever technician in magenta/gray armor with a bright weapon; an alert, evasive posture sells the role. |
| Ttocs | 344–396 | Rotated locomotion; front combat/death | A durable red-and-purple brute; use mass, a broad stance, and slow weight rather than intricate anatomy. |
| Otrebor | 397–449 | Numeric pages include directional groups; current states choose explicit pages | A large red armored technician/sub-boss. Preserve intimidating bulk and consult actor states rather than inferring frame letters. |
| Semaj | 561–573 | Front-only idle/chase, attack, pain, death | A low purple puddle with teeth. Its floor-hugging height and mouth are its gameplay warning. |
| Nerraw | 574–589 | Front-only locomotion, attack, pain, death | A small gray insectoid with yellow-green accents; harmless-looking scale contrasted with a vicious attack. |
| Eitak | 590–637 | Rotated locomotion; front combat/death | A hunched yellow-green guard. A distinct head/weapon gesture keeps groups legible. |
| Solrac | 638–652 | Front-only boss locomotion/combat/death | A floating red skull/brain/eye-energy leader; concentrate contrast around the face and supernatural core. |
| Eniram Boss | 653–664 | Front-only boss locomotion/combat/death | A solid, permanently visible heavy gunner; bright horns/armor separate it from the ordinary cloaking form. |
| Eniram | 665–689 | Front-only materialization, combat, pain, death | A bulky red gunner revealed from invisibility. Decloak frames must communicate emergence, not a normal walk cycle. |
| Mechanoid Warrior | 690–705 | Front-only boss locomotion/combat/death, with separate projectile FX | A slow, heavily armored machine. Large feet, weapon mass, and a rigid gait communicate weight. |
| Tymok | 726–737 | Front-only boss locomotion/combat/death | A fast purple gorilla-like boss; keep the arms and forward-driving posture dominant. |
| Tebazile | 814–857, plus borrowed boss forms | Five-phase transformation chain and long final death | A golden horned guardian whose changing forms are the encounter. Phase continuity and transition silhouettes are mandatory. |

Supporting monster art also includes the Mechanoid/boss projectile pages 706–709
and the non-counting red-skull apparition at 718–725. Treat projectiles,
impacts, summoned apparitions, disguises, and transformations as separate
manifested assets whenever the new behavior needs them.

## EC7Wolf sprite contract

### Canvas, alpha, and pivot

- Author on one consistent 64×64 logical canvas unless the monster has an
  intentional oversize requirement. Do not resize individual frames to fill
  the cell.
- Use RGBA or indexed PNG with explicit transparency. Final alpha values must
  be only 0 or 255; EC7Wolf thresholds alpha at 128, so soft edges cannot
  survive faithfully.
- Keep a shared logical anchor at `(32, 64)`: horizontal center and the bottom
  edge of the 64×64 canvas. Feet touch a consistent baseline; flying monsters
  preserve their intended empty space below them instead of moving their pivot.
- A PK3 PNG needs offsets. Embed a PNG `grAb` chunk with signed big-endian
  coordinates `(32, 64)` when retaining the full canvas. If a frame is tightly
  cropped from rectangle `(left, top, width, height)`, use
  `(32 - left, 64 - top)`. A WAD editor may store equivalent sprite offsets.
- Never let a generator independently center each output. Anchor normalization
  is global across every state and direction.

### Names and rotations

Put PNG files under `sprites/`. EC7Wolf reads the first four characters as the
sprite bank, the fifth as frame, and the sixth as rotation:

```text
GSTKA1.png ... GSTKA8.png   frame A, all eight directions
GSTKB1.png ... GSTKB8.png   frame B, all eight directions
GSTKE0.png                  frame E, no directional variants
```

Choose an unused, mnemonic four-character bank. Frame letters may be A–Z (the
engine also has three punctuation frame slots, but new mods should avoid them).
Rotation `0` means a single billboard view. A rotated frame must supply all
eight numbered views; EC7Wolf warns about incomplete sets.

The view sequence is the classic Wolfenstein turntable: `1` is front, `2` is
front three-quarter, `3` is profile, `4` is rear three-quarter, `5` is rear,
then `6`, `7`, and `8` return through the opposite rear three-quarter, profile,
and front three-quarter. Validate the sequence in-engine because an attractive
but reversed turntable visibly snaps as the player circles it.

The compact mirrored name form, such as `GSTKA2A8`, installs its second frame as
a mirror. Use it only for genuinely bilateral bodies with no handed weapon,
lettering, wound, cable, light, or asymmetrical animation. The default for AI
work is eight explicitly drawn views.

### Selecting appropriate states and angles

Build the manifest from behavior, not from a fixed sheet template:

| State | Normal minimum | Use eight angles when… | Typical beats |
| --- | --- | --- | --- |
| Spawn/idle | 1 frame | facing or asymmetry conveys information | watch, breathe, hover, twitch |
| Path/See locomotion | 4 looping frames | the actor moves with a heading; this is the default for ordinary mobile aliens | contact, pass, opposite contact, recovery |
| Alert | optional 1–3 | the alert gesture is directional | notice, recoil, acquire target |
| Missile/melee attack | 3–5 | side/rear weapon geometry or melee reach would otherwise pop | aim/coil, anticipation, strike/flash, recoil, recover |
| Pain | 1–2 | directional wounds or a large asymmetric body demand it | impact, recoil |
| Death | 5–8 plus terminal corpse | usually no; stock deaths are commonly front billboards | hit/fall trigger, collapse, impact, settle, corpse |
| Projectile flight | 1–4 looping | the projectile is not rotationally symmetric | charge, spin/flicker |
| Projectile impact | 3–6 | rarely | contact, bloom, dissipate |
| Special | behavior-dependent | the body orientation remains important | cloak, morph, disguise, summon, burrow, teleport |

Defaults for a conventional humanoid ranged monster are four locomotion frames
times eight views, three or four front attack frames, one or two pain frames,
and five to eight death/corpse frames. A puddle, hovering frontal boss, or
radially symmetric eye may be all `0` views. If the user asks for a special
mechanic, add the visual states required to make that mechanic fair to read.

Do not generate unused frames merely because a retail archive contains them.
Do not omit a telegraph, transformation, projectile, or corpse merely because a
basic template does not.

## Palette is a hard gate

"Looks like Corridor 7" is not palette compliance. Final opaque pixels must map
exactly to the palette embedded in the user's `CORR7CD.EXE`.

### Build the private palette authority

1. Read 768 bytes at executable offset `0x2FFC0`.
2. Reject the file unless every component is in the six-bit VGA DAC range
   0–63.
3. Expand each component to eight bits with
   `(component << 2) | (component >> 4)`.
4. Store the resulting 256 RGB triples in a temporary work directory as the
   quantizer palette, swatch, and validation lookup. Do not commit it.

This is the same rule implemented by `load_palette()` in
[`tools/c7assets.py`](../tools/c7assets.py). If working with a different release
whose palette is not at the known CD offset, use the guarded fallback search in
[`make_c7_upscaled_pk3.py`](../tools/make_c7_upscaled_pk3.py) and record the
source executable hash and discovered offset.

### Palette semantics that must survive

- Native Corridor 7 shapes use palette index 255 as transparent. Reserve it in
  native/indexed source work; for PNG delivery, use the alpha channel for
  transparency and keep alpha binary.
- Indices 15 and 254, plus 208–239, are luminous on world sprites.
- The four eight-color ramps 208–215, 216–223, 224–231, and 232–239 cycle in
  play. They are effects colors, not extra ordinary shading ramps.
- The base palette makes 232–239 black, while infrared rewrites them as a red
  sweep. Never let an ordinary black outline quantize into this band.
- Night vision and infrared rewrite the whole DAC. Two RGB colors that seem
  interchangeable in a normal screenshot may have different gameplay results.

PNG decoding remaps RGB colors to EC7Wolf's palette. Duplicate RGB entries—most
importantly the base-black 232–239 band—cannot reliably express a particular
semantic index by RGB alone. Therefore ordinary custom PNG monsters must avoid
232–239 and use 208–231 only for deliberately animated/luminous details that
have passed an in-engine index test. If exact index behavior cannot be proven,
animate the effect with shape frames instead. Never claim an infrared-only or
cycling-index effect based solely on a PNG swatch.

### Quantization procedure

1. Finish silhouette, proportions, view consistency, and anchor normalization
   before palette conversion.
2. Remove all generated backgrounds, halos, shadows outside the intended
   sprite, and antialiased edge pixels.
3. Quantize opaque pixels to the private 256-entry palette. Exclude index 255;
   exclude 232–239 unless the tested special effect explicitly requires them.
4. Use no diffusion dithering on the outside contour. Inside large forms,
   allow only deliberate, sparse ordered patterns that resemble the stock
   clustered texture.
5. Perform a manual pixel cleanup at 1× and 8× nearest-neighbor zoom. Restore
   eyes, teeth, weapon tips, feet, and one-pixel gaps lost in quantization.
6. Save with binary alpha and no color-management conversion that changes RGB
   triples.
7. Re-open every final file and report: dimensions, alpha values, opaque color
   count, unmatched RGB values, used palette indices, forbidden indices, and
   special-ramp indices.

Any unmatched opaque RGB, visible index 255 in native output, accidental use of
232–239, or alpha other than 0/255 fails the build.

## Master production workflow

### 1. Expand the short idea into a restrained brief

Accept the user's description without forcing an art questionnaire. Infer
conservative defaults and write them down. Ask only when a choice would change
the monster's identity or state topology.

The brief must define:

- one-sentence identity and combat role;
- movement method, speed impression, attack method, and death behavior;
- body plan, approximate stock-relative height/width, and floor or flying
  baseline;
- three silhouette landmarks visible at 1×;
- dominant, secondary, shadow, highlight, and optional luminous color roles;
- weapon handedness and every other asymmetry;
- personality in pose: sentry, coward, brute, ambusher, technician, boss, etc.;
- any cloak, morph, disguise, summon, projectile, or phase-change requirement;
- the two closest stock reference families and what to borrow from each;
- what must **not** appear, including scenery, text, UI, realistic soft light,
  and details too fine for 64×64.

If the idea supplies no role, default to an ordinary mobile ranged alien—not a
boss—with four-frame rotated locomotion, a front attack, pain, and death. If it
supplies no palette, choose a stock-compatible dominant family not already
confusable with the nearest gameplay peer.

### 2. Inspect references privately

Create private contact sheets for the two closest stock families, their attack,
pain, death, and any comparable special effect. Include a 1× strip and an 8×
nearest-neighbor strip. Record bounding boxes, foot/hover baseline, maximum
width/height, frame cadence, view order, and color-index histogram.

Do not prompt an image model with the entire asset archive. Use the smallest
reference set that communicates scale, pixel treatment, and the specific state
being generated. This reduces character drift and accidental copying.

### 3. Freeze a state-and-angle manifest

Assign one four-character bank and a frame letter to every animation beat.
For each letter record:

```text
frame | state | beat | rotations (0 or 1–8) | tics | bright? | action | anchor
```

Also list separate projectile/impact banks and special transition states. Check
the manifest against the intended DECORATE state graph. Changing topology after
generation is allowed, but the manifest and code must change together.

### 4. Create and approve the identity frame

Generate the front idle frame first. Work at an integer multiple of the final
canvas if the generator cannot make controlled 64×64 pixels, then reduce with
nearest-neighbor only and hand-clean. The identity frame must pass these tests:

- silhouette, role, and scale read at 1×;
- three landmarks survive palette conversion;
- no stock monster can be mistaken for it at corridor distance;
- the body fits every planned action without arbitrary per-state rescaling;
- the exact palette test passes.

This approved frame becomes the locked identity reference for every later
strip. Do not continue from an unapproved concept image.

### 5. Generate the eight-view turnaround as one unit

Generate all eight views in one ordered strip or sheet using the approved front
frame. Never generate eight unrelated prompts and hope they agree. Require the
same anatomy, proportions, palette roles, handedness, equipment, light
direction, baseline, and apparent scale in every cell.

Compare adjacent views as a turntable. Track horns, eyes, shoulders, elbows,
weapon muzzle, cables, feet, and back details across all eight cells. Redraw
inconsistent cells; do not hide a mismatch with mirroring unless the design is
actually symmetrical.

### 6. Generate complete action strips

Make one whole animation at a time from approved identity/turnaround frames:

1. locomotion loop;
2. alert if needed;
3. attack telegraph through recovery;
4. pain;
5. death through terminal corpse;
6. projectile flight and impact;
7. special transitions such as cloak, disguise, morph, burrow, or phase change.

Describe exact beats and exact cell count in every prompt. Lock frame 1 when a
tool supports it. Evaluate the animation as a strip and a timed loop, not as a
collection of attractive poses. Preserve muzzle/hand contact, planted feet,
body volume, and action direction.

For rotated locomotion, either generate an entire multi-row sheet under one
identity lock or generate each four-frame directional row using the approved
turnaround view for that row. In both cases, compare the final 32 frames as a
single set before acceptance.

### 7. Normalize globally

Place every generated source frame on the shared 64×64 coordinate system.
Choose one scale for the monster and keep it. Align ground actors to the same
foot contact line and flying actors to the same designed hover height. Use the
identity frame's center of mass as a reference, but do not erase intentional
lunges, recoil, falls, or jumps.

Run three contact sheets:

- all states in frame order;
- every angle for each rotated frame;
- the same frame from every state overlaid at low opacity around the anchor.

The overlay should reveal intended motion, not scale pumping or a wandering
pivot.

### 8. Quantize and perform final pixel art

Apply the palette procedure above to all frames in one batch, then do manual
pixel cleanup. Batch conversion prevents subtly different nearest-color choices
between prompts or states. Recheck outlines under normal, night, and infrared
palette views. A clean normal view that turns into an unreadable mass under a
visor is not finished.

### 9. Split, name, offset, and package

Split sheets deterministically from a recorded grid; never crop cells by eye.
Write final names from the manifest, embed offsets, and place only original
files in this structure:

```text
my-monster.pk3/
├── DECORATE
└── sprites/
    ├── GSTKA1.png
    ├── GSTKA2.png
    └── ...
```

Keep the reproducible working directory outside the distributable package:

```text
monster-work/<slug>/
├── brief.md
├── manifest.csv
├── references/          # private; never distribute retail material
├── source-sheets/
├── normalized/
├── final/sprites/
├── previews/
└── reports/palette.json
```

### 10. Wire behavior to art

Prefer inheriting an existing Corridor 7 actor whose gameplay is closest to the
brief. For a self-contained custom level, the least invasive placement method
is to replace that class; every native XLAT slot for the original then spawns
the new actor. A skeletal example is:

```c
actor GlassStalker : C7Rodex replaces C7Rodex
{
    states
    {
    Spawn:
        GSTK A -1 NOP A_Look
        stop
    Path:
        GSTK ABCD 8 NOP A_Chase
        loop
    See:
        GSTK ABCD 5 NOP A_Chase
        loop
    Missile:
        GSTK E 4 A_FaceTarget
        GSTK F 6 bright A_WolfAttack(0, "*", 1.0, 24)
        GSTK G 5
        goto See
    Pain:
        GSTK H 5
        goto See
    Death:
        GSTK I 0 A_Fall
        GSTK J 6 A_Scream
        GSTK KLM 6
        GSTK N -1
        stop
    }
}
```

This is a naming/state example, not universal balance. Copy inherited sounds,
health, speed, drop behavior, attack action, and timing deliberately from the
chosen actor, then adjust only what the brief requires. `bright` makes the
entire frame fullbright; use it for a flash frame only when that is intended.

A native Corridor 7 map stores raw plane-1 object words. Those words become
actors through [`corridor7.txt`](../wadsrc/static/xlat/corridor7.txt); adding a
new DECORATE class alone does not create a new native placement value. A truly
new coexisting enemy slot therefore requires a coordinated XLAT addition,
non-conflicting raw values, editor catalog support, validation, and engine/mod
compatibility work. Do not silently assign a number. EC7Edit exports maps and
metadata only, so load the monster PK3 alongside its map pack.

### 11. Validate automatically

The validation report must fail on any of the following:

- a missing manifest file or an extra unmanifested final sprite;
- a filename whose bank/frame/rotation does not match the manifest;
- a rotated frame without exactly rotations 1–8, or a mixed `0`/rotated frame;
- dimensions and offsets that do not reconstruct the declared logical canvas;
- absent/wrong `grAb` offsets or inconsistent computed anchors;
- alpha values other than 0 and 255;
- opaque RGB outside the extracted Corridor 7 palette;
- index 255 in native opaque art, accidental 232–239, or undeclared use of
  208–231;
- empty frames, clipped opaque pixels, a corpse below the baseline, or a frame
  whose bounding box differs from the declared scale tolerance;
- DECORATE references to missing banks/letters or manifest frames never used by
  any state.

Warnings should cover excessive color count, isolated noisy pixels, large
frame-to-frame center shifts, a mirrored asymmetric feature, a muzzle that
moves independently of its weapon, and identical adjacent animation frames.

### 12. Validate visually and in-engine

Create nearest-neighbor previews at 1×, 4×, and 8× on transparent checker,
black, neutral gray, and representative Corridor 7 walls. Review:

- silhouette and pose at 1×;
- seamless locomotion loop and stable hover/foot plant;
- correct turntable order while circling both directions;
- attack anticipation, damage moment, muzzle alignment, and recovery;
- pain readability without looking like death;
- collapse, floor contact, and a stable terminal corpse;
- no edge fringe, scale pumping, anchor jump, view flip, or handedness swap.

Then load the companion mod with EC7Wolf and a small test map. Exercise idle,
pathing, chase, pain, attack, death, doors, corners, near/far distance, bright
and dark sectors, and all available renderer paths. Circle the living and dead
actor through 360 degrees. Repeat under normal view, night vision, and infrared;
specifically watch luminous and 208–239 colors. Review the console for missing
rotation/frame warnings.

If the monster replaces a stock class, test every native difficulty and
stationary/pathing placement variant for that class. Finally load the intended
custom level and verify encounter readability in its real lighting and wall
palette.

## Generation prompt templates

These prompts describe raster production, not lore writing. Attach only the
approved original frame(s) and the minimum private stock reference crop needed
for visual calibration.

### Identity frame

```text
Create one production sprite for a Corridor 7-style 1990s VGA ray-caster.
Monster: <identity and role>. Body: <body plan and stock-relative size>.
Silhouette landmarks: <three landmarks>. Pose: front-facing <idle/alert pose>.
Color roles: <dominant/secondary/highlight>, constrained to the supplied exact
palette swatch. Preserve crisp pixel clusters, hard dark contour, sparse
interior dithering, readable exaggerated features, and one consistent upper-left
light direction. Transparent background; no floor, shadow haze, scenery, text,
UI, border, labels, glow halo, soft alpha, antialiasing, or extra views. Keep the
whole body on a 64x64 logical canvas with bottom-center anchor (32,64). This is
a production game asset, not concept art.
```

### Eight-view turnaround

```text
Using the approved identity frame as a locked character reference, create one
ordered eight-cell turntable of the same monster. Cells are exactly: front,
front 3/4, profile, rear 3/4, rear, opposite rear 3/4, opposite profile,
opposite front 3/4. Preserve identical anatomy, apparent scale, palette roles,
handedness, equipment, landmark placement, light direction, baseline, and pixel
treatment. Every cell uses the same neutral idle beat and 64x64 logical canvas.
Transparent background. No labels, dividers inside cells, scenery, additional
poses, cropping, mirroring of asymmetric details, soft alpha, or smoothing.
Output one complete strip/sheet, not separate illustrations.
```

### Action strip

```text
Using the approved identity and relevant turnaround view as locked references,
create exactly <N> ordered frames for <state>. Beats: 1 <beat>; 2 <beat>; ...;
N <beat>. Preserve character identity, body volume, apparent scale, exact
palette roles, handedness, equipment, light direction, and bottom-center anchor.
Only the intended action may move the silhouette. Make timing readable at
35 Hz using the supplied tic plan. Transparent background; one consistent grid;
no labels, scenery, duplicated cells, in-betweens beyond N, glow haze, soft
alpha, antialiasing, or per-frame recentering. Crisp production pixel art.
```

### Critique/repair pass

```text
Audit this sprite set against its approved identity frame and manifest. Report
by filename: anatomy drift, scale drift, anchor drift, turntable reversal,
handedness changes, missing/extra features, palette-role drift, contour noise,
unreadable 1x details, clipped pixels, foot sliding, hover wobble, muzzle/hand
disconnects, weak attack telegraph, and death/corpse discontinuity. Do not
redesign the monster. Propose the smallest pixel-level repairs and identify any
strip that must be regenerated as a unit.
```

## Agent handoff template

An agent receiving only a short description should produce this before image
generation and proceed unless a flagged decision genuinely requires the user:

```text
User idea: <verbatim short description>
Inferred role: <ordinary/elite/ambusher/boss and attack>
Closest references: <family for silhouette>; <family for motion/state grammar>
Logical size/baseline: <width x height target; ground or hover>
Landmarks: <three>
Palette roles: <indices or exact extracted RGB choices; declared effects ramps>
Asymmetries: <list>
State manifest: <frames, rotations, beats, tics, actions>
Placement: replaces <existing C7 class/raw slot>, or explicit XLAT extension
Assumptions: <short list>
Approval required before generation: <only identity-changing questions, or none>
```

The agent should expose assumptions, not offload routine art direction to the
user. It should pause after the identity frame when interactive approval is
available; in unattended execution it should run the same acceptance tests and
continue only if they pass.

## Final release checklist

- [ ] User description and corrections are preserved in `brief.md`.
- [ ] All sixteen stock families were considered; the two relevant references
      and reasons are recorded.
- [ ] Behavior and visual state graph agree.
- [ ] Every moving directional state has the required eight views.
- [ ] Every special mechanic has a readable telegraph/transition.
- [ ] All frames share one scale and logical anchor.
- [ ] All opaque RGB values are exact members of the user's Corridor 7 palette.
- [ ] Alpha is binary; no fringe or antialiasing remains.
- [ ] Reserved, luminous, and cycling indices are declared and tested.
- [ ] Normal, night-vision, and infrared previews remain readable.
- [ ] Names, frame letters, rotations, offsets, and DECORATE references agree.
- [ ] Companion PK3 and map pack load together from a clean EC7Wolf setup.
- [ ] Stationary/pathing and all intended difficulty placements were tested.
- [ ] Retail sprites, palette files, contact sheets, guide pages, and game data
      are absent from the deliverable and version-control diff.

## Repository references

- [`corridor7.md`](corridor7.md) — palette cycling, visor behavior, and the
  overall Corridor 7 implementation record.
- [`corridor7-technical-strategy-compendium.pdf`](corridor7-technical-strategy-compendium.pdf)
  — evidence-graded technical and gameplay research.
- [`monsters.txt`](../wadsrc/static/actors/corridor7/monsters.txt) — authoritative
  EC7Wolf monster state graphs and combat actions.
- [`co7map.txt`](../wadsrc/static/co7map.txt) — retail sprite-page names.
- [`corridor7.txt`](../wadsrc/static/xlat/corridor7.txt) — native map object to
  actor translation.
- [`c7assets.py`](../tools/c7assets.py) — bounded retail asset and palette
  decoder/browser.
- [`r_sprites.cpp`](../src/r_sprites.cpp) — rotation parsing, missing-view
  detection, palette cycling, and luminous world-sprite behavior.
- [`pngtexture.cpp`](../src/textures/pngtexture.cpp) — `grAb` offsets and binary
  alpha handling.
- [`ec7edit-manual.md`](ec7edit-manual.md) — custom map-pack workflow and its
  current maps-and-metadata-only boundary.
