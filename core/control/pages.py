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
M5-E in `equip_home`/`equip_pick`. M6 knowledge/media/tag pages live in
`note_home`/`note_view`, `media_home`/`media_view`, and `tag_home`/`tag_view`.
All page chrome comes from ui_components (UI_SPEC_v1.md) -- never
hand-formatted HTML.
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
from core.retrieval.service import CrossReferenceService, RetrievalResult
from core.workspace.errors import EntityNotFound
from core.workspace.groups_app import ENTITY_TYPE, _normalize_title
from core.workspace.models import Note
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
    "note": 5,
    "media": 5,
    "tag": 6,
    "search": 5,
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
        uic.primary_row("📂 Workspaces", "ctl:ws:home"),
        uic.action_row(("📦 Entities", "ctl:ent:list"),
                       ("💬 Topic Center", "ctl:topic:home")),
        uic.action_row(("🆔 Identity", "ctl:ident:active"),
                       ("⚙️ Equipment", "ctl:eq:home")),
        uic.primary_row("🔍 Cross-Reference Search", "ctl:search:home"),
        uic.action_row(("📝 Knowledge (notes)", "ctl:note:home"),
                       ("📎 Media", "ctl:media:home")),
        uic.primary_row("🏷️ Tags", "ctl:tag:home"),
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


# ── M6: Knowledge (notes) ─────────────────────────────────────────────────
#
# Notes are DB-first records (spec §8 decision D): the list/view pages read
# them straight from the engine, and Telegram projection is an explicit
# per-note "Post to topic" action through the shared tool surface.

_ICON_KN = "search"
_ICON_MEDIA = "vision"
_ICON_TAG = "list"

_PAGE_LEN["note"] = 6
_PAGE_LEN["media"] = 5
_PAGE_LEN["tag"] = 8

_MEDIA_GLYPH = {
    "photo": "📷", "video": "🎬", "document": "📄",
    "audio": "🎵", "voice": "🎙",
}


def _truncate(text, limit: int) -> str:
    text = (text or "").replace("\n", " ")
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _note_line(n) -> str:
    title = _truncate(n.title or n.content, 48)
    return f"📝 {b(esc(title))} (#{n.id}) — {esc(n.kind or 'note')}"


def _media_line(att) -> str:
    label = _truncate(att.caption or att.file_name or att.telegram_file_id, 40)
    glyph = _MEDIA_GLYPH.get(att.file_type, "📎")
    return f"{glyph} {b(esc(label))} (#{att.id}) — {esc(att.file_type)}"


def _entity_info_map(ctx, ws) -> dict:
    """entity id → (title, semantic kind) for the active workspace (display
    read only — never resolves references)."""
    return {m.id: (m.title, _kind_of(m))
            for m in ctx.engine.list_milestones(ctx.user_id, ws.id)}


def _note_display(ctx, note_id) -> Note | None:
    """Ownership-checked note fetch for display; None when missing/deleted."""
    try:
        return ctx.engine.get_note(ctx.user_id, note_id)
    except EntityNotFound:
        return None


def _media_display(ctx, media_id):
    try:
        return ctx.engine.get_media(ctx.user_id, media_id)
    except EntityNotFound:
        return None


def _tag_display(ctx, tag_id):
    try:
        return ctx.engine.get_tag(ctx.user_id, tag_id)
    except EntityNotFound:
        return None


def note_home(ctx: ControlContext, page: int = 1, q: str | None = None):
    """M6 Knowledge: the active workspace's notes (newest first), with a
    search box (one-shot gather) and Add. `q` renders a filtered list."""
    ws, _a = _active_ws(ctx)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_KN, "Knowledge", ["Control", "Knowledge"]),
            body), kb
    if q:
        notes = ctx.engine.search_notes(ctx.user_id, ws.id, q=q, limit=50)
        caption = f"{len(notes)} match(es) for {esc(q)}"
    else:
        notes = ctx.engine.list_notes(ctx.user_id, ws.id)
        caption = f"{len(notes)} note(s)"
    items, page, pages = _paginate(notes, page, _PAGE_LEN["note"])
    sections = [uic.render_section(
        "Notes",
        "\n".join(_note_line(n) for n in items) or uic.render_empty_state(
            "search", "No notes match",
            "Dump knowledge with the Worker, or Add below."))]
    text = uic.render_page(
        uic.render_header(_ICON_KN, "Knowledge",
                          ["Control", "Knowledge", ws.title],
                          f"{caption} · page {page}/{pages}"),
        *sections,
        footer=uic.render_footer("Notes are DB records — projecting to a "
                                 "Telegram topic is optional and explicit"))
    rows = []
    if q:
        rows.append(uic.action_row(("➕ Add note", "ctl:note:add"),
                                   ("✕ Clear search", "ctl:note:home")))
    else:
        rows.append(uic.action_row(("➕ Add note", "ctl:note:add"),
                                   ("🔍 Search", "ctl:note:search")))
    for n in items:
        rows.append(uic.action_row((_note_line(n), f"ctl:note:view:{n.id}")))
    rows.append(uic.nav_row("ctl:home", "ctl:note:home"))
    if pages > 1 and not q:
        rows.append(uic.pagination_row("ctl:note:home:p", page, pages))
    return text, uic.keyboard(*rows)


