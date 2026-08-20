#!/bin/sh

# Names used but never defined, in both languages this project scripts in.
#
# Neither language notices on its own. Python raises NameError only when the
# line runs, and in an installer plenty of lines run only on one platform --
# developer_environment() was deleted by an edit and every test still passed.
# The shell is worse: an unset variable under `set -u` aborts the script at the
# moment it is read, so a typo in one gate's dispatch killed an entire suite
# run after the first gate.
#
# Usage: check_undefined.sh REPO_ROOT

set -eu

root=${1:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
here="$root/tools"
status=0

echo "python:"
if ! python3 "$here/check_names.py" "$root/installer" "$here/c7disc.py" \
	"$here/make_release.py" "$here/check_names.py"; then
	status=1
fi

echo
echo "shell:"
if ! command -v shellcheck >/dev/null 2>&1; then
	echo "  shellcheck is not installed; shell scripts not checked"
else
	# SC2154 only: a variable read but never assigned. The rest of what
	# shellcheck has to say about these scripts is style, and a gate that
	# fails on style is a gate people start ignoring.
	if shellcheck -S warning -i SC2154 "$here"/*.sh 2>&1 | grep -q "SC2154"; then
		shellcheck -S warning -i SC2154 "$here"/*.sh
		status=1
	else
		echo "  $(ls "$here"/*.sh | wc -l) scripts, no unassigned variables"
	fi
fi

exit "$status"
