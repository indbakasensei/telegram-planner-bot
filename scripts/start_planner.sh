#!/usr/bin/env bash
# scripts/start_planner.sh

cd "$(dirname "$0")/.." || exit 1

export ENV_FILE="env/.env.production"
export BAKA_LOG_FILE="logs/planner.log"
export BAKA_DEBUG_LOG_FILE="logs/planner_debug.log"
export BAKA_PID_FILE="logs/planner.pid"
export APP_ENV="production"

source venv/bin/activate
set -a; source "$ENV_FILE"; set +a

nohup python main.py < /dev/null &>> "$BAKA_LOG_FILE" &
# wait for pid file
sleep 2
echo "Planner Bot started."
