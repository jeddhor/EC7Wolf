#!/usr/bin/env python3
"""Build c7_assets_upscaled.pk3 — Real-ESRGAN upscales of the Corridor 7 art.

Drop this file into the directory that holds the Corridor 7 data (GFXTILES.CO7,
VGAGRAPH.CO7, VGADICT.CO7, VGAHEAD.CO7, CORR7CD.EXE and ec7wolf.pk3) and run
it:

    python3 make_c7_upscaled_pk3.py

It will download the Real-ESRGAN ncnn/Vulkan binary if it isn't cached yet,
decode every wall page, sprite page and VGAGRAPH picture (loading screen,
credits, briefings, status bar, HUD pieces — everything the game draws),
upscale all of them, and write c7_assets_upscaled.pk3 next to the data files.

The upscaled images go into the pk3's hires/ namespace under the same lump
names the engine gives the originals, which is the namespace ECWolf already
resolves through FTextureManager::AddHiresTextures(): each replacement keeps
the original texture's scaled size and offsets, so nothing has to be redefined
in TEXTURES and no game code has to know the art got bigger.

Only the Python 3.8+ standard library is required; the originals are never
modified.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
import zlib
from collections import deque
from pathlib import Path

# --------------------------------------------------------------------------
# Real-ESRGAN ncnn/Vulkan bundle
# --------------------------------------------------------------------------

# The bundles published on the Real-ESRGAN releases page carry the binary and
# the pre-trained models together, which is what makes the "just run it"
# workflow possible. The ncnn-vulkan repository's own releases ship the binary
# without models, so don't switch to those.
BUNDLE_RELEASE = "v0.2.5.0"
BUNDLE_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/"
    f"{BUNDLE_RELEASE}/realesrgan-ncnn-vulkan-20220424-%s.zip"
)

# platform -> (bundle suffix, sha256 or None if unverified, binary name)
BUNDLES = {
    "linux": (
        "ubuntu",
        "e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96",
        "realesrgan-ncnn-vulkan",
    ),
    "darwin": ("macos", None, "realesrgan-ncnn-vulkan"),
    "windows": ("windows", None, "realesrgan-ncnn-vulkan.exe"),
}

# model name -> native scale, or None when the model comes in per-scale
# variants that the tool selects through -s.
MODELS = {
    "realesrgan-x4plus": 4,
    "realesrgan-x4plus-anime": 4,
    "realesrnet-x4plus": 4,
    "realesr-animevideov3": None,
}

DEFAULT_MODEL = "realesrgan-x4plus"

# Lumps a generative upscaler reliably ruins, checked by eye; see the file.
KEEP_FILE = "c7_upscale_keep.txt"


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    return Path(base if base else Path.home() / ".cache") / "ec7wolf-upscale"


def download(url: str, dest: Path) -> None:
    """Fetch a URL to a file, printing a single-line progress indicator."""
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as response:
        total = int(response.headers.get("Content-Length") or 0)
        read = 0
        last = 0.0
        with open(part, "wb") as out:
            while True:
                block = response.read(256 * 1024)
                if not block:
                    break
                out.write(block)
                read += len(block)
                now = time.monotonic()
                if now - last > 0.25:
                    last = now
                    if total:
                        progress(f"downloading {dest.name}", read, total)
                    else:
                        progress(f"downloading {dest.name}", read // 1024, 0, unit="KiB")
    progress_done()
    part.replace(dest)


def ensure_tool(cache: Path, tool: str | None, models: str | None) -> tuple[Path, Path]:
    """Return (binary, models directory), downloading the bundle if needed."""
    if tool:
        binary = Path(tool).expanduser().resolve()
        if not binary.is_file():
            raise SystemExit(f"--tool {binary} does not exist")
        model_dir = Path(models).expanduser() if models else binary.parent / "models"
        if not model_dir.is_dir():
            raise SystemExit(f"no models directory next to {binary}; pass --models")
        return binary, model_dir

    system = platform.system().lower()
    if system not in BUNDLES:
        raise SystemExit(
            f"no Real-ESRGAN bundle known for {platform.system()}; "
            "install realesrgan-ncnn-vulkan yourself and pass --tool"
        )
    suffix, digest, binary_name = BUNDLES[system]
    root = cache / f"realesrgan-{BUNDLE_RELEASE}-{suffix}"
    binary = root / binary_name
    model_dir = Path(models).expanduser() if models else root / "models"

    if not binary.is_file():
        root.mkdir(parents=True, exist_ok=True)
        archive = cache / f"realesrgan-ncnn-vulkan-{BUNDLE_RELEASE}-{suffix}.zip"
        if not archive.is_file():
            download(BUNDLE_URL % suffix, archive)
        if digest:
            got = hashlib.sha256(archive.read_bytes()).hexdigest()
            if got != digest:
                archive.unlink()
                raise SystemExit(
                    f"checksum mismatch for the Real-ESRGAN bundle\n"
                    f"  expected {digest}\n  got      {got}"
                )
        with zipfile.ZipFile(archive) as zf:
            # The bundles are flat, but stay defensive about member paths.
            for member in zf.infolist():
                name = member.filename
                if name.endswith("/") or name.startswith("/") or ".." in Path(name).parts:
                    continue
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        binary.chmod(0o755)

    if not binary.is_file():
        raise SystemExit(f"the Real-ESRGAN bundle did not contain {binary_name}")
    if not model_dir.is_dir():
        raise SystemExit(f"the Real-ESRGAN bundle did not contain a models directory")
    return binary, model_dir


# --------------------------------------------------------------------------
# PNG encoding and decoding (zlib only)
# --------------------------------------------------------------------------


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, pixels: bytes, *, alpha: bool, level: int = 6) -> bytes:
    channels = 4 if alpha else 3
    stride = width * channels
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (none)
        raw += pixels[y * stride : (y + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), level))
        + _png_chunk(b"IEND", b"")
    )


def decode_png(data: bytes) -> tuple[int, int, int, bytearray]:
    """Decode the 8-bit non-interlaced RGB/RGBA PNGs Real-ESRGAN writes."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    offset = 8
    idat = bytearray()
    width = height = channels = 0
    while offset + 8 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        tag = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        if tag == b"IHDR":
            width, height, depth, color, comp, filt, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or interlace != 0 or color not in (2, 6):
                raise ValueError(f"unsupported PNG (depth {depth}, color type {color})")
            channels = 4 if color == 6 else 3
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        offset += 12 + length

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(height * stride)
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        method = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        pos += stride
        if method == 1:
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 0xFF
        elif method == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif method == 3:
            for x in range(channels):
                line[x] = (line[x] + (prev[x] >> 1)) & 0xFF
            for x in range(channels, stride):
                line[x] = (line[x] + ((line[x - channels] + prev[x]) >> 1)) & 0xFF
        elif method == 4:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                b = prev[x]
                c = prev[x - channels] if x >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        elif method != 0:
            raise ValueError(f"unknown PNG filter {method}")
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return width, height, channels, out


