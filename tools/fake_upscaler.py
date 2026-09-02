#!/usr/bin/env python3
"""A stand-in for realesrgan-ncnn-vulkan, for testing the asset-pack pipeline.

make_c7_upscaled_pk3.py shells out to the real upscaler, which wants a Vulkan
device and the better part of an hour. This accepts the same arguments and does
a nearest-neighbor enlargement instead, so the parts of the pipeline that are
ours -- decoding the game's art, keeping masked walls transparent, writing the
manifest, and everything the engine then does with the pack -- can be tested on
a machine with no GPU in a few seconds.

The images it produces are not upscales in any useful sense. It exists to
exercise the plumbing, never to build a pack anyone would play with.

    make_c7_upscaled_pk3.py --tool fake_upscaler.py --models /tmp/anything
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_c7_upscaled_pk3 import decode_png, encode_png  # noqa: E402


def scale_nearest(data: bytes, factor: int) -> bytes:
    width, height, channels, pixels = decode_png(data)
    new_w, new_h = width * factor, height * factor
    stride, new_stride = width * channels, new_w * channels
    out = bytearray(new_h * new_stride)
    for y in range(new_h):
        src = (y // factor) * stride
        row = bytearray(new_stride)
        for x in range(new_w):
            s = src + (x // factor) * channels
            row[x * channels : (x + 1) * channels] = pixels[s : s + channels]
        out[y * new_stride : (y + 1) * new_stride] = row
    return encode_png(new_w, new_h, bytes(out), alpha=channels == 4, level=1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", dest="input", required=True)
    parser.add_argument("-o", dest="output", required=True)
    parser.add_argument("-s", dest="scale", type=int, default=4)
    # Accepted and ignored, so the caller does not have to special-case us.
    for flag in ("-m", "-n", "-f", "-g", "-t", "-j"):
        parser.add_argument(flag, dest=flag.lstrip("-"), default=None)
    parser.add_argument("-x", action="store_true")
    args = parser.parse_args()

    in_dir, out_dir = Path(args.input), Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(in_dir.glob("*.png")):
        (out_dir / path.name).write_bytes(scale_nearest(path.read_bytes(), args.scale))
    return 0


if __name__ == "__main__":
    sys.exit(main())
