# Issue 21: foreground corner and rear-pane review

Jason identified the missing front-facing half of the 90-degree glass corner
in the reporter's first DOS/port comparison as the first priority, followed by
the extra window blocks in front of the ammo dispensers. This iteration
addresses those two rendering rules in software and OpenGL. The issue remains
subject to joint visual verification, including further angles and locations.

## Native evidence

The original retail executable and matched test setup are documented in
`github-issue-verification-2026-11-11.md`. The unmodified executable renders the
retail MAP04 record in a disposable MAP01 test slot, so the reference HUD says
floor 1. Geometry and camera positions are held constant between renderers.

The native frame routine at load-module 0xdbf8 renders an ordinary pass with
DS:c1aa=0, then a masked pass with DS:c1aa=1 when masked cells were encountered.
Hardware read watchpoints on the native wall-hit helpers confirm the selected
cell in that second pass without modifying the executable:

| View | Camera | Heading | Native column | Selected glass cell | Wall ID |
| --- | --- | ---: | ---: | --- | ---: |
| A | (23.5, 54.5) | 105 | 208 | (23,52) | 57 |
| B | (22.5, 54.5) | 150 | 160 | (21,54) | 57 |

View B directly exposes the foreground-face error: the old port's connected
horizontal run suppresses cell (21,54)'s East face. DOS draws that face. Its
large foreground pane and corner are restored by retaining native entry faces.

The native masked ray selects the first glass cell, rather than compositing
each successive glass cell seen through its holes. Removing subsequent native
glass layers also removes the spurious frames around the rear dispensers.

Private reference and comparison frames are in the parent workspace under
`analysis/verification/issues-2026-11-11/transparency-review`. Views A and B
include DOS, old-port, and prototype frames. Native executable/data and derived
commercial artwork are not included in this source change.

## Implementation

The shared renderer classifier identifies explicit 104/105 glass separately
from other masked walls. Both mesh generation and software ray recording retain
its perpendicular entry faces. Software records only the first native glass
hit in each column while continuing to trace the opaque scene behind it.

OpenGL draws opaque geometry, ordinary masks and sprites, then selects the
nearest complete native-glass surface in a color-disabled depth pass. The color
pass tests equal depth and applies the usual artwork opacity. A nearer sprite
retains its depth and color; a sprite behind the pane remains visible through
its holes. The viewmodel does not depth-test against that selection buffer.
Color writes and the ordinary depth function are restored afterward. No extra
GPU allocations are required. The API behavior is specified by the official
[color-write mask](https://registry.khronos.org/OpenGL-Refpages/gl4/html/glColorMask.xhtml)
and [depth comparison](https://registry.khronos.org/OpenGL-Refpages/gl4/html/glDepthFunc.xhtml)
references.

Collision, sight, simulation state, saves and network packets are unchanged.
Force-field doors and other masked surfaces retain their existing path.

## Validation

`tools/test_corridor7_glass.sh BUILD DATA` checks that adding an adjacent or
distant pane behind the first one cannot remove the foreground face or change
the visible scene. It also checks a sprite in front of the pane against a
no-glass control and requires a sprite behind it to remain visible through its
holes. The matrix covers software, nearest-sampled OpenGL, and filtered 4x-MSAA
OpenGL. Filtered sprite comparisons use the fully covered interior because
antialiased boundary pixels appropriately mix with a changed background.

Retail golden-scene parity covers MAP01, MAP04 and MAP05, including exact HUD
matching. Determinism checks compare repeated runs, interpolation settings and
renderers. Animated-door, definition and packaged-startup gates also apply.
These checks support the prototype; Jason's visual review of the restored
foreground corner and farther-pane removal is the next acceptance step.