# --------------------------------------------------------------------------
# Corridor 7 palette
# --------------------------------------------------------------------------

STEAM_CD_EXECUTABLE_SIZE = 250776
STEAM_CD_PALETTE_OFFSET = 0x2FFC0
PALETTE_SIZE = 768


def _palette_looks_valid(raw: bytes) -> bool:
    if len(raw) != PALETTE_SIZE or max(raw) > 63:
        return False
    if raw[0] or raw[1] or raw[2]:
        return False  # color 0 is black in every Wolfenstein-family palette
    if raw[45:48] != b"\x3f\x3f\x3f":
        return False  # color 15 is white
    colors = {raw[i : i + 3] for i in range(0, PALETTE_SIZE, 3)}
    return len(colors) >= 200


def load_palette(executable: bytes) -> list[int]:
    """Expand the 6-bit VGA DAC palette embedded in the game executable."""
    raw = executable[STEAM_CD_PALETTE_OFFSET : STEAM_CD_PALETTE_OFFSET + PALETTE_SIZE]
    if not _palette_looks_valid(raw):
        raw = b""
        for offset in range(len(executable) - PALETTE_SIZE):
            if executable[offset] or executable[offset + 1] or executable[offset + 2]:
                continue
            window = executable[offset : offset + PALETTE_SIZE]
            if _palette_looks_valid(window):
                raw = window
                break
    if not raw:
        raise ValueError("no Corridor 7 palette found in the executable")
    return [((c << 2) | (c >> 4)) for c in raw]


# --------------------------------------------------------------------------
# GFXTILES: 64x64 wall pages and Wolfenstein column-post sprites
# --------------------------------------------------------------------------


class GfxTiles:
    def __init__(self, data: bytes):
        chunk_count, sprite_start, sound_start = struct.unpack_from("<HHH", data)
        self.data = data
        self.chunk_count = chunk_count
        self.sprite_start = sprite_start
        self.sound_start = min(sound_start, chunk_count)
        self.offsets = struct.unpack_from(f"<{chunk_count}I", data, 6)
        self.lengths = struct.unpack_from(f"<{chunk_count}H", data, 6 + chunk_count * 4)

    def page(self, index: int) -> bytes:
        start = self.offsets[index]
        return self.data[start : start + self.lengths[index]]


# Corridor 7 keys wall transparency on palette index 255 -- grates, force-field
# frames and window walls are ordinary 64x64 pages with holes punched in them.
# Those pages have to come back as RGBA: the engine reads a hires wall's
# transparency from the PNG's alpha channel (FPNGTexture::GetColumnOpacity), and
# a masked wall delivered as flat RGB would be upscaled with the key color
# baked in as a visible one, turning every grate solid.
WALL_TRANSPARENT_INDEX = 255