def note_view(ctx: ControlContext, note_id: int):
    """M6 Knowledge: one note's content + linked entities + tags + actions
    (edit / delete / post-to-topic / link)."""
    ws, _a = _active_ws(ctx)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_KN, "Knowledge", ["Control", "Knowledge"]),
            body), kb
    note = _note_display(ctx, note_id)
    if note is None:
        return _missing_entity_page("note")
    info_map = _entity_info_map(ctx, ws)
    entities = ctx.engine.note_entities(ctx.user_id, note_id)
    tags = ctx.engine.note_tags(ctx.user_id, note_id)
    info_rows = [("Kind", note.kind or "note"),
                 ("Created", note.created_at or "—")]
    if note.title:
        info_rows.insert(0, ("Title", note.title))
    if note.updated_at:
        info_rows.append(("Updated", note.updated_at))
    ent_lines = []
    for etype, eid in entities:
        title, kind = info_map.get(eid, (f"#{eid}", ""))
        glyph = _KIND_GLYPH.get(kind, "📄")
        ent_lines.append(f"{glyph} {b(esc(title))} ({etype} #{eid})")
    tag_lines = [f"🏷 {b(esc(t.name))}" for t in tags]
    text = uic.render_page(
        uic.render_header(_ICON_KN, "Note",
                          ["Control", "Knowledge", ws.title], f"#{note_id}"),
        uic.render_section("Note",
                           uic.render_information_card("Note", info_rows)),
        uic.render_section("Content",
                           uic.blockquote(_truncate(note.content, 400))),
        uic.render_section("Entities", "\n".join(ent_lines) or "—"),
        uic.render_section("Tags", "\n".join(tag_lines) or "—"),
        footer=uic.render_footer("Delete hides the DB row only — the Telegram "
                                 "topic and messages are never touched"))
    rows = [uic.action_row(("✏️ Edit", f"ctl:note:edit:{note_id}"),
                           ("🗑 Delete", f"ctl:note:del:{note_id}"))]
    if ctx.projection_factory is not None and entities:
        rows.append(uic.action_row(
            ("📝 Post to topic", f"ctl:note:post:{note_id}")))
    rows.append(uic.action_row(
        ("🔗 Link entity", f"ctl:note:link-ent:{note_id}"),
        ("🏷 Link tag", f"ctl:note:link-tag:{note_id}")))
    for etype, eid in entities:
        title, _kind = info_map.get(eid, (f"#{eid}", ""))
        rows.append(uic.action_row(
            (f"✕ {_truncate(title, 20)}", f"ctl:note:unlink-ent:{note_id}:{eid}")))
    for t in tags:
        rows.append(uic.action_row(
            (f"✕ {t.name}", f"ctl:note:unlink-tag:{note_id}:{t.id}")))
    rows.append(uic.nav_row("ctl:note:home", f"ctl:note:view:{note_id}"))
    return text, uic.keyboard(*rows)


# ── M6: Media (Telegram metadata index) ───────────────────────────────────

