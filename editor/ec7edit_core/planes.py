# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""The canonical in-memory plane model and the coordinate convention.

Frozen here so that no other module gets to have an opinion about it:

* origin `(0, 0)` is the native top-left cell;
* `x` grows to the right, `y` grows downward;
* the linear index is `y * width + x`;
* file plane order is 0, 1, 2.

The canvas is free to draw compass north upward. Raw coordinates never rotate
to suit a view -- the moment they do, an exported map stops matching the one
on screen in a way no test would catch.

A cell is not one value. Geometry lives in plane 0, objects in plane 1, and
plane 2 carries data this editor preserves without claiming to understand, so
all three are kept side by side and none is ever synthesised from another.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Both dimensions are u16 in the file, but the engine refuses anything larger.
MAX_DIMENSION = 181
MIN_DIMENSION = 1

#: Exactly three, always. The four-plane case in the engine is Rise of the
#: Triad's, reached by a different loader path that Corridor 7 never takes.
PLANE_COUNT = 3


def linear_index(x: int, y: int, width: int) -> int:
    """The one place the row-major convention is spelled out."""
    return y * width + x


def coordinates(index: int, width: int) -> tuple[int, int]:
    """Inverse of `linear_index`, for turning a diagnostic offset into a cell."""
    return index % width, index // width


def validate_dimensions(width: int, height: int, *, where: str = "") -> None:
    """Reject what `FGamemaps::Open` would reject, with the same thresholds."""
    from .errors import native_error

    for name, value in (("width", width), ("height", height)):
        if not MIN_DIMENSION <= value <= MAX_DIMENSION:
            raise native_error(
                "C7E-BOUNDARY-001" if value == 0 else "C7E-NATIVE-001",
                f"{name} {value} is outside the engine's {MIN_DIMENSION}..{MAX_DIMENSION}",
                where,
            )


@dataclass(frozen=True)
class MapPlanes:
    """Three independent `width * height` arrays of unsigned 16-bit words.

    Immutable: editing produces a new snapshot. That is what makes undo cheap
    and what stops a background thread from seeing half an edit.
    """

    width: int
    height: int
    planes: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]

    def __post_init__(self) -> None:
        from .errors import native_error

        validate_dimensions(self.width, self.height)
        if len(self.planes) != PLANE_COUNT:
            raise native_error(
                "C7E-SCHEMA-002", f"expected {PLANE_COUNT} planes, got {len(self.planes)}"
            )
        expected = self.width * self.height
        for number, plane in enumerate(self.planes):
            if len(plane) != expected:
                raise native_error(
                    "C7E-SCHEMA-002",
                    f"plane {number} holds {len(plane)} cells, "
                    f"{self.width}x{self.height} needs {expected}",
                )

    @property
    def cell_count(self) -> int:
        return self.width * self.height

    def at(self, plane: int, x: int, y: int) -> int:
        """Read one cell. Bounds are the caller's business, deliberately."""
        return self.planes[plane][linear_index(x, y, self.width)]

    def rows(self, plane: int):
        """Iterate the plane a row at a time, top row first."""
        data = self.planes[plane]
        for y in range(self.height):
            begin = y * self.width
            yield data[begin : begin + self.width]

    @classmethod
    def empty(cls, width: int, height: int) -> "MapPlanes":
        blank = (0,) * (width * height)
        return cls(width, height, (blank, blank, blank))

    def with_plane(self, plane: int, values: tuple[int, ...]) -> "MapPlanes":
        replaced = list(self.planes)
        replaced[plane] = tuple(values)
        return MapPlanes(self.width, self.height, tuple(replaced))  # type: ignore[arg-type]
