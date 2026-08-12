"""
core/control/pages.py -- pure page renderers for the Manual Control Plane.

Every function returns `(text, InlineKeyboardMarkup)` and NEVER writes the
DB or Telegram: it only READS domain state (EntityEngine / workspace
bindings) for display. Mutations happen exclusively through the ToolRegistry
(see registry.py / actions.py). Renderers take a `ControlContext` so tests
drive them against a temp DB with zero Telegram involvement.

The M5-A "Current workspace" UI lives in `workspace_page`/`workspace_detail`;
M5-B entity pages in `entity_hub`/`entity_list`/`entity_detail`; M5-C Topic
Control Center in `topic_center`/`topic_detail`; M5-D in `identity_inspector`;
M5-E in `equip_home`/`equip_pick`. All page chrome comes from ui_components
(UI_SPEC_v1.md) -- never hand-formatted HTML.
"""
from __future__ import annotations

import json

import ui_components as uic
from fmt import b, esc

from core.ai.entity_kinds import (
    KIND_ARTIFACT,
    KIND_CHARACTER,
    KIND_ENTITY,
    KIND_WEAPON,
)
from core.workspace.groups_app import ENTITY_TYPE, _normalize_title
from core.workspace.templates.registry import entity_field_specs
from core.control.registry import ControlContext

# Page-chrome vocabulary keys (ui_components ICONS -- closed set).
_ICON_CTRL = "dev"
_ICON_WS = "settings"
_ICON_ENT = "list"
_ICON_TOPIC = "chat"
_ICON_IDENT = "info"

# Per-kind display glyphs (button labels, not the icon() vocabulary).
_KIND_GLYPH = {
    KIND_CHARACTER: "👤",
    KIND_WEAPON: "⚔️",
    KIND_ARTIFACT: "🪞",
    KIND_ENTITY: "📄",
}
_KIND_LABEL = {
    KIND_CHARACTER: "Characters",
    KIND_WEAPON: "Weapons",
    KIND_ARTIFACT: "Artifacts",
    KIND_ENTITY: "Plain entities",
    "all": "All entities",
}

_PAGE_LEN = {   # list rows per page (keeps every keyboard ≤ 12 buttons)
    "entity": 5,
    "workspace": 6,
    "topic": 4,
    "equip": 6,
}


