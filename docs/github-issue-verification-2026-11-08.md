# GitHub issue verification — 8 November 2026

The nine-issue plan reviewed on 7 November covered #1 and #3–#10. Jason
subsequently authorized implementation where original-game claims could be
independently verified, and requested a running list for everything else.
Two further issues, #11 and #12, appeared on GitHub on 8 November. Jason
approved both plans and an optional mini HUD on 8 November. Those changes
are now implemented. Music/effects balance (#4) remains deferred.

## Implemented

| Issue | Evidence and resulting fix |
| --- | --- |
| [#1](https://github.com/jeddhor/EC7Wolf/issues/1) | Modern input defect, without an original-game compatibility claim. Equal mouse displacement lost turning at the shared ±100 command clamp and at fractional sensitivity division. Turning now has its own signed range and retains fractional motion; movement stays bounded. The turn change advanced the network protocol to 7 (the later shotgun rule advances it to 8); legacy demo recording applies the signed-byte command it records. |
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

## Additional completed issues

### #5 — Optional full-screen mini HUD

Jason's screenshot and the DOS reference runs show the normal status bar at
maximum available original-game view size. Although the executable contains
view-size-21 HUD branches, their presence does not establish an accessible
original mini mode. This implementation is an approved **port enhancement**,
not a claim that the observed retail game has a mini HUD.

`Options > Graphics > Full-screen Mini HUD` controls the compact overlay at
100% port view size. It is enabled there by default; the normal default view
size retains the existing full status bar. The overlay shows health, armor,
ammunition, mines, visor charge, floor, remaining aliens, score/frags and owned
access/map icons. The native small font remains readable at 320×200. Holding
Show Status draws the full bar in either renderer, independently of the mini
HUD setting. Values and icons occupy separate regions, including stacked armor.

### #11 — Ceiling lamps incorrectly grant access

The original statinfo rows for map words 24 and 25 contain `(shape,type)` pairs
`(2,0)` and `(3,0)` at data 4557:1908. Original spawn routine 2353:000f treats
type 0 as decoration. A DOS run of the affected MAP05 corridor, with the
unmodified executable, crossed the lamps without use input and granted no
access. The visible red ceiling lamp also identifies the artwork's purpose.

The translator now spawns `C7RedCeilingLamp` and `C7BlueCeilingLamp` as ordinary
decorations. Existing access-token classes remain available to terminals and
old inventories. Loading an older save replaces their erroneous world actors
with matching lamps while retaining owned access tokens. The editor catalog
now describes lamps and directs access searches toward the wall terminals.
Editor validation/reachability fixtures use actual terminals and explicitly
assert that neither ceiling-lamp color grants access.

Already acquired access is retained: old saves do not record whether a token
came from a legitimate terminal or the former bug, so revoking it would also
remove legitimate progress. Fresh traversal and saves made before collection
are corrected. Runtime checks cover MAP05 in both renderers, synthetic old
saves, owned tokens and both real terminal colors.

### #12 — Independent optional enhancements

`Options > Graphics > Numeric Status Bar` replaces the large bar's health,
armor and ammunition meters with exact totals. It defaults off. A small numeric
face fits the existing meter wells and displays the full native armor range,
including 65,535, without saturation. It is independent of the mini HUD toggle.
Both HUD preferences persist in configuration.

`Options > Gameplay > Shotgun Minimum 50` enables the approved final-damage
floor after the existing distance calculation. It defaults off and applies to
new games. The menu also shows the current mission's effective rule. The
host's choice controls multiplayer; an opposing client preference cannot alter
it. Network protocol 8 carries the rule in the authority's new-game packet.

The rule is saved in the `EC7Wolf Enhanced Shotgun` PNG metadata field, avoiding
changes to the existing snapshot layout. Loading restores the saved rule even
when the user's current preference differs. Older saves without the field use
classic behavior. Legacy demo recording and playback retain classic damage
because their file format cannot encode this option.

Matched live hit sequences at one, three and seven tiles confirm that only
hits below 50 change: sampled long-range hits of 27 and 44 become 50. Other
sampled hits, firing rate, ammo use and the upper damage formula are unchanged.
The existing surprise-damage and difficulty paths remain in force.

The issue's quoted guide range (35–350) is not independently established. The
local compendium quotes 25–350; that secondary document is not a measurement
of the executable. This discrepancy did not justify changing the classic
formula. The optional floor is an approved balance choice, rather than a
restoration of a claimed original range.

## Deferred original-game check

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

## Validation

Focused runtime gates cover equal-displacement mouse input; animated apertures
in four directions and multiple wall families with closed controls; real visor
save/load and old-trigger migration; all five ranks across three floors and a
real floor transition; probe movement frames/durations read directly from the
original executable; all eight weapon cycles in both renderers; running and
disabled bob. Editor prefab/catalog tests and generated-resource verification
also passed. Additional end-to-end checks cover both lamp colors and old-save repair,
matched shotgun hit sequences at three distances, saved/legacy rules, two
opposing host/client configurations with 350 identical world checksums each,
actual HUD digits in software and live OpenGL, independent persisted toggles,
held full-status display, maximum armor and widescreen captures. The new menu
controls were also exercised interactively. Shared command, hostile-packet,
determinism and floor-transition checks passed. Final packaging/startup results
are recorded in the local verification report.
