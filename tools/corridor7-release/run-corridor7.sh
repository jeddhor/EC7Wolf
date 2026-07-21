#!/bin/sh

set -eu

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
config_file=${EC7WOLF_CONFIG:-"$release_dir/ec7wolf.cfg"}
save_dir=${EC7WOLF_SAVEDIR:-"$release_dir/savegames"}
mkdir -p "$save_dir"
cd "$release_dir"

exec "$release_dir/ec7wolf" --data CO7 \
	--config "$config_file" \
	--savedir "$save_dir" "$@"