def media_home(ctx: ControlContext, page: int = 1, media_type=None,
               entity_id=None, tag_id=None, q: str | None = None):
    """M6 Media: the workspace's media-metadata index, filterable by type /
    entity / tag / search. Pure reads — the blob stays in Telegram."""
    ws, _a = _active_ws(ctx)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_MEDIA, "Media", ["Control", "Media"]),
            body), kb
    info_map = _entity_info_map(ctx, ws)
    if media_type is not None:
        media = ctx.engine.search_media(ctx.user_id, ws.id,
                                        media_type=media_type, limit=50)
        label = f"{_MEDIA_GLYPH.get(media_type, '📎')} {media_type}"
        clear = "ctl:media:home"
    elif entity_id is not None:
        media = ctx.engine.search_media(
            ctx.user_id, ws.id, entity_type=ENTITY_TYPE,
            entity_id=entity_id, limit=50)
        ent_title = info_map.get(entity_id, (f"#{entity_id}", ""))[0]
        label = f"linked to {ent_title}"
        clear = "ctl:media:home"
    elif tag_id is not None:
        media = ctx.engine.search_media(ctx.user_id, ws.id, tag_id=tag_id,
                                        limit=50)
        tag_name = _tag_display(ctx, tag_id).name if _tag_display(ctx, tag_id) else f"#{tag_id}"
        label = f"tagged {tag_name}"
        clear = "ctl:media:home"
    elif q:
        media = ctx.engine.search_media(ctx.user_id, ws.id, q=q, limit=50)
        label = f"{len(media)} match(es) for {q}"
        clear = "ctl:media:home"
    else:
        media = ctx.engine.list_media(ctx.user_id, ws.id)
        label = f"{len(media)} record(s)"
        clear = None
    filtered = media_type is not None or entity_id is not None \
        or tag_id is not None or bool(q)
    items, page, pages = _paginate(media, page, _PAGE_LEN["media"])
    sections = [uic.render_section(
        "Media",
        "\n".join(_media_line(m) for m in items) or uic.render_empty_state(
            "vision", "No media records",
            "Send a photo/video/document/audio to the bot, or the Worker "
            "stores metadata with store_media."))]
    text = uic.render_page(
        uic.render_header(_ICON_MEDIA, "Media", ["Control", "Media", ws.title],
                          f"{label} · page {page}/{pages}"),
        *sections,
        footer=uic.render_footer("SQLite stores metadata + Telegram ids only "
                                 "— the file stays in Telegram"))
    rows = []
    if filtered:
        rows.append(uic.action_row(("🔍 Search", "ctl:media:search"),
                                   ("✕ Clear filter", clear)))
    else:
        rows.append(uic.action_row(("📷 Photo", "ctl:media:list:type:photo"),
                                   ("🎬 Video", "ctl:media:list:type:video"),
                                   ("📄 Doc", "ctl:media:list:type:document")))
        rows.append(uic.action_row(("🎵 Audio", "ctl:media:list:type:audio"),
                                   ("🔍 Search", "ctl:media:search")))
    for m in items:
        rows.append(uic.action_row((_media_line(m), f"ctl:media:view:{m.id}")))
    rows.append(uic.nav_row("ctl:home", "ctl:media:home"))
    if pages > 1 and not filtered:
        rows.append(uic.pagination_row("ctl:media:home:p", page, pages))
    return text, uic.keyboard(*rows)


def media_view(ctx: ControlContext, media_id: int):
    """M6 Media: one media record's metadata + links + actions. Resend is a
    documented follow-up (the file_id is shown; automatic re-post needs the
    consolidated live pass)."""
    ws, _a = _active_ws(ctx)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_MEDIA, "Media", ["Control", "Media"]),
            body), kb
    att = _media_display(ctx, media_id)
    if att is None:
        return _missing_entity_page("media")
    info_map = _entity_info_map(ctx, ws)
    entities = ctx.engine.media_entities(ctx.user_id, media_id)
    tags = ctx.engine.media_tags(ctx.user_id, media_id)
    rows = [("Type", att.file_type),
            ("Telegram file", _truncate(att.telegram_file_id, 32)),
            ("Created", att.created_at or "—")]
    if att.caption:
        rows.insert(1, ("Caption", _truncate(att.caption, 60)))
    if att.file_name:
        rows.append(("File name", _truncate(att.file_name, 40)))
    if att.message_id:
        rows.append(("Message", f"#{att.message_id} (chat {att.chat_id or '—'})"))
    if att.extracted_text:
        rows.append(("Extracted text", _truncate(att.extracted_text, 60)))
    ent_lines = []
    for etype, eid in entities:
        title, kind = info_map.get(eid, (f"#{eid}", ""))
        glyph = _KIND_GLYPH.get(kind, "📄")
        ent_lines.append(f"{glyph} {b(esc(title))} ({etype} #{eid})")
    tag_lines = [f"🏷 {b(esc(t.name))}" for t in tags]
    text = uic.render_page(
        uic.render_header(_ICON_MEDIA, "Media",
                          ["Control", "Media", ws.title], f"#{media_id}"),
        uic.render_section("Record",
                           uic.render_information_card("Media", rows)),
        uic.render_section("Entities", "\n".join(ent_lines) or "—"),
        uic.render_section("Tags", "\n".join(tag_lines) or "—"),
        footer=uic.render_footer("Delete removes metadata + links only — the "
                                 "Telegram message and file stay"))
    kb_rows = [uic.action_row(("✏️ Edit", f"ctl:media:edit:{media_id}"),
                              ("🗑 Delete", f"ctl:media:del:{media_id}")),
               uic.action_row(("🔗 Link entity", f"ctl:media:link-ent:{media_id}"),
                              ("🏷 Link tag", f"ctl:media:link-tag:{media_id}"))]
    for etype, eid in entities:
        title, _kind = info_map.get(eid, (f"#{eid}", ""))
        kb_rows.append(uic.action_row(
            (f"✕ {_truncate(title, 20)}",
             f"ctl:media:unlink-ent:{media_id}:{eid}")))
    for t in tags:
        kb_rows.append(uic.action_row(
            (f"✕ {t.name}", f"ctl:media:unlink-tag:{media_id}:{t.id}")))
    kb_rows.append(uic.nav_row("ctl:media:home", f"ctl:media:view:{media_id}"))
    return text, uic.keyboard(*kb_rows)


