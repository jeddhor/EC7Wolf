#!/usr/bin/env python3
"""Validate engine-exported player banks, then convert them to private PNGs.

First run EC7Wolf with --capture-sprite-bank BANK DIR/BANK.json for MARN
and every bank in make_c7_player_colors.COLORS. Output contains retail-derived
artwork and must stay outside version control. Requires Pillow for previews.
"""
import argparse
import csv
import hashlib
import json
import struct
from pathlib import Path

from PIL import Image, ImageDraw
from c7assets import encode_png, _png_chunk, load_palette, parse_gfx_header, sprite_rgba
from make_c7_player_colors import COLORS, FRAMES


def canvas(sprite):
    w, h = sprite["width"], sprite["height"]
    raw = bytes.fromhex(sprite["pixels"])
    assert len(raw) == w * h
    out = bytearray(64 * 64)
    for x in range(w):
        for y in range(h):
            px, py = x + 32 - sprite["left"], y + 64 - sprite["top"]
            value = raw[x * h + y]
            if value:
                assert 0 <= px < 64 and 0 <= py < 64, "clipped opaque pixel"
                out[py * 64 + px] = value
    assert any(out), "empty sprite"
    return bytes(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--data", type=Path, help="also verify against this retail installation")
    args = parser.parse_args()
    work = args.directory
    variants = [("Blue", "MARN", 41, 63), *COLORS]
    source = json.loads((work / "MARN.json").read_text())
    remap = source["remap"]
    palette = source["palette"]
    retail = None
    hashes = {}
    if args.data:
        exe = (args.data / "CORR7CD.EXE").read_bytes()
        gfx = (args.data / "GFXTILES.CO7").read_bytes()
        retail = (load_palette(exe), gfx, parse_gfx_header(gfx))
        hashes = {"CORR7CD.EXE": hashlib.sha256(exe).hexdigest(),
                  "GFXTILES.CO7": hashlib.sha256(gfx).hexdigest()}
    # Freeze the complete state/angle manifest before writing any final PNG.
    with (work / "manifest.csv").open("w") as f:
        writer = csv.writer(f)
        writer.writerow(["color", "sprite", "source", "state", "rotation", "anchor_x", "anchor_y"])
        for color, bank, _, _ in variants:
            for frame in FRAMES:
                state = ("idle/walk" if frame[0] <= "E" else "pain" if frame[0] == "F"
                         else "death" if frame[0] <= "M" else "fire")
                writer.writerow([color, bank + frame, "MARN" + frame, state, frame[1], 32, 64])

    reports, images = [], {}
    for color, bank, first, last in variants:
        data = json.loads((work / f"{bank}.json").read_text())
        assert data["palette"] == palette and data["remap"] == remap
        assert set(data["sprites"]) == {bank + frame for frame in FRAMES}
        folder = work / "sprites" / color.lower()
        folder.mkdir(parents=True, exist_ok=True)
        translation = {remap[i]: remap[first + i - 41] for i in range(41, 64)}
        assert last - first == 22
        for frame in FRAMES:
            name = bank + frame
            original = canvas(source["sprites"]["MARN" + frame])
            if retail:
                pal, gfx, header = retail
                decoded = sprite_rgba(header.chunk(gfx, header.sprite_start + 459 + FRAMES.index(frame)), pal)
                # Compare opaque RGB and alpha against the retail decoder;
                # transparent RGB is immaterial and may differ between formats.
                for i, pixel in enumerate(original):
                    assert bool(pixel) == bool(decoded[i*4+3]), name
                    if pixel:
                        assert bytes(palette[pixel]) == decoded[i*4:i*4+3], name
            resolved = canvas(data["sprites"][name])
            assert resolved == bytes(translation.get(p, p) for p in original), name
            assert [bool(p) for p in resolved] == [bool(p) for p in original], name
            rgba = bytes(v for p in resolved for v in (*palette[p], 255 if p else 0))
            png = encode_png(64, 64, rgba, alpha=True)
            png = png[:33] + _png_chunk(b"grAb", struct.pack(">ii", 32, 64)) + png[33:]
            path = folder / f"{name}.png"
            path.write_bytes(png)
            with Image.open(path) as im:
                assert im.size == (64, 64)
                assert im.convert("RGBA").tobytes() == rgba
                images[color, frame] = im.convert("RGBA")
            used = sorted(set(resolved) - {0})
            reports.append({"sprite": name, "color": color, "dimensions": [64, 64],
                            "anchor": [32, 64], "alpha": [0, 255],
                            "changed_pixels": sum(a != b for a, b in zip(original, resolved)),
                            "nonuniform_changed_pixels": 0, "unmatched_rgb": [],
                            "engine_indices": used,
                            "preserved_effect_indices": [i for i in range(208, 240) if remap[i] in used]})

    preview = work / "previews"
    preview.mkdir(exist_ok=True)
    def sheet(path, columns, rows, scale=2):
        cell, label = 64 * scale, 20
        im = Image.new("RGB", (100 + len(columns) * cell, label + len(rows) * (cell + label)), (26, 26, 30))
        draw = ImageDraw.Draw(im)
        for j, frame in enumerate(columns):
            draw.text((104 + j * cell, 4), frame, fill="white")
        for i, color in enumerate(rows):
            y = label + i * (cell + label)
            draw.text((8, y + 12), color, fill="white")
            for j, frame in enumerate(columns):
                tile = images[color, frame].resize((cell, cell), Image.Resampling.NEAREST)
                im.paste(tile, (100 + j * cell, y), tile)
        im.save(path)

    names = [v[0] for v in variants]
    sheet(preview / "uniform-comparison.png", ["A1", "A3", "A5", "N0", "F0", "M0"], names)
    sheet(preview / "all-angles.png", [f"A{i}" for i in range(1, 9)], names)
    for color in names:
        # Preserve the native silhouette; previews only enlarge by integer scale.
        full = Image.new("RGBA", (8 * 64, 7 * 80), (26, 26, 30, 255))
        draw = ImageDraw.Draw(full)
        for i, frame in enumerate(FRAMES):
            x, y = i % 8 * 64, i // 8 * 80
            full.alpha_composite(images[color, frame], (x, y))
            draw.text((x + 4, y + 65), frame, fill="white")
        full.save(preview / f"{color.lower()}-all-frames.png")
        for label, frames, duration in [
            ("turntable", [f"A{i}" for i in range(1, 9)], 180),
            ("walk", [f"{f}1" for f in "ABCDE"], 86),
            ("fire", [f"{f}0" for f in "NOP"], 171),
            ("death", [f"{f}0" for f in "GHIJKLM"], 143),
        ]:
            sequence = []
            for frame in frames:
                tile = Image.new("RGBA", (64, 64), (26, 26, 30, 255))
                tile.alpha_composite(images[color, frame])
                sequence.append(tile.convert("RGB").resize((256, 256), Image.Resampling.NEAREST))
            sequence[0].save(preview / f"{color.lower()}-{label}.gif", save_all=True,
                             append_images=sequence[1:], duration=duration, loop=0)

    (work / "palette-report.json").write_text(json.dumps({
        "source": "resolved EC7Wolf textures from installed retail MARN sprites",
        "retail_sha256": hashes,
        "frames_checked": len(reports), "blue_uniform_source_indices": [41, 63],
        "all_nonuniform_pixels_unchanged": True, "all_silhouettes_unchanged": True,
        "all_anchors_unchanged": True, "frames": reports}, indent=2) + "\n")
    print(f"Validated and exported {len(reports)} sprites; previews: {preview}")


if __name__ == "__main__":
    main()
