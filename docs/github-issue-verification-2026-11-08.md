# GitHub issue verification — 8 November 2026

The nine-issue plan reviewed on 7 November covered #1 and #3–#10. Jason
subsequently authorized implementation where original-game claims could be
independently verified, and requested a running list for everything else.
Two further issues, #11 and #12, appeared on GitHub on 8 November. Their plans
below require approval before implementation.

## Implemented

| Issue | Evidence and resulting fix |
| --- | --- |
| [#1](https://github.com/jeddhor/EC7Wolf/issues/1) | Modern input defect, without an original-game compatibility claim. Equal mouse displacement lost turning at the shared ±100 command clamp and at fractional sensitivity division. Turning now has its own signed range and retains fractional motion; movement stays bounded. Network protocol advanced to 7; legacy demo recording applies the signed-byte command it records. |
| [#3](https://github.com/jeddhor/EC7Wolf/issues/3) | The MAP41 elevator openings use animated wall 73, rather than ordinary sliding-door tiles. The unmodified DOS executable permits shots through the open aperture, including a kill and floor-secured result in an isolated corridor. In the port, open marker 107 still carried a render tile that targeting and alien collision treated as solid. Sight, projectile collision and enemy traversal now recognize the open aperture. Closed apertures and solid glass retain blocking. |
| [#6](https://github.com/jeddhor/EC7Wolf/issues/6) | Retail MAP02 and a DOS use sequence identify the fan station as wall 93; wall 110 is decorative. The original consumes the station even at full charge, adds 100 charge (including above 100), and changes to wall 94 with its center lamp dark. Implemented that single-use behavior, rather than the initially proposed reusable charger. Old save trigger mappings are repaired while preserving spent textures. Editor prefab and catalog follow wall 93. |
| [#8](https://github.com/jeddhor/EC7Wolf/issues/8) | Original graphics and DOS inventory display pair red access with C7G0021, blue with C7G0020, and floor plan with C7G0019. Port icons now use those pairs. Three isolated HUD renders match the decoded original 8×16 graphics byte for byte. |
| [#9](https://github.com/jeddhor/EC7Wolf/issues/9) | Fresh DOS Corporal and Lieutenant games both show the floor-plan item and revealed inset map; Captain does not. Original floor setup checks rank <2 and grants item bit 0x20 / graphic 0x14. The port now grants the ordinary map token at floor entry, after travel, on rebirth, and after loading older saves at those ranks. Deathmatch is excluded. |
| [#7](https://github.com/jeddhor/EC7Wolf/issues/7) | Original probe state records at segment 39ac use idle shape 239 only for idle, and moving shapes 247/255/263/271 (B/C/D/E). Patrol records are B20, B5, C15, D20, D5, E15; chase records B10, B3, C8, D10, D3, E8, in native 70 Hz units. Port states now preserve those frames, pauses and durations, converting durations to DECORATE's 35 Hz units. |
| [#10](https://github.com/jeddhor/EC7Wolf/issues/10) | DOS walking captures and renderer 1cb7:0e81 establish the four ready poses. Data 4557:2c3e cycles 7,7,6,5,4,5,6,7 twice; 4557:2c1e supplies horizontal offsets 0…4…0…−4…−1. The artwork supplies vertical motion; the shotgun stays almost level. The port skipped intermediate poses and had not registered cosmetic pose sprites. Both are corrected in the shared rendering path. Phase progression accounts for elapsed tics and respects disabled bob. This restores the pose sequence, not the original DOS machine's frame-rate-dependent clock. |

Reference runs used the retail CD executable without patching it, in disposable
copies of legally owned data. Controlled fixtures removed unrelated enemies or
altered map placement; the executable, graphics and state tables were unchanged.
No commercial data, screenshots or recordings are included in this change.

## Original-game checks still needed from Jason

### #5 — Full-screen mini HUD

The original executable contains explicit view-size-21 HUD branches for health,
armor, ammunition/mines, visor, inventory, floor, remaining aliens and score
(e.g. 2f28:0b45, 0bb7, 0c96, 0ef1, 0f49 and 108c). The port omits that compact
HUD. However, the DOS reference configuration keeps clamping the maximum view
to size 20 according to its memory check. Captures made so far show the normal
status bar, **not** a verified mini HUD.

Please verify at the original game's largest view size:

- Which fields and numbers are visible, and their positions.
- Whether it appears automatically and whether the map/visor changes its layout.
- How health/armor/ammo above the ordinary graph maximum are displayed.

The approved implementation plan remains: reproduce that compact layout,
default it on at full screen, add a persistent Display toggle, and verify
updates, view-size changes, aspect ratios and software/OpenGL parity. Held
full-status display should continue to work. No HUD implementation is included.

### #4 — Music/effects balance

A difference reported by an issue author is not yet an independently calibrated
original/port comparison. PCM decoding, synthesized OPL, PCM effects and CD
music have different gain paths; a single arbitrary global adjustment would
not establish parity.

Please verify the original balance with stated Sound Blaster/music selections
and volume settings, using a repeatable scene (for example MAP01, M-16 shots,
then an elevator opening). Compare music alone, effects alone and combined;
identify AdLib versus CD music. Matched recordings or documented observations
will let us choose the correct gain path and test sliders, mute, restart,
track changes and clipping. No gain adjustment is included.

## New plans awaiting approval

### #11 — Level 5 invisible red-access pickup

Issue: https://github.com/jeddhor/EC7Wolf/issues/11

**Evaluation:** Reproduced using the attached `savegam2.ecs`. Starting near
(51,27) facing west, walking down row 27 grants red access without use input.
The retail object plane contains value 24 at (47,27), (43,27) and (39,27),
among other locations. The translator currently maps all such values directly
to `C7Static001 : Key`. This identifies a concrete investigation target; it
does not yet prove that the original considers these tiles pickups or switches.

**Plan:** Reproduce the same corridor in DOS, inspect the original static-object
spawn/use and tile context, then trace port spawning, rendering and pickup.
Determine whether these words are context-dependent map metadata, console
markers or actual items. Correct the responsible translator/activation or
visibility behavior using that evidence. Do not delete the map words or force
all keys visible without knowing their meaning. Repair already serialized
actors if an old-save spawn is part of the bug.

**Acceptance:** The supplied save and a fresh MAP05 agree with original access
acquisition; walking empty corridor does not grant unintended access; intended
red/blue terminals and keys still work; software/OpenGL visibility, save/load
and the other value-24 locations are checked. Medium risk/effort because a
translator fix may affect every floor. If original behavior cannot be verified,
retain this issue on the original-game check list.

### #12 — Optional shotgun and HUD enhancements

Issue: https://github.com/jeddhor/EC7Wolf/issues/12

This is two opt-in feature proposals, separate from compatibility fixes.
Neither is implemented. The strategy-guide damage claim and any assertion
about the original full-screen numbers still require verification before they
are described as original behavior.

**Shotgun evaluation:** Current code computes 100–355 damage inside two tiles,
50–220 inside four, and 25–195 farther away. It already exceeds the requested
50-point close-range minimum. These are code-derived port ranges, not a claim
that the strategy guide or original executable uses them.

**Shotgun plan:** Verify the executable and guide first. Keep classic damage
as the default. If approved, add an explicitly named option imposing a minimum
of 50 on the final shotgun damage after distance calculation, while retaining
its existing maxima and rate of fire. With the present formula this mainly
buffs distant shots. Any intended close-range buff needs a different agreed
rule; do not silently change timing or increase the peak. Persist the rule
and serialize/advertise it as an authority-owned multiplayer setting so peers,
replays and saves agree. Playtest at close and medium ranges before considering
any further buff. Acceptance: deterministic minimum/maximum and distance
checks, kills of 50-health targets in enhanced mode, unchanged
classic behavior, save/load and multiplayer agreement. Medium risk/effort.

**HUD plan:** After resolving #5, add an independent persistent Display option
for exact numeric health, armor and ammunition on the large status bar. Keep
classic graphs as the default. Exact totals (including over-max values) are
less ambiguous than a new multi-layer bar scheme. Verify changing values,
over-max depletion, clipping at every aspect ratio, view-size switching and
software/OpenGL parity. Low-medium risk/effort. Approval can select either
feature independently.

## Validation

Focused runtime gates cover equal-displacement mouse input; animated apertures
in four directions and multiple wall families with closed controls; real visor
save/load and old-trigger migration; all five ranks across three floors and a
real floor transition; probe movement frames/durations read directly from the
original executable; all eight weapon cycles in both renderers; running and
disabled bob. Editor prefab/catalog tests and generated-resource verification
also passed. Shared regression and packaged startup results are recorded in the
local verification report after completion.
