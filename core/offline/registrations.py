"""
registrations.py -- the explicit registration list for the default
ActionRegistry (v14.8, ADR-012).

This is the ONE file to edit when the Offline Engine gains an action:
add the matcher/runner pair and register it in build_default_registry().
engine.py never changes again for a new action -- that was the whole
point of the v14.8 refactor (Open/Closed; see ADR-012).

Everything here is a verbatim relocation of dispatch knowledge that
lived inline in OfflineEngine.execute() through v14.7 -- the phrase
tables, the matcher calls, their ORDER, and the argument shapes each
action function expects. Registration order within an intent is match
precedence (registry.py's docstring), so the order below is behavior:

  QUERY_TASK   search -> today -> week -> list -> paused
               -> habits_list -> streak_view (v14.9)
               (search prefixes first, exactly like the old
               _select_action(); the exact-phrase sets are
               disjoint so their relative order is for clarity)
  ADD_TASK     create_task -> create_habit (v14.10; both prefix-gated
               on disjoint prefix sets, so order is for clarity --
               create_task's matcher stopped being a catch-all in
               v14.10 precisely so this bucket could hold two specs)
  EDIT_TASK /  complete -> lifecycle -> update -> habitlog_view (v14.9)
  UNKNOWN      -> skip_habit (v14.10) (habit specs EDIT_TASK only;
               the three task specs are registered under both
               intents -- entry regexes are disjoint, order kept from
               v14.6/v14.7; UNKNOWN is included for the
               "rename task 5" -> UNKNOWN under-classification ADR-009
               documents)

Two builders (v14.9, ADR-013): build_default_registry() is the full
catalog (tests, benchmarks, engine fallback); build_enabled_registry()
is the production build -- it registers each domain only if its
feature flag is ON, which is how per-domain flags gate dispatch without
the engine or registry knowing flags exist.

Action-dispatch caveat, unchanged from engine.py's original note:
Intent.QUERY_TASK is coarser than the actions here (it also covers
/habits, /goals, /dashboard...), and Tier 0 entities carry no action
hint, so QUERY_TASK matchers pattern-match RequestContext.text against
hand-maintained mirrors of core/intent/rules.py's Tier 0 phrase groups.
Accepted, documented duplication (DEBUGGING.md's "Offline Engine action
dispatch is text-pattern-based, not Intent-based" entry); the real fix
(structured action hints in IntentResult.entities) remains future work.

Runners call through their module attribute (complete_task.execute, not
a captured function reference) on purpose: the old ladder resolved
these names at dispatch time, and tests monkeypatch them -- late
binding preserves both.
"""
from __future__ import annotations

import core.feature_flags as feature_flags
from core.actions import (
    complete_task, create_habit, create_task, delete_task, habit_views,
    lifecycle_task, list_tasks, search_tasks, skip_habit, today_tasks,
    update_task, week_tasks,
)
from core.intent.intent_types import Intent
from core.offline.registry import ActionRegistry, ActionSpec

# Mirrors core/intent/rules.py's _EXACT_COMMANDS "list"/"today"/"week"
# groups and _PREFIX_COMMANDS "search "/"find "/"look for " group,
# verbatim, for exactly the phrases these four actions must recognize.
# (Moved unchanged from engine.py, where they lived v14.2-v14.7.)
_TODAY_PHRASES = (
    "today", "today's tasks", "show today", "what's today",
    "what do i have today", "schedule today",
)
_WEEK_PHRASES = ("week", "this week", "weekly", "show week", "what's this week")
_LIST_PHRASES = ("list", "my tasks", "show tasks", "all tasks", "show all")
_SEARCH_PREFIXES = ("search ", "find ", "look for ")


# ── QUERY_TASK: the five read-only actions ───────────────────────────────

def _match_search(context):
    # Prefix check uses only a left-strip: the prefixes themselves end in
    # a space ("search "), so a full .strip() would remove that trailing
    # space from an input that's exactly "search " (prefix, no query
    # yet) and cause it to wrongly miss the match -- found by
    # tests/test_offline_engine.py's empty-keyword case.
    left_stripped = context.text.lstrip().lower()
    return any(left_stripped.startswith(p) for p in _SEARCH_PREFIXES) or None


def _run_search(context, storage, match):
    return search_tasks.execute(context, storage)


def _match_today(context):
    return context.text.strip().lower() in _TODAY_PHRASES or None


def _run_today(context, storage, match):
    return today_tasks.execute(context, storage)