def wall_rgb(page: bytes, palette: list[int]) -> tuple[bytes, bool]:
    """Decode a 64x64 column-major wall page to row-major RGB or RGBA bytes.

    Returns (pixels, has_alpha).
    """
    if len(page) < 64 * 64:
        raise ValueError(f"wall page is {len(page)} bytes, expected 4096")
    masked = WALL_TRANSPARENT_INDEX in page[: 64 * 64]
    channels = 4 if masked else 3
    out = bytearray(64 * 64 * channels)
    for y in range(64):
        for x in range(64):
            index = page[x * 64 + y]
            c = index * 3
            d = (y * 64 + x) * channels
            out[d] = palette[c]
            out[d + 1] = palette[c + 1]
            out[d + 2] = palette[c + 2]
            if masked:
                out[d + 3] = 0 if index == WALL_TRANSPARENT_INDEX else 255
    return bytes(out), masked


def sprite_rgba(page: bytes, palette: list[int]) -> bytes:
    """Decode a Wolfenstein column-post sprite to 64x64 RGBA bytes."""
    left, right = struct.unpack_from("<HH", page)
    if left > right or right >= 64 or 4 + (right - left + 1) * 2 > len(page):
        raise ValueError(f"invalid sprite column range {left}..{right}")
    rgba = bytearray(64 * 64 * 4)
    for x in range(left, right + 1):
        command = struct.unpack_from("<H", page, 4 + (x - left) * 2)[0]
        seen = 0
        while True:
            end_word = struct.unpack_from("<H", page, command)[0]
            if end_word == 0:
                break
            source = struct.unpack_from("<h", page, command + 2)[0]
            start_word = struct.unpack_from("<H", page, command + 4)[0]
            start, end = start_word >> 1, end_word >> 1
            if start > end or end > 64 or source + start < 0 or source + end > len(page):
                raise ValueError(f"sprite column {x} post is invalid")
            for y in range(start, end):
                c = page[source + y] * 3
                d = (y * 64 + x) * 4
                rgba[d] = palette[c]
                rgba[d + 1] = palette[c + 1]
                rgba[d + 2] = palette[c + 2]
                rgba[d + 3] = 255
            command += 6
            seen += 1
            if seen > 64:
                raise ValueError(f"sprite column {x} has excessive posts")
    return bytes(rgba)


# --------------------------------------------------------------------------
# VGAGRAPH: Huffman-compressed planar VGA pictures
# --------------------------------------------------------------------------

# ECWolf drops the pictable chunk and hands the rest to LumpRemapper, so
# VGAGRAPH chunk N carries the name at index N-1 of co7map.txt's graphics
# list. Chunks 1..2 are the fonts and chunk 3 is TILE8, which puts the first
# picture (chunk 4) at graphics index 3.
FIRST_PICTURE_NAME_INDEX = 3


def _huff_expand(source: bytes, nodes: list[tuple[int, int]], expected: int) -> bytes:
    out = bytearray()
    node = 254
    for value in source:
        for bit in range(8):
            child = nodes[node][(value >> bit) & 1]
            if child < 256:
                out.append(child)
                if len(out) == expected:
                    return bytes(out)
                node = 254
            else:
                node = child - 256
    raise ValueError(f"huffman chunk ended at {len(out)} of {expected} bytes")


def extract_pictures(vgadict: bytes, vgahead: bytes, vgagraph: bytes, palette: list[int]):
    """Yield (picture index, width, height, RGB bytes) for every VGAGRAPH picture."""
    nodes = list(struct.iter_unpack("<HH", vgadict[: 255 * 4]))
    offsets = [int.from_bytes(vgahead[i : i + 3], "little") for i in range(0, len(vgahead), 3)]
    decoded: list[bytes | None] = []
    for i, start in enumerate(offsets):
        if start >= len(vgagraph):
            break
        end = offsets[i + 1] if i + 1 < len(offsets) else len(vgagraph)
        expected = struct.unpack_from("<I", vgagraph, start)[0]
        try:
            decoded.append(_huff_expand(vgagraph[start + 4 : end], nodes, expected))
        except (ValueError, struct.error):
            # TILE8 and trailing chunks lie about their size; only the
            # pictures have to survive.
            decoded.append(None)

    if not decoded or decoded[0] is None:
        raise ValueError("VGAGRAPH pictable could not be decompressed")
    dims = []
    pictable = decoded[0]
    for w, h in struct.iter_unpack("<HH", pictable[: len(pictable) & ~3]):
        if not (0 < w <= 640 and 0 < h <= 480):
            break
        dims.append((w, h))

    for i in range(min(len(dims), max(0, len(decoded) - 4))):
        w, h = dims[i]
        data = decoded[i + 4]
        if data is None or len(data) != w * h or w % 4:
            continue
        plane = w * h // 4
        rgb = bytearray(w * h * 3)
        for y in range(h):
            prow = y * (w // 4)
            for x in range(w):
                c = data[(x & 3) * plane + prow + (x >> 2)] * 3
                d = (y * w + x) * 3
                rgb[d] = palette[c]
                rgb[d + 1] = palette[c + 1]
                rgb[d + 2] = palette[c + 2]
        yield i, w, h, bytes(rgb)


# --------------------------------------------------------------------------
# Lump names (co7map.txt)
# --------------------------------------------------------------------------

_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.S)
_SECTION = re.compile(r"(\w+)\s*\{(.*?)\}", re.S)