def _paginate(items, page: int, per_page: int):
    total = len(items)
    pages = max(1, -(-total // per_page))
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    return items[start:start + per_page], page, pages


def _active_ws(ctx: ControlContext):
    """The active workspace row or None (display read only)."""
    a = ctx.groups.current(ctx.user_id)
    if a.workspace_id is None:
        return None, None
    ws = ctx.engine.get_workspace_or_none(ctx.user_id, a.workspace_id)
    return ws, a


def _no_active_section(return_to: str):
    """A §14 empty-state + the workspace CTA, for pages that need a workspace."""
    body = uic.render_empty_state(
        "settings", "No workspace active",
        "Open or create a workspace first — the control plane operates on "
        "the active workspace, exactly like the AI Worker.",
        "Open one from the Workspaces page.")
    rows = [
        uic.primary_row("🗂 Open Workspaces", return_to),
        uic.nav_row(None, return_to),
    ]
    return body, uic.keyboard(*rows)


def _ws_status(ws) -> str:
    return (ws.status or "active").replace("_", " ")


def _kind_of(m) -> str:
    return (m.entity_type or KIND_ENTITY).lower()


def _field_preview(m, template_key: str, limit: int = 3):
    """Compact (label, value) rows from a milestone's fields, newest schema
    order first; returns (rows, extras_count)."""
    specs = entity_field_specs(template_key)
    out = []
    for spec in specs:
        val = (m.fields or {}).get(spec.name)
        if val in (None, ""):
            continue
        if spec.kind == "json":
            try:
                val = json.dumps(val, ensure_ascii=False)
            except (TypeError, ValueError):
                val = str(val)
            if len(val) > 48:
                val = val[:48] + "…"
        out.append((spec.name, str(val)))
    return out[:limit], len(out) - limit


# ── M5-A: control home + workspace control ────────────────────────────────

def control_home(ctx: ControlContext):
    """M5-A state header + section navigation."""
    ws, a = _active_ws(ctx)
    sections = []
    if ws is None:
        sections.append(uic.render_status_card(
            "warning", "No workspace active",
            "Open or create a workspace to start. The control plane drives "
            "the same tool surface the AI Worker uses."))
    else:
        rows = [
            ("Workspace", f"#{ws.id} {ws.title}"),
            ("Template", ws.template or "generic"),
            ("Status", _ws_status(ws)),
            ("Telegram", "linked" if a.linked else "not linked"),
        ]
        if a.entity_id is not None:
            rows.append(("Active entity", f"#{a.entity_id} {a.entity_title}"))
        sections.append(uic.render_information_card("Current context", rows))
    text = uic.render_page(
        uic.render_header(_ICON_CTRL, "Control Plane", ["Control"],
                          "Manual control via the shared tool surface"),
        *sections,
        footer=uic.render_footer("Admin only — denied silently to others"))
    rows = [
        uic.primary_row("🗂 Workspaces", "ctl:ws:home"),
        uic.action_row(("🗃 Entities", "ctl:ent:list"),
                       ("💬 Topic Center", "ctl:topic:home")),
        uic.action_row(("🆔 Identity", "ctl:ident:active"),
                       ("⚔️ Equipment", "ctl:eq:home")),
        uic.nav_row(None, "ctl:home"),
    ]
    return text, uic.keyboard(*rows)


def workspace_page(ctx: ControlContext):
    """M5-A: current workspace + switch list + create."""
    wss = ctx.engine.list_workspaces(ctx.user_id, status=None)
    ws, a = _active_ws(ctx)
    sections = []
    if ws is None:
        sections.append(uic.render_status_card(
            "warning", "No workspace active",
            "Nothing is open. Tap a workspace below to make it active, or "
            "create one."))
    else:
        sections.append(uic.render_information_card(
            "Current workspace",
            [("Workspace", f"#{ws.id} {ws.title}"),
             ("Template", ws.template or "generic"),
             ("Status", _ws_status(ws)),
             ("Telegram", "linked" if a.linked else "not linked")]))
    page_items, page, pages = _paginate(wss, 1, _PAGE_LEN["workspace"])
    body = "\n".join(
        f"{uic.icon('settings')} {b(esc(w.title))} — {esc(_ws_status(w))} "
        f"(#{w.id}){_mark_active(w.id, ws)}"
        for w in page_items) or uic.render_empty_state(
            "settings", "No workspaces yet",
            "Create one with /newgame, /newproject — or the button below.")
    sections.append(uic.render_section("Switch workspace", body))
    text = uic.render_page(
        uic.render_header(_ICON_WS, "Workspaces", ["Control", "Workspaces"],
                          f"{len(wss)} total · page {page}/{pages}"),
        *sections,
        footer=uic.render_footer("Tap a workspace to view its controls"))
    rows = [uic.primary_row("➕ Create workspace", "ctl:ws:create")]
    for w in page_items:
        rows.append(uic.action_row(
            (f"{uic.icon('settings')} {esc(w.title)} (#{w.id})",
             f"ctl:ws:detail:{w.id}")))
    rows.append(uic.nav_row("ctl:home", "ctl:ws:home"))
    if pages > 1:
        rows.append(uic.pagination_row("ctl:ws:home:p", page, pages))
    return text, uic.keyboard(*rows)


def _mark_active(w_id, ws):
    return " — ⭐ active" if ws is not None and ws.id == w_id else ""


def workspace_detail(ctx: ControlContext, ws_id: int):
    """M5-A: one workspace's full control surface."""
    ws = ctx.engine.get_workspace_or_none(ctx.user_id, ws_id)
    if ws is None:
        return _missing_entity_page("workspace")
    a = ctx.groups.current(ctx.user_id)
    linked = ctx.storage.tg_bindings.get_binding(ws_id) is not None
    progress = ctx.engine.workspace_progress(ctx.user_id, ws_id)
    rows = [
        ("Title", ws.title),
        ("ID", str(ws.id)),
        ("Template", ws.template or "generic"),
        ("Status", _ws_status(ws)),
        ("Progress", f"{progress}%"),
        ("Telegram", "linked" if linked else "not linked"),
        ("Active", "yes" if a.workspace_id == ws_id else "no"),
    ]
    text = uic.render_page(
        uic.render_header(_ICON_WS, "Workspace", ["Control", "Workspaces",
                                                  ws.title]),
        uic.render_section("Details",
                           uic.render_information_card("Workspace", rows)),
        footer=uic.render_footer("Close only clears the active context — it "
                                 "never touches the workspace row"))
    kb_rows = [
        uic.primary_row("⭐ Open / Switch", f"ctl:ws:open:{ws_id}"),
        uic.action_row(("✕ Close", f"ctl:ws:close:{ws_id}"),
                       ("🔍 Inspect", f"ctl:ws:inspect:{ws_id}")),
        uic.action_row(("✏️ Rename", f"ctl:ws:rename:{ws_id}"),
                       ("🗑 Archive", f"ctl:ws:archive:{ws_id}")),
        uic.action_row(("🗃 Entities", "ctl:ent:list"),
                       ("💬 Topics", "ctl:topic:home")),
        uic.nav_row("ctl:ws:home", f"ctl:ws:detail:{ws_id}"),
    ]
    return text, uic.keyboard(*kb_rows)


def workspace_inspect(ctx: ControlContext, ws_id: int):
    """Deep read view: progress + entity counts by status + recent notes."""
    ws = ctx.engine.get_workspace_or_none(ctx.user_id, ws_id)
    if ws is None:
        return _missing_entity_page("workspace")
    ms = ctx.engine.list_milestones(ctx.user_id, ws_id)
    counts = {s: 0 for s in ("todo", "in_progress", "done", "blocked")}
    for m in ms:
        counts[m.status] = counts.get(m.status, 0) + 1
    notes = ctx.engine.list_notes(ctx.user_id, ws_id, kind="progress")
    progress = ctx.engine.workspace_progress(ctx.user_id, ws_id)
    sections = [
        uic.render_section(
            "Overview",
            uic.render_statistics_card(
                "Progress", [("Entities", len(ms)),
                             ("Progress", f"{progress}%")],
                progress_percent=progress)),
        uic.render_section(
            "By status",
            uic.render_information_card(
                "Status", [(k.replace("_", " "), str(counts.get(k, 0)))
                           for k in ("todo", "in_progress", "done", "blocked")])),
    ]
    if notes:
        body = "\n".join(
            f"#{n.id} {b(esc(n.content[:80]))}" for n in notes[:5])
        sections.append(uic.render_section("Recent progress notes", body))
    text = uic.render_page(
        uic.render_header(_ICON_WS, "Inspect", ["Control", "Workspaces",
                                                ws.title],
                          f"#{ws.id}"),
        *sections)
    kb = uic.keyboard(
        uic.action_row(("↩ Back", f"ctl:ws:detail:{ws_id}"),
                       ("🔄 Refresh", f"ctl:ws:inspect:{ws_id}")),
        uic.nav_row(None, None, "ctl:home"),
    )
    return text, kb


# ── M5-B: entity control ──────────────────────────────────────────────────

def entity_hub(ctx: ControlContext):
    """Generic kind selector + Add (M5-B; no domain hardcoding)."""
    sections = []
    ws, a = _active_ws(ctx)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_ENT, "Entities", ["Control", "Entities"]),
            body), kb
    sections.append(uic.render_information_card(
        "Active workspace", [("Workspace", f"#{ws.id} {ws.title}"),
                             ("Telegram", "linked" if a.linked else "not linked")]))
    text = uic.render_page(
        uic.render_header(_ICON_ENT, "Entities", ["Control", "Entities"],
                          "generic Character / Weapon / Artifact pages"),
        *sections)
    kb = uic.keyboard(
        uic.primary_row("➕ Add entity", "ctl:ent:add"),
        uic.action_row(
            (f"{_KIND_GLYPH[KIND_CHARACTER]} {_KIND_LABEL[KIND_CHARACTER]}",
             "ctl:ent:list:character"),
            (f"{_KIND_GLYPH[KIND_WEAPON]} {_KIND_LABEL[KIND_WEAPON]}",
             "ctl:ent:list:weapon"),
            (f"{_KIND_GLYPH[KIND_ARTIFACT]} {_KIND_LABEL[KIND_ARTIFACT]}",
             "ctl:ent:list:artifact")),
        uic.action_row(
            (f"{_KIND_GLYPH[KIND_ENTITY]} {_KIND_LABEL[KIND_ENTITY]}",
             "ctl:ent:list:entity"),
            ("All", "ctl:ent:list:all")),
        uic.nav_row("ctl:home", "ctl:ent:list"),
    )
    return text, kb


