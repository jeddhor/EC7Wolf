# Wall lights, first-person brightness and Classic meters

Jason confirmed the transparency correction and reported dim ammo-dispenser
lights, dark hands/weapons, a short colored meter well, and an apparent extra
score field. Dispenser activation was resolved as a key-binding difference:
the review profile uses E rather than DOS's Space. Its interaction logic is
unchanged by this follow-up.

## Native evidence and corrections

The unmodified retail executable has SHA-256
`1287a13c2ac16624a1eb70ae1d207ad293e3aef6b852fa3d3f5eb6591d1c30f7`.
Controlled captures use retail MAP04 in a disposable MAP01 slot, so the native
HUD says floor 1. Only camera/fixture state is instrumented; executable
instructions are not modified.

At dispenser (26,53), native cameras (24.5,53.5) and (22.5,53.5), heading 0,
retain exact source colors 250..253 for the loaded yellow indicator. After
using the dispenser with room for ammunition, wall 111 becomes 112; its red
indicator retains source colors 242..247 at both distances. The generated
native scaler masks its darkening amount with the table at DS:2a1e; entries
240..254 are zero. The port already protected animated 208..239 lamps but
omitted the static red/yellow range. Both software and OpenGL now include it.
Row-zero colormaps also preserve those original indices, including under the
infrared palette. Ordinary white index 39 and the housing remain shaded.

The native first-person weapon uses source-brightness palette colors. The
measured M16 hand color (170,93,56) occurs in the native capture but was absent
from the old port's hand region. The shared viewmodel placement now selects
the unshaded palette row for C7 in both renderers, at full and reduced view
sizes. Palette/visor changes and native weapon-color cycling still apply.
Other games' viewmodel light selection is unchanged.

Classic meter borders already matched the native seven-row rectangle. The
fill included its top-border row but missed the last interior row, letting the
last numeral row lie over the scene. Filling one additional native row fixes
the apparent two-pixel shortfall at 640x400. Drawing bevel sides after the
bottom edge also preserves the native bright lower-left corner. The three
fully filled upper meters now match the DOS capture pixel for pixel in both
renderers. Unfilled meter areas remain transparent.

The long right-hand field is native score. A real S-key playtest hides it and
restores it; the restored score rectangle is pixel-identical. Native status
flags at DS:80cc initialize to 3, so score is visible in a fresh game. The port
now exposes Graphics > Mini HUD Score for either compact style, defaulting on.
Disabling it removes the complete score panel while retaining alien/floor
readouts, and persists as `C7MiniHUDScore`. The normal status bar is unaffected.

## Verification

`tools/test_corridor7_wall_lamps.sh BUILD DATA` requires exact source lamp
colors at near/far distances in software and OpenGL, in normal and infrared
views, and checks that the neighboring white indicator remains shaded.
`tools/test_corridor7_compact_hud.sh BUILD DATA` covers the measured meter row
and bevel, native hand color, optional score panel and persistence, all eight
weapon bounds, transparent empty/partial meters, native/widescreen placement,
and restoration of the full status-bar view when compact HUD is disabled.
Retail renderer parity, GL filtering/palette/MSAA, an actual score-checkbox
menu test, and the required packaged startup gate provide additional checks.

Private native/before/after frames, tables, comparison figures and results are
under the parent workspace's transparency-review/dispenser-review directory.
Commercial files and derived artwork are excluded from the source commit.