def _match_week(context):
    return context.text.strip().lower() in _WEEK_PHRASES or None


def _run_week(context, storage, match):
    return week_tasks.execute(context, storage)


def _match_list(context):
    return context.text.strip().lower() in _LIST_PHRASES or None


def _run_list(context, storage, match):
    return list_tasks.execute(context, storage)


def _match_paused(context):
    # v14.7: paused-tasks view -- same read-only shape as the Stage 1
    # actions, mirrors core/intent/rules.py's ("paused", "show paused",
    # "paused tasks") QUERY_TASK exact group.
    return context.text.strip().lower() in lifecycle_task.PAUSED_VIEW_PHRASES or None


def _run_paused(context, storage, match):
    return lifecycle_task.paused_list(context, storage)


# ── ADD_TASK: creation proposal (commit is a pending registration) ───────

def _match_add(context):
    # v14.10: prefix-gated (was match-everything through v14.9 --
    # harmless alone, but a catch-all shadows any later ADD_TASK spec,
    # and the bucket now also holds create_habit). Same check
    # propose() itself applies, so results are unchanged for every
    # input -- see create_task.matches_entry_command's docstring.
    return create_task.matches_entry_command(context.text) or None


def _run_add(context, storage, match):
    return create_task.propose(context, storage)


# ── EDIT_TASK / UNKNOWN: complete -> lifecycle -> update ─────────────────

def _match_complete(context):
    return complete_task.match_entry_command(context.text)


def _run_complete(context, storage, task_id):
    return complete_task.execute(task_id, context.user_id, storage, context.now)


def _match_lifecycle(context):
    return lifecycle_task.match_entry(context.text)


def _run_lifecycle(context, storage, match):
    operation, args = match
    return lifecycle_task.execute_entry(operation, args, context, storage)


def _match_update(context):
    return update_task.match_entry_command(context.text)


def _run_update(context, storage, task_id):
    return update_task.start_editing(task_id, context.user_id, storage)


# ── DELETE_TASK: deletion proposal ───────────────────────────────────────

def _match_delete(context):
    # No under-classification gap here (unlike ADD_TASK/EDIT_TASK) --
    # "delete 5"/"delete task 5"/"remove task 5" all classify
    # DELETE_TASK at confidence 1.0 with task_id already in entities
    # (Tier 0's extract_numeric_id(), core/intent/rules.py), verified
    # directly. Missing task_id means the message genuinely doesn't
    # name a task (e.g. "delete this") -- None here means the engine
    # returns unsupported_action and main.py falls through to Legacy,
    # exactly as before.
    return context.entities.get("task_id")


def _run_delete(context, storage, task_id):
    return delete_task.propose(task_id, context.user_id, storage)


# ── Habit domain (v14.9, Stage 1: read-only views) ───────────────────────

def _match_habits_list(context):
    # Mirrors core/intent/rules.py's ("habits", "show habits",
    # "my habits", "list habits") QUERY_TASK exact group.
    return context.text.strip().lower() in habit_views.HABITS_VIEW_PHRASES or None


def _run_habits_list(context, storage, match):
    return habit_views.habits_list(context, storage)


def _match_streak(context):
    # "streak <id>" -> QUERY_TASK (Tier 0 prefix group). Id-less
    # "streak" falls through to Legacy's usage reply.
    return habit_views.match_streak_command(context.text)


def _run_streak(context, storage, habit_id):
    return habit_views.streak_detail(habit_id, context, storage)


def _match_habitlog(context):
    # "habitlog <id>" / "habit log <id>" -> EDIT_TASK (Tier 0 groups it
    # there despite being read-only; registered under EDIT_TASK only --
    # both phrasings are Tier 0 prefixes, so unlike "rename task" they
    # can never classify UNKNOWN).
    return habit_views.match_habitlog_command(context.text)


def _run_habitlog(context, storage, habit_id):
    return habit_views.habit_log_view(habit_id, context, storage)


def _match_create_habit(context):
    # "addhabit <desc>" / "add habit <desc>" / "new habit <desc>" ->
    # ADD_TASK (Tier 0 prefix group). Prefixes are disjoint from
    # create_task's, and create_task's matcher is prefix-gated
    # (v14.10), so bucket order between the two is not load-bearing.
    return create_habit.match_entry_command(context.text)


def _run_create_habit(context, storage, description):
    return create_habit.execute(description, context, storage)


def _match_skip_habit(context):
    # "skiphabit <id>" / "skip habit <id>" / "reset streak <id>" ->
    # EDIT_TASK (Tier 0 prefix group; always -- never UNKNOWN).
    return skip_habit.match_entry_command(context.text)