def _workspace_entities(ctx: ControlContext, kind):
    ws, _a = _active_ws(ctx)
    if ws is None:
        return [], None
    ms = ctx.engine.list_milestones(ctx.user_id, ws.id)
    if kind and kind != "all":
        ms = [m for m in ms if _kind_of(m) == kind]
    ms.sort(key=lambda m: m.sort_order or 0)
    return ms, ws


def entity_list(ctx: ControlContext, kind, page: int = 1):
    """M5-B: entities of one kind (or all), paginated, one row per entity."""
    label = _KIND_LABEL.get(kind or "", "Entities")
    ms, ws = _workspace_entities(ctx, kind)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_ENT, label, ["Control", "Entities"]),
            body), kb
    items, page, pages = _paginate(ms, page, _PAGE_LEN["entity"])
    sections = [uic.render_section(
        label,
        "\n".join(_entity_line(m) for m in items) or uic.render_empty_state(
            "list", f"No {label.lower()} yet",
            "Add one with the button below."))]
    text = uic.render_page(
        uic.render_header(_ICON_ENT, label, ["Control", "Entities", label],
                          f"{ws.title} · page {page}/{pages}"),
        *sections)
    kind_cb = f"ctl:ent:list:{kind}" if kind else "ctl:ent:list"
    rows = [uic.primary_row(f"➕ Add {label.rstrip('s').lower()}",
                            f"ctl:ent:add:{kind}")]
    for m in items:
        rows.append(uic.action_row((_entity_line(m), f"ctl:ent:view:{m.id}")))
    rows.append(uic.nav_row("ctl:ent:list", kind_cb))
    if pages > 1:
        rows.append(uic.pagination_row(f"ctl:ent:list:{kind}:p", page, pages))
    return text, uic.keyboard(*rows)


