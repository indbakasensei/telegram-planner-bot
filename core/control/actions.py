"""
core/control/actions.py -- the ONE shared confirmation flow (M5-F).

Every destructive / data-entry action in the Manual Control Plane routes
through `begin_confirm`: the question wording comes from the tool spec's
`confirmation_message`, the danger flag from the spec's RiskLevel, and the
execution is `registry.execute` -- there is no per-feature confirmation
logic anywhere else.

Pending confirms live in a small per-user module dict (in-memory only; a
confirm that never resolves is simply absent -- the router shows the fresh
page instead). `confirm_yes` executes the pending tool and renders its
ToolResult; `confirm_no` discards it and redraws the page the user came
from. The return-page redraw is delegated through a `render_target`
callable supplied by the router, so this module never imports it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import ui_components as uic
from fmt import code, esc

from core.ai.tools import RiskLevel
from core.control.registry import (
    ControlContext,
    build_control_registry,
    execute_tool_async,
)

_ICON = "dev"

# per-user pending confirmation (M5-F single store)
@dataclass(frozen=True, slots=True)
class PendingConfirm:
    tool: str
    arguments: dict
    return_to: str
    question: str
    danger: bool


_PENDING: dict[int, PendingConfirm] = {}


def pending_for(user_id: int) -> PendingConfirm | None:
    """The user's pending confirmation, or None (caller keeps it in the
    store; `confirm_yes`/`confirm_no` pop it)."""
    return _PENDING.get(user_id)


def begin_confirm(ctx: ControlContext, tool: str, arguments: dict,
                  return_to: str, question: str | None = None,
                  danger: bool | None = None) -> tuple[str, object]:
    """Start M5-F for `tool`: capture the spec's confirmation wording,
    store the pending confirm, and render the shared confirm dialog.

    `question`/`danger` override the spec (used by data-entry confirms like
    create/rename/add/edit whose tool spec has no confirmation_message); the
    defaults come from the tool spec so destructive tools always read as
    destructive."""
    # Spec lookup never needs a live projection — build the registry without
    # one so the confirm dialog stays cheap and offline-safe.
    reg = build_control_registry(ctx.with_projection(None))
    spec = next((s for s in reg.specs() if s.name == tool), None)
    if spec is None:
        text = uic.render_page(
            uic.render_header(_ICON, "Unknown tool", ["Control"]),
            uic.render_section("Confirm",
                               uic.render_error(f"No tool named {esc(tool)}.")))
        kb = uic.keyboard(uic.nav_row("ctl:home", "ctl:home"))
        return text, kb
    danger = spec.risk is RiskLevel.DESTRUCTIVE if danger is None else danger
    question = question or spec.confirmation_message or f"Run {tool}?"
    _PENDING[ctx.user_id] = PendingConfirm(
        tool=tool, arguments=dict(arguments or {}),
        return_to=return_to, question=question, danger=danger)
    preview = _preview_arguments(tool, arguments or {})
    text = uic.render_page(
        uic.render_header(_ICON, "Confirm", ["Control", "Confirm"]),
        uic.render_section("Action",
                           uic.render_confirmation(question, preview,
                                                   danger=danger)),
        footer=uic.render_footer(
            "Executes the same tool the AI Worker uses — one shared path"))
    kb = uic.keyboard(uic.confirmation_row(
        "ctl:confirm:no", "✅ Yes, run it", "ctl:confirm:yes"))
    return text, kb


async def confirm_yes(ctx: ControlContext,
                      render_target: Callable[[str], tuple[str, object]]):
    """[Confirm]: execute the pending tool via the registry's sanctioned
    path (projection resolved on the loop, execution in a worker thread) and
    render its ToolResult, with a nav back to where the flow started."""
    pending = _PENDING.pop(ctx.user_id, None)
    if pending is None:
        return _nothing_pending()
    result = await execute_tool_async(ctx, pending.tool, pending.arguments)
    return render_result(result, pending.return_to)


async def confirm_no(ctx: ControlContext,
                     render_target: Callable[[str], tuple[str, object]]):
    """[Cancel]: discard the pending confirm and redraw the prior page."""
    pending = _PENDING.pop(ctx.user_id, None)
    if pending is None:
        return _nothing_pending()
    return render_target(pending.return_to)


def cancel_all(user_id: int) -> None:
    """Drop any stale pending confirm (used by /control entry + gather)."""
    _PENDING.pop(user_id, None)


def _nothing_pending() -> tuple[str, object]:
    text = uic.render_page(
        uic.render_header(_ICON, "Nothing to confirm", ["Control"]),
        uic.render_section("Confirm",
                           uic.render_info("No pending action.", "Open the "
                                           "Control Plane and try again.")))
    kb = uic.keyboard(uic.nav_row("ctl:home", "ctl:home"))
    return text, kb


def _preview_arguments(tool: str, args: dict) -> str:
    """Compact human-readable preview of the arguments (escaped HTML)."""
    if not args:
        return f"<code>{esc(tool)}</code> with no arguments."
    lines = []
    for key, value in args.items():
        lines.append(f"{esc(str(key))}: {code(str(value))}")
    return "\n".join(lines)


def render_result(result, return_to: str) -> tuple[str, object]:
    """Render a ToolResult as a control-plane result page with a nav back to
    `return_to` (used by confirm_yes and every immediate-mutation handler)."""
    if result.ok:
        section = uic.render_section(
            "Result",
            uic.render_success("Done",
                               (result.output or "")[:200] or None))
    else:
        detail = result.output or result.error_code or "unknown error"
        section = uic.render_section(
            "Result", uic.render_error("Action failed", str(detail)[:200]))
    text = uic.render_page(
        uic.render_header(_ICON, "Result", ["Control", "Result"]),
        section)
    kb = uic.keyboard(uic.nav_row(return_to, None, "ctl:home"))
    return text, kb