# ── M6: Tags ──────────────────────────────────────────────────────────────

def tag_home(ctx: ControlContext, page: int = 1):
    """M6 Tags: the workspace's tags, one row each. Same name in another
    workspace is a different tag."""
    ws, _a = _active_ws(ctx)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_TAG, "Tags", ["Control", "Tags"]),
            body), kb
    tags = ctx.engine.list_tags(ctx.user_id, ws.id)
    items, page, pages = _paginate(tags, page, _PAGE_LEN["tag"])
    sections = [uic.render_section(
        "Tags",
        "\n".join(f"🏷 {b(esc(t.name))} (#{t.id})" for t in items)
        or uic.render_empty_state(
            "list", "No tags yet",
            "Tag notes/media — or create one here."))]
    text = uic.render_page(
        uic.render_header(_ICON_TAG, "Tags", ["Control", "Tags", ws.title],
                          f"{len(tags)} tag(s) · page {page}/{pages}"),
        *sections,
        footer=uic.render_footer("Tags are workspace-scoped — the same name "
                                 "in another workspace is a distinct tag"))
    rows = [uic.primary_row("➕ Add tag", "ctl:tag:add")]
    for t in items:
        rows.append(uic.action_row((f"🏷 {t.name}", f"ctl:tag:view:{t.id}")))
    rows.append(uic.nav_row("ctl:home", "ctl:tag:home"))
    if pages > 1:
        rows.append(uic.pagination_row("ctl:tag:home:p", page, pages))
    return text, uic.keyboard(*rows)


def tag_view(ctx: ControlContext, tag_id: int):
    """M6 Tags: one tag's linked notes/media (tags never link to milestones
    directly — the 'entities of a tag' view is the indirect note/media one)."""
    ws, _a = _active_ws(ctx)
    if ws is None:
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header(_ICON_TAG, "Tags", ["Control", "Tags"]),
            body), kb
    tag = _tag_display(ctx, tag_id)
    if tag is None:
        return _missing_entity_page("tag")
    links = ctx.engine.tag_links(ctx.user_id, tag_id)
    note_ids = [eid for etype, eid in links if etype == "note"]
    media_ids = [eid for etype, eid in links if etype == "attachment"]
    note_lines = []
    for nid in note_ids[:10]:
        n = _note_display(ctx, nid)
        if n:
            note_lines.append(_note_line(n))
    media_lines = []
    for mid in media_ids[:10]:
        m = _media_display(ctx, mid)
        if m:
            media_lines.append(_media_line(m))
    text = uic.render_page(
        uic.render_header(_ICON_TAG, "Tag", ["Control", "Tags", ws.title],
                          f"#{tag_id}"),
        uic.render_section("Tag",
                           uic.render_information_card(
                               "Tag", [("Name", tag.name), ("ID", str(tag.id))])),
        uic.render_section("Linked notes", "\n".join(note_lines) or "—"),
        uic.render_section("Linked media", "\n".join(media_lines) or "—"),
        footer=uic.render_footer("Delete un-tags every linked note/media — "
                                 "the items themselves are kept"))
    kb_rows = [uic.action_row(("✏️ Rename", f"ctl:tag:rename:{tag_id}"),
                              ("🗑 Delete", f"ctl:tag:del:{tag_id}"))]
    for nid in note_ids[:10]:
        kb_rows.append(uic.action_row((f"📝 #{nid}", f"ctl:note:view:{nid}")))
    for mid in media_ids[:10]:
        kb_rows.append(uic.action_row((f"📎 #{mid}", f"ctl:media:view:{mid}")))
    kb_rows.append(uic.nav_row("ctl:tag:home", f"ctl:tag:view:{tag_id}"))
    return text, uic.keyboard(*kb_rows)


