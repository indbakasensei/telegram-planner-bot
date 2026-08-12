"""
tool_adapters.py -- v15.2 M3: Real Tool Adapters.

Thin, per-user adapters that expose BAKA's EXISTING business logic as
M2-contract AI tools (core/ai/tools.py). Every tool here is a thin layer of
argument translation + validation + one or more calls into the real services
(Storage facade, EntityEngine, WorkspaceGroups, ReferenceResolver, the M1
WorkspaceRetriever) + conversion of the result into a structured `ToolResult`
carrying machine-readable `data` (ids, fields, workspace, projection status).

Nothing here is a new abstraction, a second registry, or a new ToolResult:
every adapter is a `Tool` with a `ToolSpec`, bound per user, registered into
the M2 `ToolRegistry` by `build_tool_registry()`.

Design constraints honored (see docs/engineering/V15_2_BAKA_BRAIN.md §M3):
  * No GLM Worker, no agent loop, no multi-step reasoning, no worker routing.
    These adapters are dormant: nothing in main.py routes through them yet.
  * No rewritten business logic and no raw SQLite -- every write goes through
    database.py via the Storage facade / EntityEngine / WorkspaceGroups, and
    entity creation/update project to Telegram through the SAME alpha.13
    contract (/add and NL creation use), never a second topic mechanism.
  * Reference resolution REUSES the M1 ReferenceContext/ReferenceResolver;
    the thin name matcher below mirrors EntityManager._find_entity, it does
    not reimplement conversational resolution.
  * Task existence is checked before mark_done/delete/update because the
    underlying database.py functions return None silently on a missing row.
  * No update_habit tool (database.py has no update_habit), and no separate
    "reminders" tool (reminders ARE task due-times -- see §M3 known limits).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

from core.ai.entity_kinds import (
    ALL_KINDS,
    KIND_ARTIFACT,
    KIND_CHARACTER,
    KIND_ENTITY,
    KIND_GOAL,
    KIND_HABIT,
    KIND_TASK,
    KIND_WEAPON,
    LIST_ALL,
    EntityKindResolver,
)
from core.ai.reference_context import Referent, ReferenceContext
from core.ai.reference_resolver import ReferenceResolver
from core.ai.tools import (
    RiskLevel,
    Tool,
    ToolError,
    ToolErrorCode,
    ToolResult,
    ToolRegistry,
    ToolSpec,
)
from core.ai.workspace_retriever import WorkspaceRetriever
from core.storage import Storage
from core.workspace.engine import EntityEngine
from core.workspace.errors import EntityValidationError, EntityNotFound
from core.workspace.groups_app import (
    ENTITY_TYPE,
    KIND_TEMPLATE,
    WorkspaceGroups,
    _normalize_title,
)
from core.workspace.render import format_entity_card, format_entity_update
from date_parser import validate_datetime

__all__ = [
    "build_tool_registry",
    "ArchiveWorkspaceTool", "CloseWorkspaceTool", "CreateEntityTool",
    "CreateGoalTool", "CreateHabitTool", "CreateTaskTool",
    "CreateWorkspaceTool",
    "DeleteEntityTopicTool", "DeleteEntityTool", "DeleteTaskTool",
    "EnsureEntityTopicTool", "EquipItemTool",
    "CompleteHabitTool", "CompleteTaskTool",
    "FindTaskTool", "FindEntityTool", "GetEntityTopicTool", "GetEntityTool",
    "GetMemoriesTool", "GetWorkspaceTool", "ListEntitiesTool", "ListEntityTopicsTool",
    "ListGoalsTool", "ListHabitsTool",
    "ListTasksTool", "ListWorkspacesTool", "RecallTool", "RenameWorkspaceTool",
    "RepairTopicsTool", "SearchMemoriesTool",
    "SetEntityTopicLockedTool", "UpdateEntityTool", "UpdateGoalDeadlineTool",
    "UpdateGoalProgressTool",
    "UpdateTaskTool",
    "WsGetTool", "WsInspectTool", "WsListTool", "WsOpenTool",
]

# Workspace milestone statuses a caller may filter list_entities by.
_ENTITY_STATUSES = ("todo", "in_progress", "done", "blocked")


def _err(tool: str, message: str) -> ToolError:
    """A stable invalid_args failure. M2's code set deliberately has no
    separate 'not_found' code yet; an operation targeting an entity that
    does not exist is classified as invalid arguments, with a message that
    says exactly what is missing (see V15_2_BAKA_BRAIN.md §M3)."""
    return ToolError(ToolErrorCode.INVALID_ARGS, f"Tool '{tool}': {message}")


# ── bound base ────────────────────────────────────────────────────────────
class _BoundTool(Tool):
    """A Tool bound to exactly one user. user_id is injected at build time
    and is never a model-facing argument. `typed_refs` (v15.2 M4) is the
    shared per-kind TypedReferentStore the Worker keeps; tools note
    referents they create/list/update into it so the NEXT step of a run can
    resolve them deterministically (never a stale active entity)."""

    def __init__(self, user_id: int, storage: Storage | None = None,
                 engine: EntityEngine | None = None,
                 typed_refs=None):
        self._uid = user_id
        self._s = storage or Storage()
        self._eng = engine or EntityEngine()
        self._typed_refs = typed_refs

    def _err(self, message: str) -> ToolError:
        return _err(self.spec.name, message)

    def _note_typed(self, kind: str, id: int, name: str,
                    workspace_id: int | None = None) -> None:
        """Record a referent in the shared store (no-op without one)."""
        if self._typed_refs is not None:
            self._typed_refs.note(self._uid, kind, id, name, workspace_id)

    def _goal_title(self, goal_id: int) -> str | None:
        """Best-effort title for a goal id (for referent noting)."""
        for r in self._s.goals.get_all_full(self._uid):
            if r[0] == goal_id:
                return r[1]
        return None

    def _resolve_goal(self, ref):
        """Resolve a goal reference to (goal_id, title).

        Order: typed referent store FIRST (current-run wins, never a stale
        active entity, cross-domain pronoun → conflict), then id, then exact
        name. Returns (goal_id, title) or raises ToolError."""
        ref = str(ref).strip()
        if self._typed_refs is not None:
            out = self._typed_refs.resolve(self._uid, ref, "goal")
            if out.conflict:
                raise self._err(
                    f"{out.conflict_name!r} is a {out.conflict_kind}, not a "
                    "goal — refusing to apply a goal operation to it.")
            if out.referent is not None:
                return out.referent.id, out.referent.name
        if ref.isdigit():
            gid = int(ref)
            title = self._goal_title(gid)
            if title is not None:
                return gid, title
            raise self._err(f"goal [{gid}] not found.")
        low = ref.lower()
        matches = [(r[0], r[1]) for r in self._s.goals.get_all_full(self._uid)
                   if r[1].lower() == low]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise self._err(f"no goal matches {ref!r}.")
        raise self._err(f"{ref!r} is ambiguous — "
                       + ", ".join(t for _, t in matches) + ".")

    @staticmethod
    def _task_dict(row) -> dict:
        """Row → JSON-compatible task dict. Two row shapes come out of
        database.py: get_tasks returns 7 columns (incl. priority +
        recurrence_type) while search_tasks_by_title returns only 5 (no
        priority/recurrence) -- guard both, never index past the row."""
        return {
            "task_id": row[0], "title": row[1], "due_date": row[2],
            "due_time": row[3], "category": row[4],
            "priority": row[5] if len(row) > 5 else None,
            "recurrence_type": row[6] if len(row) > 6 else None,
        }


# ── TASKS ─────────────────────────────────────────────────────────────────
class ListTasksTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "list_tasks",
            "List the user's tasks. Includes due_date/due_time (the reminder "
            "surface -- reminders are task due-times, there is no separate "
            "reminder entity). Pass done=1 for completed tasks.",
            {"type": "object", "properties": {
                "done": {"type": "integer", "enum": [0, 1],
                         "description": "0 = pending (default), 1 = done"}}},
            risk=RiskLevel.READ_ONLY)

    def run(self, done=0, **kwargs) -> ToolResult:
        rows = self._s.tasks.get_all(self._uid, int(done or 0))
        data = [self._task_dict(r) for r in rows]
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output="No tasks.", data=[])
        lines = [f"[{t['task_id']}] {t['title']}"
                 + (f" — {t['due_date']}" if t["due_date"] else "")
                 + (f" {t['due_time']}" if t["due_time"] else "")
                 for t in data]
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"{len(data)} task(s):\n" + "\n".join(lines),
                          data=data)


class FindTaskTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "find_task",
            "Find pending tasks whose title contains the query (title "
            "substring search, the same search /search uses).",
            {"type": "object", "properties": {
                "query": {"type": "string", "minLength": 1,
                          "description": "title substring to search"}},
             "required": ["query"]},
            risk=RiskLevel.READ_ONLY)

    def run(self, query, **kwargs) -> ToolResult:
        rows = self._s.tasks.search_by_title(self._uid, query)
        data = [self._task_dict(r) for r in rows]
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output=f"No tasks match {query!r}.", data=[])
        for t in data:
            self._note_typed("task", t["task_id"], t["title"])
        lines = [f"[{t['task_id']}] {t['title']}" for t in data]
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"Matched {len(data)} task(s):\n"
                                 + "\n".join(lines), data=data)


class CreateTaskTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "create_task",
            "Create a task. due_date is %Y-%m-%d, due_time is HH:MM. "
            "Mirrors the live create flow: date/time are validated and a "
            "duplicate (same title + date) is rejected. recurrence_type is "
            "the DB value (daily/weekly/monthly).",
            {"type": "object", "properties": {
                "title": {"type": "string", "minLength": 1},
                "due_date": {"type": ["string", "null"]},
                "due_time": {"type": ["string", "null"]},
                "category": {"type": "string", "default": "General"},
                "priority": {"type": "string", "default": "medium"},
                "recurrence_type": {"type": ["string", "null"]},
                "recurrence_weekday": {"type": ["integer", "null"]},
                "recurrence_day": {"type": ["integer", "null"]}},
             "required": ["title"]},
            risk=RiskLevel.MUTATING)

    def run(self, title, due_date=None, due_time=None, category="General",
            priority="medium", recurrence_type=None, recurrence_weekday=None,
            recurrence_day=None, **kwargs) -> ToolResult:
        errors = validate_datetime(due_date, due_time)
        if errors:
            raise self._err("  ".join(errors))
        if self._s.tasks.exists(self._uid, title, due_date):
            raise self._err(
                f"task {title!r} already exists"
                + (f" on {due_date}" if due_date else "") + ".")
        task_id = self._s.tasks.add(
            self._uid, title, due_date, due_time, category, priority,
            recurrence_type, recurrence_weekday, recurrence_day)
        self._note_typed("task", task_id, title)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Created task [{task_id}] {title}.",
            data={"task_id": task_id, "title": title, "due_date": due_date,
                  "due_time": due_time, "category": category,
                  "priority": priority})


class UpdateTaskTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "update_task",
            "Update fields on an existing task by id. Pass only the fields "
            "to change (at least one). due_date is %Y-%m-%d, due_time HH:MM.",
            {"type": "object", "properties": {
                "task_id": {"type": "integer"},
                "title": {"type": ["string", "null"]},
                "due_date": {"type": ["string", "null"]},
                "due_time": {"type": ["string", "null"]},
                "category": {"type": ["string", "null"]},
                "priority": {"type": ["string", "null"]}},
             "required": ["task_id"]},
            risk=RiskLevel.MUTATING)

    def run(self, task_id, title=None, due_date=None, due_time=None,
            category=None, priority=None, **kwargs) -> ToolResult:
        existing = self._s.tasks.get_by_id(task_id, self._uid)
        if existing is None:
            raise self._err(f"task [{task_id}] not found.")
        changes = {k: v for k, v in (
            ("title", title), ("due_date", due_date), ("due_time", due_time),
            ("category", category), ("priority", priority)) if v is not None}
        if not changes:
            raise self._err("no fields to update — pass at least one.")
        errors = validate_datetime(
            changes.get("due_date"), changes.get("due_time"))
        if errors:
            raise self._err("  ".join(errors))
        self._s.tasks.update(task_id, self._uid, **changes)
        self._note_typed("task", task_id, existing[1])
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Updated task [{task_id}] "
                   + "; ".join(f"{k}={v}" for k, v in changes.items()) + ".",
            data={"task_id": task_id, "updated": changes})


class CompleteTaskTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "complete_task",
            "Mark a task done by id. If the id is a habit, logs the habit "
            "completion (with streak) instead -- the same branch /done takes.",
            {"type": "object", "properties": {
                "task_id": {"type": "integer"}},
             "required": ["task_id"]},
            risk=RiskLevel.MUTATING)

    def run(self, task_id, **kwargs) -> ToolResult:
        existing = self._s.tasks.get_by_id(task_id, self._uid)
        if existing is None:
            raise self._err(f"task [{task_id}] not found.")
        if self._s.habits.is_habit(task_id):
            ok, streak_or_msg = self._s.habits.log_completion(task_id, self._uid)
            if ok:
                return ToolResult(
                    tool=self.spec.name, ok=True,
                    output=f"Completed habit [{task_id}] {existing[1]} — "
                           f"streak {streak_or_msg}.",
                    data={"task_id": task_id, "habit": True, "streak": streak_or_msg})
            return ToolResult(
                tool=self.spec.name, ok=True,
                output=f"Habit [{task_id}] already logged today.",
                data={"task_id": task_id, "habit": True,
                      "already_logged": True})
        self._s.tasks.mark_done(task_id, self._uid)
        self._note_typed("task", task_id, existing[1])
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Completed task [{task_id}] {existing[1]}.",
            data={"task_id": task_id, "done": True, "title": existing[1]})


class DeleteTaskTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "delete_task",
            "Permanently delete a task by id (hard delete -- cannot be "
            "undone).",
            {"type": "object", "properties": {
                "task_id": {"type": "integer"}},
             "required": ["task_id"]},
            risk=RiskLevel.DESTRUCTIVE,
            confirmation_message="Permanently delete this task? This cannot be undone.")

    def run(self, task_id, **kwargs) -> ToolResult:
        existing = self._s.tasks.get_by_id(task_id, self._uid)
        if existing is None:
            raise self._err(f"task [{task_id}] not found.")
        self._s.tasks.delete(task_id, self._uid)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Deleted task [{task_id}] {existing[1]}.",
            data={"task_id": task_id, "deleted": True, "title": existing[1]})


# ── HABITS ────────────────────────────────────────────────────────────────
class CreateHabitTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "create_habit",
            "Create a habit (a recurring task). time is HH:MM; recurrence is "
            "daily or weekly (with recurrence_weekday 0=Monday..6=Sunday).",
            {"type": "object", "properties": {
                "title": {"type": "string", "minLength": 1},
                "time": {"type": ["string", "null"]},
                "recurrence": {"type": "string", "default": "daily"},
                "recurrence_weekday": {"type": ["integer", "null"]},
                "category": {"type": "string", "default": "Health"},
                "priority": {"type": "string", "default": "medium"}},
             "required": ["title"]},
            risk=RiskLevel.MUTATING)

    def run(self, title, time=None, recurrence="daily", recurrence_weekday=None,
            category="Health", priority="medium", **kwargs) -> ToolResult:
        habit_id = self._s.habits.add(
            self._uid, title, time, recurrence, recurrence_weekday,
            category, priority)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Created habit [{habit_id}] {title}.",
            data={"habit_id": habit_id, "title": title, "time": time,
                  "recurrence": recurrence})


class ListHabitsTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "list_habits",
            "List the user's active habits with current streaks.",
            {"type": "object", "properties": {}},
            risk=RiskLevel.READ_ONLY)

    def run(self, **kwargs) -> ToolResult:
        rows = self._s.habits.get_all(self._uid)
        data = [{
            "habit_id": r[0], "title": r[1], "time": r[2],
            "recurrence": r[3], "recurrence_weekday": r[4],
            "current_streak": r[5], "longest_streak": r[6],
            "last_completed": r[7], "started": r[8]} for r in rows]
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output="No habits.", data=[])
        lines = [f"[{h['habit_id']}] {h['title']} — streak {h['current_streak']}"
                 for h in data]
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"{len(data)} habit(s):\n" + "\n".join(lines),
                          data=data)


class CompleteHabitTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "complete_habit",
            "Log a habit as done for today (the id is a task id that is a "
            "habit). Reports the current streak; re-logging the same day "
            "is not an error.",
            {"type": "object", "properties": {
                "habit_id": {"type": "integer"}},
             "required": ["habit_id"]},
            risk=RiskLevel.MUTATING)

    def run(self, habit_id, **kwargs) -> ToolResult:
        if not self._s.habits.is_habit(habit_id):
            raise self._err(f"id [{habit_id}] is not a habit.")
        ok, streak_or_msg = self._s.habits.log_completion(
            habit_id, self._uid)
        if ok:
            return ToolResult(
                tool=self.spec.name, ok=True,
                output=f"Logged habit [{habit_id}] — streak {streak_or_msg}.",
                data={"habit_id": habit_id, "streak": streak_or_msg,
                      "already_logged": False})
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Habit [{habit_id}] already logged today.",
            data={"habit_id": habit_id, "already_logged": True})


# ── GOALS ─────────────────────────────────────────────────────────────────
class CreateGoalTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "create_goal",
            "Create a goal. deadline is %Y-%m-%d or null.",
            {"type": "object", "properties": {
                "title": {"type": "string", "minLength": 1},
                "deadline": {"type": ["string", "null"]}},
             "required": ["title"]},
            risk=RiskLevel.MUTATING)

    def run(self, title, deadline=None, **kwargs) -> ToolResult:
        goal_id = self._s.goals.add(self._uid, title, deadline)
        self._note_typed("goal", goal_id, title)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Created goal [{goal_id}] {title}.",
            data={"goal_id": goal_id, "title": title, "deadline": deadline})


class ListGoalsTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "list_goals",
            "List the user's goals with progress/target percentages.",
            {"type": "object", "properties": {}},
            risk=RiskLevel.READ_ONLY)

    def run(self, **kwargs) -> ToolResult:
        rows = self._s.goals.get_all_full(self._uid)
        data = [{
            "goal_id": r[0], "title": r[1], "deadline": r[2],
            "progress": r[3], "target": r[4]} for r in rows]
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output="No goals.", data=[])
        for g in data:
            self._note_typed("goal", g["goal_id"], g["title"])
        lines = [f"[{g['goal_id']}] {g['title']} — {g['progress']}/{g['target']}"
                 for g in data]
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"{len(data)} goal(s):\n" + "\n".join(lines),
                          data=data)


class UpdateGoalProgressTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "update_goal_progress",
            "Adjust a goal's progress by a delta (positive or negative), "
            "clamped to [0, target]. Returns the new progress and whether the "
            "goal is now complete.",
            {"type": "object", "properties": {
                "goal_id": {"type": "integer"},
                "delta": {"type": "integer"}},
             "required": ["goal_id", "delta"]},
            risk=RiskLevel.MUTATING)

    def run(self, goal_id, delta, **kwargs) -> ToolResult:
        title = self._goal_title(goal_id)
        result = self._s.goals.update_progress(goal_id, self._uid, delta)
        if result is None:
            raise self._err(
                f"goal [{goal_id}] not found or progress tracking unavailable.")
        new_progress, target, done = result
        self._note_typed("goal", goal_id, title or f"goal {goal_id}")
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Goal [{goal_id}] progress {new_progress}/{target}"
                   + (" — complete!" if done else "") + ".",
            data={"goal_id": goal_id, "progress": new_progress,
                  "target": target, "completed": done})


class UpdateGoalDeadlineTool(_BoundTool):
    """v15.2 M4: set (or clear) a goal's deadline -- the goal domain's OWN
    operation, so a deadline request on a goal can never fall through to a
    workspace entity (F6/F7). `goal` resolves through the typed referent
    store first (current-run wins, never the stale active character)."""

    _DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    @property
    def spec(self):
        return ToolSpec(
            "update_goal_deadline",
            "Set a goal's deadline (YYYY-MM-DD) or clear it (null). The goal "
            "domain owns deadlines -- never use an entity tool for a deadline.",
            {"type": "object", "properties": {
                "goal": {"type": "string", "minLength": 1,
                         "description": "goal name, id, or this-run referent"},
                "deadline": {"type": ["string", "null"],
                             "description": "YYYY-MM-DD, or null to clear"}},
             "required": ["goal", "deadline"]},
            risk=RiskLevel.MUTATING)

    def run(self, goal, deadline, **kwargs) -> ToolResult:
        if deadline is not None and not self._DATE_RE.fullmatch(str(deadline)):
            raise self._err(f"invalid deadline {deadline!r} — use YYYY-MM-DD.")
        goal_id, title = self._resolve_goal(goal)
        # update_deadline returns goal_id on success (even when the deadline
        # is CLEARED to None -- None is a legitimate new value, never the
        # failure signal); None means the goal vanished / schema lacks the
        # column. Existence was already proven by _resolve_goal above, so a
        # None here is a genuine failure, not a cleared deadline.
        if self._s.goals.update_deadline(goal_id, self._uid, deadline) is None:
            raise self._err(f"goal [{goal_id}] not found.")
        self._note_typed("goal", goal_id, title)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Updated goal [{goal_id}] {title}: deadline → "
                   + (deadline or "none") + ".",
            data={"goal_id": goal_id, "title": title,
                  "deadline": deadline})


# ── WORKSPACE ─────────────────────────────────────────────────────────────
class _WorkspaceTool(_BoundTool):
    """Adds pure workspace/entity resolution. The name match is a thin
    id/exact/unique-partial lookup mirroring WorkspaceGroups._resolve_workspace
    -- it is NOT the M1 conversational resolver (pronouns/ordinals), which is
    reused only in _EntityTool via ReferenceResolver."""

    def _find_workspace(self, ref=None):
        if ref is None or not str(ref).strip():
            active = self._s.tg_bindings.get_active(self._uid)
            if active and active[0] is not None:
                return self._eng.get_workspace_or_none(self._uid, active[0])
            return None
        ref = str(ref).strip()
        wss = self._eng.list_workspaces(self._uid, status=None)
        if ref.isdigit():
            wid = int(ref)
            return next((w for w in wss if w.id == wid), None)
        low = ref.lower()
        exact = [w for w in wss if w.title.lower() == low]
        if exact:
            return exact[0]
        partial = [w for w in wss if low in w.title.lower()]
        return partial[0] if len(partial) == 1 else None

    def _require_workspace(self, ref=None) -> int:
        ws = self._find_workspace(ref)
        if ws is None:
            # The spec says workspace "defaults to the active one". A ref that
            # does NOT resolve (e.g. the model passing the literal 'default',
            # or a stale workspace id) falls back to the active workspace
            # instead of failing the call. Only when there is NO active
            # workspace at all do we error.
            ws = self._find_workspace(None)
        if ws is None:
            raise self._err(
                "no active workspace — pass a 'workspace' name/#id or open "
                "one first.")
        return ws.id

    def _require_workspace_strict(self, ref=None) -> int:
        """Like `_require_workspace` but NEVER falls back to the active
        workspace when an explicit ref is given yet doesn't resolve (v15.2
        M4.x invariant: a requested ref is not the active ref without
        explicit evidence — a stale/wrong name must fail, not mutate the
        active workspace). Only an empty ref means "the active workspace"."""
        if ref is None or not str(ref).strip():
            return self._require_workspace(None)
        ws = self._find_workspace(ref)
        if ws is None:
            raise self._err(f"no workspace matches {ref!r}.")
        return ws.id


class WsListTool(_WorkspaceTool):
    @property
    def spec(self):
        return ToolSpec(
            "list_workspaces",
            "List the user's workspaces (id, title, template, status).",
            {"type": "object", "properties": {}},
            risk=RiskLevel.READ_ONLY)

    def run(self, **kwargs) -> ToolResult:
        wss = self._eng.list_workspaces(self._uid, status=None)
        data = [{"workspace_id": w.id, "title": w.title, "template": w.template,
                 "status": w.status, "icon": w.icon} for w in wss]
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output="No workspaces.", data=[])
        lines = [f"#{w['workspace_id']} {w['title']} ({w['template']})"
                 for w in data]
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"{len(data)} workspace(s):\n"
                                 + "\n".join(lines), data=data)


class WsGetTool(_WorkspaceTool):
    @property
    def spec(self):
        return ToolSpec(
            "get_workspace",
            "Get one workspace by name, #id, or the active one (omit "
            "workspace).",
            {"type": "object", "properties": {
                "workspace": {"type": ["string", "integer"],
                              "description": "workspace name or #id"}}},
            risk=RiskLevel.READ_ONLY)

    def run(self, workspace=None, **kwargs) -> ToolResult:
        ws = self._find_workspace(workspace)
        if ws is None:
            raise self._err(f"no workspace matches {workspace!r}.")
        data = {"workspace_id": ws.id, "title": ws.title, "template": ws.template,
                "status": ws.status, "icon": ws.icon}
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"#{ws.id} {ws.title} ({ws.template}) — {ws.status}",
                          data=data)


class WsOpenTool(_WorkspaceTool):
    @property
    def spec(self):
        return ToolSpec(
            "open_workspace",
            "Make a workspace the user's active workspace (clears the active "
            "entity). MUTATING: this changes persisted active state -- the "
            "same side effect /use has.",
            {"type": "object", "properties": {
                "workspace": {"type": ["string", "integer"],
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"}}},
            risk=RiskLevel.MUTATING)

    def run(self, workspace=None, **kwargs) -> ToolResult:
        ws = self._find_workspace(workspace)
        if ws is None:
            raise self._err(f"no workspace matches {workspace!r}.")
        self._s.tg_bindings.set_active(self._uid, ws.id)   # clears entity
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Active workspace: #{ws.id} {ws.title}.",
            data={"workspace_id": ws.id, "title": ws.title, "active": True})


class WsInspectTool(_WorkspaceTool):
    @property
    def spec(self):
        return ToolSpec(
            "inspect_workspace",
            "Deep view of a workspace: overall progress, entity counts by "
            "status, and the most recent progress notes.",
            {"type": "object", "properties": {
                "workspace": {"type": ["string", "integer"],
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"}}},
            risk=RiskLevel.READ_ONLY)

    def run(self, workspace=None, **kwargs) -> ToolResult:
        ws = self._find_workspace(workspace)
        if ws is None:
            raise self._err(f"no workspace matches {workspace!r}.")
        milestones = self._eng.list_milestones(self._uid, ws.id)
        counts = {s: 0 for s in _ENTITY_STATUSES}
        for m in milestones:
            counts[m.status] = counts.get(m.status, 0) + 1
        notes = self._eng.list_notes(self._uid, ws.id, kind="progress")
        data = {
            "workspace_id": ws.id, "title": ws.title, "template": ws.template,
            "status": ws.status,
            "progress": self._eng.workspace_progress(self._uid, ws.id),
            "entities": counts,
            "total_entities": len(milestones),
            "recent_notes": [{"id": n.id, "content": n.content} for n in notes[:3]],
        }
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"#{ws.id} {ws.title}: {data['progress']}% — "
                   f"{len(milestones)} entities", data=data)


# ── ENTITIES ──────────────────────────────────────────────────────────────
class _EntityTool(_WorkspaceTool):
    """Entity adapters additionally reuse the M1 ReferenceContext/Resolver so
    a pronoun/ordinal/active-entity reference resolves exactly as it does in
    NL chat (never reimplemented here), and an injected TelegramProjection is
    driven through the SAME alpha.13 contract WorkspaceGroups uses."""

    def __init__(self, user_id, storage=None, engine=None, groups=None,
                 projection=None, ref_ctx=None, typed_refs=None,
                 user_text=None):
        super().__init__(user_id, storage, engine, typed_refs=typed_refs)
        self._groups = groups or WorkspaceGroups(self._s, self._eng)
        self._projection = projection
        self._ref_ctx = ref_ctx or ReferenceContext()
        self._resolver = ReferenceResolver(self._s, self._eng, self._ref_ctx)
        self._user_text = user_text

    def _entities(self, ws_id):
        return list(self._eng.list_milestones(self._uid, ws_id))

    def _no_projection(self):
        """Contained, non-error report for a tool that needs a wired
        TelegramProjection but has none. Shared by the topic tools and the
        repair tool -- a missing projection is a soft no-op, never a raise."""
        return ToolResult(
            tool=self.spec.name, ok=True,
            output="Telegram projection is not wired — nothing to do.",
            data={"reason": "not_wired"})

    def _resolve_entity(self, ws_id, ref, action="resolve"):
        """Typed referent store FIRST (current-run wins -- never a stale
        active entity from a previous turn, and a pronoun pointing at a
        DIFFERENT domain is a conflict, never a silent reach across kinds),
        then the M1 resolver (pronoun/ordinal/deictic against conversation
        context), then a thin name match mirroring
        EntityManager._find_entity. Returns (milestone | None, entities).

        Every outcome is recorded as a structured, non-secret
        `entity_resolution:` log line (M4.x spec) so bot.log forensics can
        answer "requested X, why did Y get mutated?" without the raw message
        or any secrets."""
        ref = (ref or "").strip()
        entities = self._entities(ws_id)
        if not ref:
            self._resolution_diag(ref="", ws_id=ws_id, resolution="NO_REF",
                                  referent=None, action=action)
            return None, entities
        if self._typed_refs is not None:
            out = self._typed_refs.resolve(self._uid, ref, "entity")
            if out.conflict:
                self._resolution_diag(ref=ref, ws_id=ws_id, resolution="CONFLICT",
                                      referent=None, action=action)
                raise self._err(
                    f"{out.conflict_name!r} is a {out.conflict_kind}, not a "
                    "workspace entity — refusing to apply an entity operation "
                    "to it.")
            if out.referent is not None:
                m = next((e for e in entities if e.id == out.referent.id), None)
                if m is not None:
                    self._resolution_diag(ref=ref, ws_id=ws_id, resolution="FOUND",
                                          referent=m, action=action)
                    return m, entities
        res = self._resolver.resolve(self._uid, ref, ws_id, entities)
        if res.kind == "entity" and res.entity is not None:
            self._resolution_diag(ref=ref, ws_id=ws_id, resolution="FOUND",
                                  referent=res.entity, action=action)
            return res.entity, entities
        target = self._name_match(ref, entities)
        self._resolution_diag(ref=ref, ws_id=ws_id,
                              resolution="FOUND" if target else "NOT_FOUND",
                              referent=target, action=action)
        return target, entities

    def _resolution_diag(self, *, ref, ws_id, resolution, referent, action):
        """The structured `entity_resolution:` diagnostic. Requested reference
        (the name/id the model passed, NOT raw user text), workspace id, and
        resolution outcome only — never a secret, never the full message.
        Also recorded into the in-memory ResolutionTrace (core/ai/
        resolution_trace.py) so `/diag` can surface it."""
        if referent is not None:
            fallback = ("REFERENT" if str(ref or "").strip()
                        and referent.title.lower() != str(ref or "").lower()
                        else "EXACT")
        else:
            fallback = "NONE"
        logger.info(
            "entity_resolution: user=%s workspace_id=%s requested_name=%r "
            "kind=%s resolution=%s fallback=%s action=%s",
            self._uid, ws_id, ref, referent.entity_type if referent else "entity",
            resolution, fallback, action)
        try:
            from core.ai.resolution_trace import get_resolution_trace
            get_resolution_trace().record(
                user_id=self._uid, workspace_id=ws_id, action=action,
                requested=str(ref or ""), kind=referent.entity_type if referent
                else "entity", resolution=resolution, fallback=fallback,
                entity_title=referent.title if referent else None,
                entity_id=referent.id if referent else None)
        except Exception:   # diagnostics must never break a tool call
            logger.debug("resolution-trace record failed", exc_info=True)

    @staticmethod
    def _name_match(ref, entities):
        if ref.isdigit():
            rid = int(ref)
            return next((m for m in entities if m.id == rid), None)
        low = ref.lower()
        for m in entities:
            if m.title.lower() == low:
                return m
        partial = [m for m in entities if low in m.title.lower()]
        return partial[0] if len(partial) == 1 else None

    def _activate(self, ws_id, milestone):
        """Persist the active entity (tg_active_context) + note the referent
        in M1 conversation memory -- the same two writes EntityManager does."""
        self._s.tg_bindings.set_active(self._uid, ws_id, ENTITY_TYPE, milestone.id)
        self._note_mention(ws_id, milestone)

    def _note_mention(self, ws_id, milestone):
        self._ref_ctx.note_mention(
            self._uid, Referent(kind=ENTITY_TYPE, id=milestone.id,
                                title=milestone.title, workspace_id=ws_id))
        self._note_typed("entity", milestone.id, milestone.title, ws_id)

    @staticmethod
    def _entity_dict(m, workspace_id, workspace_title=None):
        return {"entity_id": m.id, "title": m.title, "entity_type": m.entity_type,
                "workspace_id": workspace_id, "workspace_title": workspace_title,
                "status": m.status, "progress": m.progress, "fields": m.fields}

    def _require_entity_strict(self, ws_id, ref):
        """Resolve an entity in a workspace STRICTLY: #id, exact title, or a
        UNIQUE partial — never pronouns/ordinals/active-referent fallback and
        never a cross-kind reach (v15.2 M4.x invariant). Used by the
        deterministic manual control plane so a stale or ambiguous ref fails
        instead of mutating the wrong entity. Returns the Milestone or raises."""
        ref = (ref or "").strip()
        if not ref:
            raise self._err("an entity reference is required.")
        entities = self._entities(ws_id)
        target = self._name_match(ref, entities)
        if target is None:
            raise self._err(f"no entity matches {ref!r} in workspace #{ws_id}.")
        return target


class CreateEntityTool(_EntityTool):
    """Create a workspace entity under the CANONICAL one-entity-per-name
    contract (M4 items 1/6/14): the kind is resolved generically (DB row →
    explicit utterance/name type → the model's entity_type argument → weak
    generic hints -- see EntityKindResolver), and a row whose normalized
    title already matches is NEVER duplicated: a same-kind collision is an
    honest "already exists -- update it instead", and a different-kind
    collision ADOPTS the kind onto the existing row (one entity, one topic)."""

    @property
    def spec(self):
        return ToolSpec(
            "create_entity",
            "Create a workspace entity (the single entity+topic contract /add "
            "and NL creation use: the entity is created, its Telegram topic "
            "ensured if a projection is wired, and it becomes the active "
            "entity). Set fields afterwards with update_entity. entity_type "
            "is the entity's kind -- 'character', 'weapon', 'artifact' "
            "(default 'entity'). ONE entity per name: creating a name that "
            "already exists reuses the existing row -- same kind is an "
            "'already exists' error (update it instead), a different kind "
            "adopts that kind onto the existing row.",
            {"type": "object", "properties": {
                "name": {"type": "string", "minLength": 1},
                "entity_type": {"type": "string", "default": "entity",
                                "description": "the entity's kind"},
                "workspace": {"type": ["string", "integer"],
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"}},
             "required": ["name"]},
            risk=RiskLevel.MUTATING)

    def run(self, name, workspace=None, entity_type="entity", **kwargs) -> ToolResult:
        ws_id = self._require_workspace(workspace)
        rows = self._entities(ws_id)
        # Kind resolution (M4 item 1/15): an existing DB row for this name
        # wins (priority 1); then an explicit type in the utterance/name (2);
        # then the model's entity_type argument (4); then weak generic hints
        # (3). EntityKindResolver is deterministic + offline + generic.
        resolved = EntityKindResolver().resolve_for_create(
            self._user_text, name, rows)
        if resolved is not None:
            final = resolved.kind
        else:
            final = (entity_type or "").strip().lower()
        final = final or KIND_ENTITY

        # Canonical one-entity-per-name (M4 item 6): a row whose normalized
        # title equals this name is the SAME logical entity, whatever its
        # kind -- creating it again must never insert a duplicate row/topic.
        norm = _normalize_title(name)
        existing = next((m for m in rows
                         if _normalize_title(m.title) == norm), None)
        self._resolution_diag(ref=name, ws_id=ws_id,
                              resolution="EXISTS" if existing else "NOT_FOUND",
                              referent=existing, action="create")
        if existing is not None:
            cur = (existing.entity_type or KIND_ENTITY).lower()
            if cur == final:
                raise self._err(
                    f"entity {name!r} already exists — update it instead.")
            # Different kind → adopt it onto the existing row (one entity,
            # one topic), never a second duplicate.
            try:
                self._eng.adopt_entity_type(self._uid, existing.id, final)
            except EntityValidationError as e:
                raise self._err(str(e))
            self._note_mention(ws_id, existing)
            topic_id = None
            if self._projection is not None:
                try:
                    topic_id = self._projection.ensure_entity_topic(
                        self._uid, ws_id, ENTITY_TYPE, existing.id,
                        existing.title,
                        initial_message=format_entity_card(
                            existing, with_timestamp=True))
                except Exception as e:  # best-effort -- the adoption stands
                    logger.warning(
                        "create_entity adoption topic ensure failed for %s: %s",
                        existing.title, e)
            ws = self._eng.get_workspace_or_none(self._uid, ws_id)
            return ToolResult(
                tool=self.spec.name, ok=True,
                output=f"Adopted {final} onto {existing.title!r} (id "
                       f"{existing.id}) in #{ws_id} — one entity, one topic.",
                data={"entity_id": existing.id, "title": existing.title,
                      "entity_type": final, "workspace_id": ws_id,
                      "workspace_title": ws.title if ws else None,
                      "status": existing.status, "topic_id": topic_id,
                      "topic_created": topic_id is not None,
                      "adopted": True})

        m, topic_id = self._groups.create_entity(
            self._uid, ws_id, name, self._projection, entity_type=final)
        self._note_mention(ws_id, m)
        ws = self._eng.get_workspace_or_none(self._uid, ws_id)
        topic_note = (" · Telegram topic created"
                      if topic_id else " · no topic (projection not wired)")
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Created {final} {name!r} (id {m.id}) in #{ws_id}"
                   f"{topic_note}.",
            data={"entity_id": m.id, "title": m.title, "entity_type": final,
                  "workspace_id": ws_id,
                  "workspace_title": ws.title if ws else None,
                  "status": m.status, "topic_id": topic_id,
                  "topic_created": topic_id is not None, "adopted": False})


class GetEntityTool(_EntityTool):
    @property
    def spec(self):
        return ToolSpec(
            "get_entity",
            "Get one workspace entity by name, #id, or a conversational "
            "reference (pronoun/ordinal). Read-only: never changes the active "
            "entity; only updates in-memory reference memory.",
            {"type": "object", "properties": {
                "entity": {"type": "string", "minLength": 1,
                           "description": "entity name, #id, or reference"},
                "workspace": {"type": ["string", "integer"],
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"}},
             "required": ["entity"]},
            risk=RiskLevel.READ_ONLY)

    def run(self, entity, workspace=None, **kwargs) -> ToolResult:
        ws_id = self._require_workspace(workspace)
        m, _ = self._resolve_entity(ws_id, entity, action="get")
        if m is None:
            raise self._err(f"no entity matches {entity!r} in workspace #{ws_id}.")
        self._note_mention(ws_id, m)
        ws = self._eng.get_workspace_or_none(self._uid, ws_id)
        data = self._entity_dict(m, ws_id, ws.title if ws else None)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"{data['title']} — [{data['status']}] {data['progress']}%",
            data=data)


class UpdateEntityTool(_EntityTool):
    @property
    def spec(self):
        return ToolSpec(
            "update_entity",
            "Set fields on an existing entity (by name, #id, or reference). "
            "fields is an object of {field_name: value}; unknown field names "
            "are allowed (forward-compat), values are validated against the "
            "workspace template. Appends an activity message to the entity's "
            "Telegram topic when a projection is wired.",
            {"type": "object", "properties": {
                "entity": {"type": "string", "minLength": 1},
                "workspace": {"type": ["string", "integer"]},
                "fields": {"type": "object"}},
             "required": ["entity", "fields"]},
            risk=RiskLevel.MUTATING)

    def run(self, entity, fields, workspace=None, **kwargs) -> ToolResult:
        if not isinstance(fields, dict) or not fields:
            raise self._err("'fields' must be a non-empty object.")
        ws_id = self._require_workspace(workspace)
        target, _ = self._resolve_entity(ws_id, entity, action="update")
        if target is None:
            raise self._err(f"no entity matches {entity!r} in workspace #{ws_id}.")
        old_values = {k: target.fields.get(k) for k in fields}
        applied, warnings = {}, []
        last_updated = None
        for fname, fvalue in fields.items():
            try:
                last_updated = self._eng.update_field(
                    self._uid, target.id, fname, fvalue)
                applied[fname] = fvalue
            except EntityValidationError as e:
                warnings.append(f"{fname}: {e}")
            except EntityNotFound:
                raise self._err(f"entity [{target.id}] disappeared during update")
        if not applied:
            raise self._err("no fields could be applied: "
                            + ("; ".join(warnings) or "empty fields object") + ".")
        self._activate(ws_id, target)
        changes = {f: (old_values.get(f), v) for f, v in applied.items()}
        posted = False
        if self._projection is not None:
            try:
                card_target = last_updated if last_updated is not None else target
                self._projection.post_entity_update(
                    self._uid, ws_id, ENTITY_TYPE, target.id, target.title,
                    format_entity_update(card_target, changes),
                    initial_message=format_entity_card(
                        card_target, with_timestamp=True))
                posted = True
            except Exception as e:  # best-effort -- the DB update stands
                warnings.append(f"topic update failed: {e}")
        result = ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Updated entity {target.title!r}: "
                   + "; ".join(f"{k}={v}" for k, v in applied.items()) + ".",
            data={"entity_id": target.id, "title": target.title,
                  "workspace_id": ws_id, "applied": applied,
                  "changes": changes, "topic_posted": posted,
                  "warnings": tuple(warnings)})
        return result


class ListEntitiesTool(_EntityTool):
    """Typed retrieval surface (M4 item 2): `kind` MUST be explicit and
    selects ONE domain, with these invariants --
      * list(kind=character) → characters ONLY,
      * list(kind=goal/task/habit) → that cross-domain table ONLY,
      * list(kind=all) → every supported type (entities of every kind +
        goals + tasks + habits),
      * a mixed list never leaks into a typed list (goals never appear under
        kind=character)."""

    _KIND_ENUM = tuple(ALL_KINDS) + (LIST_ALL,)

    @property
    def spec(self):
        return ToolSpec(
            "list_entities",
            "List entities by KIND (a required, explicit filter). kind is one "
            "of: 'character', 'weapon', 'artifact', 'entity' (workspace "
            "entities of that kind), 'goal'/'task'/'habit' (the user's "
            "goals/tasks/habits), or 'all' (every supported type). Typed "
            "lists never leak across kinds. status (todo/in_progress/done/"
            "blocked) filters the workspace-entity portion.",
            {"type": "object", "properties": {
                "kind": {"type": "string", "enum": list(self._KIND_ENUM),
                         "description": "the kind to list — REQUIRED"},
                "status": {"type": "string", "enum": list(_ENTITY_STATUSES),
                           "description": "workspace-entity status filter"},
                "entity_type": {"type": "string",
                                "description": "legacy alias: filter the "
                                               "workspace-entity portion to "
                                               "one kind"},
                "workspace": {"type": ["string", "integer"]}},
             "required": ["kind"]},
            risk=RiskLevel.READ_ONLY)

    def _cross_domain(self, kind) -> list:
        """The user's goals/tasks/habits (user-level, workspace-independent).
        Each dict carries a 'kind' marker so the renderer can tell domains."""
        out = []
        if kind == KIND_GOAL:
            for r in self._s.goals.get_all_full(self._uid):
                g = {"goal_id": r[0], "title": r[1], "deadline": r[2],
                     "progress": r[3], "target": r[4], "kind": KIND_GOAL}
                out.append(g)
                self._note_typed(KIND_GOAL, g["goal_id"], g["title"])
        elif kind == KIND_TASK:
            # A habit is a task row with is_habit=1 (database.py's own
            # representation): the typed task list must exclude them, or
            # kind=task leaks habit rows (typed-list leak invariant).
            habit_ids = {r[0] for r in self._s.habits.get_all(self._uid)}
            for r in self._s.tasks.get_all(self._uid, 0):
                if r[0] in habit_ids:
                    continue
                t = self._task_dict(r)
                t["kind"] = KIND_TASK
                out.append(t)
                self._note_typed(KIND_TASK, t["task_id"], t["title"])
        elif kind == KIND_HABIT:
            for r in self._s.habits.get_all(self._uid):
                h = {"habit_id": r[0], "title": r[1], "time": r[2],
                     "recurrence": r[3], "recurrence_weekday": r[4],
                     "current_streak": r[5], "longest_streak": r[6],
                     "last_completed": r[7], "started": r[8], "kind": KIND_HABIT}
                out.append(h)
                self._note_typed(KIND_HABIT, h["habit_id"], h["title"])
        return out

    def _workspace_entities(self, ws_id, status=None, entity_type=None,
                            kind=None) -> list:
        if ws_id is None:
            return []
        ws = self._eng.get_workspace_or_none(self._uid, ws_id)
        entities = self._entities(ws_id)
        if status:
            entities = [m for m in entities if m.status == status]
        et = (entity_type or "").strip().lower()
        if kind and kind != LIST_ALL:      # the typed surface wins
            et = kind
        if et:
            entities = [m for m in entities
                        if (m.entity_type or KIND_ENTITY).lower() == et]
        data = [self._entity_dict(m, ws_id, ws.title if ws else None)
                for m in entities]
        for d in data:
            d["kind"] = (d.get("entity_type") or KIND_ENTITY).lower()
            self._note_typed("entity", d["entity_id"], d["title"], ws_id)
        return data

    @staticmethod
    def _render(data) -> str:
        if not data:
            return "No entities."
        lines = []
        for d in data:
            ident = (d.get("entity_id") or d.get("goal_id")
                     or d.get("task_id") or d.get("habit_id"))
            kind = d.get("kind") or KIND_ENTITY
            title = d.get("title") or ""
            lines.append(f"[{kind}] #{ident} {title}")
        return f"{len(data)} item(s):\n" + "\n".join(lines)

    def run(self, kind, status=None, entity_type=None, workspace=None,
            **kwargs) -> ToolResult:
        kind = (kind or "").strip().lower()
        if kind not in self._KIND_ENUM:
            raise self._err(
                f"kind must be one of {', '.join(self._KIND_ENUM)}.")
        if kind in (KIND_GOAL, KIND_TASK, KIND_HABIT):
            # Cross-domain kinds are user-level -- no workspace required.
            data = self._cross_domain(kind)
            if not data:
                return ToolResult(tool=self.spec.name, ok=True,
                                  output="No entities.", data=[])
            return ToolResult(tool=self.spec.name, ok=True,
                              output=self._render(data), data=data)
        if kind == LIST_ALL:
            ws = self._find_workspace(workspace)
            ws_id = ws.id if ws is not None else None
            data = self._workspace_entities(ws_id, status, entity_type)
            data += self._cross_domain(KIND_GOAL)
            data += self._cross_domain(KIND_TASK)
            data += self._cross_domain(KIND_HABIT)
        else:
            ws_id = self._require_workspace(workspace)
            data = self._workspace_entities(ws_id, status, entity_type,
                                            kind=kind)
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output="No entities.", data=[])
        return ToolResult(tool=self.spec.name, ok=True,
                          output=self._render(data), data=data)


class FindEntityTool(_EntityTool):
    @property
    def spec(self):
        return ToolSpec(
            "find_entity",
            "Search entities by keyword across title and field values "
            "(deterministic token overlap; mirrors the NL filter's spirit). "
            "Returns matches ranked by relevance.",
            {"type": "object", "properties": {
                "query": {"type": "string", "minLength": 1},
                "workspace": {"type": ["string", "integer"]}},
             "required": ["query"]},
            risk=RiskLevel.READ_ONLY)

    @staticmethod
    def _tokens(text):
        import re
        stop = frozenset({"a", "an", "the", "of", "to", "in", "on", "for",
                          "and", "is", "are", "with", "at", "as", "my"})
        return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
                if len(t) > 1 and t not in stop}

    def run(self, query, workspace=None, **kwargs) -> ToolResult:
        ws_id = self._require_workspace(workspace)
        ws = self._eng.get_workspace_or_none(self._uid, ws_id)
        q = self._tokens(query)
        scored = []
        for m in self._entities(ws_id):
            hay = self._tokens(f"{m.title} "
                               + " ".join(str(v) for v in (m.fields or {}).values()
                                          if v is not None))
            overlap = q & hay
            if overlap:
                scored.append((m, len(overlap)))
        scored.sort(key=lambda p: p[1], reverse=True)
        data = [self._entity_dict(m, ws_id, ws.title if ws else None)
                for m, _ in scored]
        for d in data:
            self._note_typed("entity", d["entity_id"], d["title"], ws_id)
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output=f"No entities match {query!r}.", data=[])
        lines = [f"[{d['entity_id']}] {d['title']}" for d in data]
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"Matched {len(data)} entity(ies):\n"
                                 + "\n".join(lines), data=data)


# ── TOPIC LIFECYCLE (v15.2 M4 items 7/8/10) ───────────────────────────────
# The generic TopicProjection tool surface. Entity → Telegram topic is the
# projection's ONLY job (core/workspace/adapters/projection.py); these tools
# expose that surface generically so the Worker can inspect / ensure / lock /
# delete an entity's topic WITHOUT reimplementing projection logic. "DELETE
# ENTITY ≠ DELETE TOPIC": delete_entity_topic removes only the Telegram topic
# + its binding, never the DB entity -- and a LOCKED topic refuses ordinary
# deletion (item 8). All four reuse the entity/workspace/reference machinery
# of _EntityTool and the SAME injected projection /add and /use drive.


class _TopicTool(_EntityTool):
    """Topic tools are _EntityTool + a projection. Without a projection they
    are inert: every call reports projection-not-wired honestly (the same
    non-error stance create_entity takes for a missing projection)."""

    def _resolve_topic_entity(self, workspace, ref):
        """→ (ws_id, milestone). Resolves the entity in the active (or given)
        workspace through the SAME chain the entity tools use."""
        ws_id = self._require_workspace(workspace)
        m, _ = self._resolve_entity(ws_id, ref, action="topic")
        if m is None:
            raise self._err(f"no entity matches {ref!r} in workspace #{ws_id}.")
        return ws_id, m


class GetEntityTopicTool(_TopicTool):
    @property
    def spec(self):
        return ToolSpec(
            "get_entity_topic",
            "Inspect the Telegram topic for a workspace entity: its topic id "
            "and whether it is locked. Read-only — never creates or changes "
            "anything. Resolves the entity in the active workspace.",
            {"type": "object", "properties": {
                "entity": {"type": "string", "minLength": 1,
                           "description": "entity name, #id, or this-run referent"},
                "workspace": {"type": ["string", "integer"],
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"}},
             "required": ["entity"]},
            risk=RiskLevel.READ_ONLY)

    def run(self, entity, workspace=None, **kwargs) -> ToolResult:
        if self._projection is None:
            return self._no_projection()
        ws_id, m = self._resolve_topic_entity(workspace, entity)
        res = self._projection.get_topic(ws_id, ENTITY_TYPE, m.id)
        locked = (res.topic_id is not None
                  and self._projection.is_topic_locked(ws_id, ENTITY_TYPE, m.id))
        data = {"entity_id": m.id, "title": m.title, "entity_type": m.entity_type,
                "topic_id": res.topic_id, "locked": locked}
        if res.topic_id is None:
            return ToolResult(tool=self.spec.name, ok=True,
                              output=f"{m.title!r} has no Telegram topic yet.",
                              data=data)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"{m.title!r} → topic #{res.topic_id}"
                   + (" (locked)" if locked else ""),
            data=data)


class EnsureEntityTopicTool(_TopicTool):
    @property
    def spec(self):
        return ToolSpec(
            "ensure_entity_topic",
            "Ensure a workspace entity has a Telegram topic: returns the "
            "existing topic when one exists, creates EXACTLY ONE when it "
            "doesn't (the canonical one-topic-per-entity binding — never a "
            "duplicate), and posts the entity's current card into a newly "
            "created topic. The DB entity is untouched. Use after entity "
            "ops when the user expects a topic.",
            {"type": "object", "properties": {
                "entity": {"type": "string", "minLength": 1},
                "workspace": {"type": ["string", "integer"]}},
             "required": ["entity"]},
            risk=RiskLevel.MUTATING)

    def run(self, entity, workspace=None, **kwargs) -> ToolResult:
        if self._projection is None:
            return self._no_projection()
        ws_id, m = self._resolve_topic_entity(workspace, entity)
        had = self._projection.get_topic(ws_id, ENTITY_TYPE, m.id).topic_id
        topic_id = self._projection.ensure_entity_topic(
            self._uid, ws_id, ENTITY_TYPE, m.id, m.title,
            initial_message=format_entity_card(m))
        if topic_id is None:
            return ToolResult(
                tool=self.spec.name, ok=True,
                output=(f"Workspace #{ws_id} isn't linked to a Telegram group "
                        "— no topic can be created."),
                data={"entity_id": m.id, "title": m.title,
                      "entity_type": m.entity_type, "topic_id": None,
                      "created": False, "reason": "not_linked"})
        locked = self._projection.is_topic_locked(ws_id, ENTITY_TYPE, m.id)
        created = had is None
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=(f"{m.title!r} → topic #{topic_id}"
                    + (" created" if created else " (already exists)")
                    + (" — locked" if locked else "")),
            data={"entity_id": m.id, "title": m.title, "entity_type": m.entity_type,
                  "topic_id": topic_id, "created": created, "locked": locked})


class SetEntityTopicLockedTool(_TopicTool):
    @property
    def spec(self):
        return ToolSpec(
            "set_entity_topic_locked",
            "Durably lock or unlock an entity's Telegram topic. A LOCKED "
            "topic refuses ordinary deletion (delete_entity_topic without "
            "force) — the topic and its canonical binding are protected. "
            "Never touches the entity or the Telegram topic itself. The "
            "workspace must be linked to a group.",
            {"type": "object", "properties": {
                "entity": {"type": "string", "minLength": 1},
                "locked": {"type": "boolean",
                           "description": "true to lock, false to unlock"},
                "workspace": {"type": ["string", "integer"]}},
             "required": ["entity", "locked"]},
            risk=RiskLevel.MUTATING)

    def run(self, entity, locked, workspace=None, **kwargs) -> ToolResult:
        if self._projection is None:
            return self._no_projection()
        ws_id, m = self._resolve_topic_entity(workspace, entity)
        res = self._projection.set_topic_locked(
            ws_id, ENTITY_TYPE, m.id, bool(locked))
        data = {"entity_id": m.id, "title": m.title, "entity_type": m.entity_type,
                "topic_id": res.topic_id, "locked": bool(locked),
                "reason": res.reason}
        if res.reason == "not_linked":
            return ToolResult(
                tool=self.spec.name, ok=True,
                output=(f"Workspace #{ws_id} isn't linked to a Telegram group "
                        "— cannot lock."),
                data=data)
        state = "locked" if locked else "unlocked"
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"{m.title!r} topic {state}"
                   + (f" (topic #{res.topic_id})" if res.topic_id
                      else " (no topic yet)"),
            data=data)


class DeleteEntityTopicTool(_TopicTool):
    @property
    def spec(self):
        return ToolSpec(
            "delete_entity_topic",
            "Delete an entity's Telegram topic and its canonical binding. "
            "DISTINCT from deleting the entity: the DB entity stays. A LOCKED "
            "topic refuses deletion unless force=true (unlock it first or "
            "pass force). DESTRUCTIVE — the Worker asks for confirmation "
            "before this ever runs.",
            {"type": "object", "properties": {
                "entity": {"type": "string", "minLength": 1},
                "force": {"type": "boolean", "default": False,
                          "description": "delete even a locked topic"},
                "workspace": {"type": ["string", "integer"]}},
             "required": ["entity"]},
            risk=RiskLevel.DESTRUCTIVE,
            confirmation_message=("This permanently deletes the Telegram topic "
                                  "(the entity stays). Delete it?"))

    def run(self, entity, force=False, workspace=None, **kwargs) -> ToolResult:
        if self._projection is None:
            return self._no_projection()
        ws_id, m = self._resolve_topic_entity(workspace, entity)
        res = self._projection.delete_topic(
            self._uid, ws_id, ENTITY_TYPE, m.id, force=bool(force))
        data = {"entity_id": m.id, "title": m.title, "entity_type": m.entity_type,
                "topic_id": res.topic_id, "reason": res.reason}
        refusals = {
            "not_linked": f"Workspace #{ws_id} isn't linked to a Telegram group.",
            "no_topic": f"{m.title!r} has no Telegram topic to delete.",
            "locked": (f"{m.title!r}'s topic is LOCKED — unlock it first or "
                       "pass force=true."),
        }
        if res.reason in refusals:
            return ToolResult(tool=self.spec.name, ok=False,
                              output=refusals[res.reason], data=data)
        if res.reason == "telegram_deleted":
            return ToolResult(
                tool=self.spec.name, ok=True,
                output=(f"{m.title!r}'s topic binding removed; Telegram could "
                        "not delete the topic itself."),
                data=data)
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"{m.title!r}'s topic deleted.", data=data)


class ListEntityTopicsTool(_TopicTool):
    @property
    def spec(self):
        return ToolSpec(
            "list_entity_topics",
            "List every entity → Telegram topic binding in a workspace "
            "(entity, kind, topic id, locked). Read-only.",
            {"type": "object", "properties": {
                "workspace": {"type": ["string", "integer"],
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"}}},
            risk=RiskLevel.READ_ONLY)

    def run(self, workspace=None, **kwargs) -> ToolResult:
        if self._projection is None:
            return self._no_projection()
        ws_id = self._require_workspace(workspace)
        entities = {m.id: m for m in self._entities(ws_id)}
        data = []
        for entity_type, entity_id, topic_id in self._s.tg_bindings.get_entity_topics(
                ws_id):
            m = entities.get(entity_id)
            locked = self._projection.is_topic_locked(ws_id, entity_type, entity_id)
            data.append({
                "entity_id": entity_id,
                "title": m.title if m else f"#{entity_id}",
                "entity_type": m.entity_type if m else entity_type,
                "topic_id": topic_id, "locked": locked})
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output=f"Workspace #{ws_id} has no entity topics.",
                              data=[])
        for d in data:
            self._note_typed("entity", d["entity_id"], d["title"], ws_id)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"{len(data)} entity topic(s) in workspace #{ws_id}.",
            data=data)


# ── MEMORY / RECALL ───────────────────────────────────────────────────────
class GetMemoriesTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "get_memories",
            "List everything in the user's memory store (key/value facts). "
            "Read-only.",
            {"type": "object", "properties": {}},
            risk=RiskLevel.READ_ONLY)

    def run(self, **kwargs) -> ToolResult:
        rows = self._s.memory.get_all(self._uid)
        data = [{"key": k, "value": v} for k, v in rows]
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output="No memories.", data=[])
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"{len(data)} memor(ies/y) stored.", data=data)


class SearchMemoriesTool(_BoundTool):
    @property
    def spec(self):
        return ToolSpec(
            "search_memories",
            "Search the user's memory store by keyword (smart search: falls "
            "back to significant words so a natural question still matches). "
            "Read-only.",
            {"type": "object", "properties": {
                "query": {"type": "string", "minLength": 1}},
             "required": ["query"]},
            risk=RiskLevel.READ_ONLY)

    def run(self, query, **kwargs) -> ToolResult:
        rows = self._s.memory.search_smart(self._uid, query)
        data = [{"key": k, "value": v} for k, v in rows]
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output=f"No memories match {query!r}.", data=[])
        lines = [f"{k} = {v}" for k, v in rows]
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"Matched {len(data)} memor(ies/y):\n"
                                 + "\n".join(lines), data=data)


class RecallTool(_BoundTool):
    """Structured variant of the /ws RecallTool: reuses the exact M1
    WorkspaceRetriever, but returns the Documents as structured data instead
    of a formatted string."""

    @property
    def spec(self):
        return ToolSpec(
            "recall",
            "Search across everything stored in the user's workspaces "
            "(entities, statuses, notes) for anything related to the query. "
            "Use for broad/open questions. Grounded in real stored data.",
            {"type": "object", "properties": {
                "query": {"type": "string", "minLength": 1}},
             "required": ["query"]},
            risk=RiskLevel.READ_ONLY)

    def __init__(self, user_id, storage=None, engine=None, typed_refs=None):
        super().__init__(user_id, storage, engine, typed_refs=typed_refs)
        self._retriever = WorkspaceRetriever(self._uid, self._eng, self._s)

    def run(self, query, **kwargs) -> ToolResult:
        docs = self._retriever.retrieve(query, k=6)
        data = [{"id": d.id, "text": d.text, "score": d.score,
                 "metadata": d.metadata} for d in docs]
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output="I couldn't find anything about that in "
                                     "your saved data.", data=[])
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"Found {len(data)} related item(s).", data=data)


# ── v15.3 M5: workspace lifecycle (Manual Control Plane + Lifecycle) ───────
# Thin tools wrapping the SAME domain methods /newgame, /use, /topicrepair and
# the M4 topic tools use — never a second implementation. The Manual Control
# Plane and the AI Worker execute through these identically.
class _WorkspaceLifecycleTool(_WorkspaceTool):
    """Workspace lifecycle tools additionally hold the WorkspaceGroups
    service so create/close/repair use the exact contract the manual commands
    use (WorkspaceGroups.create, close_workspace, repair_topics)."""

    def __init__(self, user_id, storage=None, engine=None, groups=None,
                 typed_refs=None):
        super().__init__(user_id, storage, engine, typed_refs=typed_refs)
        self._groups = groups or WorkspaceGroups(self._s, self._eng)


class CreateWorkspaceTool(_WorkspaceLifecycleTool):
    @property
    def spec(self):
        return ToolSpec(
            "create_workspace",
            "Create a workspace of a friendly kind and make it the ACTIVE "
            "workspace (same side effect /newgame has). Kinds: game, "
            "project, goal, workspace.",
            {"type": "object", "properties": {
                "title": {"type": "string", "minLength": 1},
                "template": {"type": "string", "default": "game",
                             "description": "game, project, goal, or workspace "
                                            "(default game)"}},
             "required": ["title"]},
            risk=RiskLevel.MUTATING)

    def run(self, title, template="game", **kwargs) -> ToolResult:
        kind = (template or "game").strip().lower()
        if kind not in KIND_TEMPLATE:
            raise self._err(f"unknown workspace kind {template!r} — use "
                            "game, project, goal, or workspace.")
        ws = self._groups.create(self._uid, kind, title)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Created {kind} workspace #{ws.id} {ws.title!r} and made "
                   "it active.",
            data={"workspace_id": ws.id, "title": ws.title,
                  "template": ws.template, "active": True})


class RenameWorkspaceTool(_WorkspaceLifecycleTool):
    @property
    def spec(self):
        return ToolSpec(
            "rename_workspace",
            "Rename a workspace. Strict: an explicit workspace ref that does "
            "not resolve fails (never silently renames the active workspace).",
            {"type": "object", "properties": {
                "workspace": {"type": ["string", "integer"],
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"},
                "title": {"type": "string", "minLength": 1}},
             "required": ["workspace", "title"]},
            risk=RiskLevel.MUTATING)

    def run(self, workspace, title, **kwargs) -> ToolResult:
        ws_id = self._require_workspace_strict(workspace)
        ws = self._eng.rename_workspace(self._uid, ws_id, title)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Renamed workspace #{ws.id} to {ws.title!r}.",
            data={"workspace_id": ws.id, "title": ws.title})


class CloseWorkspaceTool(_WorkspaceLifecycleTool):
    @property
    def spec(self):
        return ToolSpec(
            "close_workspace",
            "Close the active workspace: clear the persisted active context "
            "(workspace + entity). NEVER deletes or archives the workspace — "
            "it stays in storage, just not active. No-op when nothing is "
            "active.",
            {"type": "object", "properties": {}},
            risk=RiskLevel.MUTATING)

    def run(self, **kwargs) -> ToolResult:
        self._groups.close_workspace(self._uid)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output="Closed the active workspace (nothing is active now).",
            data={"active": False})


class ArchiveWorkspaceTool(_WorkspaceLifecycleTool):
    @property
    def spec(self):
        return ToolSpec(
            "archive_workspace",
            "Archive a workspace: a SOFT lifecycle transition to 'archived' "
            "— every entity, note, and Telegram binding stays in storage "
            "(nothing is deleted). DESTRUCTIVE in the risk sense: the "
            "workspace leaves the active surface. The Worker asks for "
            "confirmation before this ever runs.",
            {"type": "object", "properties": {
                "workspace": {"type": ["string", "integer"],
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"}},
             "required": ["workspace"]},
            risk=RiskLevel.DESTRUCTIVE,
            confirmation_message=("This archives the workspace (soft — nothing "
                                  "is deleted, it just stops being active). "
                                  "Archive it?"))

    def run(self, workspace, **kwargs) -> ToolResult:
        ws_id = self._require_workspace_strict(workspace)
        before = self._eng.get_workspace_or_none(self._uid, ws_id)
        ws = self._eng.archive_workspace(self._uid, ws_id)
        if before is not None and before.status == ws.status:
            return ToolResult(
                tool=self.spec.name, ok=True,
                output=f"Workspace #{ws.id} {ws.title!r} was already "
                       f"{ws.status}.",
                data={"workspace_id": ws.id, "title": ws.title,
                      "status": ws.status, "noop": True})
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Archived workspace #{ws.id} {ws.title!r}.",
            data={"workspace_id": ws.id, "title": ws.title,
                  "status": ws.status, "noop": False})


class DeleteEntityTool(_EntityTool):
    """Soft-delete the DB entity row. DISTINCT from delete_entity_topic: the
    Telegram topic (if any) is untouched — a topic is deleted through the
    topic tools, never silently here."""

    @property
    def spec(self):
        return ToolSpec(
            "delete_entity",
            "Soft-delete a workspace entity: the row is stamped deleted and "
            "stops appearing in active lists, but stays in storage. Its "
            "Telegram topic is NEVER touched — delete a topic separately via "
            "delete_entity_topic. DESTRUCTIVE — the Worker asks for "
            "confirmation before this ever runs.",
            {"type": "object", "properties": {
                "entity": {"type": "string", "minLength": 1},
                "workspace": {"type": ["string", "integer"]}},
             "required": ["entity"]},
            risk=RiskLevel.DESTRUCTIVE,
            confirmation_message=("This soft-deletes the entity (the Telegram "
                                  "topic, if any, stays). Delete it?"))

    def run(self, entity, workspace=None, **kwargs) -> ToolResult:
        ws_id = self._require_workspace_strict(workspace)
        m = self._require_entity_strict(ws_id, entity)
        self._eng.delete_milestone(self._uid, m.id)
        # If it was the active entity, clear just the entity slot (keep the
        # workspace active) so a later photo/log can't target a deleted row.
        active = self._s.tg_bindings.get_active(self._uid)
        if active and active[0] is not None and active[2] == m.id:
            self._s.tg_bindings.set_active(self._uid, active[0])
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Deleted entity {m.title!r} (#{m.id}) from workspace "
                   f"#{ws_id} (topic untouched).",
            data={"entity_id": m.id, "title": m.title, "workspace_id": ws_id,
                  "deleted": True})


class RepairTopicsTool(_EntityTool):
    """The /topicrepair command's domain call as a shared tool, so the Topic
    Control Center's [Repair] button runs the exact idempotent self-heal the
    command runs (never a second repair implementation)."""

    @property
    def spec(self):
        return ToolSpec(
            "repair_topics",
            "Self-heal the entity→topic projection across every linked "
            "workspace: collapse title-duplicate entities onto one canonical "
            "entity/topic, adopt a concrete kind onto an untyped canonical "
            "row, ensure a topic + current card for every canonical entity, "
            "and preserve locked bindings. Idempotent — re-running creates "
            "nothing when nothing is broken.",
            {"type": "object", "properties": {}},
            risk=RiskLevel.MUTATING)

    def run(self, **kwargs) -> ToolResult:
        if self._projection is None:
            return self._no_projection()
        report = self._groups.repair_topics(self._uid, self._projection)
        created = existing = duplicates = errors = 0
        for info in report.values():
            created += len(info.get("created") or [])
            existing += len(info.get("existing") or [])
            duplicates += len(info.get("duplicates") or [])
            errors += len(info.get("errors") or [])
        summary = (f"Repaired {len(report)} workspace(s): {created} topic(s) "
                   f"created, {existing} already fine, {duplicates} "
                   f"duplicate(s) collapsed, {errors} error(s).")
        return ToolResult(
            tool=self.spec.name, ok=True, output=summary,
            data={"workspaces": len(report), "created": created,
                  "existing": existing, "duplicates": duplicates,
                  "errors": errors})


class EquipItemTool(_EntityTool):
    """v15.3 M5-E minimal Genshin equipment foundation: equip a WEAPON entity
    onto a CHARACTER entity by writing the character's existing game-template
    `weapon` field with the item's title (deterministic, schema-clean — no
    second equipment database). `item` omitted clears the field (unequip).
    Artifact slots / refinement / stats are M6+, documented in
    docs/engineering/V15_3_MANUAL_CONTROL_PLANE.md — an artifact item is
    refused here, never silently written."""

    @property
    def spec(self):
        return ToolSpec(
            "equip_item",
            "Equip a weapon entity onto a character entity: writes the "
            "character's existing game-template 'weapon' field with the "
            "weapon's title. Omit `item` to unequip (clears the field). "
            "Artifacts are refused — artifact equipment is not implemented. "
            "Never touches any other field or the Telegram topic.",
            {"type": "object", "properties": {
                "character": {"type": "string", "minLength": 1},
                "item": {"type": "string", "description": "weapon entity "
                          "name/#id; omit to unequip"},
                "workspace": {"type": ["string", "integer"]}},
             "required": ["character"]},
            risk=RiskLevel.MUTATING)

    def run(self, character, item=None, workspace=None, **kwargs) -> ToolResult:
        ws_id = self._require_workspace_strict(workspace)
        ch = self._require_entity_strict(ws_id, character)
        ch_kind = (ch.entity_type or KIND_ENTITY).lower()
        if ch_kind in (KIND_WEAPON, KIND_ARTIFACT):
            raise self._err(f"{ch.title!r} is a {ch_kind}, not an equippable "
                            "character.")
        if item is None or not str(item).strip():
            updated = self._eng.update_field(self._uid, ch.id, "weapon", "")
            return ToolResult(
                tool=self.spec.name, ok=True,
                output=f"Unequipped {ch.title!r}'s weapon.",
                data={"entity_id": ch.id, "title": ch.title, "field": "weapon",
                      "value": ""})
        it = self._require_entity_strict(ws_id, item)
        it_kind = (it.entity_type or KIND_ENTITY).lower()
        if it_kind not in (KIND_WEAPON, KIND_ARTIFACT):
            raise self._err(f"{it.title!r} is a {it_kind}, not equippable — "
                            "only weapon/artifact items.")
        if it_kind == KIND_ARTIFACT:
            raise self._err(
                f"{it.title!r} is an artifact — artifact equipment (slots) "
                "isn't implemented in M5; see the M5 doc.")
        updated = self._eng.update_field(self._uid, ch.id, "weapon", it.title)
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Equipped {it.title!r} on {ch.title!r}.",
            data={"entity_id": ch.id, "title": ch.title, "field": "weapon",
                  "value": it.title, "item_id": it.id})


# ── registry builder ──────────────────────────────────────────────────────
def build_tool_registry(user_id: int,
                        storage: Storage | None = None,
                        engine: EntityEngine | None = None,
                        projection=None,
                        ref_ctx: ReferenceContext | None = None,
                        typed_refs=None,
                        user_text: str | None = None) -> ToolRegistry:
    """Build a per-user registry of every M3 real adapter.

    `projection` (a TelegramProjection or duck-typed equivalent) is injected
    by a live caller so entity create/update project to Telegram through the
    alpha.13 contract; default None means no projection (offline tests, or a
    caller that has not wired a live client yet). `ref_ctx` lets tests share
    one M1 conversation context across registries; a fresh one is built
    otherwise. `typed_refs` (v15.2 M4) is the Worker's TypedReferentStore:
    every tool notes referents it creates/lists/updates into it and resolves
    references through it FIRST, so a create→set→show chain uses the
    CURRENT run's ids, never a stale active entity. Active-workspace state
    is read from the DB-backed tg_active_context at call time -- the same
    source /use and /add use.

    `user_text` (v15.2 M4) is the RAW user utterance for the current run;
    the create-entity adapter uses it for generic kind resolution
    ("Create Artifact X" → artifact) via EntityKindResolver.
    """
    storage = storage or Storage()
    engine = engine or EntityEngine()
    ref_ctx = ref_ctx or ReferenceContext()
    groups = WorkspaceGroups(storage, engine)
    reg = ToolRegistry()
    for tool in (
        # tasks
        ListTasksTool(user_id, storage, engine, typed_refs=typed_refs),
        FindTaskTool(user_id, storage, engine, typed_refs=typed_refs),
        CreateTaskTool(user_id, storage, engine, typed_refs=typed_refs),
        UpdateTaskTool(user_id, storage, engine, typed_refs=typed_refs),
        CompleteTaskTool(user_id, storage, engine, typed_refs=typed_refs),
        DeleteTaskTool(user_id, storage, engine, typed_refs=typed_refs),
        # habits
        CreateHabitTool(user_id, storage, engine, typed_refs=typed_refs),
        ListHabitsTool(user_id, storage, engine, typed_refs=typed_refs),
        CompleteHabitTool(user_id, storage, engine, typed_refs=typed_refs),
        # goals
        CreateGoalTool(user_id, storage, engine, typed_refs=typed_refs),
        ListGoalsTool(user_id, storage, engine, typed_refs=typed_refs),
        UpdateGoalProgressTool(user_id, storage, engine, typed_refs=typed_refs),
        UpdateGoalDeadlineTool(user_id, storage, engine, typed_refs=typed_refs),
        # entities (projection + M1 reference reuse)
        CreateEntityTool(user_id, storage, engine, groups, projection, ref_ctx,
                         typed_refs=typed_refs, user_text=user_text),
        GetEntityTool(user_id, storage, engine, groups, projection, ref_ctx,
                      typed_refs=typed_refs),
        UpdateEntityTool(user_id, storage, engine, groups, projection, ref_ctx,
                         typed_refs=typed_refs),
        ListEntitiesTool(user_id, storage, engine, groups, projection, ref_ctx,
                         typed_refs=typed_refs),
        FindEntityTool(user_id, storage, engine, groups, projection, ref_ctx,
                       typed_refs=typed_refs),
        # topic lifecycle (projection-driven, v15.2 M4 items 7/8/10)
        GetEntityTopicTool(user_id, storage, engine, groups, projection, ref_ctx,
                           typed_refs=typed_refs),
        EnsureEntityTopicTool(user_id, storage, engine, groups, projection,
                              ref_ctx, typed_refs=typed_refs),
        SetEntityTopicLockedTool(user_id, storage, engine, groups, projection,
                                 ref_ctx, typed_refs=typed_refs),
        DeleteEntityTopicTool(user_id, storage, engine, groups, projection,
                              ref_ctx, typed_refs=typed_refs),
        ListEntityTopicsTool(user_id, storage, engine, groups, projection,
                             ref_ctx, typed_refs=typed_refs),
        # workspace
        WsListTool(user_id, storage, engine, typed_refs=typed_refs),
        WsGetTool(user_id, storage, engine, typed_refs=typed_refs),
        WsOpenTool(user_id, storage, engine, typed_refs=typed_refs),
        WsInspectTool(user_id, storage, engine, typed_refs=typed_refs),
        # v15.3 M5: workspace lifecycle + entity delete + topic repair + equip
        # (Manual Control Plane + Lifecycle — same tools the manual UI uses)
        CreateWorkspaceTool(user_id, storage, engine, groups,
                            typed_refs=typed_refs),
        RenameWorkspaceTool(user_id, storage, engine, groups,
                            typed_refs=typed_refs),
        CloseWorkspaceTool(user_id, storage, engine, groups,
                           typed_refs=typed_refs),
        ArchiveWorkspaceTool(user_id, storage, engine, groups,
                             typed_refs=typed_refs),
        DeleteEntityTool(user_id, storage, engine, groups, projection, ref_ctx,
                         typed_refs=typed_refs),
        RepairTopicsTool(user_id, storage, engine, groups, projection, ref_ctx,
                         typed_refs=typed_refs),
        EquipItemTool(user_id, storage, engine, groups, projection, ref_ctx,
                      typed_refs=typed_refs),
        # memory / recall (read-only)
        GetMemoriesTool(user_id, storage, engine, typed_refs=typed_refs),
        SearchMemoriesTool(user_id, storage, engine, typed_refs=typed_refs),
        RecallTool(user_id, storage, engine, typed_refs=typed_refs),
    ):
        reg.register(tool)
    return reg
