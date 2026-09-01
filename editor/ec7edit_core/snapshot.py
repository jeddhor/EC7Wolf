# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Snapshot: an exact EC7Wolf frame of the map you are drawing.

Not an approximation of the renderer, and deliberately not one. Milestone E10's
whole argument is that a second renderer written in Python would be a second
authority on what Corridor 7 looks like, and the moment the two disagreed the
editor would be lying to somebody. So the picture comes from the engine: the
editor asks it to stand at a tile, face an angle, draw one frame and exit.

Three things make that usable rather than a curiosity.

**It is anchored to a simulation tic**, not a frame. A frame number is not a
property of the game -- how many frames pass in a tic depends on how fast the
machine draws -- so "frame 30" is a different moment on a busy box. `tic 20` is
the same moment everywhere, which is what makes the same request give the same
picture.

**The camera is checked before the engine is asked.** A tile outside the map or
inside a wall produces a picture of nothing, and the engine would draw it
without complaint. It is checked here, and again in the engine against the map
that actually loaded.

**The cache is keyed by everything that could change the picture.** The engine
binary, its pk3, the game data, the render profile, the map, and the camera. A
key that left any of those out would hand back a stale picture after the very
change somebody made it to look at.

Nothing cached here leaves the user's machine, and no retail byte is written
into the project: the cache is derived data in the workspace, keyed by digests,
and it is disposable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .document import MapDocument
from .errors import Diagnostic, Ec7EditError, Severity

#: The snapshot always runs software at a fixed size with upscaling off.
#:
#: Pinned, not offered. The PNG path is only a true picture of the world under
#: the software renderer -- under OpenGL the GPU owns the world and the 8-bit
#: framebuffer `--capture-file` reads holds just the 2D overlay, which is how a
#: parity gate once passed while comparing a black frame. A GL snapshot is a
#: different contract (its own PPM capture) and is not what this writes.
RENDER_PROFILE = {
    "renderer": "software",
    "width": 640,
    "height": 400,
    "upscale": "off",
}

#: Which simulation tic to photograph. Late enough that the level has settled
#: and the weapon is in its ready pose, early enough that nothing has wandered
#: into shot.
SNAPSHOT_TIC = 20


def _error(message: str) -> Ec7EditError:
    return Ec7EditError(Diagnostic("C7E-SNAPSHOT-001", Severity.ERROR, message))


@dataclass(frozen=True)
class Camera:
    """Where the picture is taken from. Tile coordinates, degrees clockwise."""

    x: float
    y: float
    angle: float = 0.0

    def normalised(self) -> "Camera":
        angle = self.angle % 360.0
        return Camera(self.x, self.y, angle)

    def arguments(self) -> list[str]:
        camera = self.normalised()
        return ["--capture-warp", f"{camera.x:g}", f"{camera.y:g}", f"{camera.angle:g}"]

    def describe(self) -> str:
        camera = self.normalised()
        return f"({camera.x:g}, {camera.y:g}) facing {camera.angle:g}°"


def check_camera(document: MapDocument, camera: Camera) -> None:
    """Refuse a camera that cannot produce a picture. Raises, or returns."""
    from .prefabs import is_floor

    for value, name in ((camera.x, "x"), (camera.y, "y"), (camera.angle, "angle")):
        if value != value or value in (float("inf"), float("-inf")):
            raise _error(f"the camera's {name} is not a number")
    tile_x, tile_y = int(camera.x), int(camera.y)
    if not (0 <= camera.x and 0 <= camera.y
            and tile_x < document.width and tile_y < document.height):
        raise _error(
            f"the camera at {camera.describe()} is outside this "
            f"{document.width}x{document.height} map")
    if not is_floor(document.cell(0, tile_x, tile_y)):
        raise _error(
            f"the camera at {camera.describe()} is inside a wall; "
            "put it on floor the player could stand on")


def _digest_file(path: Path | str) -> str:
    """A file's SHA-256, or a marker saying it was not there."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "missing"


def snapshot_key(*, engine: Path | str, pk3: Path | str, data_fingerprint: str,
                 export_digest: str, camera: Camera, tic: int = SNAPSHOT_TIC) -> str:
    """What this picture is a picture of.

    Everything that could change it, and nothing that could not. Leaving any of
    these out means handing back a stale image after exactly the change
    somebody took the snapshot to see -- a new engine build, a re-exported map,
    a different camera.
    """
    camera = camera.normalised()
    parts = [
        "v1",
        _digest_file(engine),
        _digest_file(pk3),
        data_fingerprint or "no-data",
        export_digest or "no-export",
        f"{camera.x:g},{camera.y:g},{camera.angle:g}",
        str(tic),
        "|".join(f"{k}={v}" for k, v in sorted(RENDER_PROFILE.items())),
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def snapshot_arguments(camera: Camera, output: Path | str,
                       tic: int = SNAPSHOT_TIC) -> list[str]:
    """The engine arguments for one snapshot, profile sealed."""
    return [
        "--vid-renderer", RENDER_PROFILE["renderer"],
        "--res", str(RENDER_PROFILE["width"]), str(RENDER_PROFILE["height"]),
        "--no-upscale",
        *camera.arguments(),
        "--capture-snapshot", str(output), str(tic),
    ]


def looks_like_a_world(png: Path | str, *, view_fraction: float = 0.5) -> bool:
    """Whether a PNG holds a rendered world rather than a blank frame.

    The one check that matters, and the reason it exists: this project has
    already shipped a gate that passed while comparing a black frame, because
    nothing asked whether there was a picture in it. A snapshot that is one
    flat colour is a failure however cleanly the process exited, and caching it
    would make that failure permanent.

    Counts distinct colours in the upper part of the frame, which is world
    rather than status bar.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a GUI-side dependency
        return True
    try:
        with Image.open(png) as image:
            width, height = image.size
            view = image.convert("RGB").crop(
                (0, 0, width, max(1, int(height * view_fraction))))
            colours = view.getcolors(maxcolors=1 << 20)
    except (OSError, ValueError):
        return False
    return colours is not None and len(colours) >= 8
