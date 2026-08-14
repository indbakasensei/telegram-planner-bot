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
    if p[0] == "note":
        if len(p) == 1 or p[1] in ("home", "list"):
            return pages.note_home(ctx)
        if len(p) >= 4 and p[1] in ("home", "list") and p[2] == "p":
            return pages.note_home(ctx, page=_int_or(p[3], 1))
        if p[1] == "view":
            return pages.note_view(ctx, _int_or(p[2], 0))
    if p[0] == "media":
        if len(p) == 1 or (p[1] in ("home", "list") and len(p) == 2):
            return pages.media_home(ctx)
        if p[1] in ("home", "list"):
            if p[2] == "p":
                return pages.media_home(ctx, page=_int_or(p[3], 1))
            mtype, eid, tid, page = _media_filter(p)
            return pages.media_home(ctx, page=page, media_type=mtype,
                                    entity_id=eid, tag_id=tid)
        if p[1] == "view":
            return pages.media_view(ctx, _int_or(p[2], 0))
    if p[0] == "tag":
        if len(p) == 1 or p[1] in ("home", "list"):
            return pages.tag_home(ctx)
        if len(p) >= 4 and p[1] in ("home", "list") and p[2] == "p":
            return pages.tag_home(ctx, page=_int_or(p[3], 1))
        if p[1] == "view":
            return pages.tag_view(ctx, _int_or(p[2], 0))
    if p[0] == "search":
        if len(p) == 1 or p[1] in ("home", "list"):
            return pages.search_home(ctx)
        if len(p) >= 4 and p[1] in ("home", "list") and p[2] == "p":
            return pages.search_home(ctx, page=_int_or(p[3], 1))
    return pages.control_home(ctx)


def _target(ctx: ControlContext, target: str):
    """Render a full `ctl:` target string to (text, keyboard)."""
    return _route_page(ctx, target.split(":"))


