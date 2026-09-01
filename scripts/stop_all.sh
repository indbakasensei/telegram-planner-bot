#!/usr/bin/env bash
# stop_all.sh

cd "$(dirname "$0")/.." || exit 1

if [ -f logs/planner.pid ]; then
    PLANNER_PID=$(cat logs/planner.pid)
    if kill -0 "$PLANNER_PID" 2>/dev/null; then
        echo "Stopping Planner Bot (PID: $PLANNER_PID)..."
        kill "$PLANNER_PID"
    fi
    rm -f logs/planner.pid
fi

if [ -f logs/baka_qa.pid ]; then
    QA_PID=$(cat logs/baka_qa.pid)
    if kill -0 "$QA_PID" 2>/dev/null; then
        echo "Stopping QA Bot (PID: $QA_PID)..."
        kill "$QA_PID"
    fi
    rm -f logs/baka_qa.pid
fi

echo "All bots stopped."
