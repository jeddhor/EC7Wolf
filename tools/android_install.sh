# Sourced by the Android device gates. Not executable on its own.
#
# install_apk APK -- "adb install -r", but it comes back.
#
# A sideloaded APK that Google has never seen makes Play Protect put up "Send
# app for a security check?" *in front of the installer*, and the install then
# waits for an answer that a script is not there to give. adb blocks with no
# output and no timeout: one gate sat on a 19 MB install for fourteen minutes
# before anyone looked at the screen.
#
# So: run the install in the background, and while it is going, watch for that
# dialog and answer it. The answer is "Don't send" -- a test run is not a
# reason to upload somebody's private build to Google. If the prompt never
# appears, which is the normal case once the device has seen this signing key,
# this costs one uiautomator dump.
#
# Returns adb's own exit status, or 1 on timeout.
install_apk() {
	_apk=$1
	_out=$(mktemp)
	adb install -r "$_apk" >"$_out" 2>&1 &
	_pid=$!

	_waited=0
	while kill -0 "$_pid" 2>/dev/null; do
		sleep 3
		_waited=$((_waited + 3))

		# A hang this long is not a slow link; give up rather than
		# stall the whole suite behind one gate.
		if [ "$_waited" -ge 300 ]; then
			kill "$_pid" 2>/dev/null
			wait "$_pid" 2>/dev/null
			rm -f "$_out"
			install_output='timed out'
			return 1
		fi

		# Only start looking once it is slower than a healthy install.
		[ "$_waited" -ge 30 ] || continue
		[ $((_waited % 15)) -eq 0 ] || continue

		case $(adb shell dumpsys window 2>/dev/null |
		       grep -m1 'mCurrentFocus') in
		*protectdialogs*|*PlayProtect*) ;;
		*) continue ;;
		esac

		adb shell rm -f /sdcard/pp.xml >/dev/null 2>&1
		adb shell uiautomator dump /sdcard/pp.xml >/dev/null 2>&1 || continue
		_b=$(adb shell cat /sdcard/pp.xml 2>/dev/null | tr '<' '\n' |
		     grep -i "Don't send" |
		     grep -oE 'bounds="\[[0-9]+,[0-9]+\]\[[0-9]+,[0-9]+\]"' | head -1)
		adb shell rm -f /sdcard/pp.xml >/dev/null 2>&1
		[ -n "$_b" ] || continue

		_n=$(printf '%s' "$_b" | grep -oE '[0-9]+')
		_x1=$(printf '%s\n' "$_n" | sed -n 1p)
		_y1=$(printf '%s\n' "$_n" | sed -n 2p)
		_x2=$(printf '%s\n' "$_n" | sed -n 3p)
		_y2=$(printf '%s\n' "$_n" | sed -n 4p)
		printf '  ..   declining Play Protect upload prompt\n'
		adb shell input tap $(( (_x1 + _x2) / 2 )) $(( (_y1 + _y2) / 2 )) \
			>/dev/null 2>&1
	done

	_rc=0
	wait "$_pid" || _rc=$?
	install_output=$(tr -d '\r' <"$_out")
	rm -f "$_out"
	return $_rc
}
