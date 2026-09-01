#!/usr/bin/env bash
# doctor.sh - Validates BAKA repository hygiene and runtime dependencies.

echo "Running BAKA Doctor..."
FAIL=0

# 1. Runtime / Virtual Environment
echo "1. Checking Virtual Environment..."
if [ ! -d "venv" ]; then
    echo "❌ Missing venv/"
    FAIL=1
else
    echo "✅ Canonical venv/ found."
fi

# 2. PTB Version
echo "2. Checking python-telegram-bot (PTB) version..."
PTB_VER=$(source venv/bin/activate && python -c "import telegram; print(telegram.__version__)" 2>/dev/null)
if [[ "$PTB_VER" == *"20.7"* ]]; then
    echo "✅ PTB Version is 20.7"
else
    echo "❌ PTB Version mismatch or missing (found: $PTB_VER)"
    FAIL=1
fi

# 3. Analytics Imports
echo "3. Checking Analytics Imports..."
if source venv/bin/activate && python -c "import analytics" 2>/dev/null; then
    echo "✅ Analytics module is importable."
else
    echo "❌ Analytics module failed to import."
    FAIL=1
fi

# 4. WAL Mode
echo "4. Checking SQLite WAL Mode..."
WAL_MODE=$(source venv/bin/activate && python -c "import sqlite3; print(sqlite3.connect('planner.db').execute('PRAGMA journal_mode;').fetchone()[0])" 2>/dev/null)
if [ "$WAL_MODE" = "wal" ]; then
    echo "✅ SQLite is in WAL mode."
else
    echo "❌ SQLite not in WAL mode (found: $WAL_MODE)"
    FAIL=1
fi

# 5. Duplicate DBs
echo "5. Checking duplicate/temporary databases..."
TEMP_DBS=$(find . -maxdepth 1 -name "*.db" ! -name "planner.db" ! -name "bugs.db" | wc -l)
if [ "$TEMP_DBS" -eq 0 ]; then
    echo "✅ No duplicate/temporary databases found."
else
    echo "❌ Found temporary DBs:"
    find . -maxdepth 1 -name "*.db" ! -name "planner.db" ! -name "bugs.db"
    FAIL=1
fi

# 6. Nested Repo
echo "6. Checking nested repository..."
if [ -d "telegram-planner-bot" ]; then
    echo "❌ Nested telegram-planner-bot directory found!"
    FAIL=1
else
    echo "✅ No nested repository found."
fi

# 7. Playwright install
echo "7. Checking Playwright install..."
if source venv/bin/activate && python -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    echo "✅ Playwright Python package installed."
else
    echo "❌ Playwright missing."
    FAIL=1
fi

# 8. Self-tests
echo "8. Checking Self-Tests..."
# We will just run a simple subset or rely on pytest discovery.
if source venv/bin/activate && pytest tests/ -q --disable-warnings > /dev/null 2>&1; then
    echo "✅ Self-tests run successfully."
else
    echo "❌ Self-tests failed or not runnable."
    FAIL=1
fi

if [ "$FAIL" -eq 0 ]; then
    echo "All checks passed! BAKA is healthy."
    exit 0
else
    echo "Doctor found issues."
    exit 1
fi
