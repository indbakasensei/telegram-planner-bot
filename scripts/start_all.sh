#!/usr/bin/env bash
# start_all.sh

cd "$(dirname "$0")/.." || exit 1

echo "Starting Planner Bot..."
./scripts/start_planner.sh

# Wait until Planner acquires instance lock by checking the PID file
echo "Waiting for Planner Bot to acquire instance lock..."
while [ ! -s logs/planner.pid ]; do
    sleep 0.5
done

echo "Starting QA Bot..."
./scripts/start_qa.sh

# Wait for QA Bot lock
while [ ! -s logs/baka_qa.pid ]; do
    sleep 0.5
done

PLANNER_PID=$(cat logs/planner.pid)
QA_PID=$(cat logs/baka_qa.pid)

echo ""
echo "Planner Bot  PID: $PLANNER_PID"
echo "QA Bot       PID: $QA_PID"
echo ""
echo "Logs:"
echo "logs/planner.log"
echo "logs/baka_qa.log"
