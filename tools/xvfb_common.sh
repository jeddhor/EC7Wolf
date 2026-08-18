# Shared Xvfb startup for the gates that manage their own display.
#
# Most gates use `xvfb-run -a`, which picks a free display and waits for it.
# A few need a display number they can hand to xdotool or screenshot from, so
# they start Xvfb themselves -- and they all used to do it the same wrong way:
#
#     Xvfb "$display" ... &
#     sleep 2
#
# Two seconds is a guess, and on a machine where Mesa probes a GPU it cannot
# open during X startup it is not enough. The game then dies with "Could not
# initialize SDL video: x11 not available", the gate fails, and the failure
# reads exactly like a rendering regression rather than a race. Two gates lost
# that race the first time the whole suite was run in one go.
#
# Usage:  . "$(dirname "$0")/xvfb_common.sh"
#         xvfb_start "$display" "$work/xvfb.log" 900x600x24
#         ...
#         xvfb_stop
#
# xvfb_start exports nothing; the caller keeps passing DISPLAY explicitly as
# before. It sets $xvfb to the server's pid, which existing cleanup traps
# already kill.

xvfb_start() {
	_disp=$1
	_log=$2
	_geom=${3:-900x600x24}

	Xvfb "$_disp" -screen 0 "$_geom" >"$_log" 2>&1 &
	xvfb=$!

	# Poll for the server actually accepting connections. xdpyinfo is the
	# honest test; where it is missing, fall back to waiting for the socket and
	# then pausing, which is still better than a blind sleep.
	_i=0
	while [ "$_i" -lt 150 ]; do
		if command -v xdpyinfo >/dev/null 2>&1; then
			if DISPLAY="$_disp" xdpyinfo >/dev/null 2>&1; then
				return 0
			fi
		elif [ -e "/tmp/.X11-unix/X${_disp#:}" ]; then
			sleep 0.5
			return 0
		fi
		# If the server died, stop waiting for it.
		kill -0 "$xvfb" 2>/dev/null || break
		_i=$((_i + 1))
		sleep 0.1
	done

	printf 'FAIL: Xvfb %s never became ready; see %s\n' "$_disp" "$_log" >&2
	[ -s "$_log" ] && tail -10 "$_log" >&2
	return 1
}

xvfb_stop() {
	[ -n "${xvfb:-}" ] && kill "$xvfb" 2>/dev/null || true
}