def _entity_line(m) -> str:
    glyph = _KIND_GLYPH.get(_kind_of(m), "📄")
    return f"{glyph} {b(esc(m.title))} (#{m.id}) — {esc(m.status or 'todo')}"


def entity_detail(ctx: ControlContext, eid: int):
    """M5-B: one entity's card + actions."""
    m, ws = _find_entity(ctx, eid)
    if m is None:
        return _missing_entity_page("entity")
    rows = [("Name", m.title), ("Entity ID", str(m.id)),
            ("Kind", _kind_of(m)), ("Status", m.status or "todo"),
            ("Progress", f"{m.progress}%"),
            ("Workspace", f"#{ws.id} {ws.title}")]
    fields, extra = _field_preview(m, ws.template)
    if fields:
        rows.append(("Fields", "; ".join(f"{k}={v}" for k, v in fields)
                     + (f" · +{extra} more" if extra else "")))
    else:
        rows.append(("Fields", "—"))
    text = uic.render_page(
        uic.render_header(_ICON_ENT, m.title, ["Control", "Entities", m.title],
                          f"#{m.id}"),
        uic.render_section("Card", uic.render_information_card("Entity", rows)),
        footer=uic.render_footer("Delete is soft — the Telegram topic stays"))
    kb_rows = [
        uic.primary_row("✏️ Edit fields", f"ctl:ent:edit:{eid}"),
        uic.action_row(("🆔 Identity", f"ctl:ident:{eid}"),
                       ("💬 Topic", f"ctl:topic:view:{eid}")),
    ]
    if _kind_of(m) == KIND_CHARACTER:
        kb_rows.append(uic.action_row(("⚔️ Equip…", f"ctl:eq:pick:{eid}")))
    kb_rows.append(uic.action_row(("🗑 Delete", f"ctl:ent:del:{eid}")))
    kb_rows.append(uic.nav_row(_back_to_list(kind=_kind_of(m)),
                               f"ctl:ent:view:{eid}"))
    return text, uic.keyboard(*kb_rows)


