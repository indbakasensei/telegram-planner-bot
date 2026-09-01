#!/usr/bin/env bash
# scripts/stop_all.sh

cd "$(dirname "$0")" || exit 1
./stop_qa.sh

cd ..
if [ -f "logs/planner.pid" ]; then
    PID=$(cat logs/planner.pid)
    echo "Stopping Planner Bot (PID $PID)..."
    kill "$PID" 2>/dev/null
    sleep 2
    if kill -0 "$PID" 2>/dev/null; then
        kill -9 "$PID"
    fi
    echo "Planner Bot stopped."
else
    echo "Planner Bot not running (no PID file)."
fi

cd scripts
./status.sh
