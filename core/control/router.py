"""
core/control/router.py -- /control entry, `ctl:` callback routing, data entry.

Everything routes on the `ctl:` namespace (registered in main.handle_callback
next to `dash`): page targets redraw a renderer; action targets execute a
ToolRegistry tool (immediately for safe mutations, through the ONE shared
M5-F confirm flow for destructive / data-entry ones); `ctl:confirm:yes|no`
resolves the pending confirm. Data entry (Create/Rename/Add/Edit) reuses
conversation_state.set_gathering/get_gathering with a `partial_data["_ctl"]`
marker; main.py's gathering branch hands those messages back here before any
AI parsing.

This module NEVER writes the DB or Telegram itself: pages render domain
state, and every mutation goes through `execute_tool_async` → the same
ToolRegistry the Worker uses (the no-second-logic rule).
"""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

import ui_components as uic
from fmt import esc

from conversation_state import clear_state, set_gathering
from notification_service import safe_answer_callback_query, safe_edit_message_text

from core.ai.entity_kinds import (
    EntityKindResolver,
    KIND_ARTIFACT,
    KIND_CHARACTER,
    KIND_ENTITY,
    KIND_WEAPON,
)
from core.control import pages
from core.control.actions import (
    begin_confirm,
    cancel_all,
    confirm_no,
    confirm_yes,
    render_result,
)
from core.control.registry import (
    ControlContext,
    build_context,
    execute_tool_async,
)
from core.workspace.groups_app import ENTITY_TYPE, KIND_TEMPLATE
from core.workspace.templates.registry import (
    entity_field_specs,
    normalize_entity_fields,
    validate_entity_fields,
)

logger = logging.getLogger(__name__)

_ICON = "dev"

_VALID_ADD_KINDS = (KIND_CHARACTER, KIND_WEAPON, KIND_ARTIFACT, KIND_ENTITY)

# ── page targets ──────────────────────────────────────────────────────────

def _route_page(ctx: ControlContext, parts):
    """Pure page target renderer. `parts` includes 'ctl' at index 0; returns
    (text, keyboard). Never mutates anything."""
    p = parts[1:]
    if not p or p[0] == "home":
        return pages.control_home(ctx)
    if p[0] == "ws":
        if len(p) == 1 or p[1] == "home":
            return pages.workspace_page(ctx)
        if len(p) >= 4 and p[1] == "home" and p[2] == "p":
            return pages.workspace_page(ctx, page=_int_or(p[3], 1))
        if p[1] == "detail":
            return pages.workspace_detail(ctx, _int_or(p[2], 0))
        if p[1] == "inspect":
            return pages.workspace_inspect(ctx, _int_or(p[2], 0))
    if p[0] == "ent":
        if len(p) == 1 or (p[1] == "list" and len(p) == 2):
            return pages.entity_hub(ctx)
        if p[1] == "list":
            kind = p[2] if len(p) > 2 else "all"
            if len(p) >= 5 and p[3] == "p":
                return pages.entity_list(ctx, kind, page=_int_or(p[4], 1))
            return pages.entity_list(ctx, kind)
        if p[1] == "view":
            return pages.entity_detail(ctx, _int_or(p[2], 0))
    if p[0] == "topic":
        if len(p) == 1 or p[1] == "home":
            return pages.topic_center(ctx)
        if len(p) >= 4 and p[1] == "home" and p[2] == "p":
            return pages.topic_center(ctx, page=_int_or(p[3], 1))
        if p[1] == "view":
            return pages.topic_detail(ctx, _int_or(p[2], 0))
    if p[0] == "ident":
        if len(p) > 1 and p[1] != "active":
            return pages.identity_inspector(ctx, _int_or(p[1], 0))
        return pages.identity_inspector(ctx, None)
    if p[0] == "eq":
        if len(p) == 1 or p[1] == "home":
            return pages.equip_home(ctx)
        if len(p) >= 4 and p[1] == "home" and p[2] == "p":
            return pages.equip_home(ctx, page=_int_or(p[3], 1))
        if p[1] == "pick":
            return pages.equip_pick(ctx, _int_or(p[2], 0))
    return pages.control_home(ctx)


def _target(ctx: ControlContext, target: str):
    """Render a full `ctl:` target string to (text, keyboard)."""
    return _route_page(ctx, target.split(":"))