def _find_entity(ctx: ControlContext, eid: int):
    ws, _a = _active_ws(ctx)
    if ws is None:
        return None, None
    for m in ctx.engine.list_milestones(ctx.user_id, ws.id):
        if m.id == eid:
            return m, ws
    return None, ws


def find_entity(ctx: ControlContext, eid: int):
    """Public lookup helper (display read only). Returns (milestone, ws) or
    (None, ws) when the entity is missing from the active workspace."""
    return _find_entity(ctx, eid)


def _back_to_list(kind: str):
    return f"ctl:ent:list:{kind}" if kind else "ctl:ent:list"


def _missing_entity_page(what: str):
    body = uic.render_empty_state(
        "list", f"{what.title()} not found",
        "It may have been deleted or the workspace changed.",
        "Use Back to return.")
    return uic.render_page(
        uic.render_header(_ICON_ENT, "Not found", ["Control"]),
        body), uic.keyboard(uic.nav_row("ctl:home", "ctl:home"))


# ── M5-C: Topic Control Center ────────────────────────────────────────────

def _topic_status(ctx: ControlContext, ws_id, m):
    """(topic_id, locked, status_label, glyph) for one entity — read from the
    durable binding table, never a Telegram call (offline-safe)."""
    linked = ctx.storage.tg_bindings.get_binding(ws_id) is not None
    if not linked:
        return None, False, "no group", "🔌"
    topic_id = ctx.storage.tg_bindings.get_workspace_entity_topic(
        ws_id, ENTITY_TYPE, m.id)
    locked = ctx.storage.tg_bindings.get_entity_topic_locked(
        ws_id, ENTITY_TYPE, m.id)
    if topic_id is None:
        return None, False, "missing", "🕳"
    if locked:
        return topic_id, True, "locked", "🔒"
    return topic_id, False, "healthy", "✅"


def topic_center(ctx: ControlContext, page: int = 1):
    """M5-C: one canonical topic per entity — health list + repair."""
    ws, a = _active_ws(ctx)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_TOPIC, "Topic Center",
                              ["Control", "Topics"]), body), kb
    linked = ctx.storage.tg_bindings.get_binding(ws.id) is not None
    ms = ctx.engine.list_milestones(ctx.user_id, ws.id)
    # duplicate set (M5-C): normalized titles that appear more than once
    seen, dups = {}, set()
    for m in ms:
        key = _normalize_title(m.title)
        if key in seen:
            dups.add(key)
        else:
            seen[key] = m
    healthy = missing = locked = 0
    for m in ms:
        _tid, _lk, status, _g = _topic_status(ctx, ws.id, m)
        if _normalize_title(m.title) in dups and status != "no group":
            status = "duplicate"
        if status == "healthy":
            healthy += 1
        elif status == "locked":
            locked += 1
        elif status == "missing":
            missing += 1
    items = sorted(ms, key=lambda m: m.sort_order or 0)
    items, page, pages = _paginate(items, page, _PAGE_LEN["topic"])
    sections = [
        uic.render_section(
            "Group",
            uic.render_information_card(
                "Telegram link",
                [("Workspace", f"#{ws.id} {ws.title}"),
                 ("Linked", "yes" if linked else "no"),
                 ("Healthy topics", str(healthy)),
                 ("Missing", str(missing)),
                 ("Locked", str(locked)),
                 ("Duplicates", str(len(dups)))])),
    ]
    if not linked:
        sections.append(uic.render_section(
            "Repair", uic.render_warning(
                "Not linked to a group",
                "Link the workspace first (/linkhere) — topic tools refuse "
                "until then.")))
    body_lines = []
    for m in items:
        tid, locked_m, status, glyph = _topic_status(ctx, ws.id, m)
        if _normalize_title(m.title) in dups:
            status = "duplicate"
            glyph = "⧉"
        body_lines.append(
            f"{glyph} {b(esc(m.title))} (#{m.id}) — {esc(status)}"
            + (f" · topic #{tid}" if tid else ""))
    sections.append(uic.render_section(
        "Entity → topic", "\n".join(body_lines) or uic.render_empty_state(
            "chat", "No entities yet",
            "Add entities first, then return here to manage their topics.")))
    text = uic.render_page(
        uic.render_header(_ICON_TOPIC, "Topic Center",
                          ["Control", "Topics", ws.title],
                          f"page {page}/{pages}"),
        *sections,
        footer=uic.render_footer("Repair is idempotent — duplicates collapse "
                                 "onto one canonical topic"))
    rows = [uic.primary_row("🔧 Repair now", "ctl:topic:repair")]
    for m in items:
        rows.append(uic.action_row((f"{_KIND_GLYPH.get(_kind_of(m), '📄')} "
                                    f"{esc(m.title)}", f"ctl:topic:view:{m.id}")))
    rows.append(uic.nav_row("ctl:home", "ctl:topic:home"))
    if pages > 1:
        rows.append(uic.pagination_row("ctl:topic:home:p", page, pages))
    return text, uic.keyboard(*rows)


