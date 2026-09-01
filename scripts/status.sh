#!/usr/bin/env bash
# scripts/status.sh

cd "$(dirname "$0")/.." || exit 1

echo "BAKA Runtime Status"
echo ""

if [ -f "logs/planner.pid" ]; then
    PID=$(cat logs/planner.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "Planner Bot    : RUNNING (PID $PID)"
    else
        echo "Planner Bot    : STOPPED (Stale PID $PID)"
    fi
else
    echo "Planner Bot    : STOPPED"
fi

if [ -f "logs/baka_qa.pid" ]; then
    PID=$(cat logs/baka_qa.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "QA Bot         : RUNNING (PID $PID)"
    else
        echo "QA Bot         : STOPPED (Stale PID $PID)"
    fi
else
    echo "QA Bot         : STOPPED"
fi

echo ""
echo "Planner Log    : logs/planner.log"
echo "QA Log         : logs/baka_qa.log"
