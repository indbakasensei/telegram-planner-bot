# Debugging

## Built-in tooling

| Tool | What it does |
|---|---|
| `debug` / `/debug` | Toggles per-user verbose mode — every bot reply gets an appended debug box showing detected intent, extracted entities, and parsed date/time. State is in-memory only (see [Known Issues](#known-issues)) |
| `report <text>` / `/report` | Files a bug into `bugs.db`, auto-capturing the user's last message, detected intent, entities, and (for auto-caught exceptions) a full traceback |
| `bugs` / `/bugs` | Lists open bug reports |
| `resolve <id>` / `/resolve` | Marks a bug resolved |
| `trace` / `/trace` | Shows the last AI interaction in detail: input, intent, entities, reply. Backed by an in-memory rolling log of the last 50 interactions per user (`debug_system.py`) — also does not survive a restart |
| `selftest` / `/selftest` | Prints the current 72-test manual checklist from `debug_system.py`'s `SELFTEST_MESSAGES` — see [TESTING.md](TESTING.md) |
| `sql <SELECT ...>` (admin only) | Read-only SQL console against `planner.db`, capped at 30 rows |
| `bot.log` | Full activity log — messages, intents, entities, API errors, reminder fires, exceptions with stack traces. Passes through `log_sanitizer.py`, which redacts bot tokens, `nvapi-...`/`sk-...` keys, and Telegram user IDs before they hit the log file |

`error_handler` in `main.py` catches every unhandled exception in any
handler, auto-logs it to `bugs.db` via `debug_system.log_exception()`, and
replies to the user rather than crashing the process.

## Where to look for a given kind of bug

| Symptom | Likely cause / where to look |
|---|---|
| Wrong date/time extracted | `date_parser.py` regex patterns, or the AI overriding a value it shouldn't — check `get_baka_response()`'s disambiguation rules in [PROMPTS.md](PROMPTS.md) |
| Task misclassified (e.g. TASK vs HABIT vs GOAL) | `get_baka_response()`'s intent taxonomy/disambiguation rules, `baka_brain.py` ~L220-302 |
| Reminder fires at the wrong time, twice, or not at all | `scheduler.py`'s `get_due_tasks()` — five separate query cases (one-time, daily/weekly/monthly recurring, expired-snooze) each with their own dedup logic; see [docs/scheduler.md](docs/scheduler.md) |
| A dashboard button/callback does nothing or errors | `main.py`'s `handle_callback` router — check the callback's namespace prefix (`dash:`, `proj:`, plain) routes to the right sub-handler |
| `/usage`, `/performance`, `/errors` show nothing | Expected right now — see [Known Issues](#known-issues) below |
| State seems to "forget" what the user was doing | Check whether the bot process restarted — `conversation_state.py` and `debug_system.py`'s trace/debug state are in-memory only |
| Admin commands not responding | Confirm `/claimadmin` was run and `admin_id.txt` contains the right ID; admin denial is silent by design ("Unknown command"), not an error |

## Known issues

Found during the 2026-07 documentation pass. These are real, current gaps
between behavior and what earlier comments/docs claimed — not hypothetical.
Tracked with more remediation detail in [ROADMAP.md](ROADMAP.md#fix-it-list-found-during-the-2026-07-documentation-pass).

### The `analytics` package doesn't exist — AI analytics commands are silently broken

`usage_logger.py`, `usage_service.py`, `model_metrics.py`,
`token_counter.py`, `performance_tracker.py` are written as if they belong
to an `analytics/` package (`usage_logger.py` uses `from .token_counter
import ...`, a package-relative import; `init.py` reads like that
package's `__init__.py`). **They currently sit flat at the repo root with
no such package.**

Effects, all currently live:
- `database.py`'s `init_db()` does `from analytics import init_usage_table`
  inside `try/except: pass` — the import fails, so the `ai_usage` table is
  **never created**
- `baka_brain.py` does `from analytics import log_ai_request` /
  `log_image_request` at 5 call sites, each wrapped in
  `try/except Exception: pass` — every AI call's attempt to log usage
  silently no-ops
- `main.py` does `import analytics` at the handlers for `/models`,
  `/usage`, `/performance`, `/errors`, each wrapped in try/except that
  falls back to empty stats or an error message

**Fix shape** (not applied — docs-only pass, see
[ROADMAP.md](ROADMAP.md)): create an `analytics/` package directory,
move the five files into it plus an `__init__.py` that re-exports the
names `main.py`/`baka_brain.py`/`database.py` expect
(`init_usage_table`, `log_ai_request`, `log_image_request`, plus whatever
`usage_service.py`/`model_metrics.py`/`performance_tracker.py` expose for
the query side). No schema or business-logic changes needed — this is
purely a packaging fix.

### Hardcoded-looking API key in `ai_helper.py`

Line 9 passes what looks like a real NVIDIA API key as the **argument
name** to `os.getenv(...)` instead of passing `"NVIDIA_API_KEY"` as the
argument and using the key as its value — i.e. it's broken even on its own
terms, but the key string is still sitting in tracked source. The file is
dead code (not imported anywhere), which doesn't change the fact that the
key is committed to git history. **Recommended: rotate that NVIDIA key and
remove the literal from the file**, independent of the rest of this
documentation work.

### In-memory-only state doesn't survive a restart

`conversation_state.py`'s own docstring says its module-level dicts
"survive across messages reliably" — true within one running process, but
they're wiped on every restart. `feature_list.md` (now superseded) went
further and claimed this meant state "survive[s] bot restarts," which is
incorrect. Same limitation applies to `debug_system.py`'s per-user
debug-mode flag and last-trace log. Practical effect: if the bot crashes or
is redeployed while a user is mid-conversation (e.g. in `gathering` or
`editing` state), that user's in-progress action is silently lost and they
return to `idle`.

### `check_reminders` and `check_followups` don't check quiet hours

Every other scheduled job in `main.py` calls `is_quiet_hours(uid)` before
acting; these two primary reminder jobs don't. Unconfirmed whether this is
intentional (arguably you always want the *first* reminder to fire, only
follow-ups should respect quiet hours) — flagged here rather than assumed.

### `check_deadlines` bypasses the data-access layer

This one job opens its own `sqlite3.connect("planner.db")` directly instead
of going through `database.py`, the only place in `main.py` that does so.
Not a correctness bug, but an inconsistency worth fixing for
maintainability.

### Stale model references outside `baka_brain.py`

`token_counter.py`'s `MODEL_COSTS` table still lists `z-ai/glm-5.1`,
`flux.1-dev`, and `cosmos-1.0-7b-text2world`, none of which are the
models actually in use anymore (see [docs/ai_system.md](docs/ai_system.md)).
Cost/provider lookups for current models fall through to a fuzzy-match
fallback or return `$0.00`/`"Unknown"`. This will self-resolve once the
analytics package fix above lands and someone updates the cost table
alongside it — until then, don't trust any cost figures the analytics
commands would show even after the import is fixed.

### Version banner lag

The startup log line and some in-app help text said "v11.1" even after
v12.0 (Project Management) shipped — the release note in `VERSION.md`
wasn't mirrored into the runtime strings. Worth a quick grep for `"v11.1"`
and `"v11.2"` literals in `main.py` when next touching that area.
