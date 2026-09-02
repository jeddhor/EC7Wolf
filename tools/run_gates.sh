#!/bin/sh

# Run the EC7Wolf gate suite.
#
# One entry point for the whole thing, so that "did I break anything" is a
# single command locally and the same command in CI. Before this existed the
# gates were 27 scripts you had to remember to run, in no particular order, and
# the answer to "are we green" was whatever you happened to have run last.
#
# THE DATA PROBLEM. Almost every gate drives the actual game, which needs the
# commercial Corridor 7 files. Those must never be committed, so a hosted CI
# runner cannot have them. The suite therefore splits in two:
#
#   * data-free gates run anywhere, including on a stock GitHub runner. Today
#     that is the source-contract check, which is not a small thing -- it is the
#     one that keeps catching refactors that quietly changed a measured
#     constant.
#   * data gates need a directory holding MAPTEMP.CO7 and friends. They are run
#     locally, or by a self-hosted runner on a machine that owns the data.
#
# With no data directory this reports what it skipped and exits 0, because "the
# runner has no game" is not a build failure. Pass --require-data to turn that
# into an error, which is what the self-hosted CI job does so a runner that
# silently lost its data cannot report green.
#
# Usage:
#   run_gates.sh [-b BUILD_DIR] [-d DATA_DIR] [-r RELEASE_DIR]
#                [--editor-package DIR] [--require-data] [--list] [GATE...]
#
# GATE names are matched as substrings, so `run_gates.sh gl_` runs the OpenGL
# gates and `run_gates.sh laser` runs both laser ones.

set -eu

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)

build_dir=""
data_dir=""
release_dir=""
editor_package=""
require_data=0
list_only=0
selected=""

while [ "$#" -gt 0 ]; do
	case "$1" in
		-b) build_dir=$2; shift 2 ;;
		-d) data_dir=$2; shift 2 ;;
		-r) release_dir=$2; shift 2 ;;
		--editor-package) editor_package=$2; shift 2 ;;
		--require-data) require_data=1; shift ;;
		--list) list_only=1; shift ;;
		-h|--help)
			sed -n '3,40p' "$0" | sed 's/^# \{0,1\}//'
			exit 0 ;;
		-*) printf 'unknown option: %s\n' "$1" >&2; exit 2 ;;
		*)  selected="$selected $1"; shift ;;
	esac
done

# Defaults that match the layout this project actually uses.
[ -n "$build_dir" ]   || build_dir=$root/../builds/release-build
[ -n "$data_dir" ]    || data_dir=$root/../builds/release
[ -n "$release_dir" ] || release_dir=$root/../builds/release

# --- the gate list ---------------------------------------------------------
#
# Order is deliberate: the cheap source check first so an obvious contract
# breakage fails in a second rather than twenty minutes, then determinism (the
# one that says whether the simulation moved), then the rest.

# gl_selftest is here rather than below because --gltest is handled before the
# IWAD is opened: it needs no game data, and it is the only thing that proves the
# shaders actually compile on the runner's driver. A broken shader still links.
data_free_gates='definitions names ec7edit_e0 ec7edit_e1 ec7edit_e2 ec7edit_e3 ec7edit_e4 ec7edit_e5 ec7edit_e6 ec7edit_e7 ec7edit_e8 android_native android_apk android_device android_controls android_import gl_selftest corridor7_flic installer installer_gui installer_kde installer_windows installer_lifecycle ec7edit_e12 ec7edit_package'

data_gates='
corridor7
corridor7_determinism
corridor7_ai
corridor7_hearing
corridor7_automap_doorway
corridor7_door_jam
corridor7_cdaudio
corridor7_floorplan_reveal
corridor7_invulnerability
corridor7_keys_per_floor
corridor7_laserbarrier
corridor7_laserdamage
corridor7_menu_backdrop
corridor7_menu_transition
corridor7_pages
corridor7_topmessage
corridor7_upscale
corridor7_controls
ec7edit_e9
ec7edit_e10
ec7edit_e11
ec7edit_e13
ec7edit_override
ec7edit_assets
ec7edit_slice
multiplayer_loopback
multiplayer_latency
multiplayer_menu
multiplayer_arenas
multiplayer_rules
multiplayer_classes
multiplayer_presentation
multiplayer_hostile
multiplayer_setup
multiplayer_cancel
gl_world
gl_frame
gl_live
gl_visibility
gl_parity
gl_viewmodel_door
gl_filtering
gl_hardening
gl_bench
gl_modeswitch
glxbrz_parity
xbrz_scaling
renderscale'

# Needs the packaged release rather than a build dir, so it is called
# differently and only when that directory looks packaged.
release_gates='corridor7_release_startup'

matches() {
	# $1 = gate name. With no selection everything matches.
	[ -z "$selected" ] && return 0
	for want in $selected; do
		case "$1" in *"$want"*) return 0 ;; esac
	done
	return 1
}

