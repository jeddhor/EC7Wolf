#!/bin/sh

set -eu

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
config_file=${EC7WOLF_CONFIG:-"$release_dir/ec7wolf.cfg"}
save_dir=${EC7WOLF_SAVEDIR:-"$release_dir/savegames"}
# Launch on the hardware renderer by default rather than inheriting whatever
# Vid_Renderer the config happens to hold, so a stray write to ec7wolf.cfg cannot
# quietly drop the game back to the software raycaster. Set EC7WOLF_RENDERER
# (opengl or software) to override; it has to be passed here rather than appended
# to "$@" because the engine's --vid-renderer scan stops at the first match.
renderer=${EC7WOLF_RENDERER:-opengl}
mkdir -p "$save_dir"
cd "$release_dir"

exec "$release_dir/ec7wolf" --data CO7 \
	--vid-renderer "$renderer" \
	--config "$config_file" \
	--savedir "$save_dir" "$@"
