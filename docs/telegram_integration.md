# Telegram Integration

## Framework

`python-telegram-bot` 20.7 (async), with `httpx` **pinned to 0.25.2** —
newer `httpx` versions break this PTB version. `main()` in `main.py`
validates Python ≥3.12 and the presence of `BOT_TOKEN` at startup, calls
`init_db()`, builds the `Application`, registers all handlers and jobs, and
calls `app.run_polling()` — long polling, not webhooks.

## Handler registration

Roughly 90 `CommandHandler`s, 1 `CallbackQueryHandler`, plus
`MessageHandler`s for photos (routes to the vision pipeline) and free text
(the main conversational entry point). Full command-to-purpose table:
[API.md](../API.md#command-reference).

Several commands are registered under multiple names pointing at the same
handler function — e.g. `materials`→`need_cmd`, `have`→`got_cmd`,
`log`→`worklog_cmd`, `projects`→`project_cmd`, `generate`→`image_cmd`,
`home`→`dashboard_cmd`, `templates`→`template_cmd`, `ask`→`think_cmd`.

## Slashless commands

A ~40-entry prefix/exact-match table inside the free-text handler lets
every command work without a leading `/` (`list` behaves the same as
`/list`). This is checked before falling through to intent-classification
via the AI, so slashless commands are cheap (no AI call) compared to
free-form natural language. See
[ARCHITECTURE.md](../ARCHITECTURE.md#message-lifecycle) for where this
sits in the overall message flow.

## Conversation state machine

Backed by `conversation_state.py` — module-level dicts, **not** Telegram's
built-in `context.user_data`/session storage (deliberately: the in-code
comment notes `user_data` can get wiped by commands like `/ai` mid-conversation).
Four states: `idle` (default), `gathering` (collecting missing task
fields), `confirming` (waiting on a yes/no or pending action), `editing`
(patching a specific task via `set_editing`/`get_editing_id`). **Does not
survive a process restart** — see
[DEBUGGING.md](../DEBUGGING.md#known-issues).

## Callback query routing

`handle_callback` in `main.py` is the single entry point for every inline
button. It dispatches by callback-data namespace:
- `dash:*` → `route_dashboard_callback` (dashboard card actions — see
  [docs/dashboard.md](dashboard.md))
- `proj:*` → project-card actions (`proj:started`, `proj:finished`,
  `proj:got`, `proj:view`, `proj:shopping`)
- unnamespaced values → the older reminder/task action set (Done, Snooze,
  Tomorrow, Stop, Delete, etc.)

Task-ID parsing from callback data is wrapped in `try/except` so a stale or
malformed callback (e.g. from an old message after a task was deleted)
can't crash the handler.

## Admin lock

Single-owner design, no role system. `admin_id.txt` (gitignored) stores one
Telegram user ID. `get_admin_id()`/`set_admin_id()` in `main.py` read/write
it directly (no database involvement). `/claimadmin` is unlocked for
everyone until the file is populated — **the first person to run it becomes
the permanent admin** — after which `is_admin()` gates access for everyone
else. This is a single point of failure by design: resetting admin means
deleting `admin_id.txt` and re-running `/claimadmin`.

The `admin_only` decorator wraps `admin`, `adminmode`, `resettasks`,
`resetmemory`, `resethabits`, `resetlearning`, `resetall`, and `sql` with
**silent denial** — non-admins get "Unknown command," not an explicit
"access denied," intentionally hiding that these commands exist at all.
`/myid`, `/claimadmin`, `/misses`, and `/reviewed` are *not* gated by this
decorator (the latter two expose AI miss-log data but are scoped to the
requesting user's own data, not global).

`/sql` additionally restricts to `SELECT`-only query text and caps results
at 30 rows, on top of the `admin_only` gate.

## Logging

`log_sanitizer.py`'s `LogSanitizer` (a `logging.Filter`) is installed at
startup and redacts bot tokens in URLs, `nvapi-...`/`sk-...` API keys, and
numeric Telegram IDs (the admin's ID → `"admin"`, others →
`"user_***XXX"` keeping the last 3 digits) before anything reaches
`bot.log`.

## Error handling

`error_handler`, registered as the application's global error handler,
catches every unhandled exception from any handler, logs it to `bugs.db`
via `debug_system.log_exception()` (with a full traceback and the
triggering user input/intent), and replies to the user with a friendly
message instead of letting the process crash.