if [ "$list_only" -eq 1 ]; then
	for g in $data_free_gates $data_gates $release_gates; do
		matches "$g" && printf '%s\n' "$g"
	done
	exit 0
fi

# --- environment -----------------------------------------------------------

have_data=0
if [ -n "$data_dir" ] && [ -f "$data_dir/MAPTEMP.CO7" ] && [ -f "$data_dir/GFXTILES.CO7" ]; then
	have_data=1
fi

missing_tools=""
for tool in python3 xvfb-run convert; do
	command -v "$tool" >/dev/null 2>&1 || missing_tools="$missing_tools $tool"
done

# SDL2 on a Wayland session ignores DISPLAY, so a test window opens on the
# developer's own screen instead of the Xvfb one. Every gate sets this itself;
# exporting it here as well means an ad-hoc run inside this script's environment
# cannot get it wrong either.
SDL_VIDEODRIVER=x11
SDL_AUDIODRIVER=dummy
export SDL_VIDEODRIVER SDL_AUDIODRIVER

printf 'EC7Wolf gates\n'
printf '  build   %s\n' "$build_dir"
if [ "$have_data" -eq 1 ]; then
	printf '  data    %s\n' "$data_dir"
else
	printf '  data    (none -- data gates will be skipped)\n'
fi
[ -n "$missing_tools" ] && printf '  missing:%s\n' "$missing_tools"
printf '\n'

if [ "$have_data" -eq 0 ] && [ "$require_data" -eq 1 ]; then
	printf 'FAIL: --require-data was given but %s holds no Corridor 7 data.\n' "$data_dir" >&2
	exit 1
fi

# --- run -------------------------------------------------------------------

# Where each gate's output lands. Overridable so CI can put it somewhere it can
# upload from -- a failed parity or visibility run says far more in its own log
# than in the 25 lines tailed below.
if [ -n "${GATE_LOG_DIR:-}" ]; then
	log_dir=$GATE_LOG_DIR
	mkdir -p "$log_dir"
else
	log_dir=$(mktemp -d /tmp/ec7wolf-gates.XXXXXX)
fi
passed=0
failed=0
skipped=0
failed_names=""

run_gate() {
	name=$1
	cmd_desc=$2
	shift 2

	printf '%-34s ' "$name"
	start=$(date +%s)
	if "$@" >"$log_dir/$name.log" 2>&1; then
		end=$(date +%s)
		# A gate that decided it had nothing to test says so on its first line
		# and exits 0, because "this runner has no phone" is not a build
		# failure. It is not a pass either, and reporting it as one is how a
		# suite comes to say the Android gates are green on a machine with no
		# Android device attached.
		first=$(sed -n '/[^[:space:]]/{p;q;}' "$log_dir/$name.log" 2>/dev/null)
		case $first in
			SKIP:*)
				printf 'SKIP  %s\n' "${first#SKIP: }"
				skipped=$((skipped + 1))
				;;
			*)
				printf 'PASS  %3ds\n' "$((end - start))"
				passed=$((passed + 1))
				;;
		esac
	else
		end=$(date +%s)
		printf 'FAIL  %3ds  %s\n' "$((end - start))" "$log_dir/$name.log"
		failed=$((failed + 1))
		failed_names="$failed_names $name"
	fi
	unset cmd_desc
}

skip_gate() {
	printf '%-34s SKIP  %s\n' "$1" "$2"
	skipped=$((skipped + 1))
}