def _int_or(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _media_filter(p):
    """Parse 'ctl:media:list[:type:T|:ent:N|:tag:N][:p:N]' segments (p starts
    at 'media'). Returns (media_type, entity_id, tag_id, page)."""
    media_type = entity_id = tag_id = None
    page = 1
    i = 2  # skip 'media', 'home'/'list'
    while i < len(p):
        seg = p[i]
        if seg == "p" and i + 1 < len(p):
            page = _int_or(p[i + 1], 1)
            i += 2
            continue
        if seg == "type" and i + 1 < len(p):
            media_type = p[i + 1]
            i += 2
            continue
        if seg == "ent" and i + 1 < len(p):
            entity_id = _int_or(p[i + 1], 0)
            i += 2
            continue
        if seg == "tag" and i + 1 < len(p):
            tag_id = _int_or(p[i + 1], 0)
            i += 2
            continue
        i += 1
    return media_type, entity_id, tag_id, page


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

    # ── M6 knowledge actions
    if p[0] == "note":
        if p[1] == "add":
            return _begin_gather(ctx, p, "create_note",
                                 {"_ctl": "note_add"}, ["content"],
                                 "Send the note. A title plus body works: "
                                 "<code>Title</code> then a blank line then "
                                 "the content — or just the content alone.")
        if p[1] == "search":
            return _begin_gather(ctx, p, "list_notes",
                                 {"_ctl": "note_search"}, ["q"],
                                 "Send a search query — notes matching the "
                                 "text in their title/content are shown.")
        if p[1] == "edit" and len(p) >= 3:
            note_id = _int_or(p[2], 0)
            if _note_for_gather(ctx, note_id) is None:
                return pages._missing_entity_page("note")
            return _begin_gather(ctx, p, "update_note",
                                 {"_ctl": "note_edit", "note_id": note_id},
                                 ["content"],
                                 f"Send the new content for note #{note_id} "
                                 "(title line, blank line, body — or just "
                                 "content).")
        if p[1] == "del" and len(p) >= 3:
            note_id = _int_or(p[2], 0)
            if _note_for_gather(ctx, note_id) is None:
                return pages._missing_entity_page("note")
            return begin_confirm(ctx, "delete_note", {"note_id": note_id},
                                 return_to="ctl:note:home")
        if p[1] == "post" and len(p) >= 3:
            note_id = _int_or(p[2], 0)
            if _note_for_gather(ctx, note_id) is None:
                return pages._missing_entity_page("note")
            return await _run_immediate(ctx, "post_note",
                                        {"note_id": note_id},
                                        f"ctl:note:view:{note_id}")
        if p[1] == "link-ent" and len(p) >= 3:
            note_id = _int_or(p[2], 0)
            if _note_for_gather(ctx, note_id) is None:
                return pages._missing_entity_page("note")
            return _begin_gather(ctx, p, "link_note_entity",
                                 {"_ctl": "note_link_ent", "note_id": note_id},
                                 ["entity"],
                                 "Send the entity name or #id to link this "
                                 "note to.")
        if p[1] == "link-tag" and len(p) >= 3:
            note_id = _int_or(p[2], 0)
            if _note_for_gather(ctx, note_id) is None:
                return pages._missing_entity_page("note")
            return _begin_gather(ctx, p, "link_note_tag",
                                 {"_ctl": "note_link_tag", "note_id": note_id},
                                 ["tag"],
                                 "Send the tag name — it is created when "
                                 "missing.")
        if p[1] == "unlink-ent" and len(p) >= 4:
            note_id = _int_or(p[2], 0)
            return await _run_immediate(
                ctx, "unlink_note_entity",
                {"note_id": note_id, "entity": f"#{_int_or(p[3], 0)}"},
                f"ctl:note:view:{note_id}")
        if p[1] == "unlink-tag" and len(p) >= 4:
            note_id = _int_or(p[2], 0)
            tag_name = _tag_name_by_id(ctx, _int_or(p[3], 0))
            if _note_for_gather(ctx, note_id) is None or tag_name is None:
                return pages._missing_entity_page("note")
            return await _run_immediate(
                ctx, "unlink_note_tag",
                {"note_id": note_id, "tag": tag_name},
                f"ctl:note:view:{note_id}")
        return _route_page(ctx, parts)

    # ── M6 media actions
    if p[0] == "media":
        if p[1] == "search":
            return _begin_gather(ctx, p, "list_media",
                                 {"_ctl": "media_search"}, ["q"],
                                 "Send a search query — media matching the "
                                 "text in caption/file name/extracted text "
                                 "are shown.")
        if p[1] == "del" and len(p) >= 3:
            media_id = _int_or(p[2], 0)
            if _media_for_gather(ctx, media_id) is None:
                return pages._missing_entity_page("media")
            return begin_confirm(ctx, "delete_media", {"media_id": media_id},
                                 return_to="ctl:media:home")
        if p[1] == "edit" and len(p) >= 3:
            media_id = _int_or(p[2], 0)
            if _media_for_gather(ctx, media_id) is None:
                return pages._missing_entity_page("media")
            return _begin_gather(ctx, p, "update_media",
                                 {"_ctl": "media_edit", "media_id": media_id},
                                 ["caption"],
                                 "Send the new caption for this media record "
                                 "(the Telegram message is untouched).")
        if p[1] == "link-ent" and len(p) >= 3:
            media_id = _int_or(p[2], 0)
            if _media_for_gather(ctx, media_id) is None:
                return pages._missing_entity_page("media")
            return _begin_gather(ctx, p, "link_media_entity",
                                 {"_ctl": "media_link_ent", "media_id": media_id},
                                 ["entity"],
                                 "Send the entity name or #id to link this "
                                 "media to.")
        if p[1] == "link-tag" and len(p) >= 3:
            media_id = _int_or(p[2], 0)
            if _media_for_gather(ctx, media_id) is None:
                return pages._missing_entity_page("media")
            return _begin_gather(ctx, p, "link_media_tag",
                                 {"_ctl": "media_link_tag", "media_id": media_id},
                                 ["tag"],
                                 "Send the tag name — it is created when "
                                 "missing.")
        if p[1] == "unlink-ent" and len(p) >= 4:
            media_id = _int_or(p[2], 0)
            return await _run_immediate(
                ctx, "unlink_media_entity",
                {"media_id": media_id, "entity": f"#{_int_or(p[3], 0)}"},
                f"ctl:media:view:{media_id}")
        if p[1] == "unlink-tag" and len(p) >= 4:
            media_id = _int_or(p[2], 0)
            tag_name = _tag_name_by_id(ctx, _int_or(p[3], 0))
            if _media_for_gather(ctx, media_id) is None or tag_name is None:
                return pages._missing_entity_page("media")
            return await _run_immediate(
                ctx, "unlink_media_tag",
                {"media_id": media_id, "tag": tag_name},
                f"ctl:media:view:{media_id}")
        return _route_page(ctx, parts)

    # ── M6 tag actions
    if p[0] == "tag":
        if p[1] == "add":
            return _begin_gather(ctx, p, "create_tag",
                                 {"_ctl": "tag_add"}, ["name"],
                                 "Send the new tag name.")
        if p[1] == "rename" and len(p) >= 3:
            tag_id = _int_or(p[2], 0)
            t = _tag_by_id(ctx, tag_id)
            if t is None:
                return pages._missing_entity_page("tag")
            return _begin_gather(ctx, p, "rename_tag",
                                 {"_ctl": "tag_rename", "tag_id": tag_id,
                                  "old_name": t.name},
                                 ["new_name"],
                                 f"Send the new name for tag "
                                 f"<b>{esc(t.name)}</b>.")
        if p[1] == "del" and len(p) >= 3:
            tag_id = _int_or(p[2], 0)
            t = _tag_by_id(ctx, tag_id)
            if t is None:
                return pages._missing_entity_page("tag")
            return begin_confirm(ctx, "delete_tag",
                                 {"tag": t.name,
                                  "workspace": _active_ws_id(ctx) or 0},
                                 return_to="ctl:tag:home")
        return _route_page(ctx, parts)

    # ── M7 cross-reference search actions
    if p[0] == "search":
        if p[1] == "gather":
            return _begin_gather(ctx, p, "search_knowledge",
                                 {"_ctl": "search_gather"}, ["q"],
                                 "Send a search query — matching notes (title/content) "
                                 "and media (caption/file_name/extracted_text) are shown.")
        if p[1] == "execute":
            # Execute search with accumulated filters
            from conversation_state import get_search_state
            return pages.search_home(ctx, execute=True, **get_search_state(ctx.user_id))
        if p[1] == "clear":
            from conversation_state import clear_search_state
            clear_search_state(ctx.user_id)
            return pages.search_home(ctx)
        if p[1] == "entities":
            return _begin_gather(ctx, p, "search_knowledge",
                                 {"_ctl": "search_entities"}, ["entities"],
                                 "Send comma-separated entity names or #ids to filter by.")
        if p[1] == "ws":
            return _begin_gather(ctx, p, "search_knowledge",
                                 {"_ctl": "search_ws"}, ["workspace"],
                                 "Send the workspace name or #id to search in "
                                 "(or 'all' for cross-workspace).")
        if p[1] == "mode":
            return _begin_gather(ctx, p, "search_knowledge",
                                 {"_ctl": "search_mode"}, ["entity_mode", "tag_mode"],
                                 "Send entity_mode and tag_mode as 'and' or 'or' "
                                 "separated by space (e.g., 'and or').")
        if p[1] == "dates":
            return _begin_gather(ctx, p, "search_knowledge",
                                 {"_ctl": "search_dates"}, ["created_after", "created_before"],
                                 "Send date range as 'after before' in ISO format "
                                 "(e.g., '2026-01-01 2026-12-31', empty = no bound).")
        if p[1] == "mtype":
            return _begin_gather(ctx, p, "search_knowledge",
                                 {"_ctl": "search_mtype"}, ["media_type"],
                                 "Send media type filter: photo, video, document, or audio "
                                 "(empty = all).")
        if p[1] == "tags":
            return _begin_gather(ctx, p, "search_knowledge",
                                 {"_ctl": "search_tags"}, ["tags"],
                                 "Send comma-separated tag names to filter by.")
        if p[1] == "scope":
            return _begin_gather(ctx, p, "search_knowledge",
                                 {"_ctl": "search_scope"}, ["scope"],
                                 "Send 'active' (default) or 'all' for cross-workspace search.")
        if p[1] == "kind":
            return _begin_gather(ctx, p, "search_knowledge",
                                 {"_ctl": "search_kind"}, ["kind"],
                                 "Send note kind filter (e.g., 'note', 'log', 'idea') or empty for all.")
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
    if kind == "note_add":
        return await _gather_note_add(update, user_id, ctx, text)
    if kind == "note_edit":
        return await _gather_note_edit(update, user_id, ctx, partial, text)
    if kind == "note_search":
        return _gather_note_search(update, user_id, ctx, text)
    if kind == "note_link_ent":
        return await _gather_note_link(update, user_id, ctx, partial, text,
                                       tag=False)
    if kind == "note_link_tag":
        return await _gather_note_link(update, user_id, ctx, partial, text,
                                       tag=True)
    if kind == "media_search":
        return _gather_media_search(update, user_id, ctx, text)
    if kind == "media_edit":
        return await _gather_media_edit(update, user_id, ctx, partial, text)
    if kind == "media_link_ent":
        return await _gather_media_link(update, user_id, ctx, partial, text,
                                        tag=False)
    if kind == "media_link_tag":
        return await _gather_media_link(update, user_id, ctx, partial, text,
                                        tag=True)
    if kind == "tag_add":
        return await _gather_tag_add(update, user_id, ctx, text)
    if kind == "tag_rename":
        return await _gather_tag_rename(update, user_id, ctx, partial, text)
    # M7 search gather handlers
    if kind == "search_gather":
        return await _gather_search(update, user_id, ctx, text)
    if kind == "search_entities":
        return await _gather_search_entities(update, user_id, ctx, text)
    if kind == "search_ws":
        return await _gather_search_ws(update, user_id, ctx, text)
    if kind == "search_mode":
        return await _gather_search_mode(update, user_id, ctx, text)
    if kind == "search_dates":
        return await _gather_search_dates(update, user_id, ctx, text)
    if kind == "search_mtype":
        return await _gather_search_mtype(update, user_id, ctx, text)
    if kind == "search_tags":
        return await _gather_search_tags(update, user_id, ctx, text)
    if kind == "search_scope":
        return await _gather_search_scope(update, user_id, ctx, text)
    if kind == "search_kind":
        return await _gather_search_kind(update, user_id, ctx, text)
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


def _split_note_input(text: str):
    """'Title\\n\\nbody' → (title, body); else (None, text). Deterministic —
    a blank line separates the title from the body."""
    if "\n\n" in text:
        title, _, body = text.partition("\n\n")
        title, body = title.strip(), body.strip()
        if body:
            return (title or None), body
    return None, text.strip()


def _note_for_gather(ctx, note_id):
    try:
        return ctx.engine.get_note(ctx.user_id, note_id)
    except Exception:
        return None


def _media_for_gather(ctx, media_id):
    try:
        return ctx.engine.get_media(ctx.user_id, media_id)
    except Exception:
        return None


def _tag_by_id(ctx, tag_id):
    try:
        return ctx.engine.get_tag(ctx.user_id, tag_id)
    except Exception:
        return None


def _tag_name_by_id(ctx, tag_id) -> str | None:
    t = _tag_by_id(ctx, tag_id)
    return t.name if t else None


async def _gather_note_add(update, user_id, ctx, text):
    if not text.strip():
        clear_state(user_id)
        return _reply(update, "No content — send the note text.")
    title, content = _split_note_input(text)
    if not content:
        clear_state(user_id)
        return _reply(update, "No content — send the note text.")
    clear_state(user_id)
    args = {"content": content}
    if title:
        args["title"] = title
    return begin_confirm(ctx, "create_note", args, return_to="ctl:note:home",
                         question="Save this note to the active workspace?")


async def _gather_note_edit(update, user_id, ctx, partial, text):
    note_id = int(partial.get("note_id") or 0)
    if not text.strip():
        clear_state(user_id)
        return _reply(update, "No content — send the new note text.")
    title, content = _split_note_input(text)
    if not content:
        clear_state(user_id)
        return _reply(update, "No content — send the new note text.")
    clear_state(user_id)
    args = {"note_id": note_id, "content": content}
    if title:
        args["title"] = title
    return begin_confirm(ctx, "update_note", args,
                         return_to=f"ctl:note:view:{note_id}",
                         question=f"Update note #{note_id} with this text?")


def _gather_note_search(update, user_id, ctx, text):
    q = text.strip()
    clear_state(user_id)
    if not q:
        return _reply(update, "No query — send some text to search for.")
    return pages.note_home(ctx, q=q)


def _gather_media_search(update, user_id, ctx, text):
    q = text.strip()
    clear_state(user_id)
    if not q:
        return _reply(update, "No query — send some text to search for.")
    return pages.media_home(ctx, q=q)


async def _gather_note_link(update, user_id, ctx, partial, text, tag=False):
    note_id = int(partial.get("note_id") or 0)
    value = text.strip()
    clear_state(user_id)
    if not value:
        return _reply(update, "No value — send the entity name/#id or tag name.")
    if tag:
        return begin_confirm(ctx, "link_note_tag",
                             {"note_id": note_id, "tag": value},
                             return_to=f"ctl:note:view:{note_id}",
                             question=f"Tag note #{note_id} with "
                                      f"<b>{esc(value)}</b>?")
    return begin_confirm(ctx, "link_note_entity",
                         {"note_id": note_id, "entity": value},
                         return_to=f"ctl:note:view:{note_id}",
                         question=f"Link note #{note_id} to "
                                  f"<b>{esc(value)}</b>?")


async def _gather_media_edit(update, user_id, ctx, partial, text):
    media_id = int(partial.get("media_id") or 0)
    if not text.strip():
        clear_state(user_id)
        return _reply(update, "No caption — send the new caption text.")
    clear_state(user_id)
    return begin_confirm(ctx, "update_media",
                         {"media_id": media_id, "caption": text.strip()},
                         return_to=f"ctl:media:view:{media_id}",
                         question=f"Update media record #{media_id} caption?")


async def _gather_media_link(update, user_id, ctx, partial, text, tag=False):
    media_id = int(partial.get("media_id") or 0)
    value = text.strip()
    clear_state(user_id)
    if not value:
        return _reply(update, "No value — send the entity name/#id or tag name.")
    if tag:
        return begin_confirm(ctx, "link_media_tag",
                             {"media_id": media_id, "tag": value},
                             return_to=f"ctl:media:view:{media_id}",
                             question=f"Tag media #{media_id} with "
                                      f"<b>{esc(value)}</b>?")
    return begin_confirm(ctx, "link_media_entity",
                         {"media_id": media_id, "entity": value},
                         return_to=f"ctl:media:view:{media_id}",
                         question=f"Link media #{media_id} to "
                                  f"<b>{esc(value)}</b>?")


async def _gather_tag_add(update, user_id, ctx, text):
    name = text.strip()
    clear_state(user_id)
    if not name:
        return _reply(update, "No name — send the new tag name.")
    ws_id = _active_ws_id(ctx)
    if ws_id is None:
        return _reply(update, "No workspace active — open one first.",
                      nav="ctl:ws:home")
    return begin_confirm(ctx, "create_tag", {"name": name, "workspace": ws_id},
                         return_to="ctl:tag:home",
                         question=f"Create tag <b>{esc(name)}</b> in workspace "
                                  f"#{ws_id}?")


async def _gather_tag_rename(update, user_id, ctx, partial, text):
    tag_id = int(partial.get("tag_id") or 0)
    old_name = partial.get("old_name") or f"#{tag_id}"
    new_name = text.strip()
    clear_state(user_id)
    if not new_name:
        return _reply(update, "No name — send the new tag name.")
    ws_id = _active_ws_id(ctx)
    if ws_id is None:
        return _reply(update, "No workspace active — open one first.",
                      nav="ctl:ws:home")
    return begin_confirm(ctx, "rename_tag",
                         {"tag": old_name, "new_name": new_name,
                          "workspace": ws_id},
                         return_to=f"ctl:tag:view:{tag_id}",
                         question=f"Rename tag <b>{esc(old_name)}</b> to "
                                  f"<b>{esc(new_name)}</b>?")


# ── M7 cross-reference search gather handlers

async def _gather_search(update, user_id, ctx, text):
    from conversation_state import set_search_state, get_search_state
    q = text.strip()
    clear_state(user_id)
    if not q:
        return _reply(update, "No query — send some text to search for.")
    set_search_state(user_id, q=q)
    return pages.search_home(ctx, **get_search_state(user_id))


async def _gather_search_ws(update, user_id, ctx, text):
    from conversation_state import set_search_state, get_search_state
    ws_ref = text.strip()
    clear_state(user_id)
    if not ws_ref:
        return _reply(update, "No workspace — send name/#id or 'all'.")
    if ws_ref.lower() == "all":
        set_search_state(user_id, scope="all", workspace=None)
        return pages.search_home(ctx, **get_search_state(user_id))
    ws = ctx.engine.get_workspace_or_none(ctx.user_id, ws_ref)
    if not ws:
        return _reply(update, f"No workspace matches {esc(ws_ref)!r}.", nav="ctl:search:home")
    set_search_state(user_id, workspace=ws.id, scope="active")
    return pages.search_home(ctx, **get_search_state(user_id))


async def _gather_search_mode(update, user_id, ctx, text):
    from conversation_state import set_search_state, get_search_state
    parts = text.strip().split()
    clear_state(user_id)
    if len(parts) != 2 or parts[0] not in ("and", "or") or parts[1] not in ("and", "or"):
        return _reply(update, "Send two modes: entity_mode and tag_mode as 'and' or 'or' "
                      "(e.g., 'and or').", nav="ctl:search:home")
    entity_mode, tag_mode = parts[0], parts[1]
    set_search_state(user_id, entity_mode=entity_mode, tag_mode=tag_mode)
    return pages.search_home(ctx, **get_search_state(user_id))


async def _gather_search_dates(update, user_id, ctx, text):
    from conversation_state import set_search_state, get_search_state
    parts = text.strip().split()
    clear_state(user_id)
    created_after = None
    created_before = None
    if len(parts) >= 1 and parts[0]:
        created_after = parts[0]
    if len(parts) >= 2 and parts[1]:
        created_before = parts[1]
    set_search_state(user_id, created_after=created_after, created_before=created_before)
    return pages.search_home(ctx, **get_search_state(user_id))


async def _gather_search_mtype(update, user_id, ctx, text):
    from conversation_state import set_search_state, get_search_state
    mt = text.strip().lower()
    clear_state(user_id)
    if mt and mt not in ("photo", "video", "document", "audio"):
        return _reply(update, "Unknown media type — use photo, video, document, or audio.",
                      nav="ctl:search:home")
    set_search_state(user_id, media_type=mt or None)
    return pages.search_home(ctx, **get_search_state(user_id))


async def _gather_search_tags(update, user_id, ctx, text):
    from conversation_state import set_search_state, get_search_state
    tags = text.strip()
    clear_state(user_id)
    if not tags:
        return _reply(update, "No tags — send comma-separated tag names.",
                      nav="ctl:search:home")
    set_search_state(user_id, tags=tags)
    return pages.search_home(ctx, **get_search_state(user_id))


async def _gather_search_scope(update, user_id, ctx, text):
    from conversation_state import set_search_state, get_search_state
    scope = text.strip().lower()
    clear_state(user_id)
    if scope not in ("active", "all"):
        return _reply(update, "Send 'active' (default) or 'all' for cross-workspace search.",
                      nav="ctl:search:home")
    set_search_state(user_id, scope=scope)
    return pages.search_home(ctx, **get_search_state(user_id))


async def _gather_search_kind(update, user_id, ctx, text):
    from conversation_state import set_search_state, get_search_state
    kind = text.strip()
    clear_state(user_id)
    set_search_state(user_id, kind=kind or None)
    return pages.search_home(ctx, **get_search_state(user_id))


async def _gather_search_entities(update, user_id, ctx, text):
    from conversation_state import set_search_state, get_search_state
    entities = text.strip()
    clear_state(user_id)
    if not entities:
        return _reply(update, "No entities — send comma-separated entity names or #ids.",
                      nav="ctl:search:home")
    set_search_state(user_id, entities=entities)
    return pages.search_home(ctx, **get_search_state(user_id))


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
