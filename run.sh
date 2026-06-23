#!/bin/bash
cd ~/telegram-planner-bot
source venv/bin/activate

echo "🤖 Starting bot with auto-restart..."
while true; do
    python3 main.py
    echo "⚠️ Bot crashed or stopped. Restarting in 5 seconds..."
    sleep 5
done
