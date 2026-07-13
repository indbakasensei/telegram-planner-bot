# Database

Single SQLite file, `planner.db` (path constant `DB_NAME` in
`database.py`), plus a separate `bugs.db` for `debug_system.py`'s bug
reports (deliberately isolated so debug data never touches user data).

## Migration pattern

There is no versioned-migration system. `init_db()` runs on every startup
and:
1. Issues `CREATE TABLE IF NOT EXISTS` for each table's base shape
2. Follows up with a list of `ALTER TABLE ... ADD COLUMN` statements, each
   wrapped in `try/except: pass` — so adding a column that already exists
   (on an upgrade-in-place from an older DB) is a harmless no-op, and a
   truly new column gets added on the next startup

This makes the schema additive-only and safe to run against any prior
version's database file. When adding a column, follow this same pattern
(list of `(column, ddl)` tuples inside a `try/except`) rather than
introducing a separate migration mechanism.

Sub-tables get their own `_init_*(conn)` helper, called from `init_db()`:
`_init_preferences`, `_init_learning_tables`, `_init_templates`,
`_init_missed_capabilities`, `_init_observations`, `_init_project_tables`.
`_init_project_tables` additionally creates indexes (`idx_materials_goal`,
`idx_materials_user`, `idx_worklog_goal`, `idx_worklog_user`) — the only
tables in the schema with explicit indexes beyond the primary key.

One more `_init_*`-style call exists but currently fails silently: `from
analytics import init_usage_table` inside a `try/except` — see
[docs/ai_system.md](ai_system.md) and
[DEBUGGING.md](../DEBUGGING.md#known-issues). As a result, **there is no
`ai_usage` table in the live schema** despite it being described in
`README.md` and `CHANGELOG.md`'s v11.1 entry.

## Schema (13 active tables, confirmed in code)

### `tasks`
The largest table — also stores habits (`is_habit` flag) and project goals
share the separate `goals` table, not this one. Core columns: `id`,
`user_id`, `title`, `due_date`, `due_time`, `category`, `priority`, `done`,
`recurrence_type`/`recurrence_weekday`/`recurrence_day`, `created_at`.
Columns added via the `ALTER TABLE` migration list: `paused`,
`snooze_until`, `last_reminded`, `tags`, `reminder_count`,
`parent_task_id` (subtask linkage), `is_habit`, `habit_start_date`,
`current_streak`, `longest_streak`, `last_completed`, `followup_sent`,
`followup_count`, `snooze_count`, `stale_flagged`, `is_deadline`,
`buffer_sent`.

### `memories`
`id`, `user_id`, `key`, `value`, `created_at`. No `UNIQUE` constraint —
`save_memory()` does a manual check-then-insert/update instead of
`INSERT ... ON CONFLICT`, deliberately, so it works whether the table was
just created or predates the `UNIQUE` idea entirely.

### `habit_log`
`id`, `habit_id`, `user_id`, `log_date`, `completed`, `created_at`.
`UNIQUE(habit_id, log_date)` — one completion record per habit per day.

### `goals`
`id`, `user_id`, `title`, `deadline`, `progress`, `done`, `created_at`,
plus `target` (added in a v9.0 hotfix migration). This is also the table
Projects (v12.0) extend — a "project" is a goal with rows in
`project_materials`/`project_worklog`, not a separate entity type.

### `user_preferences`
Created by `_init_preferences`. Holds `quiet_start`/`quiet_end`,
`interval`, `max_reminders`, and (added later) `wellness_on`/
`wellness_interval`/`wellness_types`/`last_wellness`.

### `completions_log`, `snooze_log`, `interaction_log`
Created by `_init_learning_tables` (v6.0, behavioral learning). Log every
task completion (with delay-from-scheduled), every snooze (category +
duration), and every user interaction (timestamp) respectively — the raw
data `preferences.py`'s `analyze_user()` derives insights from.

### `task_templates`
Created by `_init_templates` (v10.0). Reusable task patterns: `name`,
`title`, `category`, `priority`, plus recurrence/default-time fields.

### `missed_capabilities`
Created by `_init_missed_capabilities` (v10.2). Logs `user_input`,
`ai_intent`, `ai_response`, a miss-type classification, and a `reviewed`
flag — the feature-gap-mining mechanism surfaced via `/misses`.

### `ai_observations`
Created by `_init_observations` (v11.0). AI-generated daily suggestions:
`observation`, `suggestion`, `action_type`, `action_payload`, `status`.

### `project_materials` (v12.0)
Created by `_init_project_tables`. `id`, `user_id`, `goal_id` (→
`goals.id`, no formal FK constraint but used as one), `name`, `quantity`,
`acquired`, `cost`, `notes`, `created_at`, `acquired_at`. Indexed on
`goal_id` and `user_id`.

### `project_worklog` (v12.0)
Created by `_init_project_tables`. `id`, `user_id`, `goal_id`, `entry`,
`kind` (auto-detected: `note`/`progress`/`blocker`/`started`/`finished`),
`created_at`. Indexed on `goal_id` and `user_id`.

## Relationships

No formal foreign keys (SQLite FKs aren't enforced unless explicitly
turned on, and this schema doesn't enable them) — relationships are
implicit via matching ID columns, all additionally scoped by `user_id`:
- `tasks.parent_task_id` → `tasks.id` (subtasks)
- `habit_log.habit_id` → `tasks.id` (habits are tasks with `is_habit=1`)
- `project_materials.goal_id` / `project_worklog.goal_id` → `goals.id`

## Data integrity patterns

- **Every query is scoped by `user_id`** — this is the entire multi-user
  isolation mechanism; there's no per-user database or schema separation
- **Duplicate prevention** is manual (`task_exists()` checks title+date
  before insert; `save_memory()` checks key before insert/update) rather
  than relying on SQL constraints
- **`resettasks` resets the autoincrement counter** back to 1
  (`reset_all_tasks()` in `database.py`) — the only place IDs get
  deliberately reset
- **Read-only admin SQL** (`/sql`) is restricted to `SELECT` statements at
  the `main.py` handler level, not enforced by the database itself

## Function inventory

See [API.md](../API.md#databasepy-grouped-by-entity--one-line-purpose-each)
for the full grouped list of every function.
