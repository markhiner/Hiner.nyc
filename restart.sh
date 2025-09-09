#!/bin/bash
# restart.sh – kill and restart yocto app.py server

# adjust path if app.py lives elsewhere
APP_PATH="$HOME/hiner.nyc/yocto/app.py"
VENV_PATH="$HOME/yocto-venv/bin/activate"

echo ">>> Stopping any running app.py..."
pkill -f "$APP_PATH"

echo ">>> Starting app.py..."
cd "$(dirname "$APP_PATH")" || exit 1
source "$VENV_PATH"
nohup python3 "$APP_PATH" > server.log 2>&1 &

echo ">>> app.py restarted. Logs: $(dirname "$APP_PATH")/server.log"