def _int_or(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _error_page(message: str):
    text = uic.render_page(
        uic.render_header(_ICON, "Control Plane error", ["Control"]),
        uic.render_section("Error", uic.render_error(message)))
    kb = uic.keyboard(uic.nav_row("ctl:home", "ctl:home"))
    return text, kb


def _no_workspace_page():
    body, kb = pages._no_active_section("ctl:ws:home")
    return uic.render_page(
        uic.render_header(_ICON, "Control Plane", ["Control"]), body), kb


# ── callback dispatch ─────────────────────────────────────────────────────

async def route_control_callback(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 parts, ctx: ControlContext | None = None):
    """Handle a `ctl:` callback query. `parts` is main.py's `data.split(":")`
    (index 0 == 'ctl'). Resolves a ControlContext (or uses the injected one),
    dispatches, and edits the message in place."""
    query = update.callback_query
    user_id = query.from_user.id if query else (update.effective_user.id
                                                if update.effective_user else 0)
    ctx = ctx or build_context(user_id)
    try:
        text, kb = await _dispatch(ctx, parts)
    except Exception as exc:  # never let a control callback crash the bot
        logger.exception("control callback dispatch failed for %r", parts)
        text, kb = _error_page(f"{type(exc).__name__}: {exc}")
    await safe_answer_callback_query(query)
    await safe_edit_message_text(query, text, parse_mode="HTML",
                                 reply_markup=kb)


async def _dispatch(ctx: ControlContext, parts):
    """Dispatch a ctl: callback to a page, an immediate mutation, a confirm,
    or a gather start. Returns (text, keyboard)."""
    p = parts[1:]
    if not p:
        return pages.control_home(ctx)
    render_target = lambda target: _target(ctx, target)  # noqa: E731

    # M5-F shared confirm resolution
    if p[0] == "confirm":
        if len(p) > 1 and p[1] == "yes":
            return await confirm_yes(ctx, render_target)
        return await confirm_no(ctx, render_target)

    # ── workspace actions
    if p[0] == "ws":
        if p[1] == "home":
            return pages.workspace_page(ctx)
        if p[1] == "create":
            return _begin_gather(ctx, p, "create_workspace", {"_ctl": "create_workspace"}, ["title"],
                                 "Send the new workspace's title and kind — "
                                 "e.g. <code>My Game | game</code> "
                                 "(game / project / goal / workspace).")
        if p[1] == "rename" and len(p) >= 3:
            ws_id = _int_or(p[2], 0)
            return _begin_gather(ctx, p, "rename_workspace",
                                 {"_ctl": "rename_workspace", "workspace": ws_id},
                                 ["title"],
                                 f"Send the new title for workspace #{ws_id}.")
        if p[1] == "archive" and len(p) >= 3:
            ws_id = _int_or(p[2], 0)
            return begin_confirm(ctx, "archive_workspace",
                                 {"workspace": ws_id},
                                 return_to="ctl:ws:home")
        if p[1] == "open" and len(p) >= 3:
            ws_id = _int_or(p[2], 0)
            return await _run_immediate(ctx, "open_workspace",
                                        {"workspace": ws_id},
                                        f"ctl:ws:detail:{ws_id}")
        if p[1] == "close" and len(p) >= 3:
            await _run_immediate(ctx, "close_workspace", {},
                                 "ctl:ws:home")
            return pages.workspace_page(ctx)
        return _route_page(ctx, parts)

    # ── entity actions
    if p[0] == "ent":
        if p[1] == "add":
            kind = p[2] if len(p) >= 3 and p[2] in _VALID_ADD_KINDS else ""
            return _begin_gather(ctx, p, "add_entity",
                                 {"_ctl": "add_entity", "entity_type": kind},
                                 ["name"],
                                 "Send the new entity's name." + (f" It will be "
                                 f"added as a <b>{kind}</b>." if kind else ""))
        if p[1] == "del" and len(p) >= 3:
            eid = _int_or(p[2], 0)
            m, ws = pages.find_entity(ctx, eid)
            if m is None or ws is None:
                return _no_workspace_page() if ws is None \
                    else pages._missing_entity_page("entity")
            return begin_confirm(ctx, "delete_entity",
                                 {"entity": str(eid), "workspace": ws.id},
                                 return_to=f"ctl:ent:list:{_kind_or_entity(m)}")
        if p[1] == "edit" and len(p) >= 3:
            eid = _int_or(p[2], 0)
            m, ws = pages.find_entity(ctx, eid)
            if m is None:
                return pages._missing_entity_page("entity")
            fields = _schema_hint(m, ws)
            return _begin_gather(ctx, p, "edit_entity",
                                 {"_ctl": "edit_entity", "entity": eid},
                                 ["fields"],
                                 f"Send fields for <b>{esc(m.title)}</b> as "
                                 f"<code>name=value</code> lines.{fields}")
        return _route_page(ctx, parts)

    # ── topic actions
    if p[0] == "topic":
        if p[1] == "repair":
            return begin_confirm(
                ctx, "repair_topics", {}, return_to="ctl:topic:home",
                question=("Repair every entity→topic across linked "
                          "workspaces? Idempotent: creates only missing "
                          "topics, collapses title-duplicates onto one "
                          "canonical topic, preserves locks."))
        if len(p) >= 3:
            eid = _int_or(p[2], 0)
            m, ws = pages.find_entity(ctx, eid)
            if m is None or ws is None:
                return _no_workspace_page() if ws is None \
                    else pages._missing_entity_page("entity")
            if p[1] == "ensure":
                return await _run_immediate(
                    ctx, "ensure_entity_topic",
                    {"entity": str(eid), "workspace": ws.id},
                    f"ctl:topic:view:{eid}")
            if p[1] == "lock":
                return await _run_immediate(
                    ctx, "set_entity_topic_locked",
                    {"entity": str(eid), "workspace": ws.id, "locked": True},
                    f"ctl:topic:view:{eid}")
            if p[1] == "unlock":
                return await _run_immediate(
                    ctx, "set_entity_topic_locked",
                    {"entity": str(eid), "workspace": ws.id, "locked": False},
                    f"ctl:topic:view:{eid}")
            if p[1] == "del":
                return _topic_delete_dialog(ctx, m, ws)
            if p[1] == "force":
                return begin_confirm(
                    ctx, "delete_entity_topic",
                    {"entity": str(eid), "workspace": ws.id, "force": True},
                    return_to=f"ctl:topic:view:{eid}")
        return _route_page(ctx, parts)

    # ── equipment actions
    if p[0] == "eq":
        if p[1] == "set" and len(p) >= 4:
            char_id, item_id = _int_or(p[2], 0), _int_or(p[3], 0)
            _m, ws = pages.find_entity(ctx, char_id)
            if ws is None:
                return _no_workspace_page()
            return await _run_immediate(
                ctx, "equip_item",
                {"character": str(char_id), "item": str(item_id),
                 "workspace": ws.id},
                f"ctl:eq:pick:{char_id}")
        if p[1] == "unequip" and len(p) >= 3:
            char_id = _int_or(p[2], 0)
            _m, ws = pages.find_entity(ctx, char_id)
            if ws is None:
                return _no_workspace_page()
            return await _run_immediate(
                ctx, "equip_item",
                {"character": str(char_id), "workspace": ws.id},
                f"ctl:eq:pick:{char_id}")
        return _route_page(ctx, parts)

    return _route_page(ctx, parts)


async def _run_immediate(ctx, tool: str, args: dict, return_to: str):
    """Execute a safe mutation via the shared ToolRegistry path and render
    its result page (nav back to `return_to`)."""
    result = await execute_tool_async(ctx, tool, args)
    return render_result(result, return_to)


def _kind_or_entity(m) -> str:
    return (m.entity_type or KIND_ENTITY).lower()


def _schema_hint(m, ws) -> str:
    """A one-line schema hint for the Edit gather (generic — never
    domain-hardcoded)."""
    specs = entity_field_specs(ws.template)
    names = [s.name for s in specs if s.name not in ("level", "priority")]
    if not names:
        return ""
    sample = "weapon=Festering Desire, level=80" if "weapon" in names \
        else f"{names[0]}=value"
    return f" Example: <code>{sample}</code>."


def _topic_delete_dialog(ctx, m, ws):
    """M5-C locked-topic delete: when the topic is LOCKED the user gets
    [Unlock] [Force delete] [Cancel] instead of a plain confirm."""
    eid = m.id
    linked = ctx.storage.tg_bindings.get_binding(ws.id) is not None
    topic_id = (ctx.storage.tg_bindings.get_workspace_entity_topic(
        ws.id, ENTITY_TYPE, eid) if linked else None)
    locked = (ctx.storage.tg_bindings.get_entity_topic_locked(
        ws.id, ENTITY_TYPE, eid) if linked else False)
    if not locked:
        return begin_confirm(ctx, "delete_entity_topic",
                             {"entity": str(eid), "workspace": ws.id},
                             return_to=f"ctl:topic:view:{eid}")
    text = uic.render_page(
        uic.render_header(_ICON, "Delete topic", ["Control", "Topics", m.title]),
        uic.render_section(
            "Locked topic",
            uic.render_confirmation(
                f"Topic #{topic_id} is LOCKED.",
                f"Entity <b>{esc(m.title)}</b> (#{eid}) — the topic is "
                "protected against accidental deletion. Unlock it first, or "
                "force-delete the topic (the entity stays).",
                danger=True)),
        footer=uic.render_footer("Delete removes ONLY the topic — never the "
                                 "DB entity"))
    kb = uic.keyboard(
        uic.action_row(("🔓 Unlock", f"ctl:topic:unlock:{eid}"),
                       ("💥 Force delete", f"ctl:topic:force:{eid}")),
        uic.nav_row(f"ctl:topic:view:{eid}", None, "ctl:home"))
    return text, kb


# ── data entry (M5-F) ─────────────────────────────────────────────────────

def _begin_gather(ctx, parts, marker, partial, missing, prompt):
    """Start a control-plane gather: store the _ctl-marked partial and
    return the prompt page (the caller edits the message with it). The
    prompt is pre-built HTML (controlled content, user text already
    escaped) so it renders inline."""
    user_id = ctx.user_id
    clear_state(user_id)
    set_gathering(user_id, partial, missing)
    body = (uic.render_info("Enter the details below") + "\n"
            + uic.blockquote(prompt, escape=False))
    text = uic.render_page(
        uic.render_header(_ICON, "Enter data", ["Control"]),
        uic.render_section("New input", body),
        footer=uic.render_footer("Answer with a text message; send /control "
                                 "to cancel"))
    kb = uic.keyboard(uic.nav_row("ctl:home", "ctl:home"))
    return text, kb


async def route_control_gathering(update: Update, context, partial, missing,
                                  ctx: ControlContext):
    """Handle a text answer for an in-progress control-plane gather. Called
    by main.py's gathering branch when `partial_data["_ctl"]` is set. Returns
    (reply_text, keyboard) for the handler to send."""
    user_id = ctx.user_id
    text = (update.message.text or "").strip() if update.message else ""
    kind = partial.get("_ctl")
    if kind == "create_workspace":
        return await _gather_create_workspace(update, user_id, ctx, text)
    if kind == "rename_workspace":
        return await _gather_rename_workspace(update, user_id, ctx, partial, text)
    if kind == "add_entity":
        return await _gather_add_entity(update, user_id, ctx, partial, text)
    if kind == "edit_entity":
        return await _gather_edit_entity(update, user_id, ctx, partial, text)
    clear_state(user_id)
    return _reply(update, "❓ That control flow is no longer active.",
                  nav="ctl:home")


async def _gather_create_workspace(update, user_id, ctx, text):
    title, template = _split_title_kind(text)
    if template is not None and template not in KIND_TEMPLATE:
        clear_state(user_id)
        return _reply(update,
                      f"Unknown workspace kind <code>{esc(template)}</code> — "
                      "use game, project, goal, or workspace.")
    if not title:
        clear_state(user_id)
        return _reply(update, "No title — send <code>My Game | game</code>.")
    clear_state(user_id)
    return begin_confirm(ctx, "create_workspace",
                         {"title": title, "template": template or "game"},
                         return_to="ctl:ws:home",
                         question=f"Create a {template or 'game'} workspace "
                                  f"named <b>{esc(title)}</b> and make it "
                                  "active?")


async def _gather_rename_workspace(update, user_id, ctx, partial, text):
    ws_id = int(partial.get("workspace") or 0)
    if not text:
        clear_state(user_id)
        return _reply(update, "No title — send the new workspace title.")
    clear_state(user_id)
    return begin_confirm(ctx, "rename_workspace",
                         {"workspace": ws_id, "title": text},
                         return_to=f"ctl:ws:detail:{ws_id}",
                         question=f"Rename workspace #{ws_id} to "
                                  f"<b>{esc(text)}</b>?")


async def _gather_add_entity(update, user_id, ctx, partial, text):
    preset = (partial.get("entity_type") or "").strip().lower()
    if not text:
        clear_state(user_id)
        return _reply(update, "No name — send the entity name.")
    ws_id = _active_ws_id(ctx)
    if ws_id is None:
        clear_state(user_id)
        return _reply(update, "No workspace active — open one first.",
                      nav="ctl:ws:home")
    kind, conflict = _resolve_add_kind(ctx, text, preset)
    if conflict:
        clear_state(user_id)
        return _reply(update, conflict, nav=f"ctl:ent:list:{preset or 'all'}")
    clear_state(user_id)
    return begin_confirm(ctx, "create_entity",
                         {"name": text, "entity_type": kind,
                          "workspace": ws_id},
                         return_to=f"ctl:ent:list:{kind}",
                         question=f"Add <b>{esc(text)}</b> to workspace "
                                  f"#{ws_id} as a <b>{kind}</b>?")


async def _gather_edit_entity(update, user_id, ctx, partial, text):
    eid = int(partial.get("entity") or 0)
    m, ws = pages.find_entity(ctx, eid)
    if m is None:
        clear_state(user_id)
        return _reply(update, "Entity not found.", nav="ctl:ent:list")
    fields = _parse_kv_lines(text)
    if not fields:
        clear_state(user_id)
        return _reply(update,
                      "No <code>name=value</code> pairs found — send e.g. "
                      "<code>weapon=Festering Desire, level=80</code>.")
    errors = validate_entity_fields(ws.template, fields)
    if errors:
        clear_state(user_id)
        return _reply(update, "Validation failed:\n• " + "\n• ".join(
            esc(e) for e in errors))
    clear_state(user_id)
    fields_norm = normalize_entity_fields(ws.template, fields)
    return begin_confirm(ctx, "update_entity",
                         {"entity": str(eid), "workspace": ws.id,
                          "fields": fields_norm},
                         return_to=f"ctl:ent:view:{eid}",
                         question=f"Apply these edits to <b>{esc(m.title)}</b>?")


def _reply(update, text_html: str, nav: str | None = None):
    """A plain text-page result: the HTML message plus a keyboard that just
    navigates back (or to `nav`). Returns (text, keyboard)."""
    if nav is None:
        nav = "ctl:home"
    text = uic.render_page(
        uic.render_header(_ICON, "Control Plane", ["Control"]),
        uic.render_section("Note", text_html))
    kb = uic.keyboard(uic.nav_row("ctl:home", None, nav))
    return text, kb


def _split_title_kind(text: str):
    """Parse 'Title' or 'Title | kind' (also 'Title|kind'). Returns
    (title, template|None)."""
    if "|" in text:
        title, _, template = text.partition("|")
        return title.strip(), template.strip().lower() or None
    return text.strip(), None


def _parse_kv_lines(text: str) -> dict:
    """Parse 'k=v' / 'k: v' pairs separated by newlines, commas, or
    semicolons into a fields dict (string values)."""
    fields = {}
    for chunk in re.split(r"[\n,;]+", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*(.+)$", chunk)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields


def _resolve_add_kind(ctx, name: str, preset: str):
    """Deterministic kind for the Add flow. `preset` is the page's kind (or
    '' on the generic Add). An explicit/DB kind already claimed by the name
    wins (M4 resolver priority); when it CONFLICTS with the page preset we
    refuse with a diagnostic instead of silently creating the wrong kind.
    Returns (kind, conflict_message|None)."""
    ws_id = _active_ws_id(ctx)
    rows = ctx.engine.list_milestones(ctx.user_id, ws_id) if ws_id else []
    resolved = EntityKindResolver().resolve_for_create(None, name, rows)
    if resolved is not None and resolved.kind not in (None, KIND_ENTITY):
        if preset and resolved.kind != preset:
            return (None,
                    f"<b>{esc(name)}</b> reads as <b>{resolved.kind}</b>, not "
                    f"<b>{preset}</b> — use the {resolved.kind} page (or the "
                    "generic Add) for that name.")
        return resolved.kind, None
    return (preset or KIND_ENTITY), None


def _active_ws_id(ctx) -> int | None:
    a = ctx.groups.current(ctx.user_id)
    return a.workspace_id


# ── /control entry ────────────────────────────────────────────────────────

async def control_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      ctx: ControlContext | None = None):
    """/control entry. main.py is responsible for the admin gate (silent
    denial per CLAUDE.md) BEFORE calling this; this renders the home page and
    clears any stale control gather/confirm state."""
    user_id = update.effective_user.id if update.effective_user else 0
    cancel_all(user_id)
    clear_state(user_id)
    ctx = ctx or build_context(user_id)
    text, kb = pages.control_home(ctx)
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)