def parse_lump_names(text: str) -> dict[str, list[str]]:
    """Parse co7map.txt into {section: [lump name, ...]}."""
    clean = _COMMENTS.sub("", text)
    sections = {}
    for match in _SECTION.finditer(clean):
        sections[match.group(1).lower()] = re.findall(r'"([^"]*)"', match.group(2))
    return sections


def find_lump_names(data_dir: Path, override: str | None) -> dict[str, list[str]]:
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override).expanduser())
    else:
        for directory in (data_dir, Path(__file__).resolve().parent):
            for path in sorted(directory.glob("*")):
                if path.suffix.lower() in (".pk3", ".zip") or path.name.lower() == "co7map.txt":
                    candidates.append(path)
        # ec7wolf.pk3 is the authoritative source; look at it first.
        candidates.sort(key=lambda p: 0 if "ec7wolf" in p.name.lower() else 1)

    for path in candidates:
        if not path.exists():
            continue
        try:
            if path.suffix.lower() in (".pk3", ".zip"):
                with zipfile.ZipFile(path) as zf:
                    names = [n for n in zf.namelist() if n.lower().endswith("co7map.txt")]
                    if not names:
                        continue
                    text = zf.read(names[0]).decode("latin-1")
            else:
                text = path.read_text("latin-1")
        except (OSError, zipfile.BadZipFile):
            continue
        sections = parse_lump_names(text)
        if sections.get("textures") and sections.get("sprites") and sections.get("graphics"):
            print(f"lump names   : {path}")
            return sections

    raise SystemExit(
        "could not find co7map.txt (the Corridor 7 lump-name table).\n"
        "Put ec7wolf.pk3 next to the game data or pass --namemap PATH."
    )


# --------------------------------------------------------------------------
# Image helpers
# --------------------------------------------------------------------------