# ── M7: Cross-Reference Search ──────────────────────────────────────────────

def _search_result_line(r: RetrievalResult) -> str:
    """Format a RetrievalResult for list display."""
    if r._type == "note":
        title = r.title or "(untitled)"
        return f"  📝 #{r.note_id} {esc(title)}"
    else:
        ft = r.file_type or "media"
        fn = r.file_name or "(unnamed)"
        return f"  🎬 #{r.media_id} [{ft}] {esc(fn)}"


def _search_result_kb_line(r: RetrievalResult) -> tuple[str, str]:
    """Return (label, callback_data) for a search result row."""
    if r._type == "note":
        title = r.title or "(untitled)"
        return (f"📝 #{r.note_id} {_truncate(title, 30)}", f"ctl:note:view:{r.note_id}")
    else:
        ft = r.file_type or "media"
        fn = r.file_name or "(unnamed)"
        return (f"🎬 #{r.media_id} [{ft}] {_truncate(fn, 25)}", f"ctl:media:view:{r.media_id}")




def _search_config_page(ctx: ControlContext, ws, ws_id, page: int,
                        q: str | None, entities: str | None, entity_mode: str,
                        tags: str | None, tag_mode: str, media_type: str | None,
                        kind: str | None, created_after: str | None,
                        created_before: str | None, limit: int, scope: str):
    """Render the search configuration page showing current filters WITHOUT executing."""
    ws_title = ws.title if ws else ("All workspaces" if scope == "all" else "Active workspace")

    # Build caption showing current filters
    caption_parts = []
    if q:
        caption_parts.append(f"text={esc(q)}")
    if entities:
        caption_parts.append(f"entities={esc(entities)} ({entity_mode})")
    if tags:
        caption_parts.append(f"tags={esc(tags)} ({tag_mode})")
    if media_type:
        caption_parts.append(f"type={media_type}")
    if kind:
        caption_parts.append(f"kind={kind}")
    if created_after or created_before:
        date_range = f"{created_after or '..'}..{created_before or '..'}"
        caption_parts.append(f"date={date_range}")
    caption = f"Filters: {' | '.join(caption_parts)}" if caption_parts else "No filters set — configure below, then press  Search to execute"

    text = uic.render_page(
        uic.render_header("search", "Cross-Reference Search",
                          ["Control", "Search", ws_title],
                          caption),
        uic.render_section("Current Filters",
            "\n".join(f"  • {p}" for p in caption_parts) if caption_parts else "  (none)"),
        footer=uic.render_footer("Configure filters below, then press  Search to execute"))

    rows = []
    # Main action buttons
    rows.append(uic.primary_row("🔍 Execute Search", "ctl:search:execute"))
    rows.append(uic.action_row(("🗑️ Clear All", "ctl:search:clear")))
    # Filter configuration buttons
    rows.append(uic.action_row(("📂 Workspace", "ctl:search:ws"),
                               ("📦 Entities", "ctl:search:entities"),
                               ("🏷️ Tags", "ctl:search:tags")))
    rows.append(uic.action_row(("🔀 AND/OR", "ctl:search:mode"),
                               ("📅 Dates", "ctl:search:dates"),
                               ("📎 Media type", "ctl:search:mtype")))
    rows.append(uic.action_row(("📦 Scope", "ctl:search:scope")))
    # Kind filter (notes only)
    rows.append(uic.action_row(("📝 Kind (notes)", "ctl:search:kind")))

    rows.append(uic.nav_row("ctl:home", "ctl:search:home"))
    return text, uic.keyboard(*rows)