def _run_skip_habit(context, storage, habit_id):
    return skip_habit.execute(habit_id, context, storage)


# ── Pending commits (ADR-008's confirm-step second half) ─────────────────

def _commit_add(pending_data, user_id, storage):
    return create_task.commit(pending_data, user_id, storage)


def _commit_delete(pending_data, user_id, storage):
    return delete_task.commit(pending_data, user_id, storage)


_EDIT_SPECS = (
    ActionSpec("complete_task", _match_complete, _run_complete),
    ActionSpec("lifecycle_task", _match_lifecycle, _run_lifecycle),
    ActionSpec("update_task", _match_update, _run_update),
)


def _register_task_domain(registry: ActionRegistry) -> None:
    """Every Task-domain action shipped v14.2-v14.7, in the exact
    precedence order the pre-v14.8 ladder encoded."""
    registry.register(Intent.QUERY_TASK, ActionSpec("search_tasks", _match_search, _run_search))
    registry.register(Intent.QUERY_TASK, ActionSpec("today_tasks", _match_today, _run_today))
    registry.register(Intent.QUERY_TASK, ActionSpec("week_tasks", _match_week, _run_week))
    registry.register(Intent.QUERY_TASK, ActionSpec("list_tasks", _match_list, _run_list))
    registry.register(Intent.QUERY_TASK, ActionSpec("paused_list", _match_paused, _run_paused))

    registry.register(Intent.ADD_TASK, ActionSpec("create_task", _match_add, _run_add))

    for spec in _EDIT_SPECS:
        registry.register(Intent.EDIT_TASK, spec)
        registry.register(Intent.UNKNOWN, spec)

    registry.register(Intent.DELETE_TASK, ActionSpec("delete_task", _match_delete, _run_delete))

    registry.register_pending("offline_add_task", _commit_add)
    registry.register_pending("offline_delete_task", _commit_delete)


def _register_habit_domain(registry: ActionRegistry) -> None:
    """Habit-domain Stage 1 (v14.9, the three read-only views) +
    Stage 2 (v14.10, the two deterministic writes: create + skip;
    habit "update" and "delete" need no habit code -- habits are task
    rows, so v14.4's edit flow and v14.5's delete flow already cover
    them, verified + test-pinned). Habit matchers are disjoint from
    every Task matcher ("habits" phrases vs. task phrase sets;
    "streak "/"habitlog "/"addhabit "/"skiphabit " prefixes vs. task
    verb regexes/prefixes), so registration order across domains is not
    load-bearing -- appended after Task specs for stable, readable
    resolve() output."""
    registry.register(Intent.QUERY_TASK, ActionSpec("habits_list", _match_habits_list, _run_habits_list))
    registry.register(Intent.QUERY_TASK, ActionSpec("streak_view", _match_streak, _run_streak))
    registry.register(Intent.EDIT_TASK, ActionSpec("habitlog_view", _match_habitlog, _run_habitlog))
    registry.register(Intent.ADD_TASK, ActionSpec("create_habit", _match_create_habit, _run_create_habit))
    registry.register(Intent.EDIT_TASK, ActionSpec("skip_habit", _match_skip_habit, _run_skip_habit))


def build_default_registry() -> ActionRegistry:
    """The full action catalog -- every Offline action in every domain,
    regardless of feature flags. OfflineEngine.__init__ falls back to
    this when no registry is injected (tests, benchmarks); production
    (main.py) injects build_enabled_registry() instead, which is the
    flag-aware subset -- see ADR-013."""
    registry = ActionRegistry()
    _register_task_domain(registry)
    _register_habit_domain(registry)
    return registry


def build_enabled_registry() -> ActionRegistry:
    """The production registry: only the domains whose feature flags
    are ON (env-read-once at import, core/feature_flags.py -- so this
    reflects the process's startup environment, same semantics as every
    other flag use). With all flags OFF this returns an empty registry,
    and every message resolves to unsupported_intent -> Legacy;
    main.py's flag-OR gate short-circuits before even calling in that
    case. Per-domain gating lives HERE, at construction time, rather
    than in the engine or per-message checks -- see ADR-013 for the
    alternatives considered."""
    registry = ActionRegistry()
    if feature_flags.OFFLINE_TASKS:
        _register_task_domain(registry)
    if feature_flags.OFFLINE_HABITS:
        _register_habit_domain(registry)
    return registry
