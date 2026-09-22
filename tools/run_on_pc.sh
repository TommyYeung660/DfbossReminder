#!/usr/bin/env bash
# Run a command on the game PC inside its *interactive desktop session*.
#
# Why this exists: SSH sessions on Windows run in session 0, which cannot see or
# create anything on the visible desktop. The overlay window is exactly such a
# thing, so it cannot be verified over a plain SSH command. A scheduled task with
# /it runs in the interactive session instead, so this script drives that.
#
# Usage:
#   tools/run_on_pc.sh 'call tools\pc\verify-overlay.cmd' --timeout 120
#   tools/run_on_pc.sh 'py -3 tools\dfboss_main.py --once --user-id 14008279'
#
# The command text is written to <repo>\.run.cmd, the DFB-Interactive task is
# triggered, and its output (.run-out-<run token>.txt) is printed here.
#
# One-time setup (already done on the game PC, recorded for a rebuild):
#   ssh df-pc 'schtasks /create /tn DFB-Interactive /tr "cmd /c C:\DFTools\DfbossReminder\tools\pc\dfb-interactive.cmd" /sc once /st 23:59 /it /f'
# Remove it with:
#   ssh df-pc 'schtasks /delete /tn DFB-Interactive /f'
set -euo pipefail

HOST="${DFB_HOST:-df-pc}"
REMOTE_REPO="${DFB_PC_REPO:-C:/DFTools/DfbossReminder}"
TASK="${DFB_TASK:-DFB-Interactive}"
TIMEOUT="${DFB_TIMEOUT:-180}"

# Raw ssh: the exit status is the remote command's, which the polling depends on.
remote() {
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" "$@" 2>&1 |
        grep -v "post-quantum\|store now\|openssh.com/pq" || true
}

# Same, but keep the exit status for a question we are asking the remote side.
remote_status() {
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" "$@" >/dev/null 2>&1
}

COMMAND="${1:-}"
if [[ -z "$COMMAND" ]]; then
    echo "usage: $0 '<command to run on the PC>' [--timeout seconds]" >&2
    exit 2
fi
shift || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --timeout) TIMEOUT="$2"; shift 2 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

command_file="$(mktemp)"
output_file="$(mktemp)"
trap 'rm -f "$command_file" "$output_file"' EXIT

# A run token makes the wait loop immune to stale output: the scheduled task is
# ignored while a previous instance is still running, so a plain "does the file
# have EXITCODE" check can return another run's result.
#
# The token also names the output file. It used to be one shared .run-out.txt that the
# runner deleted first, which fails in a way that looks like a hung PC: a command that
# leaves a background process behind - an overlay started to keep running, say - hands
# that process its inherited stdout handle, so the file cannot be deleted or rewritten
# and every later run polls its own token in a file nobody is writing and times out.
# A file per run cannot be held hostage by an earlier run's process.
run_token="DFB-RUN-$(date +%s)-$$"
# Two spellings of the same file, because the two callers disagree about separators:
# scp wants the unix-ish form, while findstr and del reject a path whose last separator
# is a forward slash and fail with only "cannot open" (findstr) or silence (del). Both
# of those failing quietly is what a poll timeout looks like from here.
remote_out="$REMOTE_REPO/.run-out-$run_token.txt"
remote_out_shell="$REMOTE_REPO\\.run-out-$run_token.txt"
{
    printf 'chcp 65001 >nul\r\n'
    printf 'set PYTHONIOENCODING=utf-8\r\n'
    printf 'echo %s\r\n' "$run_token"
    printf '%s\r\n' "$COMMAND"
    # The completion marker is written by the file that runs the command, not by the
    # wrapper that called it. A command that leaves a background process holding the
    # console made the wrapper's own trailing EXITCODE line never appear, and the poll
    # then timed out even though the work had finished.
    printf 'echo EXITCODE=%%ERRORLEVEL%%\r\n'
} > "$command_file"

token_file="$(mktemp)"
printf '%s' "$run_token" > "$token_file"

scp -q -o BatchMode=yes "$command_file" "$HOST:$REMOTE_REPO/.run.cmd"
# How the task wrapper learns which output file to write: it cannot be given an
# argument, so the name travels in the body of .run-token.txt.
scp -q -o BatchMode=yes "$token_file" "$HOST:$REMOTE_REPO/.run-token.txt"
rm -f "$token_file"
remote "schtasks /run /tn $TASK" >/dev/null

# Poll for the completion marker. The wrapper writes EXITCODE= only after the
# command returns, so this is also what tells us it is safe to read the file.
started=$SECONDS
finished=0
while ((SECONDS - started < TIMEOUT)); do
    if remote_status "findstr /c:\"$run_token\" \"$remote_out_shell\"" &&
        remote_status "findstr /c:\"EXITCODE=\" \"$remote_out_shell\""; then
        finished=1
        break
    fi
    sleep 5
done

scp -q -o BatchMode=yes "$HOST:$remote_out" "$output_file"
cat "$output_file"
# This run's file only, and only now that it has been read.
remote "del /q \"$remote_out_shell\" 2>nul" >/dev/null

if ((finished == 0)); then
    echo "--- still running after ${TIMEOUT}s; output above is partial ---" >&2
    exit 1
fi
if ! grep -q "EXITCODE=0" "$output_file"; then
    echo "--- the command failed (see EXITCODE above) ---" >&2
    exit 1
fi
