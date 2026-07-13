# Dashboard

Introduced in v9.0 to move BAKA from purely chat-driven to also having a
tappable home hub. `ui.py` is a pure presentation layer — no database or
business-logic calls — built on top of `fmt.py`'s HTML helpers. Every
function returns either a text string, or a `(text, InlineKeyboardMarkup)`
tuple ready to hand to `python-telegram-bot`.

## Card types

| Function | Renders |
|---|---|
| `dashboard_card(data)` | The home hub: today/overdue/pending/done counts, goals + habits summary, completion bar. Buttons: Today / Tasks / Goals / Habits / Stats / Refresh |
| `task_card(task)` | Single task detail. Buttons: Done / Snooze / Tomorrow / Edit / Delete / Back. Accepts either a dict or a raw DB tuple |
| `today_card(groups)` | Today's tasks grouped into Overdue / High-priority / Upcoming / Done |
| `task_list_card(tasks)` | Tappable list — each row opens that task's `task_card` |
| `goal_card(goals)` | Progress bars per goal with inline +/- adjust buttons |
| `habit_card(habits)` | Streak display (fire emoji) with a "did it" button |
| `stat_card(stats)` | Productivity dashboard: completion rate, overdue rate, top categories, insights |
| `reminder_card(task)` | The push-notification card sent when a reminder fires: Done / Snooze 10m / Snooze 1h / Tomorrow / Stop / Delete |

Primitives used across the above: `progress_bar()`, `priority_dot()`,
`recurrence_icon()`, `section()`.

Project cards (v12.0 — materials checklist, worklog, progress bar) are
built inline in `main.py`'s `project_cmd`/`projects_cmd` handlers rather
than as a `ui.py` function; if `ui.py` gains a formal project card in the
future, that's where to add it for consistency with the rest of the
dashboard system.

## Callback routing

Dashboard buttons use a `dash:` callback-data namespace, routed inside
`main.py`'s `handle_callback` via `route_dashboard_callback` — a dedicated
sub-router kept separate from the plain (non-namespaced) callbacks used by
older features (Done/Snooze/etc. on reminders) and the `proj:` namespace
used by project cards. Dashboard callbacks **edit the existing message in
place** rather than sending a new one, specifically to reduce chat clutter.

`handle_callback` parses task IDs from callback data with a `try/except`
around the `int()` conversion, so a malformed or stale callback can't crash
the bot — this hardening was added in v9.0 and applies to all callbacks,
not just dashboard ones.

## Formatting layer (`fmt.py`)

All dashboard text goes through `fmt.py`, which targets Telegram's HTML
parse mode (not Markdown — switched in v7.1 because Markdown corrupted on
titles containing `.`, `-`, `(`, `+`, `&`). Key helpers: `esc()` (escapes
`&`, `<`, `>` — the only three characters Telegram HTML requires),
`b()`/`i()`/`code()`/`u()`/`pre()` (escape-and-wrap), `header()`,
`task_line()` (single-line task render with priority dot + recurrence
icon), `confirm_box()` (pre-save confirmation card), `bullet()`, and the
`DIVIDER` constant. All user-supplied content passes through `esc()` before
being embedded — no unescaped-HTML injection points were found during
review.

## Entry points

`/dashboard`, `/home`, the persistent reply-keyboard menu button, and the
natural-language phrases "dashboard"/"home" all route to the same
`dashboard_cmd` handler in `main.py`.
