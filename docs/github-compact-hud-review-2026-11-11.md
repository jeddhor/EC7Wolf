# Compact HUD and full-screen weapon follow-up

Jason identified two differences while reviewing the matched DOS/port glass
captures: opaque backgrounds inside the lower compact meters and a weapon
that showed substantially less of the gun and hand at rest.

Both differences reproduce with the unmodified retail executable in a
controlled, stationary view-21 room. DOS leaves the unfilled part of each
compact meter transparent, including the initially empty armor and mines
meters on the lower row. The port added a black rectangle before drawing each
gauge. Removing that rectangle preserves the original border, numbers and
filled gauge while exposing the rendered scene in the unfilled area. The
three large right-hand readout boxes retain their native black backgrounds.

The native weapon setup at 1e37:0061 initializes each weapon's scaler entry
at DS:b82a from view height / 4. The weapon draw at 1cb7:0e81 uses that entry;
2163:000a selects its vertical VGA offset from DS:1558. At full-screen view 21
the measured values are height 200, scaler 50 and offset 4000 bytes (50 VGA
rows), giving a 100x100 logical weapon canvas anchored at y=100. At view 20
the canvas is 80x80. The port retained its 80x80 scale and applied the inherited
32-unit full-screen downward adjustment, making the weapon smaller and lower.

Full-screen C7 viewmodel placement now derives its scale from view height,
centers the enlarged canvas, and retains the native anchor. The texture
offset's half-unit component is canceled exactly. The placement function is
shared by software and OpenGL, including weapon animation frames and walk
poses. It also handles loaded weapons carrying the old serialized yadjust.
The standard status-bar view and other games' positioning retain their
existing calculation.

`tools/test_corridor7_compact_hud.sh BUILD DATA` compares all eight resting
weapon bounds with DOS measurements, allowing one native pixel for scaler
rounding. It checks empty and partly depleted meters against a HUD-hidden
control, requires the outlines/readouts to remain visible, and covers native
resolution and widescreen placement in both renderers. Matched before/after
captures also verify that the standard status-bar view is pixel-identical to
the previous build. Retail software/OpenGL scene parity and the required
packaged startup gate provide additional checks.

Private screenshots are in the parent workspace's
`analysis/verification/issues-2026-11-11/transparency-review/compact-hud-review`.
They include a DOS / previous port / corrected OpenGL comparison. Commercial
artwork and game files remain outside the source commit. Visual review of
issue 21 remains open; this follow-up does not publish a release or close it.
