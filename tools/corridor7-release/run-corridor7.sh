#!/bin/sh

set -eu

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
config_file=${ECWOLF_CONFIG:-"$release_dir/ecwolf.cfg"}
save_dir=${ECWOLF_SAVEDIR:-"$release_dir/savegames"}
mkdir -p "$save_dir"
cd "$release_dir"

exec "$release_dir/ecwolf" --data CO7 \
	--config "$config_file" \
	--savedir "$save_dir" "$@"