def bleed_edges(rgba: bytes, width: int, height: int, waves: int) -> bytes:
    """Grow the opaque colors outwards so upscaling can't drag black in.

    Real-ESRGAN sees the RGB planes of a transparent pixel as ordinary data,
    and Wolfenstein sprites store black there. Without this the model paints a
    dark fringe around every sprite, which survives the engine's 1-bit alpha
    reduction as a black outline.
    """
    pixels = bytearray(rgba)
    known = bytearray(pixels[3::4])
    for _ in range(waves):
        frontier = []
        for y in range(height):
            row = y * width
            for x in range(width):
                index = row + x
                if known[index]:
                    continue
                r = g = b = n = 0
                if x > 0 and known[index - 1]:
                    s = (index - 1) * 4
                    r += pixels[s]; g += pixels[s + 1]; b += pixels[s + 2]; n += 1
                if x + 1 < width and known[index + 1]:
                    s = (index + 1) * 4
                    r += pixels[s]; g += pixels[s + 1]; b += pixels[s + 2]; n += 1
                if y > 0 and known[index - width]:
                    s = (index - width) * 4
                    r += pixels[s]; g += pixels[s + 1]; b += pixels[s + 2]; n += 1
                if y + 1 < height and known[index + width]:
                    s = (index + width) * 4
                    r += pixels[s]; g += pixels[s + 1]; b += pixels[s + 2]; n += 1
                if n:
                    frontier.append((index, r // n, g // n, b // n))
        if not frontier:
            break
        for index, r, g, b in frontier:
            d = index * 4
            pixels[d] = r
            pixels[d + 1] = g
            pixels[d + 2] = b
            known[index] = 1
    return bytes(pixels)


def resample_area(
    pixels: bytes, width: int, height: int, channels: int, new_width: int, new_height: int
) -> bytes:
    """Box-filter an image down to a smaller size."""
    out = bytearray(new_width * new_height * channels)
    x_edges = [(x * width) // new_width for x in range(new_width + 1)]
    y_edges = [(y * height) // new_height for y in range(new_height + 1)]
    for ny in range(new_height):
        y0, y1 = y_edges[ny], max(y_edges[ny + 1], y_edges[ny] + 1)
        for nx in range(new_width):
            x0, x1 = x_edges[nx], max(x_edges[nx + 1], x_edges[nx] + 1)
            count = (y1 - y0) * (x1 - x0)
            for c in range(channels):
                total = 0
                for y in range(y0, y1):
                    base = (y * width + x0) * channels + c
                    for step in range(x1 - x0):
                        total += pixels[base + step * channels]
                out[(ny * new_width + nx) * channels + c] = total // count
    return bytes(out)


def binarize_alpha(pixels: bytearray, threshold: int = 128) -> None:
    for i in range(3, len(pixels), 4):
        pixels[i] = 255 if pixels[i] >= threshold else 0


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------

DATA_STEMS = ("GFXTILES", "VGADICT", "VGAHEAD", "VGAGRAPH")


def find_data_files(data_dir: Path) -> dict[str, Path]:
    """Locate the Corridor 7 data files regardless of case or extension."""
    entries = [p for p in data_dir.iterdir() if p.is_file()]
    found: dict[str, Path] = {}
    for stem in DATA_STEMS:
        matches = [p for p in entries if p.stem.upper() == stem]
        if not matches:
            raise SystemExit(
                f"{stem}.* not found in {data_dir}\n"
                "Run this script from the directory holding the Corridor 7 data files, "
                "or pass --dir."
            )
        # Prefer the extension GFXTILES uses so mixed installs stay consistent.
        if "GFXTILES" in found:
            wanted = found["GFXTILES"].suffix.lower()
            matches.sort(key=lambda p: 0 if p.suffix.lower() == wanted else 1)
        found[stem] = matches[0]

    executables = [p for p in entries if p.suffix.lower() == ".exe"]
    executables.sort(key=lambda p: (0 if p.name.upper() == "CORR7CD.EXE" else 1, p.name))
    if not executables:
        raise SystemExit(
            f"no game executable in {data_dir}; CORR7CD.EXE is needed for the palette"
        )
    found["EXE"] = executables[0]
    return found


def progress(label: str, done: int, total: int, unit: str = "") -> None:
    if total:
        line = f"  {label}: {done}/{total} ({done * 100 // total}%)"
    else:
        line = f"  {label}: {done}{unit}"
    if sys.stderr.isatty():
        sys.stderr.write("\r" + line.ljust(70))
        sys.stderr.flush()
    elif total and (done == total or done % max(1, total // 10) == 0):
        print(line, flush=True)


def progress_done() -> None:
    if sys.stderr.isatty():
        sys.stderr.write("\n")
        sys.stderr.flush()


class Job:
    """One image on its way from the game data into the pk3."""

    __slots__ = ("name", "group", "width", "height", "alpha", "source")

    def __init__(self, name: str, group: str, width: int, height: int, alpha: bool, source: str):
        self.name = name
        self.group = group
        self.width = width
        self.height = height
        self.alpha = alpha
        self.source = source  # name of the job whose upscale this one reuses


def decode_assets(args, files: dict[str, Path], names: dict[str, list[str]], in_dir: Path):
    """Decode every requested asset into in_dir/<group> as a PNG.

    Returns (jobs, originals), where originals maps a source name to the
    decoded 1x image so --compare can put the two side by side later.
    """
    palette = load_palette(files["EXE"].read_bytes())
    jobs: list[Job] = []
    seen: dict[bytes, str] = {}
    used: set[str] = set()
    skipped: list[str] = []
    kept: list[str] = []
    originals: dict[str, tuple[int, int, int, bytes]] = {}

    def emit(name: str, group: str, width: int, height: int, pixels: bytes, alpha: bool) -> None:
        name = name.lower()
        if name in used:
            skipped.append(f"{group} {name}: duplicate lump name")
            return
        used.add(name)
        # Deliberately left at the original resolution: excluded from the pack
        # AND from its manifest, so the game keeps its own art for this lump and
        # still treats the pack as complete. See --keep.
        if name in args.keep:
            kept.append(name)
            return
        # Identical pages are common (256 wall pages hold 246 distinct
        # images); upscale each distinct image once and alias the rest. Keyed
        # per group because each group can be upscaled by a different model,
        # and an alias has to come out of its own group's output directory.
        key = hashlib.sha1(pixels).digest() + bytes([alpha, len(group)]) + group.encode()
        source = seen.get(key)
        if source is None:
            seen[key] = name
            source = name
            group_dir = in_dir / group
            group_dir.mkdir(parents=True, exist_ok=True)
            group_dir.joinpath(f"{name}.png").write_bytes(
                encode_png(width, height, pixels, alpha=alpha, level=1)
            )
            originals[f"{group}/{name}"] = (width, height, 4 if alpha else 3, pixels)
        jobs.append(Job(name, group, width, height, alpha, source))

    if "walls" in args.groups or "sprites" in args.groups:
        tiles = GfxTiles(files["GFXTILES"].read_bytes())
        wall_names = names["textures"]
        sprite_names = names["sprites"]

        if "walls" in args.groups:
            total = tiles.sprite_start
            for index in range(total):
                if index >= len(wall_names):
                    break
                try:
                    pixels, masked = wall_rgb(tiles.page(index), palette)
                except (ValueError, struct.error) as error:
                    skipped.append(f"wall page {index}: {error}")
                    progress("walls", index + 1, total)
                    continue
                if masked and args.bleed:
                    pixels = bleed_edges(pixels, 64, 64, args.bleed)
                emit(wall_names[index], "walls", 64, 64, pixels, masked)
                progress("walls", index + 1, total)
            progress_done()

        if "sprites" in args.groups:
            total = tiles.sound_start - tiles.sprite_start
            for offset in range(total):
                if offset >= len(sprite_names):
                    break
                index = tiles.sprite_start + offset
                try:
                    rgba = sprite_rgba(tiles.page(index), palette)
                except (ValueError, struct.error) as error:
                    skipped.append(f"sprite page {offset}: {error}")
                    continue
                if args.bleed:
                    rgba = bleed_edges(rgba, 64, 64, args.bleed)
                emit(sprite_names[offset], "sprites", 64, 64, rgba, True)
                progress("sprites", offset + 1, total)
            progress_done()

    if "graphics" in args.groups:
        graphic_names = names["graphics"]
        pictures = list(
            extract_pictures(
                files["VGADICT"].read_bytes(),
                files["VGAHEAD"].read_bytes(),
                files["VGAGRAPH"].read_bytes(),
                palette,
            )
        )
        for count, (index, width, height, rgb) in enumerate(pictures, 1):
            name_index = index + FIRST_PICTURE_NAME_INDEX
            if name_index >= len(graphic_names):
                skipped.append(f"picture {index}: no lump name")
                continue
            emit(graphic_names[name_index], "graphics", width, height, rgb, False)
            progress("graphics", count, len(pictures))
        progress_done()

    for message in skipped:
        print(f"  skipped {message}")
    if kept:
        print(f"  keeping {len(kept)} lump(s) at the original resolution: "
              + ", ".join(sorted(kept)[:8]) + ("..." if len(kept) > 8 else ""))
    return jobs, originals


def run_upscaler(args, binary: Path, model_dir: Path, in_dir: Path, out_dir: Path,
                 total: int, model: str):
    native = MODELS.get(model)
    command = [
        str(binary),
        "-i", str(in_dir),
        "-o", str(out_dir),
        "-m", str(model_dir),
        "-n", model,
        "-f", "png",
    ]
    if native is None:
        # Per-scale model variants: let the tool pick the right one.
        command += ["-s", str(args.scale)]
    if args.gpu is not None:
        command += ["-g", str(args.gpu)]
    if args.tile is not None:
        command += ["-t", str(args.tile)]
    if args.threads:
        command += ["-j", args.threads]
    if args.tta:
        command.append("-x")

    print(f"upscaling {total} images with {model} ...")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )

    # In directory mode the tool only prints per-image percentages, so count
    # finished files instead. The output has to be drained anyway or the tool
    # blocks once the pipe fills up.
    tail: deque[str] = deque(maxlen=20)

    def drain() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if line and not line.endswith("%"):
                tail.append(line)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    done = 0
    while process.poll() is None:
        done = min(total, len(os.listdir(out_dir)))
        progress("upscaled", done, total)
        time.sleep(0.5)
    reader.join(timeout=5)
    done = len(os.listdir(out_dir))
    progress("upscaled", min(done, total), total)
    progress_done()
    if process.returncode != 0:
        print("\n".join(tail), file=sys.stderr)
        raise SystemExit(
            "realesrgan-ncnn-vulkan failed. It needs a working Vulkan driver; "
            "on a headless box install mesa-vulkan-drivers (lavapipe) or pass --gpu."
        )
    if done < total:
        print(f"  warning: only {done} of {total} images came back from the upscaler")


def write_comparisons(originals, out_dir: Path, compare_dir: Path, scale: int) -> int:
    """Write original-beside-upscaled strips, one PNG per distinct image.

    No neural upscaler can be trusted with five-pixel-tall bitmap text: it will
    happily turn ACCESS GRANTED into ACCE55 GRVNITED and report success. Two
    automatic measures of "how wrong is this" were tried and both failed -- they
    rank tiles by how much the model changed, which is not the same question, so
    a detailed tile the model handled well scores worse than a sign it ruined.
    That judgment needs eyes, so this makes it a two-minute job: browse the
    folder, note the names that got worse, and pass them to --keep.
    """
    compare_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for key, (w, h, channels, pixels) in sorted(originals.items()):
        group, name = key.split("/", 1)
        upscaled = out_dir / group / f"{name}.png"
        if not upscaled.is_file():
            continue
        bw, bh, bch, big = decode_png(upscaled.read_bytes())
        # Nearest-neighbor so the left half is exactly what the game draws
        # today, magnified -- not a second opinion about how it should look.
        factor = max(1, bw // w)
        gap = 4
        out_w, out_h = w * factor + gap + bw, max(h * factor, bh)
        strip = bytearray(b"\x00" * (out_w * out_h * 3))
        # Transparent texels keep the palette's key color underneath, which on a
        # masked wall is a magenta field that has nothing to do with how the
        # tile looks in game. Show a checkerboard through them instead.
        def blit(src, sw, sch, ox, dst_w, dst_h, mag):
            for y in range(dst_h):
                for x in range(dst_w):
                    s0 = ((y // mag) * sw + (x // mag)) * sch
                    d = (y * out_w + ox + x) * 3
                    if sch == 4 and src[s0 + 3] < 128:
                        v = 0x60 if ((x >> 3) + (y >> 3)) & 1 else 0x30
                        strip[d:d+3] = bytes((v, v, v))
                    else:
                        strip[d:d+3] = src[s0:s0+3]

        blit(pixels, w, channels, 0, w * factor, h * factor, factor)
        blit(big, bw, bch, w * factor + gap, bw, bh, 1)
        compare_dir.joinpath(f"{name}.png").write_bytes(
            encode_png(out_w, out_h, bytes(strip), alpha=False)
        )
        written += 1
        progress("comparing", written, len(originals))
    progress_done()
    return written


def build_pk3(args, jobs: list[Job], out_dir: Path, output: Path, metadata: str) -> tuple[int, int]:
    """Pack the upscaled images into the pk3's hires/ namespace."""
    cache: dict[str, bytes] = {}
    written = 0

    # Build beside the target and rename, so an interrupted run never leaves a
    # truncated pk3 where a good one used to be.
    partial = output.with_name(output.name + ".part")
    missing: list[str] = []
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as pk3:
        pk3.writestr("c7upscal.txt", metadata)
        # The manifest of what this build set out to write, which is not the
        # same as what it managed to write: an upscaler that dies partway
        # through still leaves a loadable pk3, just one with holes in it. The
        # game treats the pack as all-or-nothing and checks every name here
        # against what actually arrived, so this list has to be the intent.
        pk3.writestr("c7upscal.lst", "".join(f"{job.name}\n" for job in jobs))
        for index, job in enumerate(jobs, 1):
            key = f"{job.group}/{job.source}"
            data = cache.get(key)
            if data is None:
                path = out_dir / job.group / f"{job.source}.png"
                if not path.is_file():
                    missing.append(job.source)
                    continue
                # Each group can be upscaled by a different model, and the
                # per-scale models produce their native size rather than the one
                # asked for, so whether a resize is needed is a per-group answer.
                native = MODELS.get(args.model_for[job.group]) or args.scale
                resize = args.scale != native
                data = path.read_bytes()
                if resize or (job.alpha and args.alpha == "binary"):
                    width, height, channels, pixels = decode_png(data)
                    if resize:
                        new_w = max(1, job.width * args.scale)
                        new_h = max(1, job.height * args.scale)
                        if (new_w, new_h) != (width, height):
                            pixels = bytearray(
                                resample_area(pixels, width, height, channels, new_w, new_h)
                            )
                            width, height = new_w, new_h
                    if channels == 4 and args.alpha == "binary":
                        binarize_alpha(pixels)
                    data = encode_png(width, height, bytes(pixels), alpha=channels == 4)
                cache[key] = data
            # PNG payloads are already deflated; storing them keeps the pk3
            # small enough and the build fast.
            info = zipfile.ZipInfo(f"hires/{job.name}.png", date_time=(1996, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o644 << 16
            pk3.writestr(info, data)
            written += 1
            progress("packing", index, len(jobs))
    progress_done()
    partial.replace(output)
    if missing:
        shown = ", ".join(sorted(set(missing))[:6])
        print(
            f"  WARNING: {len(missing)} images never came back from the upscaler "
            f"({shown}).\n"
            "  The game checks the manifest and will refuse an incomplete pack. "
            "Re-run to finish it.",
            file=sys.stderr,
        )
    return written, len(cache)


def main() -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Upscale the Corridor 7 art with Real-ESRGAN into c7_assets_upscaled.pk3.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--dir", help="directory holding the Corridor 7 data files")
    parser.add_argument("-o", "--out", help="output pk3 (default <dir>/c7_assets_upscaled.pk3)")
    parser.add_argument("-s", "--scale", type=int, choices=(2, 3, 4), default=4)
    parser.add_argument("-n", "--model", choices=sorted(MODELS), default=DEFAULT_MODEL,
        help="model for every group that has no override below")
    # The two useful models fail in opposite directions on this art, and which
    # one wins is a property of the picture rather than of the pack:
    # realesrgan-x4plus keeps flat color and hard geometry (SECURITY OFFICE
    # stays yellow and legible) but invents film grain on flat walls and
    # rewrites small text; realesr-animevideov3 holds small text together
    # (ACCESS GRANTED survives it) but softens fine line work and desaturates.
    # Neither is right for everything, so the choice is per group.
    for group in ("walls", "sprites", "graphics"):
        parser.add_argument(f"--model-{group}", choices=sorted(MODELS), default=None,
            help=f"override the model for {group}")
    parser.add_argument("--keep", default="", metavar="NAMES",
        help="comma separated lump names to leave at the original resolution; "
             "they are left out of the pack and out of its manifest, so the game "
             "keeps its own art for them and still sees a complete pack")
    parser.add_argument("--keep-file", metavar="FILE", default=str(here / KEEP_FILE),
        help="a file of lump names to --keep, one per line; defaults to the "
             "checked list beside this script. Pass /dev/null to upscale "
             "everything")
    parser.add_argument("--compare", metavar="DIR",
        help="also write original-beside-upscaled strips here, to pick --keep from")
    parser.add_argument(
        "--groups",
        default="walls,sprites,graphics",
        help="comma separated subset of walls,sprites,graphics",
    )
    parser.add_argument(
        "--alpha",
        choices=("soft", "binary"),
        default="soft",
        help="keep the model's antialiased sprite alpha, or force it back to 1 bit",
    )
    parser.add_argument(
        "--bleed",
        type=int,
        default=4,
        metavar="N",
        help="pixels of color to grow under transparent sprite areas (0 disables)",
    )
    parser.add_argument("--namemap", help="co7map.txt or a pk3 containing it")
    parser.add_argument("--tool", help="an existing realesrgan-ncnn-vulkan binary")
    parser.add_argument("--models", help="directory holding the Real-ESRGAN .param/.bin models")
    parser.add_argument("--cache", default=str(default_cache_dir()), help="download cache")
    parser.add_argument("--work", help="working directory (default: a temporary one)")
    parser.add_argument("--keep-work", action="store_true", help="do not delete the working directory")
    parser.add_argument("-g", "--gpu", type=int, help="Vulkan device index (default: auto)")
    parser.add_argument("-t", "--tile", type=int, help="tile size (0 = auto)")
    parser.add_argument("-j", "--threads", help="load:proc:save thread counts, e.g. 1:2:2")
    parser.add_argument("--tta", action="store_true", help="8x slower, slightly cleaner output")
    args = parser.parse_args()

    args.keep = {n.strip().lower() for n in args.keep.split(",") if n.strip()}
    keep_file = Path(args.keep_file).expanduser() if args.keep_file else None
    if keep_file and keep_file.is_file():
        for line in keep_file.read_text().splitlines():
            line = line.split("//")[0].strip().lower()
            if line:
                args.keep.add(line)
    args.model_for = {
        group: getattr(args, f"model_{group}") or args.model
        for group in ("walls", "sprites", "graphics")
    }

    args.groups = {g.strip().lower() for g in args.groups.split(",") if g.strip()}
    unknown = args.groups - {"walls", "sprites", "graphics"}
    if unknown:
        raise SystemExit(f"unknown group(s): {', '.join(sorted(unknown))}")
    if not args.groups:
        raise SystemExit("nothing to do: --groups is empty")

    if args.dir:
        data_dir = Path(args.dir).expanduser().resolve()
    else:
        # "Drop it next to the data files and run it" works from either the
        # data directory or the script's own directory.
        data_dir = Path.cwd()
        if not any(p.stem.upper() == "GFXTILES" for p in data_dir.iterdir() if p.is_file()):
            data_dir = here
    if not data_dir.is_dir():
        raise SystemExit(f"{data_dir} is not a directory")

    files = find_data_files(data_dir)
    output = Path(args.out).expanduser() if args.out else data_dir / "c7_assets_upscaled.pk3"
    print(f"data files   : {data_dir}")
    print(f"palette from : {files['EXE'].name}")
    names = find_lump_names(data_dir, args.namemap)

    binary, model_dir = ensure_tool(Path(args.cache).expanduser(), args.tool, args.models)
    print(f"upscaler     : {binary}")

    work = Path(args.work).expanduser() if args.work else Path(tempfile.mkdtemp(prefix="c7upscale-"))
    work.mkdir(parents=True, exist_ok=True)
    in_dir, out_dir = work / "original", work / "upscaled"
    for directory in (in_dir, out_dir):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
    print(f"work         : {work}")

    started = time.monotonic()
    try:
        print("decoding original art ...")
        jobs, originals = decode_assets(args, files, names, in_dir)
        if not jobs:
            raise SystemExit("no images were decoded")

        # One run per group, because each can name its own model. The upscaler
        # is a directory-in, directory-out tool, so the groups were decoded into
        # separate directories to begin with.
        for group in sorted(args.groups):
            group_in = in_dir / group
            if not group_in.is_dir():
                continue
            group_out = out_dir / group
            group_out.mkdir(parents=True, exist_ok=True)
            run_upscaler(args, binary, model_dir, group_in, group_out,
                         len(list(group_in.glob("*.png"))), args.model_for[group])

        if args.compare:
            compare_dir = Path(args.compare).expanduser()
            print(f"writing comparisons to {compare_dir} ...")
            n = write_comparisons(originals, out_dir, compare_dir, args.scale)
            print(f"  {n} before/after strips; anything the model made worse "
                  "belongs in --keep")

        counts = {group: sum(1 for job in jobs if job.group == group) for group in args.groups}
        metadata = "\n".join(
            [
                "// Corridor 7 upscaled asset pack",
                "// Built by make_c7_upscaled_pk3.py; load with -file c7_assets_upscaled.pk3",
                *(f"model-{group} {args.model_for[group]}"
                  for group in sorted(args.groups)),
                f"scale {args.scale}",
                f"alpha {args.alpha}",
                f"bleed {args.bleed}",
                f"tta {'on' if args.tta else 'off'}",
                f"kept {len(args.keep)}",
                # Read by the engine, along with c7upscal.lst, to decide whether
                # the pack is complete enough to use at all.
                f"lumps {len(jobs)}",
                *(f"{group} {counts[group]}" for group in sorted(counts)),
                f"source {files['GFXTILES'].name} {files['VGAGRAPH'].name}",
                f"built {time.strftime('%Y-%m-%dT%H:%M:%S')}",
                "",
            ]
        )

        print("packing ...")
        written, unique = build_pk3(args, jobs, out_dir, output, metadata)
    finally:
        if not args.keep_work and not args.work:
            shutil.rmtree(work, ignore_errors=True)

    size = output.stat().st_size
    elapsed = time.monotonic() - started
    print(
        f"\nwrote {output} ({size / 1048576:.1f} MiB)\n"
        f"  {written} lumps from {unique} distinct upscales at {args.scale}x "
        f"in {elapsed / 60:.1f} min"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