def topic_detail(ctx: ControlContext, eid: int):
    """M5-C: one entity's topic controls (Ensure / Lock / Unlock / Delete)."""
    m, ws = _find_entity(ctx, eid)
    if m is None:
        return _missing_entity_page("entity")
    linked = ctx.storage.tg_bindings.get_binding(ws.id) is not None
    topic_id, locked, status, glyph = _topic_status(ctx, ws.id, m)
    rows = [("Entity", f"#{m.id} {m.title}"),
            ("Kind", _kind_of(m)),
            ("Status", status), ("Topic ID", str(topic_id) if topic_id else "—"),
            ("Locked", "yes" if locked else "no"),
            ("Group", "linked" if linked else "not linked")]
    text = uic.render_page(
        uic.render_header(_ICON_TOPIC, "Topic", ["Control", "Topics", m.title]),
        uic.render_section("Binding", uic.render_information_card("Topic", rows)),
        footer=uic.render_footer("Delete removes ONLY the topic — the entity "
                                 "stays"))
    kb = uic.keyboard(
        uic.primary_row("➕ Ensure topic", f"ctl:topic:ensure:{eid}"),
        uic.action_row(("🔒 Lock", f"ctl:topic:lock:{eid}"),
                       ("🔓 Unlock", f"ctl:topic:unlock:{eid}")),
        uic.action_row(("🗑 Delete", f"ctl:topic:del:{eid}"),
                       ("🆔 Identity", f"ctl:ident:{eid}")),
        uic.nav_row("ctl:topic:home", f"ctl:topic:view:{eid}"),
    )
    return text, kb


# ── M5-D: identity inspector ──────────────────────────────────────────────

def identity_inspector(ctx: ControlContext, eid=None):
    """Name / Entity ID / Kind / Workspace ID+name / Topic ID / Topic status
    / Lock status / Active status — never secrets, never raw text."""
    if eid is None:
        ws, a = _active_ws(ctx)
        if ws is None or a.entity_id is None:
            body = uic.render_empty_state(
                "info", "No active entity",
                "Open an entity first, or pick one from the Entities page.",
                "ctl:ent:list")
            return uic.render_page(
                uic.render_header(_ICON_IDENT, "Identity Inspector",
                                  ["Control"]), body), uic.keyboard(
                    uic.nav_row("ctl:home", "ctl:ident:active"))
        eid = a.entity_id
    m, ws = _find_entity(ctx, eid)
    if m is None:
        return _missing_entity_page("entity")
    topic_id, locked, status, _glyph = _topic_status(ctx, ws.id, m)
    active_flag = ctx.groups.current(ctx.user_id).entity_id == eid
    rows = [
        ("Name", m.title),
        ("Entity ID", str(m.id)),
        ("Kind", _kind_of(m)),
        ("Workspace", f"#{ws.id} {ws.title}"),
        ("Topic ID", str(topic_id) if topic_id else "none"),
        ("Topic status", status),
        ("Lock status", "locked" if locked else ("—" if not topic_id else "unlocked")),
        ("Active", "active" if active_flag else "not active"),
    ]
    text = uic.render_page(
        uic.render_header(_ICON_IDENT, "Identity", ["Control", m.title]),
        uic.render_section("Inspector",
                           uic.render_information_card("Identity", rows)),
        footer=uic.render_footer("Linked = the workspace is bound to a group; "
                                 "lock is the durable topic protect bit"))
    kb = uic.keyboard(
        uic.action_row(("🗃 Entity", f"ctl:ent:view:{eid}"),
                       ("💬 Topic", f"ctl:topic:view:{eid}")),
        uic.nav_row("ctl:topic:home", f"ctl:ident:{eid}"),
    )
    return text, kb


