#!/usr/bin/env bash
# status.sh

cd "$(dirname "$0")/.." || exit 1

check_status() {
    local pid_file=$1
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo "RUNNING (PID $pid)"
        else
            echo "STOPPED (stale PID $pid)"
        fi
    else
        echo "STOPPED"
    fi
}

echo "BAKA Runtime Status"
echo ""

printf "%-15s: %s\n" "Planner Bot" "$(check_status logs/planner.pid)"
printf "%-15s: %s\n" "QA Bot" "$(check_status logs/baka_qa.pid)"
echo ""
printf "%-15s: %s\n" "Planner Log" "logs/planner.log"
printf "%-15s: %s\n" "QA Log" "logs/baka_qa.log"
