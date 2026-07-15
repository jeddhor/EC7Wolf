#!/bin/sh

set -eu

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p "$release_dir/savegames"
cd "$release_dir"

exec "$release_dir/ecwolf" --data CO7 \
	--config "$release_dir/ecwolf.cfg" \
	--savedir "$release_dir/savegames" "$@"
