# Alien facing and attack timing: GitHub #28 and #29

- **#28** Animated Probes look diagonal while flying straight at the player,
  perhaps a widescreen effect.
- **#29** On Major in beta302, a Rodex hits the player the moment it is in
  range, without an attack frame and sometimes without facing the player.

Both are real. #29 was introduced in beta302 by the combat rework
([github-issue-verification-2026-11-15.md](github-issue-verification-2026-11-15.md));
#28 is older than Corridor 7 support and affects every rotated sprite.

Baseline: EC7Wolf 1.0-beta302. Engine base: ECWolf 1.4.2-9-g1bff92d
(18 February 2026), on the upstream 1.5.0pre line.

## #29: a released action runs as its frame ends

The original's actor loop (CORR7CD.EXE bc70, Wolf3D's `DoActor`) counts a
state's tics down and, when they run out, calls that state's *action* and
moves to the next state; the state's *think* runs every frame. So the action
of a frame happens at its end. ECWolf runs a DECORATE action when the state is
entered. Its own Wolf3D guards account for this: Wolf3D's `T_Shoot` belongs to
the second shooting frame, and ECWolf's guard fires on the third.

beta302 transcribed each alien's attack chain without that shift, so every shot
came one frame early. For aliens whose first attack frame carries the
sound-and-shoot action (18455) -- Rodex, Tenaj, Ttocs, Otrebor, the Mechanoid
-- the first shot landed on the very tic the alien decided to attack, before any
attack frame had been drawn. A Rodex chain is 233 (6 tics, 18455), 234 (20),
235 (10, `T_Shoot`), 236 (20): in the original the first round lands six tics in,
as 234 appears.

Every alien `Missile` sequence now carries each released action on the frame
after the one that owns it, with a zero-tic state where the last frame's action
falls at the hand-back to the chase. The three per-frame shooters (Nerraw and
Eniram's `T_Shoot`, the Semaj's bite) are think functions and were already
right; the Eniram's two sound cues move to their frames' ends. A lab corridor
on Major with one Rodex: from entering the attack to the first hit, beta302
measured 0 tics on half the volleys; now 6, or 36 when the first round misses
and the second lands.

Facing: an attack frame in the original is not rotated (its state's rotate flag
is 0), so it is always drawn face-on, and `A_WolfAttack` turns the alien to the
player. A shot that came before the attack frame was the one that could appear
to come from an alien looking elsewhere.

## #28: the rotation frame came from the view direction

Which of eight rotation frames to draw depends on the angle between the
alien's facing and the line from the eye to the alien. Wolf3D's `CalcRotate`
approximated that line as the view angle plus `(centerx - viewx)/8`: a screen
offset in pixels, divided by eight, read as degrees, since Wolf3D's angles run
0..359. ECWolf kept the expression but its angles are 32-bit, where the same
few hundred units are no correction at all. The frame was therefore chosen from
the direction the player looks, not the direction to the alien, and anything
off the centre of the view was drawn as if seen from straight behind the
player's crosshair. A wide screen puts the edges of the view far enough off it
to cross a 22.5-degree boundary.

`CalcRotate` now takes the bearing from the coordinates `TransformActor` has
already computed (`atan2(-transy, transx)`), so the frame matches the line of
sight at every resolution and aspect ratio, in both renderers, which share the
function. Rendering only; the simulation is untouched. Measured: a Probe flying
straight down a corridor at a player turned 25 degrees away was drawn with
rotation 1 (front-diagonal); it is now rotation 0, face-on, with the bearing
computed as -24 degrees.

At the original's 320x200 the approximation corrected about half the true
angle, so near the edges of a 4:3 view the port can now pick the neighboring
frame where DOS did not. That is the original's stated intent ("it should vary
by a trig value, but it is close enough") rather than its approximation, and
the approximation cannot be kept for wider views without bringing #28 back.

## Tests

The definition checks pin the attack sequences against the new timing and
forbid a shot on the first frame of any alien attack. `--capture-actors-player`
now also records each alien's facing angle, which is how the Probe's angle was
shown to match its direction of travel.
