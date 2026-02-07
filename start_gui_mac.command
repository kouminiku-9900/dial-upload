#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
nohup "$PYTHON_BIN" "$SCRIPT_DIR/dialup_gui.py" >/tmp/dialup_gui.log 2>&1 &
PID=$!
echo "$PID" > "$SCRIPT_DIR/.dialup_gui.pid"
echo "Dial-Up GUI started. PID=$PID"
