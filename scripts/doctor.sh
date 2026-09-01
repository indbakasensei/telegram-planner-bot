#!/usr/bin/env bash
# doctor.sh - Validates BAKA repository hygiene and runtime dependencies.

echo "Running BAKA Doctor..."
FAIL=0

# --- Core Checks ---

echo "1. Checking Virtual Environment..."
if [ ! -d "venv" ]; then
    echo "❌ Missing venv/"
    FAIL=1
else
    echo "✅ Canonical venv/ found."
fi

echo "2. Checking python-telegram-bot (PTB) version..."
PTB_VER=$(source venv/bin/activate && python -c "import telegram; print(telegram.__version__)" 2>/dev/null)
if [[ "$PTB_VER" == *"20.7"* ]]; then
    echo "✅ PTB Version is 20.7"
else
    echo "❌ PTB Version mismatch or missing (found: $PTB_VER)"
    FAIL=1
fi

echo "3. Checking Analytics Imports..."
if source venv/bin/activate && python -c "import analytics" 2>/dev/null; then
    echo "✅ Analytics module is importable."
else
    echo "❌ Analytics module failed to import."
    FAIL=1
fi

echo "4. Checking SQLite WAL Mode..."
WAL_MODE=$(source venv/bin/activate && python -c "import sqlite3; print(sqlite3.connect('planner.db').execute('PRAGMA journal_mode;').fetchone()[0])" 2>/dev/null)
if [ "$WAL_MODE" = "wal" ]; then
    echo "✅ SQLite is in WAL mode."
else
    echo "❌ SQLite not in WAL mode (found: $WAL_MODE)"
    FAIL=1
fi

echo "5. Checking duplicate/temporary databases..."
TEMP_DBS=$(find . -maxdepth 1 -name "*.db" ! -name "planner.db" ! -name "bugs.db" ! -name "test_baka.db" | wc -l)
if [ "$TEMP_DBS" -eq 0 ]; then
    echo "✅ No duplicate/temporary databases found."
else
    echo "❌ Found temporary DBs:"
    find . -maxdepth 1 -name "*.db" ! -name "planner.db" ! -name "bugs.db" ! -name "test_baka.db"
    FAIL=1
fi

echo "6. Checking nested repository..."
if [ -d "telegram-planner-bot" ]; then
    echo "❌ Nested telegram-planner-bot directory found!"
    FAIL=1
else
    echo "✅ No nested repository found."
fi

echo "7. Checking Playwright install..."
if source venv/bin/activate && python -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    echo "✅ Playwright Python package installed."
else
    echo "❌ Playwright missing."
    FAIL=1
fi

# --- Dual Runtime Checks ---
echo ""
echo "--- Planner Runtime Health ---"

echo "8. Checking Planner Environment..."
if [ -f "env/.env.production" ]; then
    echo "✅ Planner environment (env/.env.production) exists."
else
    echo "❌ Missing env/.env.production"
    FAIL=1
fi

echo "9. Checking Planner Token..."
if grep -q "^BOT_TOKEN=." env/.env.production 2>/dev/null; then
    echo "✅ Planner token configured."
else
    echo "❌ Planner token missing in env/.env.production"
    FAIL=1
fi

echo "10. Checking Planner Log Writable..."
touch logs/planner.log 2>/dev/null
if [ -w "logs/planner.log" ]; then
    echo "✅ Planner log is writable."
else
    echo "❌ Cannot write to logs/planner.log"
    FAIL=1
fi

echo "11. Checking Planner PID..."
if [ -f "logs/planner.pid" ]; then
    PID=$(cat logs/planner.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "✅ Planner PID $PID is active."
    else
        echo "❌ Planner PID $PID is stale."
        FAIL=1
    fi
else
    echo "✅ No Planner PID (not running)."
fi

echo ""
echo "--- QA Runtime Health ---"

echo "12. Checking QA Environment..."
if [ -f "env/.env.qa" ]; then
    echo "✅ QA environment (env/.env.qa) exists."
else
    echo "❌ Missing env/.env.qa"
    FAIL=1
fi

echo "13. Checking QA Token..."
if grep -q "^BOT_TOKEN=." env/.env.qa 2>/dev/null; then
    echo "✅ QA token configured."
else
    echo "❌ QA token missing in env/.env.qa"
    FAIL=1
fi

echo "14. Checking QA Log Writable..."
touch logs/baka_qa.log 2>/dev/null
if [ -w "logs/baka_qa.log" ]; then
    echo "✅ QA log is writable."
else
    echo "❌ Cannot write to logs/baka_qa.log"
    FAIL=1
fi

echo "15. Checking QA PID..."
if [ -f "logs/baka_qa.pid" ]; then
    PID=$(cat logs/baka_qa.pid)
    if kill -0 "$PID" 2>/dev/null; then
        echo "✅ QA PID $PID is active."
    else
        echo "❌ QA PID $PID is stale."
        FAIL=1
    fi
else
    echo "✅ No QA PID (not running)."
fi

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "All checks passed! BAKA Dual Runtime is healthy."
    exit 0
else
    echo "Doctor found issues."
    exit 1
fi
