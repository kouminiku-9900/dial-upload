#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/.dialup_gui.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "PID file not found: $PID_FILE"
  echo "If GUI is running manually, close it from the window title bar."
  exit 1
fi

PID="$(cat "$PID_FILE")"
if kill "$PID" >/dev/null 2>&1; then
  rm -f "$PID_FILE"
  echo "Dial-Up GUI stopped."
else
  rm -f "$PID_FILE"
  echo "Failed to stop PID $PID (already closed?)."
  exit 1
fi
