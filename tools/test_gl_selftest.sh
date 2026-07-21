#!/bin/sh

# OpenGL device + indexed-palette pipeline self-test (renderer redesign Phase 4).
#
# Runs the built-in --gltest path headlessly (Xvfb + Mesa is fine) which creates
# a GL 3.3+ context, renders a known index image through the palette-lookup
# shader into an offscreen buffer, reads it back, and verifies every one of the
# 256 palette indices resolves to the exact RGB. Exits non-zero on failure.
#
# Usage: test_gl_selftest.sh EC7WOLF_BUILD_DIR CORRIDOR7_DATA_DIR [PPM_OUT]

set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
	printf 'usage: %s BUILD_DIR DATA_DIR [PPM_OUT]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
ppm_out=${3:-}
ec7wolf="$build_dir/ec7wolf"

if [ ! -x "$ec7wolf" ]; then
	printf 'EC7Wolf executable not found: %s\n' "$ec7wolf" >&2
	exit 1
fi

log=$(mktemp /tmp/ec7wolf-gltest.XXXXXX)
cleanup() { rm -f "$log"; }
trap cleanup EXIT HUP INT TERM

set +e
(
	cd "$data_dir"
	timeout 60s env SDL_AUDIODRIVER=dummy xvfb-run -a "$ec7wolf" \
		--data CO7 --gltest "${ppm_out:-/dev/null}"
) >"$log" 2>&1
status=$?
set -e

grep -iE "^GL: version" "$log" || true

if [ "$status" -eq 0 ] && grep -q "GL self-test: PASS" "$log"; then
	printf 'PASS: OpenGL indexed-palette pipeline verified\n'
	exit 0
fi

printf 'FAIL: GL self-test did not pass (status %d)\n' "$status" >&2
tail -n 20 "$log" >&2
exit 1
