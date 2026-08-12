"""
core/control/registry.py -- the Manual Control Plane's execution seam.

The control plane never writes the DB or Telegram directly. Every mutation
executes through the SAME ToolRegistry the AI Worker uses (layering: AI
Worker → Manual Control Plane → ToolRegistry → domain services → DB /
Telegram projection). This module builds that registry and runs a tool to
completion -- the one sanctioned execution path, identical to main.py's
`worker_confirm`.

A `ControlContext` bundles the per-invocation services (storage / engine /
groups) plus a lazy `projection_factory` so live callbacks can build a
Telegram projection at execution time while offline tests inject nothing
(topic/equip/repair tools then answer with a graceful no-projection refusal).

THREADING CONTRACT: a live projection is built from `asyncio.get_running_loop()`
(see main._ws_projection), so it MUST be resolved in the async context, never
inside the worker thread. `execute_tool_async` therefore resolves the
projection FIRST (still on the loop), bakes it into the context via
`with_projection`, and only then hands the rest to `asyncio.to_thread`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable

from core.storage import Storage
from core.workspace.engine import EntityEngine
from core.workspace.groups_app import WorkspaceGroups


@dataclass(frozen=True, slots=True)
class ControlContext:
    """Everything one control-plane interaction needs.

    `projection_factory` is a zero-arg callable returning a live
    TelegramProjection (or duck-typed equivalent), wired by main.py as
    `lambda: _ws_projection(context)`; None means "offline / not wired" —
    tools that need a projection refuse gracefully instead of raising.
    `_projection` is the pre-resolved projection (see `with_projection`);
    when set it wins over the factory, so a factory that needs a running
    loop can be resolved in the async context and frozen before a thread
    runs the tool.
    """

    user_id: int
    storage: Storage
    engine: EntityEngine
    groups: WorkspaceGroups
    projection_factory: Callable[[], object] | None = None
    _projection: object | None = None

    def projection(self):
        """A live projection for THIS invocation. Returns the pre-resolved
        projection if one was frozen in; else builds it from the factory
        (call this on the event loop, never inside a worker thread)."""
        if self._projection is not None:
            return self._projection
        if self.projection_factory is None:
            return None
        return self.projection_factory()

    def with_projection(self, projection):
        """A copy of this context with a specific projection frozen in
        (and the factory cleared), so execution can run in a thread."""
        return ControlContext(self.user_id, self.storage, self.engine,
                              self.groups, None, projection)


def build_context(user_id, storage=None, engine=None, groups=None,
                  projection_factory=None) -> ControlContext:
    """Assemble a ControlContext, defaulting storage/engine/groups so an
    offline test can pass a temp-DB Storage and nothing else."""
    storage = storage or Storage()
    engine = engine or EntityEngine()
    groups = groups or WorkspaceGroups(storage, engine)
    return ControlContext(user_id, storage, engine, groups, projection_factory)


def build_control_registry(ctx: ControlContext):
    """A fresh per-user registry bound to this invocation's projection.

    Built per execution (like worker_confirm) so state is never stale and a
    live projection is only created when one is wired. Offline callers pass
    a context with `projection_factory=None` -- the registry is still fully
    buildable and read/mutating-non-Telegram tools work normally."""
    from core.ai.tool_adapters import build_tool_registry
    # ctx.projection() already handles every case: a pre-resolved frozen
    # projection (with_projection), a live factory build, or None when not
    # wired. Checking projection_factory instead would DROP a frozen
    # projection (factory cleared by with_projection) and make every
    # topic/repair/equip tool report "not wired" on the async path.
    projection = ctx.projection()
    return build_tool_registry(
        ctx.user_id, storage=ctx.storage, engine=ctx.engine,
        projection=projection)


def execute_tool(ctx: ControlContext, name: str, arguments: dict | None = None):
    """Run one tool to completion -- THE mutation path of the control plane.

    Synchronous `ToolRegistry.execute` (contains every failure in a
    ToolResult, never raises). Callers in async handlers should wrap this in
    `asyncio.to_thread` so projection-bridged Telegram I/O never blocks the
    loop (same as the Worker's `asyncio.to_thread` usage)."""
    reg = build_control_registry(ctx)
    return reg.execute(name, arguments or {})


def execute_tool_async(ctx: ControlContext, name: str, arguments: dict | None = None):
    """asyncio wrapper for execute_tool: resolve the projection on the event
    loop FIRST (a live projection needs the running loop), freeze it into the
    context, then run the tool in a worker thread."""
    projection = ctx.projection()
    exec_ctx = ctx.with_projection(projection)
    return asyncio.to_thread(execute_tool, exec_ctx, name, arguments or {})