for g in $data_free_gates; do
	matches "$g" || continue
	case "$g" in
		definitions)
			if ! command -v python3 >/dev/null 2>&1; then
				skip_gate "$g" "python3 is missing"
			else
				run_gate "$g" "source contract" python3 "$here/test_corridor7_definitions.py"
			fi ;;
		installer)
			# The dependency scan and --check need nothing but a build; the
			# full install half of this gate finds the disc itself, or skips.
			if [ ! -x "$build_dir/ec7wolf" ]; then
				skip_gate "$g" "no ec7wolf in $build_dir"
			else
				run_gate "$g" "installer" "$here/test_installer.sh" "$build_dir"
			fi ;;
		ec7edit_e0)
			# Data-free by design: no Corridor 7 data, no engine build, no
			# display. The editor's E0 foundation -- synthetic fixtures,
			# provenance, link containment.
			run_gate "$g" "ec7edit E0 foundation" \
				"$here/test_ec7edit_e0.sh" ;;
		ec7edit_e6)
			# Data-free: the compound tools, and the coverage report that is
			# E6's exit gate -- every semantic reachable or labeled.
			run_gate "$g" "ec7edit E6 semantics" \
				"$here/test_ec7edit_e6.sh" ;;
		ec7edit_e8)
			# The owned-data round trip needs the archive and is skipped
			# without it; the persistence half runs either way.
			run_gate "$g" "ec7edit E8 persistence" \
				"$here/test_ec7edit_e8.sh" "$data_dir" ;;
		ec7edit_e7)
			# Mostly data-free. The false-positive review needs the archive
			# and is skipped without it, so this runs either way and says
			# which half it did; it never prints anything from the maps but
			# a count of codes.
			run_gate "$g" "ec7edit E7 validation" \
				"$here/test_ec7edit_e7.sh" "$data_dir" ;;
		ec7edit_e5)
			# Data-free: tool geometry with no Qt, plus the tools driven
			# through the real window on the offscreen platform.
			run_gate "$g" "ec7edit E5 editing" \
				"$here/test_ec7edit_e5.sh" ;;
		ec7edit_e4)
			# Real Qt widgets on the offscreen platform: no display, no game
			# data. Skips where PySide6 is not installed.
			run_gate "$g" "ec7edit E4 shell" \
				"$here/test_ec7edit_e4.sh" ;;
		ec7edit_e3)
			# Data-free: ten thousand modeled operations and eleven injected
			# save failures, neither of which needs a display or the game.
			run_gate "$g" "ec7edit E3 document" \
				"$here/test_ec7edit_e3.sh" ;;
		ec7edit_e2)
			# Data-free: synthetic pages, plus the two "regenerate and diff"
			# checks that stop the catalog and the single-file asset browser
			# drifting from the engine and the decoders they are built from.
			run_gate "$g" "ec7edit E2 assets" \
				"$here/test_ec7edit_e2.sh" ;;
		ec7edit_e1)
			# Also data-free: the codec's own inputs are all generated. Runs
			# under CPython 3.12 when one is available, since that is the
			# reference runtime and not what this machine has by default.
			run_gate "$g" "ec7edit E1 codec" \
				"$here/test_ec7edit_e1.sh" ;;
		android_native)
			# Needs an NDK, not the game data, so it lives with the data-free
			# gates; it skips itself where there is no SDK, which is every
			# hosted runner.
			run_gate "$g" "android native libraries" \
				"$here/test_android_native.sh" ;;
		android_apk)
			# Reads a built APK back; skips when there is not one.
			run_gate "$g" "android apk" "$here/test_android_apk.sh" ;;
		android_device)
			# Installs on an attached phone and reads the result off the
			# screen. Needs hardware and the game data on it, so it is the
			# one gate that skips on the self-hosted runner too.
			run_gate "$g" "android device" \
				"$here/test_android_device.sh" ;;
		ec7edit_slice)
			# E5's exit gate: edit a real map through the real window, export
			# it, and watch EC7Wolf spawn the player where the edit put them.
			run_gate "$g" "ec7edit editing slice" \
				"$here/test_ec7edit_slice.sh" "$build_dir" "$data_dir" ;;
		ec7edit_assets)
			# Decodes the real artwork and checks the catalog against the
			# shipped maps. Reports counts and a digest, never retail bytes.
			run_gate "$g" "ec7edit asset decode" \
				"$here/test_ec7edit_assets.sh" "$build_dir" "$data_dir" ;;
		ec7edit_override)
			# The one editor claim unit tests cannot make: the engine loads
			# what the exporter writes, in place of a stock map. Needs the
			# owned archive, so it is a data gate rather than a hosted one.
			run_gate "$g" "ec7edit map override" \
				"$here/test_ec7edit_override.sh" "$build_dir" "$data_dir" ;;
		gl_bench)
			# Frame time at the shipped default. A floor, not a competition.
			run_gate "$g" "gl frame time" "$here/test_gl_bench.sh" \
				"$build_dir" "$data_dir" ;;
		android_controls)
			# Presses each control on an attached phone and reads the result out
			# of the game's own state. Needs hardware and the data on it.
			run_gate "$g" "android controls" \
				"$here/test_android_controls.sh" ;;
		android_import)
			# Runs after android_device and android_controls on purpose: it
			# clears the app to test a first install, which destroys the game
			# data those two need. Ordered the other way, they skip.
			# Wipes the app and installs the game the way a player would,
			# through the launcher's own import. Needs a phone and a copy of
			# the game to zip up, and skips without either.
			run_gate "$g" "android import" \
				"$here/test_android_import.sh" ;;
		names)
			# Names used but never defined. Python does not notice until
			# the line runs, and in an installer plenty of lines run only
			# on one platform.
			if ! command -v python3 >/dev/null 2>&1; then
				skip_gate "$g" "python3 is missing"
			else
				run_gate "$g" "undefined names" \
					"$here/check_undefined.sh" "$root"
			fi ;;
		installer_gui)
			# Drives the real wizard on Qt's offscreen platform. Needs no
			# display and no game data; the half that installs finds the
			# disc itself, or stops after the pages that need none.
			if ! python3 -c "import PySide6.QtWidgets" >/dev/null 2>&1; then
				skip_gate "$g" "PySide6 is missing"
			else
				run_gate "$g" "installer window" "$here/test_installer_gui.sh"
			fi ;;
		installer_kde)
			# The desktop entry, icons, launcher and uninstaller need
			# nothing but python3. The window-class measurement at the end
			# needs a playable install, and says so when there is not one.
			if ! command -v python3 >/dev/null 2>&1; then
				skip_gate "$g" "python3 is missing"
			else
				run_gate "$g" "desktop integration" "$here/test_installer_kde.sh" "$release_dir"
			fi ;;
		installer_windows)
			# Runs the installer's Windows path for real, under Wine: the
			# .cmd launcher, .lnk shortcuts made by Wine's own IShellLink,
			# and the Add/Remove Programs keys. Skips where wine is absent.
			if ! command -v wine >/dev/null 2>&1; then
				skip_gate "$g" "wine is missing"
			else
				run_gate "$g" "windows install" "$here/test_installer_windows.sh"
			fi ;;
		ec7edit_e12)
			run_gate "$g" "editor release consistency" \
				"$here/test_ec7edit_e12.sh" "$build_dir" ;;
		ec7edit_package)
			# The packaged editor. Skips itself when no package has been
			# built, which is the ordinary state during development: this
			# is a release check, and building one takes half a minute.
			if [ -z "$editor_package" ]; then
				skip_gate "$g" "no --editor-package given"
			else
				run_gate "$g" "packaged editor startup" \
					"$here/test_ec7edit_release_startup.sh" \
					"$editor_package" "$release_dir" ;
			fi ;;
		installer_lifecycle)
			# Installing twice, removing, resuming, and the unattended
			# front end. Needs a built engine and the disc; skips itself
			# without them.
			if [ ! -x "$build_dir/ec7wolf" ]; then
				skip_gate "$g" "no ec7wolf in $build_dir"
			else
				run_gate "$g" "install lifecycle" \
					"$here/test_installer_lifecycle.sh" "" "$build_dir"
			fi ;;
		corridor7_flic)
			# Needs a build and nothing else: --flictest decodes before any game
			# data is opened.
			if [ ! -x "$build_dir/ec7wolf" ]; then
				skip_gate "$g" "no ec7wolf in $build_dir"
			else
				run_gate "$g" "FLIC decoder" "$here/test_corridor7_flic.sh" "$build_dir"
			fi ;;
		gl_selftest)
			if ! command -v xvfb-run >/dev/null 2>&1; then
				skip_gate "$g" "xvfb-run is missing"
			elif [ ! -x "$build_dir/ec7wolf" ]; then
				skip_gate "$g" "no ec7wolf in $build_dir"
			elif [ "$have_data" -eq 1 ]; then
				run_gate "$g" "GL pipeline" "$here/test_gl_selftest.sh" "$build_dir" "$data_dir"
			else
				run_gate "$g" "GL pipeline" "$here/test_gl_selftest.sh" "$build_dir"
			fi ;;
	esac
