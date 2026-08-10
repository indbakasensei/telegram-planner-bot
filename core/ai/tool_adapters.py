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
from core.workspace.groups_app import ENTITY_TYPE, WorkspaceGroups
from core.workspace.render import format_entity_card, format_entity_update
from date_parser import validate_datetime

__all__ = [
    "build_tool_registry",
    "CreateGoalTool", "CreateHabitTool", "CreateTaskTool", "CreateEntityTool",
    "DeleteTaskTool", "CompleteHabitTool", "CompleteTaskTool",
    "FindTaskTool", "FindEntityTool", "GetEntityTool", "GetMemoriesTool",
    "GetWorkspaceTool", "ListEntitiesTool", "ListGoalsTool", "ListHabitsTool",
    "ListTasksTool", "ListWorkspacesTool", "RecallTool", "SearchMemoriesTool",
    "UpdateEntityTool", "UpdateGoalProgressTool", "UpdateTaskTool",
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
    and is never a model-facing argument."""

    def __init__(self, user_id: int, storage: Storage | None = None,
                 engine: EntityEngine | None = None):
        self._uid = user_id
        self._s = storage or Storage()
        self._eng = engine or EntityEngine()

    def _err(self, message: str) -> ToolError:
        return _err(self.spec.name, message)

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
        result = self._s.goals.update_progress(goal_id, self._uid, delta)
        if result is None:
            raise self._err(
                f"goal [{goal_id}] not found or progress tracking unavailable.")
        new_progress, target, done = result
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Goal [{goal_id}] progress {new_progress}/{target}"
                   + (" — complete!" if done else "") + ".",
            data={"goal_id": goal_id, "progress": new_progress,
                  "target": target, "completed": done})


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
            raise self._err(
                "no active workspace — pass a 'workspace' name/#id or open "
                "one first.")
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
                "workspace": {"type": "string",
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
                "workspace": {"type": "string",
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
                "workspace": {"type": "string",
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
                 projection=None, ref_ctx=None):
        super().__init__(user_id, storage, engine)
        self._groups = groups or WorkspaceGroups(self._s, self._eng)
        self._projection = projection
        self._ref_ctx = ref_ctx or ReferenceContext()
        self._resolver = ReferenceResolver(self._s, self._eng, self._ref_ctx)

    def _entities(self, ws_id):
        return list(self._eng.list_milestones(self._uid, ws_id))

    def _resolve_entity(self, ws_id, ref):
        """M1 resolver first (pronoun/ordinal/deictic against conversation
        context), then a thin name match mirroring EntityManager._find_entity.
        Returns (milestone | None, entities)."""
        ref = (ref or "").strip()
        entities = self._entities(ws_id)
        if not ref:
            return None, entities
        res = self._resolver.resolve(self._uid, ref, ws_id, entities)
        if res.kind == "entity" and res.entity is not None:
            return res.entity, entities
        return self._name_match(ref, entities), entities

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

    @staticmethod
    def _entity_dict(m, workspace_id, workspace_title=None):
        return {"entity_id": m.id, "title": m.title,
                "workspace_id": workspace_id, "workspace_title": workspace_title,
                "status": m.status, "progress": m.progress, "fields": m.fields}


class CreateEntityTool(_EntityTool):
    @property
    def spec(self):
        return ToolSpec(
            "create_entity",
            "Create a workspace entity (goes through the same single "
            "entity+topic contract /add and NL creation use: the entity is "
            "created, its Telegram topic ensured if a projection is wired, "
            "and it becomes the active entity). Set fields afterwards with "
            "update_entity.",
            {"type": "object", "properties": {
                "name": {"type": "string", "minLength": 1},
                "workspace": {"type": "string",
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"}},
             "required": ["name"]},
            risk=RiskLevel.MUTATING)

    def run(self, name, workspace=None, **kwargs) -> ToolResult:
        ws_id = self._require_workspace(workspace)
        for m in self._entities(ws_id):
            if m.title.lower() == name.lower():
                raise self._err(
                    f"entity {name!r} already exists in workspace #{ws_id}.")
        m, topic_id = self._groups.create_entity(
            self._uid, ws_id, name, self._projection)
        self._note_mention(ws_id, m)
        ws = self._eng.get_workspace_or_none(self._uid, ws_id)
        topic_note = (" · Telegram topic created"
                      if topic_id else " · no topic (projection not wired)")
        return ToolResult(
            tool=self.spec.name, ok=True,
            output=f"Created entity {name!r} (id {m.id}) in #{ws_id}"
                   f"{topic_note}.",
            data={"entity_id": m.id, "title": m.title,
                  "workspace_id": ws_id,
                  "workspace_title": ws.title if ws else None,
                  "status": m.status, "topic_id": topic_id,
                  "topic_created": topic_id is not None})


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
                "workspace": {"type": "string",
                              "description": "workspace name or #id (defaults "
                                             "to the active one)"}},
             "required": ["entity"]},
            risk=RiskLevel.READ_ONLY)

    def run(self, entity, workspace=None, **kwargs) -> ToolResult:
        ws_id = self._require_workspace(workspace)
        m, _ = self._resolve_entity(ws_id, entity)
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
                "workspace": {"type": "string"},
                "fields": {"type": "object"}},
             "required": ["entity", "fields"]},
            risk=RiskLevel.MUTATING)

    def run(self, entity, fields, workspace=None, **kwargs) -> ToolResult:
        if not isinstance(fields, dict) or not fields:
            raise self._err("'fields' must be a non-empty object.")
        ws_id = self._require_workspace(workspace)
        target, _ = self._resolve_entity(ws_id, entity)
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
    @property
    def spec(self):
        return ToolSpec(
            "list_entities",
            "List entities in a workspace, optionally filtered by status "
            "(todo/in_progress/done/blocked). Omit status for all.",
            {"type": "object", "properties": {
                "status": {"type": "string", "enum": list(_ENTITY_STATUSES)},
                "workspace": {"type": "string"}},
             "required": []},
            risk=RiskLevel.READ_ONLY)

    def run(self, status=None, workspace=None, **kwargs) -> ToolResult:
        ws_id = self._require_workspace(workspace)
        ws = self._eng.get_workspace_or_none(self._uid, ws_id)
        entities = self._entities(ws_id)
        if status:
            entities = [m for m in entities if m.status == status]
        data = [self._entity_dict(m, ws_id, ws.title if ws else None)
                for m in entities]
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output="No entities.", data=[])
        lines = [f"[{d['entity_id']}] {d['title']} — {d['status']}"
                 for d in data]
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"{len(data)} entity(ies):\n"
                                 + "\n".join(lines), data=data)


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
                "workspace": {"type": "string"}},
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
        if not data:
            return ToolResult(tool=self.spec.name, ok=True,
                              output=f"No entities match {query!r}.", data=[])
        lines = [f"[{d['entity_id']}] {d['title']}" for d in data]
        return ToolResult(tool=self.spec.name, ok=True,
                          output=f"Matched {len(data)} entity(ies):\n"
                                 + "\n".join(lines), data=data)


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

    def __init__(self, user_id, storage=None, engine=None):
        super().__init__(user_id, storage, engine)
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


# ── registry builder ──────────────────────────────────────────────────────
def build_tool_registry(user_id: int,
                        storage: Storage | None = None,
                        engine: EntityEngine | None = None,
                        projection=None,
                        ref_ctx: ReferenceContext | None = None) -> ToolRegistry:
    """Build a per-user registry of every M3 real adapter.

    `projection` (a TelegramProjection or duck-typed equivalent) is injected
    by a live caller so entity create/update project to Telegram through the
    alpha.13 contract; default None means no projection (offline tests, or a
    caller that has not wired a live client yet). `ref_ctx` lets tests share
    one M1 conversation context across registries; a fresh one is built
    otherwise. Active-workspace state is read from the DB-backed
    tg_active_context at call time -- the same source /use and /add use.
    """
    storage = storage or Storage()
    engine = engine or EntityEngine()
    ref_ctx = ref_ctx or ReferenceContext()
    groups = WorkspaceGroups(storage, engine)
    reg = ToolRegistry()
    for tool in (
        # tasks
        ListTasksTool(user_id, storage, engine),
        FindTaskTool(user_id, storage, engine),
        CreateTaskTool(user_id, storage, engine),
        UpdateTaskTool(user_id, storage, engine),
        CompleteTaskTool(user_id, storage, engine),
        DeleteTaskTool(user_id, storage, engine),
        # habits
        CreateHabitTool(user_id, storage, engine),
        ListHabitsTool(user_id, storage, engine),
        CompleteHabitTool(user_id, storage, engine),
        # goals
        CreateGoalTool(user_id, storage, engine),
        ListGoalsTool(user_id, storage, engine),
        UpdateGoalProgressTool(user_id, storage, engine),
        # entities (projection + M1 reference reuse)
        CreateEntityTool(user_id, storage, engine, groups, projection, ref_ctx),
        GetEntityTool(user_id, storage, engine, groups, projection, ref_ctx),
        UpdateEntityTool(user_id, storage, engine, groups, projection, ref_ctx),
        ListEntitiesTool(user_id, storage, engine, groups, projection, ref_ctx),
        FindEntityTool(user_id, storage, engine, groups, projection, ref_ctx),
        # workspace
        WsListTool(user_id, storage, engine),
        WsGetTool(user_id, storage, engine),
        WsOpenTool(user_id, storage, engine),
        WsInspectTool(user_id, storage, engine),
        # memory / recall (read-only)
        GetMemoriesTool(user_id, storage, engine),
        SearchMemoriesTool(user_id, storage, engine),
        RecallTool(user_id, storage, engine),
    ):
        reg.register(tool)
    return reg