def search_home(ctx: ControlContext, page: int = 1,
                workspace: str | int | None = None,
                q: str | None = None,
                entities: str | None = None,
                entity_mode: str = "and",
                tags: str | None = None,
                tag_mode: str = "and",
                media_type: str | None = None,
                kind: str | None = None,
                created_after: str | None = None,
                created_before: str | None = None,
                limit: int = 50,
                scope: str = "active",
                execute: bool = False):
    """M7 Cross-Reference Search: unified search over notes AND media.

    Uses the SAME CrossReferenceService the Worker uses — no direct SQL.
    `workspace` defaults to active (per spec: active workspace is mandatory
    unless an explicit cross-workspace query). `scope` can be 'active' or
    'all' (explicit cross-workspace). All filters support AND/OR modes.

    When `execute=False` (default), renders the configuration page showing
    current filter values WITHOUT executing the search.
    When `execute=True`, runs the search and renders results.
    """
    # Determine workspace
    ws_id = None
    ws = None
    if scope == "all":
        # Cross-workspace search (explicit opt-in) — we'll search all workspaces
        pass  # handled by service
    elif workspace:
        ws = ctx.engine.get_workspace_or_none(ctx.user_id, workspace)
        if ws:
            ws_id = ws.id
    else:
        ws, _a = _active_ws(ctx)
        if ws:
            ws_id = ws.id

    if ws_id is None and scope != "all":
        body, kb = _no_active_section("ctl:ws:home")
        return uic.render_page(
            uic.render_header("search", "Search", ["Control", "Search"]),
            body), kb

    # If not executing, render configuration page only
    if not execute:
        return _search_config_page(ctx, ws, ws_id, page, q, entities, entity_mode,
                                   tags, tag_mode, media_type, kind,
                                   created_after, created_before, limit, scope)

    # Use the CrossReferenceService
    svc = CrossReferenceService(ctx.engine)
    results = svc.search(
        user_id=ctx.user_id,
        workspace_id=ws_id or 0,  # 0 for 'all' scope — service handles it
        q=q,
        entities=entities.split(",") if entities else None,
        entity_mode=entity_mode,
        tags=tags.split(",") if tags else None,
        tag_mode=tag_mode,
        media_type=media_type,
        created_after=created_after,
        created_before=created_before,
        limit=limit,
        kind=kind,
    )

    caption_parts = []
    if q:
        caption_parts.append(f"text={esc(q)}")
    if entities:
        caption_parts.append(f"entities={esc(entities)} ({entity_mode})")
    if tags:
        caption_parts.append(f"tags={esc(tags)} ({tag_mode})")
    if media_type:
        caption_parts.append(f"type={media_type}")
    if kind:
        caption_parts.append(f"kind={kind}")
    if created_after or created_before:
        date_range = f"{created_after or '..'}..{created_before or '..'}"
        caption_parts.append(f"date={date_range}")
    caption = f"{len(results)} result(s)" + (f" — {' | '.join(caption_parts)}" if caption_parts else "")

    items, page, pages = _paginate(results, page, _PAGE_LEN["search"])

    sections = [uic.render_section(
        "Results",
        "\n".join(_search_result_line(r) for r in items)
        or uic.render_empty_state(
            "search", "No results",
            "Try broadening your filters or search all workspaces."))]

    ws_title = ws.title if ws else ("All workspaces" if scope == "all" else "Active workspace")
    text = uic.render_page(
        uic.render_header("search", "Cross-Reference Search",
                          ["Control", "Search", ws_title],
                          f"{caption} · page {page}/{pages}"),
        *sections,
        footer=uic.render_footer("Results use the SAME retrieval service as the "
                                 "AI Worker — active workspace is the default"))

    rows = []
    # Filter actions
    rows.append(uic.action_row(("🔍 Search", "ctl:search:gather"),
                               ("✕ Clear", "ctl:search:clear")))
    rows.append(uic.action_row(("📂 Workspace", "ctl:search:ws"),
                               ("📦 Entities", "ctl:search:entities"),
                               ("🏷 Tags", "ctl:search:tags")))
    rows.append(uic.action_row(("🔀 AND/OR", "ctl:search:mode"),
                               ("📅 Dates", "ctl:search:dates"),
                               ("📎 Media type", "ctl:search:mtype")))
    rows.append(uic.action_row(("📦 Scope", "ctl:search:scope")))

    for r in items:
        label, cb = _search_result_kb_line(r)
        rows.append(uic.action_row((label, cb)))

    rows.append(uic.nav_row("ctl:home", "ctl:search:home"))
    if pages > 1:
        rows.append(uic.pagination_row("ctl:search:home:p", page, pages))
    return text, uic.keyboard(*rows)
