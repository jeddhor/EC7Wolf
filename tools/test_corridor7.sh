#!/bin/sh

# Build ECWolf and smoke-test direct loading from an original Corridor 7 CD
# installation. No game data is copied or modified.

set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
	printf 'usage: %s ECWOLF_BUILD_DIR CORRIDOR7_DATA_DIR [LOG_FILE]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
log_file=${3:-"$build_dir/corridor7-smoke.log"}
ecwolf="$build_dir/ecwolf"

cmake --build "$build_dir"

if [ ! -x "$ecwolf" ]; then
	printf 'ECWolf executable not found: %s\n' "$ecwolf" >&2
	exit 1
fi

config_dir=$(mktemp -d /tmp/ecwolf-corridor7-config.XXXXXX)
config_file="$config_dir/ecwolf.cfg"
savedir=$(mktemp -d /tmp/ecwolf-corridor7-save.XXXXXX)
cleanup() {
	rm -rf "$config_dir"
	rm -rf "$savedir"
}
trap cleanup EXIT HUP INT TERM

set +e
(
	cd "$data_dir"
	timeout 8s env SDL_AUDIODRIVER=dummy \
		xvfb-run -a stdbuf -oL -eL "$ecwolf" --data CO7 --config "$config_file" \
		--savedir "$savedir" --nowait --tedlevel MAP01 --skill 2
) >"$log_file" 2>&1
status=$?
set -e

# A timeout is expected because this smoke test deliberately leaves the game
# running after it enters the level. Any earlier process failure is not.
if [ "$status" -ne 0 ] && [ "$status" -ne 124 ]; then
	printf 'ECWolf exited unexpectedly (%d); see %s\n' "$status" "$log_file" >&2
	exit 1
fi

if ! grep -q 'GFXTILES.CO7, 1115 lumps (graphics only)' "$log_file"; then
	printf 'Corridor 7 installation was not detected; see %s\n' "$log_file" >&2
	exit 1
fi

if ! grep -q '120 lumps (self-contained TED5)' "$log_file"; then
	printf 'The expected 60-map TED5 archive was not enumerated; see %s\n' "$log_file" >&2
	exit 1
fi

if ! grep -q 'MAP01 - Corridor 7 Level 1' "$log_file"; then
	printf 'Corridor 7 MAP01 was not entered; see %s\n' "$log_file" >&2
	exit 1
fi

if grep -Eqi 'invalid TED5|parser error|fatal error|segmentation fault|assertion.*failed' "$log_file"; then
	printf 'A parser/runtime failure was logged; see %s\n' "$log_file" >&2
	exit 1
fi

printf 'Corridor 7 smoke test passed; log: %s\n' "$log_file"
