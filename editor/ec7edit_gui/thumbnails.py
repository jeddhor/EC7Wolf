# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jason Tripp
"""Turning a catalog entry into a picture, using the user's own game data.

The catalog says *which* wall page or sprite page a thing is. This is where
that becomes pixels — read from the copy of Corridor 7 the user pointed the
editor at, decoded in memory, and cached in memory. Nothing is written to disk.

That is the licensing boundary made concrete: the catalog is a file this
project can ship, and the artwork is not, so the artwork is never in the
catalog, never in a project file, and never in a cache on disk. It exists
while the editor is running and then it is gone.

An entry whose page will not decode still gets a tile — a labeled placeholder
rather than a gap. A palette that silently omits broken items is a palette that
hides the fact something is wrong with the data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from ec7edit_core.assets import (
    AssetError,
    ImageCache,
    average_color,
    load_palette,
    parse_gfx_header,
    sprite_rgba,
    wall_rgb,
)
from ec7edit_core.catalog import CatalogEntry

#: Wall value 1 is page 0, and the catalog records the value.
WALL_PAGE_OFFSET = 1


@dataclass
class AssetSource:
    """The user's game data, opened once and read from many times."""

    data_dir: Path
    palette: list[int]
    gfx: bytes
    header: object
    fingerprint: str = ""

    @classmethod
    def open(cls, data_dir: Path | str, *, fingerprint: str = "") -> "AssetSource":
        data_dir = Path(data_dir)
        palette = load_palette((data_dir / "CORR7CD.EXE").read_bytes())
        gfx = (data_dir / "GFXTILES.CO7").read_bytes()
        return cls(data_dir, palette, gfx, parse_gfx_header(gfx), fingerprint)

    def wall(self, page: int) -> bytes:
        if not 0 <= page < self.header.sprite_start:
            raise AssetError(f"wall page {page} is outside 0..{self.header.sprite_start - 1}")
        return wall_rgb(self.header.chunk(self.gfx, page), self.palette)

    def sprite(self, page: int) -> bytes:
        index = self.header.sprite_start + page
        if not self.header.sprite_start <= index < self.header.sound_start:
            raise AssetError(f"sprite page {page} is outside the artwork")
        return sprite_rgba(self.header.chunk(self.gfx, index), self.palette)


class ThumbnailFactory:
    """Catalog entry to `QPixmap`, cached by key, size and data fingerprint.

    The fingerprint is in the key because a user may repoint the editor at a
    different copy of the game -- a different rip, a patched executable -- and
    a cache that ignored that would show the old pictures indefinitely.
    """

    def __init__(self, source: AssetSource | None = None, *, budget_bytes: int = 32 << 20) -> None:
        self.source = source
        self._pixels = ImageCache(budget_bytes)
        self._pixmaps: dict[str, QPixmap] = {}

    @property
    def available(self) -> bool:
        return self.source is not None

    def key_for(self, entry: CatalogEntry, size: int) -> str:
        fingerprint = self.source.fingerprint if self.source else "none"
        return f"{fingerprint}:{entry.key}:{size}"

    def pixels_for(self, entry: CatalogEntry) -> tuple[bytes, int, bool]:
        """Decoded pixels, their edge length, and whether they have alpha.

        Runs off the GUI thread. Returns buffers, not Qt objects: a QPixmap may
        only be made on the GUI thread, and a worker that built one would
        either crash or quietly corrupt the display.
        """
        if self.source is None:
            raise AssetError("no game data is open")

        if entry.category in ("walls", "specials") and entry.texture:
            page = entry.value - WALL_PAGE_OFFSET
            return self._pixels.fetch(f"wall:{page}", lambda: self.source.wall(page)), 64, False
        if entry.sprite is not None:
            page = entry.sprite
            return self._pixels.fetch(f"sprite:{page}", lambda: self.source.sprite(page)), 64, True
        raise AssetError(f"{entry.key} has no artwork to draw")

    def image_from(self, pixels: bytes, edge: int, alpha: bool) -> QImage:
        """Wrap decoded bytes as a QImage. GUI thread only."""
        fmt = QImage.Format_RGBA8888 if alpha else QImage.Format_RGB888
        stride = edge * (4 if alpha else 3)
        # copy(): the QImage must not alias a Python buffer that may be freed.
        return QImage(pixels, edge, edge, stride, fmt).copy()

    def placeholder(self, entry: CatalogEntry, size: int) -> QPixmap:
        """A labeled tile for an entry with no artwork, or artwork that failed.

        Color comes from the entry's own key, so the same thing is the same
        color every time and a palette of placeholders is still scannable.
        """
        pixmap = QPixmap(size, size)
        tint = QColor.fromHsv((hash(entry.key) % 360), 70, 90)
        pixmap.fill(tint)
        painter = QPainter(pixmap)
        painter.setPen(QColor(235, 235, 235))
        painter.drawRect(0, 0, size - 1, size - 1)
        label = str(entry.value)
        font = painter.font()
        font.setPixelSize(max(8, size // 3))
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, label)
        painter.end()
        return pixmap

    def cached(self, entry: CatalogEntry, size: int) -> QPixmap | None:
        return self._pixmaps.get(self.key_for(entry, size))

    def store(self, entry: CatalogEntry, size: int, pixmap: QPixmap) -> QPixmap:
        self._pixmaps[self.key_for(entry, size)] = pixmap
        return pixmap

    def swatch(self, entry: CatalogEntry, size: int = 16) -> QColor:
        """The average color of an entry's artwork, for a compact list."""
        try:
            pixels, _, alpha = self.pixels_for(entry)
        except AssetError:
            return QColor.fromHsv((hash(entry.key) % 360), 70, 90)
        if alpha:
            opaque = bytearray()
            for index in range(0, len(pixels), 4):
                if pixels[index + 3]:
                    opaque += pixels[index : index + 3]
            pixels = bytes(opaque)
        return QColor(*average_color(pixels))

    def clear(self) -> None:
        self._pixels.clear()
        self._pixmaps.clear()

    @property
    def memory_bytes(self) -> int:
        return self._pixels.size_bytes
