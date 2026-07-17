#!/usr/bin/env bash
# dev_reset.sh — safe developer reset (v14.21, Maintenance sprint).
#
# Removes ONLY regenerable development artifacts:
#   - __pycache__/ directories (bytecode caches)
#   - .pytest_cache/            (pytest state)
#   - .coverage                 (coverage data)
#   - debugbot.log + rotations  (the dedicated debug log — DEBUGGING.md)
#
# NEVER touches: source files, documentation, git history, venv/,
# .env, admin_id.txt, planner.db, bugs.db, bot.log (production log),
# backups/. Test databases need no cleanup here — the pytest suite
# creates them in the system temp directory via tmp_path and they are
# cleaned automatically.
#
# Must be run explicitly by a developer:  ./dev_reset.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "BAKA dev reset — removing regenerable development artifacts only."

find . -path ./venv -prune -o -type d -name '__pycache__' -print -exec rm -rf {} + 2>/dev/null || true
rm -rf .pytest_cache && echo "removed .pytest_cache"
rm -f .coverage && echo "removed .coverage (if present)"
rm -f debugbot.log debugbot.log.* && echo "removed debugbot.log (+rotations, if present)"

echo "Done. Production data (planner.db, bugs.db, bot.log, .env, backups/) untouched."
