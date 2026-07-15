#!/bin/sh

# Load a representative cross-section of Corridor 7's campaign, secret,
# unused, and network maps from an original installation. No game data is
# copied or modified.

set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
	printf 'usage: %s ECWOLF_BUILD_DIR CORRIDOR7_DATA_DIR [LOG_DIR] [--all]\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
log_dir=${3:-"$build_dir/corridor7-map-validation"}
ecwolf="$build_dir/ecwolf"
maps="MAP01 MAP10 MAP20 MAP29 MAP30 MAP31 MAP39 MAP40 MAP41 MAP46 MAP51 MAP60"
validation_label="representative-map"
if [ "${4:-}" = "--all" ]; then
	maps=$(i=1; while [ "$i" -le 60 ]; do printf 'MAP%02d ' "$i"; i=$((i + 1)); done)
	validation_label="all-map"
elif [ "$#" -eq 4 ]; then
	printf 'unknown validation mode: %s\n' "$4" >&2
	exit 2
fi

cmake --build "$build_dir"
mkdir -p "$log_dir"

config_root=$(mktemp -d /tmp/ecwolf-corridor7-validation.XXXXXX)
cleanup() {
	rm -rf "$config_root"
}
trap cleanup EXIT HUP INT TERM

for map in $maps; do
	log="$log_dir/$map.log"
	config="$config_root/$map.cfg"
	save="$config_root/$map-save"
	mkdir -p "$save"
	set +e
	(
		cd "$data_dir"
		timeout 6s env SDL_AUDIODRIVER=dummy \
			xvfb-run -a stdbuf -oL -eL "$ecwolf" --data CO7 --config "$config" \
			--savedir "$save" --nowait --tedlevel "$map" --skill 2
	) >"$log" 2>&1
	status=$?
	set -e
	if [ "$status" -ne 0 ] && [ "$status" -ne 124 ]; then
		printf '%s exited unexpectedly (%d); see %s\n' "$map" "$status" "$log" >&2
		exit 1
	fi
	if ! grep -q "^$map - " "$log"; then
		printf '%s was not entered; see %s\n' "$map" "$log" >&2
		exit 1
	fi
	if grep -Eqi 'Unknown old type|invalid TED5|parser error|fatal error|segmentation fault|assertion.*failed' "$log"; then
		printf '%s logged a translation/runtime failure; see %s\n' "$map" "$log" >&2
		exit 1
	fi
	printf '%s ok\n' "$map"
done

printf 'Corridor 7 %s validation passed; logs: %s\n' "$validation_label" "$log_dir"
