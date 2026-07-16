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
               (search prefixes first, exactly like the old
               _select_action(); the four exact-phrase sets are
               disjoint so their relative order is for clarity)
  EDIT_TASK /  complete -> lifecycle -> update
  UNKNOWN      (same three specs registered under both intents --
               entry regexes are disjoint, order kept from v14.6/v14.7;
               UNKNOWN is included for the "rename task 5" -> UNKNOWN
               under-classification ADR-009 documents)

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

from core.actions import (
    complete_task, create_task, delete_task, lifecycle_task, list_tasks,
    search_tasks, today_tasks, update_task, week_tasks,
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
    # Every ADD_TASK message goes to propose() -- the old ladder had no
    # text pre-filter here (create_task.propose itself rejects
    # non-matching prefixes with not_a_create_command), so this matcher
    # always matches.
    return True


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


def build_default_registry() -> ActionRegistry:
    """The production registry: every Offline action shipped through
    v14.7, registered in the exact precedence order the old ladder
    encoded. OfflineEngine.__init__ calls this when no registry is
    injected; tests inject their own to exercise dispatch in isolation."""
    registry = ActionRegistry()

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

    return registry
