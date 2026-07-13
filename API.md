# API Reference

BAKA has no REST API — "API" here means two things: (1) the Telegram command
surface, and (2) the internal Python module interfaces other code calls
into. This supersedes `README.md`'s command tables, which were missing
several commands that exist in code.

Every command works with or without the leading `/`, and most also have a
natural-language trigger (see [ARCHITECTURE.md](ARCHITECTURE.md#message-lifecycle)).

## Command reference

### Tasks
| Command | Purpose |
|---|---|
| `start`, `help` | Onboarding / full command list |
| `cancel` | Clear current conversation state |
| `list` | All pending tasks |
| `today`, `week` | Filtered views |
| `done <id>` | Mark complete |
| `delete <id>` | Remove a task |
| `edit <id>` | Enter edit mode for a task |
| `deadline <id> [on|off]` | Toggle pre-deadline buffer warnings |
| `tag <id> <tags>`, `tagged <tag>` | Tag management / search by tag |
| `checktasks` | Diagnostic view of reminder-related task state |

### Reminders
| Command | Purpose |
|---|---|
| `pause <id>` / `resume <id>` / `paused` | Stop/restart/list paused reminders |
| `snooze <id> <minutes>` | Custom snooze duration |
| `stopreminder <id>` | Stop reminders without deleting the task |
| `delreminder <id>` | Delete a task from its reminder |

### Deadlines & overdue tracking
| Command | Purpose |
|---|---|
| `overdue` | List overdue tasks |
| `carryforward` | Move all overdue tasks to today |
| `deadlines` | Tasks due in the next few days |
| `review` | Stale tasks (3+ days overdue) |

### Habits
| Command | Purpose |
|---|---|
| `habits` | All active habits with streaks |
| `streak <id>` | 14-day visual grid |
| `habitlog <id>` | 30-day history |
| `addhabit <title>` | Quick creation |
| `skiphabit <id>` | Skip (resets streak) |

### Goals & Projects (v12.0)
| Command | Purpose |
|---|---|
| `goals` | Progress dashboard |
| `need`/`materials <id> <items>` | Add comma-separated materials to a project |
| `got`/`have <name>` | Fuzzy-mark a material acquired across all projects |
| `worklog`/`log <id> <text>` | Log progress (kind auto-detected: progress/blocker/started/finished) |
| `started <id>` | Log a "work started" entry |
| `finished <id>` | Log a "finished" entry and mark the goal done |
| `project <id>` / `projects` | Full project dashboard card / list all active projects |
| `shopping` | Cross-project list of everything still unacquired |

### AI & planning
| Command | Purpose |
|---|---|
| `think`/`ask <question>` | Free-form AI reasoning over the user's real data |
| `plan today` / `plan week` | Time-blocked AI plan (asks to apply) |
| `breakdown <id>` | Split a task into subtasks |
| `reschedule <id>` | AI picks a conflict-free time |
| `overload` | Flags overloaded days in the next 2 weeks |
| `suggest <goal>` | 5 actionable tasks toward a goal |
| `analyze` | Productivity report |
| `insights` | Learned behavioral patterns |
| `suggestions` | Pending AI-generated daily suggestions |
| `approve <id>` / `dismiss <id>` | Apply / reject a suggestion |

### Memory
| Command | Purpose |
|---|---|
| `memory` | List all saved memories |
| `forget <key>` | Delete a memory |
| *(natural language)* | "Remember X" / "when is X" — save/retrieve without a command |

### Search & tools
| Command | Purpose |
|---|---|
| `search <keyword>` | Search tasks, memories, habits, goals |
| `template <name>` / `templates` | Create from / list saved templates |
| `savetemplate <name> <id>` | Save a task as a template |
| `export` | Full data backup as plain text |

### AI models & media
| Command | Purpose |
|---|---|
| `models` | All model statuses with live ping + usage (usage currently broken — see [DEBUGGING.md](DEBUGGING.md#known-issues)) |
| `image`/`generate <prompt>` | Generate an image |
| `video <prompt>` | Generate a short video (FLUX frame → SVD animation) |
| *(send a photo)* | Llama Vision describes it or extracts a todo list |

### AI analytics — currently degraded
| Command | Purpose |
|---|---|
| `usage` | Today + lifetime AI call stats |
| `performance` | p50/p95/p99 latency + trends |
| `errors` | Error timeline + breakdown |
| `status` / `status full` | Quick 3-test or deep 6-test AI benchmark, graded A+–F |

> These four commands are implemented and wired up, but `import analytics`
> fails silently at every call site, so `usage`/`performance`/`errors`
> currently return empty data instead of real stats. `status`/`status full`
> are unaffected (they run live probes, not stored analytics). See
> [DEBUGGING.md](DEBUGGING.md#known-issues).

### Settings
| Command | Purpose |
|---|---|
| `settings` | View all preferences |
| `quiethours <start> <end>` | Sleep window (no pings) |
| `interval <minutes>` | Reminder frequency (minimum 5) |
| `wellness on|off|interval <n>|water|break|eyes|all` | Opt-in wellness nudges |
| `proactive` | Panel showing every proactive feature's status |
| `dashboard`/`home` | Open the dashboard card |

### Debug
| Command | Purpose |
|---|---|
| `debug` | Toggle verbose debug mode (per-user, in-memory) |
| `report <description>` | File a bug; auto-captures last message + what the bot understood |
| `bugs` | List open bug reports |
| `resolve <id>` | Mark a bug resolved |
| `trace` | Last AI interaction (input, intent, entities, reply) |
| `selftest` | The current test-message checklist (see [TESTING.md](TESTING.md)) |

### Admin (owner-only)
Gated by the `admin_only` decorator (silent "Unknown command" denial to
everyone else) except where noted. See
[docs/telegram_integration.md](docs/telegram_integration.md#admin-lock).

| Command | Purpose |
|---|---|
| `myid` | *(not gated)* Show your Telegram ID and admin-claim status |
| `claimadmin` | *(not gated, one-time)* First caller becomes the permanent admin |
| `admin` | Control panel with data stats |
| `adminmode` | Toggle verbose debug globally |
| `resettasks` | Delete all tasks and reset task IDs to 1 |
| `resetmemory` / `resethabits` / `resetlearning` | Wipe one data category |
| `resetall` | Nuclear wipe (requires typed `YES NUKE EVERYTHING` confirmation) |
| `sql <SELECT query>` | Read-only SQL console |
| `misses` / `reviewed` | *(not gated)* Review AI missed-capability log |

## Internal module interfaces

### `database.py` (grouped by entity — one-line purpose each)

**Tasks:** `add_task`, `get_tasks`, `get_tasks_by_date`, `get_tasks_by_week`,
`get_task_by_id`, `search_tasks_by_title`, `mark_done`, `delete_task`,
`update_task`, `task_exists`, `get_recurring_tasks`, `set_tags`,
`get_tasks_by_tag`, `carry_forward_overdue`, `add_subtask`, `get_subtasks`,
`get_tasks_for_planning`, `count_tasks_per_day`, `count_tasks_at_time`,
`get_high_priority_soon`

**Reminders/scheduling support:** `snooze_task`, `postpone_task`,
`pause_task`, `resume_task`, `mark_reminded`, `get_paused_tasks`,
`get_overdue_tasks`, `get_upcoming_deadlines`, `increment_reminder_count`,
`get_reminder_count`, `get_tasks_needing_reminder`, `stop_reminders`,
`clear_snooze`, `get_tasks_for_followup`, `mark_followup_sent`,
`increment_snooze_count`, `get_snooze_count`, `get_stale_tasks`,
`get_unresolved_today`

**Deadlines (v10.1):** `mark_as_deadline`, `get_pending_deadlines`,
`mark_buffer_sent`, `parse_buffer_sent`

**Habits:** `add_habit`, `is_habit`, `log_habit_completion`,
`get_habit_log`, `get_habits`, `get_missed_days`, `reset_streak`

**Goals/Projects:** `add_goal`, `get_goals`, `get_goals_full`,
`update_goal_progress`, `get_done_today_count`; project extensions
`add_materials`, `get_materials`, `mark_material_acquired`,
`delete_material`, `find_material_by_name`, `add_worklog`, `get_worklog`,
`get_last_worklog_days`, `compute_project_progress`,
`get_project_overview`, `get_active_projects`, `get_all_pending_materials`

**Memory:** `save_memory`, `get_memory`, `get_all_memories`,
`search_memories`, `delete_memory`

**Preferences/learning:** `get_user_prefs`, `set_quiet_hours`,
`set_reminder_interval`, `log_completion`, `log_snooze`, `log_interaction`,
`get_active_hours`, `get_completion_patterns`, `get_snooze_patterns`,
`get_category_distribution`, `get_typical_time_for_category`,
`get_wellness_prefs`, `set_wellness`, `mark_wellness_sent`,
`get_wellness_enabled_users`

**Templates:** `save_template`, `get_template`, `get_all_templates`,
`delete_template`

**AI-autonomy support:** `log_missed_capability`, `get_missed_capabilities`,
`mark_missed_reviewed`, `get_user_context_for_ai`, `add_observation`,
`get_pending_observations`, `respond_to_observation`, `get_observation`

**Search/reports/export:** `search_all`, `get_weekly_report_data`,
`export_user_data`

**Admin/reset:** `reset_all_tasks`, `reset_all_memories`,
`reset_all_habits`, `reset_learning_data`, `reset_everything`,
`get_data_stats`, `get_all_user_ids`, `get_all_active_user_ids`

Full schema and migration pattern: [docs/database.md](docs/database.md).

### `baka_brain.py` (grouped by purpose)

**Dispatch:** `call_nvidia()` (legacy, still widely used), `_call_model()`
(v11.0 generic dispatcher), `call_main()`, `call_fast()`, `call_think()`,
`call_vision()`

**Intent/extraction:** `get_baka_response()`, `fast_intent_classify()`
(currently unused — `ENABLE_FAST_ROUTING=False`), `extract_memory_key()`

**Planning:** `generate_structured_plan()`, `generate_daily_plan()`,
`generate_weekly_plan()`, `generate_task_breakdown()`,
`suggest_reschedule_time()`, `generate_study_plan()`

**Reasoning/chat:** `think_freely()`, `chat_with_ai()`, `suggest_tasks()`,
`analyze_productivity()`

**Media:** `generate_image()`, `generate_video()`

**Diagnostics:** `check_api_status()`, `benchmark_ai()`,
`benchmark_all_models()`

Full detail (models, prompts, the broken analytics hooks):
[docs/ai_system.md](docs/ai_system.md), [PROMPTS.md](PROMPTS.md).
