#!/usr/bin/env bash
# Copy this working tree to the game PC, and prove the copy arrived intact.
#
# The PC's checkout is a plain directory, not a clone, so it is kept in step by copying
# files into it - and a hand-written list of files is how it drifted: a file that was not on
# somebody's list stayed old, got built into the Desktop exe, and the only symptom was a
# button raising inside a Tk callback that swallowed the error. So this copies everything and
# then compares digests of every source file on both machines, which is the part that makes
# the copy trustworthy rather than hopeful.
#
# Usage:
#   tools/deploy-to-pc.sh                 # copy and verify
#   tools/deploy-to-pc.sh --no-verify     # copy only (not recommended)
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PC="${DFB_PC:-df-pc}"
REMOTE="C:/DFTools/DfbossReminder"
VERIFY=1
[ "${1:-}" = "--no-verify" ] && VERIFY=0

cd "$HERE"
echo "copying src, tools, tests, docs to $PC:$REMOTE"
scp -q -r -o BatchMode=yes src tools tests docs "$PC:$REMOTE/"

if [ "$VERIFY" = "0" ]; then
    echo "copied (not verified)"
    exit 0
fi

echo "comparing digests"
python3 tools/pc/source-digests.py --write /tmp/dfb-digests-here.txt >/dev/null
ssh -o BatchMode=yes "$PC" 'cmd /c "cd /d C:\DFTools\DfbossReminder && py -3 tools\pc\source-digests.py --write C:\Windows\Temp\dfb-digests-there.txt"' >/dev/null
scp -q -o BatchMode=yes "$PC:C:/Windows/Temp/dfb-digests-there.txt" /tmp/dfb-digests-there.txt
python3 tools/pc/source-digests.py --check /tmp/dfb-digests-there.txt
