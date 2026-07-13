# BAKA Bot — Roadmap

This consolidates every "not yet built" idea found across the old
`VERSION.md`'s planned-roadmap section, `feature_list.md`'s "Known
Limitations", and gaps found during the 2026-07 documentation pass.

**A note on version numbers:** the original `VERSION.md` roadmap section
labeled ideas `v12.0` (Voice Notes) through `v14.3` (Themes) — written
*before* v12.0 actually shipped as "Project Management" (see
[CHANGELOG.md](CHANGELOG.md)). Those numbers now collide with real
released versions. This file drops fixed version numbers for backlog items
and groups by priority/theme instead. Treat "Next up" as literally next;
everything else is unordered backlog, not a commitment.

---

## Fix-it list (found during the 2026-07 documentation pass)

These aren't feature requests — they're real gaps between what the code
does and what earlier docs/comments claimed. Tracked here since there was
nowhere else to put them. Full detail in [DEBUGGING.md](DEBUGGING.md#known-issues).

- **Analytics package is missing.** `usage_logger.py`, `usage_service.py`,
  `model_metrics.py`, `token_counter.py`, `performance_tracker.py` are meant
  to live in an `analytics/` package (per `init.py`'s package-style
  docstring and relative imports) but currently sit flat at the repo root
  with no `__init__.py`. Every `import analytics` call site fails silently
  (`try/except: pass`), so the `ai_usage` table is never created and
  `/usage`, `/performance`, `/errors`, and real per-model stats in `/models`
  all run on empty fallback data. Fixing this is a self-contained, low-risk
  change (add the package wiring; no schema or business-logic changes
  needed) — good first task.
- **Hardcoded-looking API key in `ai_helper.py:9`.** Passed as the
  *argument name* to `os.getenv(...)` instead of the env var name (a bug —
  the file is also unused dead code). The key string should be removed from
  source regardless, and the corresponding NVIDIA key should be rotated
  since it's committed to git history.
- **Dead code:** `ai_helper.py` and `bot_state.py` are not imported
  anywhere (superseded by `baka_brain.py` and `conversation_state.py`
  respectively). Candidates for deletion once confirmed safe.
- **`token_counter.py`'s `MODEL_COSTS` table has stale model IDs**
  (`z-ai/glm-5.1`, `flux.1-dev`, `cosmos-1.0-7b-text2world`) that no longer
  match the models actually in use (`meta/llama-3.3-70b-instruct`,
  `flux.1-schnell`, `stabilityai/stable-video-diffusion`). Cost/provider
  lookups for current models fall through to a fuzzy-match fallback or
  silently return `$0.00`/`"Unknown"`.
- **`conversation_state.py`'s docstring claims state "survives across
  messages reliably"** via module-level dicts. True within a running
  process, but it does **not** survive a process restart — contrary to
  `feature_list.md`'s claim that state "survive[s] bot restarts". Either
  fix the docs (cheap) or back the state with SQLite (more work, but would
  also fix `/trace` and debug-mode state in `debug_system.py`, which have
  the same in-memory-only limitation).
- **`check_reminders` and `check_followups` jobs don't check quiet hours**,
  unlike every other scheduled job. Confirm whether this is intentional
  (primary reminders should always fire) or a gap.
- **`check_deadlines` job bypasses `database.py`**, opening its own raw
  `sqlite3.connect("planner.db")` — the only place in `main.py` that
  doesn't go through the data-access layer. Worth aligning for consistency.
- **`anthropic` SDK is in `requirements.txt`** but no `import anthropic`
  was found anywhere in the reviewed modules — confirm whether it's a
  leftover dependency or used by code not yet located, and prune if unused.

---

## Next up (from v12.0's own "ideas for next")

- **Project photos via Vision** — send a photo, Llama Vision describes
  progress, auto-adds a worklog entry
- **Cost/budget tracking** — sum material costs, show budget vs. spent per
  project
- **Milestones** — split projects into named stages, each with its own
  progress
- **Template projects** — save a project's material list as a template so
  the next similar build populates instantly

---

## Backlog (from the original roadmap, unordered, numbers dropped)

- **Voice notes** — accept Telegram voice messages, transcribe (Whisper or
  similar), treat transcript as regular text input with a confirm-before-act
  step
- **Task dependencies** — "Task B depends on Task A"; B's reminder only
  fires after A is done. `parent_task_id` column already exists as a
  possible foundation
- **Location-based reminders** — geofence check in the reminder scheduler,
  using Telegram's live-location sharing
- **Personalized briefing times** — use `interaction_log`'s active-hours
  data (already collected since v6.0) instead of a fixed 08:00 morning
  briefing
- **Bulk task import** — paste a numbered/bulleted list, one AI call
  extracts and confirms all of them
- **Named goal milestones + task linking** — `ai_observations`'
  `action_type` hook was built with this in mind
- **GLM 5.2 upgrade** — swap `MODEL_MAIN` once NVIDIA's GLM 5.2 endpoint is
  stable (GLM 5.1 was EOL'd, see [docs/ai_system.md](docs/ai_system.md));
  benchmark both once the analytics pipeline actually works
- **Fast routing enabled** — flip `ENABLE_FAST_ROUTING=True` so Llama 3.1
  8B pre-filters simple intents before escalating to the main model
- **`/replay` command** — full debug timeline for any interaction by
  timestamp, pulling from `ai_usage`, `missed_capabilities`,
  `interaction_log`, and `debug_system.py` — blocked on the analytics
  fix-it item above
- **`/export_usage`** — export `ai_usage` as CSV/JSON — also blocked on the
  analytics fix-it item
- **Multi-user admin mode** — the data model already scopes everything by
  `user_id`; the admin panel itself is currently single-user only
- **Pomodoro mode** — `/pomodoro <task_id>` timer, new `pomodoro_log` table
- **AI weekly insights** — narrative (not just pattern-based) weekly
  productivity summary
- **Themes/personalities** — switchable communication style stored in
  `user_preferences`, applied in `think_freely()`'s system prompt

---

## Future integrations (no timeline)

- Calendar sync (Google Calendar, two-way)
- Email integration (e.g. "did I get a reply from them yet?")
- Notion/Obsidian export
- Music integration (e.g. "play study playlist")
- Streak heatmap (GitHub-style year view of completed tasks)

---

## Known limitations carried over from `feature_list.md`

Reconciled against the current code — some of these are actually already
built; kept here only where still true:

- No web dashboard — all interaction is through Telegram only. **Still
  true.**
- Smart scheduling (`/plan`) creates a schedule and can apply it to the DB
  (v4.0+) — the original "text plan only, no DB tasks" limitation is
  **resolved**.
- Productivity scoring exists via `/analyze` and `/insights` (v6.0+) — the
  original "not yet tracked" limitation is **resolved**.
- Proactive suggestions (stagnation nudges, wellness nudges, priority
  nudges) exist (v8.0, v12.0) — the original "not yet implemented"
  limitation is **resolved**.
- Deployment target: To Be Documented — `README.md` said "hosted locally
  (WSL), not yet deployed to Railway cloud" as of its last update; confirm
  current hosting status before relying on this.
