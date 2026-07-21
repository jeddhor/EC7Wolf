#!/bin/sh

# Build a single-directory Corridor 7 package from an EC7Wolf build tree and a
# legally owned Corridor 7 installation. The output intentionally contains
# commercial game data and must not be committed or redistributed.

set -eu

if [ "$#" -ne 3 ]; then
	printf 'usage: %s EC7WOLF_BUILD_DIR CORRIDOR7_DATA_DIR OUTPUT_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
data_dir=$(cd "$2" && pwd)
output_parent=$(dirname -- "$3")
output_name=$(basename -- "$3")
mkdir -p "$output_parent"
output_parent=$(cd "$output_parent" && pwd)
output_dir="$output_parent/$output_name"
staging_dir="$output_parent/.$output_name.tmp.$$"
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

cleanup() {
	rm -rf "$staging_dir"
}
trap cleanup EXIT HUP INT TERM

for required in ec7wolf ec7wolf.pk3; do
	if [ ! -f "$build_dir/$required" ]; then
		printf 'required EC7Wolf build artifact is missing: %s\n' "$build_dir/$required" >&2
		exit 1
	fi
done

for required in CORR7CD.EXE MAPTEMP.CO7 GFXTILES.CO7 \
	VGADICT.CO7 VGAHEAD.CO7 VGAGRAPH.CO7 AUDIOHED.CO7 AUDIOT.CO7; do
	if [ ! -f "$data_dir/$required" ]; then
		printf 'required Corridor 7 game file is missing: %s\n' "$data_dir/$required" >&2
		exit 1
	fi
done

# If the build directory is an actual CMake build tree, refresh it before
# packaging. The revision-header target is always run and can update its header
# after Ninja has already evaluated dependencies, so a second incremental pass
# ensures a newly committed revision is compiled into the packaged executable.
# When given a pre-built release folder (e.g. the release/ produced by
# docker.sh, which contains only ec7wolf + ec7wolf.pk3), skip the rebuild and
# package the artifacts as-is.
if [ -f "$build_dir/CMakeCache.txt" ]; then
	cmake --build "$build_dir"
	cmake --build "$build_dir"
fi

rm -rf "$staging_dir"
mkdir -p "$staging_dir/savegames"
cp -a "$data_dir/." "$staging_dir/"
install -m 755 "$build_dir/ec7wolf" "$staging_dir/ec7wolf"
install -m 644 "$build_dir/ec7wolf.pk3" "$staging_dir/ec7wolf.pk3"
install -m 755 "$script_dir/corridor7-release/run-corridor7.sh" \
	"$staging_dir/run-corridor7.sh"
install -m 644 "$script_dir/corridor7-release/README.txt" \
	"$staging_dir/README.txt"

rm -rf "$output_dir"
mv "$staging_dir" "$output_dir"
trap - EXIT HUP INT TERM

printf 'Corridor 7 release package created: %s\n' "$output_dir"
printf 'Launch it with: %s/run-corridor7.sh\n' "$output_dir"
