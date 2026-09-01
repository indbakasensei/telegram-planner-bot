#!/usr/bin/env bash
# start_qa.sh

cd "$(dirname "$0")/.." || exit 1

export ENV_FILE="env/.env.qa"
export BAKA_LOG_FILE="logs/baka_qa.log"
export BAKA_DEBUG_LOG_FILE="logs/baka_qa_debug.log"
export BAKA_PID_FILE="logs/baka_qa.pid"
export BAKA_ADMIN_FILE="logs/qa_admin_id.txt"
export APP_ENV="qa"

source venv/bin/activate
set -a; source env/.env.qa; set +a
nohup python main.py < /dev/null &>> "$BAKA_LOG_FILE" &