# ── M5-E: equipment (minimal foundation) ──────────────────────────────────

def equip_home(ctx: ControlContext, page: int = 1):
    """M5-E: characters + current weapon, one Equip row each."""
    chars, ws = _characters(ctx)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_WS, "Equipment", ["Control", "Equipment"]),
            body), kb
    items, page, pages = _paginate(chars, page, _PAGE_LEN["equip"])
    lines = []
    for m in items:
        weapon = (m.fields or {}).get("weapon")
        lines.append(f"👤 {b(esc(m.title))} (#{m.id}) — "
                     f"{b(esc(weapon)) if weapon else esc('no weapon')}")
    body = "\n".join(lines) or uic.render_empty_state(
        "settings", "No characters yet",
        "Add a character entity, then equip a weapon onto it here.",
        "ctl:ent:add:character")
    text = uic.render_page(
        uic.render_header(_ICON_WS, "Equipment", ["Control", "Equipment"],
                          f"{ws.title} · page {page}/{pages}"),
        uic.render_section("Characters", body),
        footer=uic.render_footer("M5-E minimal: the character's existing "
                                 "'weapon' field — no second database"))
    rows = [uic.nav_row("ctl:home", "ctl:eq:home")]
    for m in items:
        rows.append(uic.action_row(
            (f"⚔️ {esc(m.title)}", f"ctl:eq:pick:{m.id}")))
    if pages > 1:
        rows.append(uic.pagination_row("ctl:eq:home:p", page, pages))
    return text, uic.keyboard(*rows)


def equip_pick(ctx: ControlContext, char_id: int):
    """Pick a weapon to equip on a character (or unequip)."""
    m, ws = _find_entity(ctx, char_id)
    if m is None:
        return _missing_entity_page("entity")
    weapons = [w for w in ctx.engine.list_milestones(ctx.user_id, ws.id)
               if _kind_of(w) == KIND_WEAPON]
    current = (m.fields or {}).get("weapon")
    rows_body = [("Character", f"#{m.id} {m.title}"),
                 ("Kind", _kind_of(m))]
    if current:
        rows_body.append(("Weapon", str(current)))
    text = uic.render_page(
        uic.render_header(_ICON_WS, "Equip", ["Control", "Equipment", m.title]),
        uic.render_section("Character",
                           uic.render_information_card("Target", rows_body)),
        uic.render_section("Choose weapon",
                           "\n".join(f"⚔️ {b(esc(w.title))} (#{w.id})"
                                     for w in weapons)
                           or uic.render_empty_state(
                               "settings", "No weapons in this workspace",
                               "Add a weapon entity first.",
                               "ctl:ent:add:weapon")),
        footer=uic.render_footer("Equip writes the character's 'weapon' field "
                                 "— deterministic, schema-permitting only"))
    kb_rows = []
    for w in weapons:
        kb_rows.append(uic.action_row(
            (f"⚔️ {esc(w.title)}", f"ctl:eq:set:{char_id}:{w.id}")))
    if current:
        kb_rows.append(uic.action_row(("✕ Unequip", f"ctl:eq:unequip:{char_id}")))
    kb_rows.append(uic.nav_row("ctl:eq:home", f"ctl:eq:pick:{char_id}"))
    return text, uic.keyboard(*kb_rows)


def _characters(ctx: ControlContext):
    ws, _a = _active_ws(ctx)
    if ws is None:
        return [], None
    ms = [m for m in ctx.engine.list_milestones(ctx.user_id, ws.id)
          if _kind_of(m) == KIND_CHARACTER]
    return ms, ws