done

for g in $data_gates; do
	matches "$g" || continue
	script="$here/test_$g.sh"
	if [ ! -x "$script" ]; then
		skip_gate "$g" "no such gate script"
		continue
	fi
	if [ "$have_data" -eq 0 ]; then
		skip_gate "$g" "needs Corridor 7 data"
		continue
	fi
	if [ -n "$missing_tools" ]; then
		skip_gate "$g" "missing:$missing_tools"
		continue
	fi
	if [ ! -x "$build_dir/ec7wolf" ]; then
		skip_gate "$g" "no ec7wolf in $build_dir"
		continue
	fi
	run_gate "$g" "gate" "$script" "$build_dir" "$data_dir"
done

for g in $release_gates; do
	matches "$g" || continue
	script="$here/test_$g.sh"
	if [ ! -x "$script" ] || [ ! -x "$release_dir/ec7wolf" ] || [ "$have_data" -eq 0 ]; then
		skip_gate "$g" "no packaged release in $release_dir"
		continue
	fi
	run_gate "$g" "packaged release" "$script" "$release_dir"
done

printf '\n%d passed, %d failed, %d skipped\n' "$passed" "$failed" "$skipped"

if [ "$failed" -ne 0 ]; then
	printf '\nfailed:%s\n' "$failed_names" >&2
	for n in $failed_names; do
		printf '\n--- %s ---\n' "$n" >&2
		tail -25 "$log_dir/$n.log" >&2
	done
	exit 1
fi

if [ "$passed" -eq 0 ]; then
	printf 'FAIL: nothing ran.\n' >&2
	exit 1
fi

printf 'logs: %s\n' "$log_dir"
