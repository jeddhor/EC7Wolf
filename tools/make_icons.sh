#!/bin/sh

# Regenerate every application icon from one SVG.
#
# The icon exists in seventeen files across five platforms, at sizes from 16 to
# 1024 pixels and in three formats. Converting them by hand is how a set drifts
# apart -- one platform quietly keeping the old artwork because its file was
# missed. So the SVG is the source and everything else is generated from it.
#
# Usage: make_icons.sh [SOURCE.svg]
#   default source: src/posix/icon.svg, which is itself part of the set

set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$here/.." && pwd)
source=${1:-$root/src/posix/icon.svg}

if [ ! -f "$source" ]; then
	printf 'no such file: %s\n' "$source" >&2
	exit 1
fi
for tool in rsvg-convert convert; do
	if ! command -v "$tool" >/dev/null 2>&1; then
		printf '%s is needed (librsvg2-bin, imagemagick)\n' "$tool" >&2
		exit 1
	fi
done

work=$(mktemp -d /tmp/ec7wolf-icons.XXXXXX)
trap 'rm -rf "$work"' EXIT INT TERM

render() {  # render SIZE OUTPUT
	rsvg-convert -w "$1" -h "$1" "$source" -o "$2"
}

# The scalable one, if we were given something else.
if [ "$source" != "$root/src/posix/icon.svg" ]; then
	cp "$source" "$root/src/posix/icon.svg"
	printf '  %s\n' "src/posix/icon.svg"
fi

# macOS: an .iconset is a directory of exact names Apple's tooling expects.
for pair in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" \
            "64 icon_32x32@2x" "128 icon_128x128" "256 icon_128x128@2x" \
            "256 icon_256x256" "512 icon_256x256@2x" "512 icon_512x512" \
            "1024 icon_512x512@2x"; do
	size=${pair%% *}
	name=${pair#* }
	render "$size" "$root/src/macosx/icon.iconset/$name.png"
	printf '  %s (%s)\n' "src/macosx/icon.iconset/$name.png" "$size"
done

# Android launcher densities.
for pair in "36 ldpi" "48 mdpi" "72 hdpi" "96 xhdpi"; do
	size=${pair%% *}
	density=${pair#* }
	target="$root/android-libs/launcher/res/drawable-$density/ic_launcher.png"
	[ -d "$(dirname "$target")" ] || continue
	render "$size" "$target"
	printf '  %s (%s)\n' "drawable-$density/ic_launcher.png" "$size"
done

# Windows: one .ico holding every size Explorer might ask for, and a second
# for Windows 9x, which never had the larger ones.
for size in 16 24 32 48 64 128 256; do
	render "$size" "$work/win-$size.png"
done

# icon.ico through Pillow, which stores every entry PNG-compressed: 78 KB
# against 373 KB for ImageMagick's uncompressed BMP entries, and smaller even
# than the file it replaces. PNG entries need Windows Vista or newer, which is
# no constraint at all for an engine that wants OpenGL 3.3.
python3 - "$work" "$root" <<'PYEOF'
import sys
from pathlib import Path
from PIL import Image

work, root = Path(sys.argv[1]), Path(sys.argv[2])
Image.open(work / "win-256.png").save(
    root / "src" / "win32" / "icon.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128),
           (256, 256)])
PYEOF
printf '  %s (16-256)\n' "src/win32/icon.ico"

# icon9x.ico is the legacy one, and Windows 9x predates PNG inside an icon
# entirely -- so this one keeps ImageMagick's plain BMP entries. At 48 pixels
# and below the size costs nothing.
convert "$work/win-48.png" -define icon:auto-resize=48,32,24,16 \
        "$root/src/win32/icon9x.ico"
printf '  %s (16-48, uncompressed for Windows 9x)\n' "src/win32/icon9x.ico"

printf '\nregenerated from %s\n' "$source"
