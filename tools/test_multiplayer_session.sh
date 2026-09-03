#!/bin/sh

# Regression test: authority, peer, player slot and local view are four
# separate things.
#
# Milestone S2 of docs/multiplayer-bots-and-server.md.
#
# The engine had one number that meant the number of sockets, the number of
# command producers, the number of player_t objects and the bound of every
# spawn, score and respawn loop -- and one other number that meant the slot
# this machine plays, the slot it draws, and the machine that owns the arbiter
# role. Both are fine while one process holds one player and one player holds
# one socket. Neither a bot, which occupies a slot and owns no socket, nor a
# dedicated server, which owns a socket and occupies no slot, can be described
# in that vocabulary. That is why both projects were blocked on the same
# refactor.
#
# So the engine is asked to construct the sessions it cannot yet play:
#
#   * an authority with eleven players, none of which are its own;
#   * a slot 0 owned by a peer that is not the authority;
#   * a roster with more slots than peers, and one with more peers than slots;
#   * the three capacities pushed past their own bounds, one at a time; and
#   * a roster corrupted in each of the ways the invariants forbid.
#
# None of it touches players[], ConsolePlayer or a socket, which is most of
# what it is proving: if a playerless authority can only be described by code
# that indexes a player array, it cannot exist, and Phase D would be far too
# late to find that out.
#
# Runs before any game data is opened, so it needs neither a Corridor 7
# installation nor a window.
#
# Usage: test_multiplayer_session.sh BUILD_DIR

set -eu

if [ "$#" -lt 1 ]; then
	printf 'usage: %s BUILD_DIR\n' "$0" >&2
	exit 2
fi

build_dir=$(cd "$1" && pwd)
[ -x "$build_dir/ec7wolf" ] || { printf 'SKIP: no ec7wolf in %s\n' "$build_dir"; exit 0; }

work=$(mktemp -d /tmp/ec7wolf-session.XXXXXX)
cleanup() {
	if [ "${KEEP_WORK:-0}" = "1" ]; then
		printf 'kept: %s\n' "$work"
	else
		rm -rf "$work"
	fi
}
trap cleanup EXIT INT TERM

# Deliberately not run under stdbuf, unlike most of this suite. stdbuf works by
# preloading libstdbuf.so, which displaces the AddressSanitizer runtime from
# the front of the library list -- so a sanitizer build refuses to start with
# "ASan runtime does not come first", and this gate fails on the build most
# likely to have something to say. Nothing is lost by leaving it out: this
# process runs to completion and is never cut short, so there is no tail for
# buffering to eat.
if "$build_dir/ec7wolf" --sessiontest >"$work/out.txt" 2>&1; then
	rc=0
else
	rc=$?
fi

sed 's/^/  /' "$work/out.txt"

checks=$(sed -n 's/^\([0-9]*\) checks.*/\1/p' "$work/out.txt")
[ -n "$checks" ] || checks=0

if [ "$rc" -ne 0 ]; then
	printf '\nFAIL: the session model does not hold.\n'
	exit 1
fi

# A self-test that stops constructing sessions still exits zero. The count is
# the difference between "everything passed" and "nothing ran", and this suite
# has been fooled by that distinction before.
if [ "$checks" -lt 50 ]; then
	printf '\nFAIL: only %s checks ran; the self-test has lost most of itself.\n' \
		"$checks"
	exit 1
fi

printf '\nPASS: %s checks, including an authority that owns no player.\n' "$checks"
