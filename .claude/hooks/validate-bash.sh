#!/usr/bin/env bash
# PreToolUse hook for Bash — blocks obviously destructive commands.
# Wired into .claude/settings.json under "hooks".
#
# Uses python3 instead of jq to read tool_input.command: this project already
# requires Python 3.11+, but jq isn't guaranteed to be installed, especially
# on the Windows machines this project's webui.bat/webui.sh split targets.
set -euo pipefail

cmd=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))')

if echo "$cmd" | grep -qE 'rm -rf /(\s|$)|:\(\)\{ :\|:& \};:'; then
  echo "Blocked: destructive command detected" >&2
  exit 2
fi

exit 0
