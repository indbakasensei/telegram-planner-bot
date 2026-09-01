#!/usr/bin/env bash
# scripts/stop_qa.sh

cd "$(dirname "$0")/.." || exit 1

if [ -f "logs/baka_qa.pid" ]; then
    PID=$(cat logs/baka_qa.pid)
    echo "Stopping QA Bot (PID $PID)..."
    kill "$PID" 2>/dev/null
    sleep 2
    if kill -0 "$PID" 2>/dev/null; then
        kill -9 "$PID"
    fi
    echo "QA Bot stopped."
else
    echo "QA Bot not running (no PID file)."
fi
