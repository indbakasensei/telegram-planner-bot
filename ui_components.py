"""
ui_components.py — the reusable UI component library (UI Phase 0).

Implements UI_SPEC_v1.md §12 exactly: every future screen (Phases 1–9)
is assembled from these builders — hand-assembled messages fail review
(§13.2). This module is deliberately UNWIRED in Phase 0: no handler
imports it yet, so the running bot is byte-identical to before. Phase 1
re-expresses ui.py's existing cards on top of it; Phases 2–8 build the
screens. It is "dead" only the way core/intent/ was in Shadow Mode —
by staged design, fully covered by tests/test_ui_components.py.

Design rules enforced MECHANICALLY here (violations raise ValueError at
build time, so they surface in tests, not in review):

  - closed icon vocabulary (§5.5)          → icon() raises on unknown
  - canonical labels (§7)                  → LABELS table, label() raises
  - status never without words (§5.4/§6.3) → status builders require text
  - card row cap (§5.3)                    → information card ≤ 8 rows
  - message budget (§6.1)                  → render_page raises > 4000
  - callback_data ≤ 64 bytes (§5.7)        → button() raises
  - row width ≤ 3, ≤ 12 buttons (§6.2)     → keyboard() raises
  - nav order Back·Refresh·Home (§2.5)     → nav_row() builds it, callers
                                             can't reorder
  - confirmation order safe-left (§8)      → confirmation_row() fixes it

Every component is stateless, side-effect free, and independent of
handlers: text builders return HTML strings (built ONLY from fmt.py
helpers — user content is always escaped); button builders return
telegram objects but never touch the network. Each docstring documents
Purpose / Inputs / Outputs / Example / Used by (spec screen numbers).

MUST NOT (and does not): import database.py, core/, main.py, or any
handler module; perform I/O; read the clock except where a caller
passes datetimes in (timestamp helpers take explicit values — §5.6's
IST rule is the caller's responsibility, same as core/'s injected-clock
discipline).
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from fmt import DIVIDER, b, blockquote, esc, i

# ── §5.5: the closed icon vocabulary ─────────────────────────────────────
# Chrome + status icons. Unknown names raise: an icon outside the
# vocabulary is a spec violation and must fail in tests, not ship.
ICONS = {
    # chrome / navigation
    "home": "🏠", "task": "📌", "habit": "🌱", "goal": "🎯", "ai": "🧠",
    "stats": "📊", "settings": "⚙️", "dev": "🛠", "search": "🔍",
    "add": "➕", "edit": "✏️", "delete": "🗑", "back": "⬅",
    "refresh": "🔄", "duplicate": "⧉", "reminder": "⏰", "date": "📅",
    "calendar": "📆", "chat": "💬", "think": "💭", "vision": "📷",
    "export": "📤", "test": "🧪", "cancel": "✕", "confirm": "✓",
    # status
    "success": "✅", "warning": "⚠️", "error": "❌", "info": "ℹ️",
    "loading": "⏳", "streak": "🔥", "paused": "⏸", "recurring": "🔁",
    "priority_high": "🔴", "priority_medium": "🟡", "priority_low": "🟢",
    "flag_on": "🟢", "flag_off": "⚪",
    # Phase 1 vocabulary completion (UI_SPEC_v1.md §5.5): icons that were
    # ALREADY in production chrome before Phase 0 froze the vocabulary
    # (ui.py card headers since v9.0, fmt.task_line's monthly icon) --
    # documenting existing reality, not new chrome. Flagged for Board
    # ratification in the Phase 1 report.
    "list": "📋", "bell": "🔔", "recurring_monthly": "🗓",
}

# Recurrence-type → icon, the single owner of this mapping (Phase 1 --
# ui.py's recurrence_icon() delegates here; fmt.task_line's inline copy
# predates this and is scheduled for consolidation when its screens are
# migrated in Phases 2-3).
RECURRENCE_ICONS = {
    "daily": ICONS["recurring"],
    "weekly": ICONS["calendar"],
    "monthly": ICONS["recurring_monthly"],
}


def priority_dot(priority: str) -> str:
    """Purpose: priority → dot icon (§5.5), the single owner of the
    mapping (unknown/missing priorities render medium, matching the
    pre-Phase-1 behavior everywhere). Inputs: 'high'/'medium'/'low'.
    Outputs: 🔴/🟡/🟢. Used by: task rows/cards on every screen."""
    if priority == "high":
        return ICONS["priority_high"]
    if priority == "low":
        return ICONS["priority_low"]
    return ICONS["priority_medium"]

# ── §7: canonical button labels (closed table) ───────────────────────────
LABELS = {
    "add_task": "➕ Add Task", "add_habit": "➕ Add Habit",
    "home": "🏠 Home", "back": "⬅ Back", "refresh": "🔄 Refresh",
    "delete": "🗑 Delete", "edit": "✏️ Edit", "save": "✓ Save",
    "cancel": "✕ Cancel", "search": "🔍 Search",
    "statistics": "📊 Statistics", "settings": "⚙ Settings",
    "complete": "✓ Complete", "check_in": "✓ Check In",
    "duplicate": "⧉ Duplicate",
}

_MAX_MESSAGE = 4000        # §6.1 hard safety cap (design target 3,500)
_MAX_CALLBACK_BYTES = 64   # §5.7 Telegram limit
_MAX_ROW = 3               # §6.2
_MAX_BUTTONS = 12          # §5.7 design cap
_MAX_CARD_ROWS = 8         # §5.3


def icon(name: str) -> str:
    """Purpose: closed-vocabulary icon lookup (§5.5).
    Inputs: vocabulary key. Outputs: the emoji.
    Raises KeyError for anything outside the vocabulary.
    Example: icon("habit") -> "🌱". Used by: every screen."""
    if name not in ICONS:
        raise KeyError(
            f"icon {name!r} is not in UI_SPEC_v1.md §5.5's closed vocabulary")
    return ICONS[name]


def label(name: str) -> str:
    """Purpose: canonical button label lookup (§7).
    Inputs: table key. Outputs: the exact label text.
    Raises KeyError on unknown key (synonyms are spec violations).
    Example: label("add_task") -> "➕ Add Task". Used by: every keyboard."""
    if name not in LABELS:
        raise KeyError(
            f"label {name!r} is not in UI_SPEC_v1.md §7's canonical table")
    return LABELS[name]


# ── Typography (§5.1, §5.6) ──────────────────────────────────────────────

def page_title(icon_name: str, title: str) -> str:
    """Purpose: H1 — one per message, always line 1 (§5.1).
    Inputs: vocabulary icon key, title text (escaped, upper-cased).
    Outputs: 'ICON <b>TITLE</b>'.
    Example: page_title("habit", "Habits") -> '🌱 <b>HABITS</b>'.
    Used by: render_header(), i.e. every screen."""
    return f"{icon(icon_name)} {b(str(title).upper())}"


def subheader(text: str) -> str:
    """Purpose: H2 section heading (§5.1). Inputs: heading text.
    Outputs: bold line (caller supplies surrounding blank line via
    render_section). Example: subheader("Today") -> '<b>Today</b>'.
    Used by: render_section(), all hub screens."""
    return b(text)


def caption(text: str) -> str:
    """Purpose: meta/caption line (§5.1). Outputs: italic, escaped.
    Example: caption("3 active") -> '<i>3 active</i>'.
    Used by: headers, footers, list metadata everywhere."""
    return i(text)


def breadcrumb(*segments: str) -> str:
    """Purpose: the where-am-I line (§2.4). Inputs: path segments,
    root-first, WITHOUT the leading home icon (added here); max 3.
    Outputs: '<i>🏠 Dashboard › Tasks › Today</i>'.
    Raises ValueError above 3 segments (depth cap is architectural).
    Example: breadcrumb("Tasks", "Today"). Used by: every screen
    except Home (S02–S44)."""
    if len(segments) > 3:
        raise ValueError("UI_SPEC_v1.md §2.4: breadcrumbs have at most "
                         f"3 segments after Dashboard, got {len(segments)}")
    path = " › ".join([f"{ICONS['home']} Dashboard", *[esc(s) for s in segments]])
    return f"<i>{path}</i>"


def separator() -> str:
    """Purpose: THE divider (§5.1 — only between the H1 block and footer
    hints; never between list items). Outputs: fmt.DIVIDER.
    Used by: render_footer() when a hint is present."""
    return DIVIDER


def status_indicator(level: str, text: str) -> str:
    """Purpose: icon+words status pair — a status icon never appears
    without words (§5.4/§6.3). Inputs: level in
    success/warning/error/info/loading, short text.
    Outputs: '✅ Saved'-style line start. Raises on empty text.
    Used by: state renderers, dev cards, selftest rows."""
    if level not in ("success", "warning", "error", "info", "loading"):
        raise ValueError(f"unknown status level {level!r}")
    if not str(text).strip():
        raise ValueError("UI_SPEC_v1.md §6.3: a status icon never "
                         "appears without descriptive text")
    return f"{ICONS[level]} {esc(text)}"


def fmt_timestamp(dt, now=None) -> str:
    """Purpose: §5.6 date format — 'Tue 17 Jun' in the current year,
    '17 Jun 2027' otherwise. Inputs: datetime/date to render; `now`
    (same family) decides "current year" — REQUIRED to be passed by the
    caller for anything user-facing (IST discipline; this module never
    reads the clock). Outputs: formatted string.
    Used by: task/habit cards, stats screens."""
    if now is not None and dt.year != now.year:
        return dt.strftime("%d %b %Y")
    return dt.strftime("%a %d %b")


def fmt_time(dt_or_str) -> str:
    """Purpose: §5.6 time format — 24h 'HH:MM'. Accepts a datetime or a
    pre-formatted 'HH:MM' string (the schema stores strings).
    Used by: task/habit cards."""
    if hasattr(dt_or_str, "strftime"):
        return dt_or_str.strftime("%H:%M")
    return str(dt_or_str)


def progress_indicator(percent, width: int = 10) -> str:
    """Purpose: textual progress bar (evolves ui.progress_bar; §12).
    Inputs: 0–100 (clamped), bar width. Outputs: '▓▓▓░░░░░░░ 30%'.
    Used by: goal cards (S20), statistics screens (S29–S33)."""
    pct = max(0, min(100, int(percent)))
    filled = round(width * pct / 100)
    return "▓" * filled + "░" * (width - filled) + f" {pct}%"


# ── Rendering (§12): page skeleton ───────────────────────────────────────

def render_header(icon_name: str, title: str, crumb_segments=None,
                   caption_text: str | None = None) -> str:
    """Purpose: screen header — H1 + optional breadcrumb + optional
    caption (§2.4, §5.1). Inputs: icon key, title, iterable of
    breadcrumb segments (None/empty for Home), optional caption.
    Outputs: 1–3 lines of HTML.
    Example: render_header("habit", "Habits", ["Habits"], "3 active").
    Used by: every screen S01–S44."""
    lines = [page_title(icon_name, title)]
    if crumb_segments:
        lines.append(breadcrumb(*crumb_segments))
    if caption_text:
        lines.append(caption(caption_text))
    return "\n".join(lines)


def render_section(title: str, body: str) -> str:
    """Purpose: H2 + body block (§5.1: one blank line above the heading
    is added by render_page's join; none below). Inputs: section title,
    pre-built body HTML. Outputs: section HTML.
    Used by: hubs and detail screens."""
    return f"{subheader(title)}\n{body}"


def render_footer(hint: str | None = None) -> str:
    """Purpose: optional footer hint line, preceded by THE divider
    (§5.1). Inputs: hint text (italicized, escaped) or None.
    Outputs: footer HTML or ''. Used by: screens with usage hints."""
    if not hint:
        return ""
    return f"{separator()}\n{caption(hint)}"


def render_page(header: str, *sections: str, footer: str = "") -> str:
    """Purpose: assemble a complete screen message (§12): header +
    sections (one blank line between blocks, §5.1) + footer; enforces
    the §6.1 hard message cap. Inputs: pre-built header, section HTML
    blocks (empties skipped), optional footer. Outputs: full message
    HTML. Raises ValueError above 4,000 chars — overflow means the
    screen needs pagination or an expandable block, not a longer
    message. Used by: every screen."""
    blocks = [header, *[s for s in sections if s], footer]
    text = "\n\n".join(block for block in blocks if block)
    if len(text) > _MAX_MESSAGE:
        raise ValueError(
            f"UI_SPEC_v1.md §6.1: message is {len(text)} chars "
            f"(cap {_MAX_MESSAGE}) — paginate or use an expandable block")
    return text


# ── Cards (§5.3, §12) ────────────────────────────────────────────────────

def render_information_card(title: str, rows) -> str:
    """Purpose: labeled key-value card in a blockquote (§5.3, ≤ 8 rows).
    Inputs: card title, iterable of (label, value) pairs (both escaped).
    Outputs: bold title + blockquote body. Raises ValueError over 8
    rows. Example: render_information_card("Task", [("Due", "Fri")]).
    Used by: detail screens (S09, S18, S21), settings (S34–S38)."""
    rows = list(rows)
    if len(rows) > _MAX_CARD_ROWS:
        raise ValueError(
            f"UI_SPEC_v1.md §5.3: information card has {len(rows)} rows "
            f"(cap {_MAX_CARD_ROWS}) — move detail to a child screen")
    body = "\n".join(f"{esc(lbl)}: {esc(val)}" for lbl, val in rows)
    return f"{b(title)}\n{blockquote(body, escape=False)}"


def render_status_card(level: str, title: str, body: str) -> str:
    """Purpose: one-status-level card (§5.4): status headline + body in
    a blockquote. Inputs: level (success/warning/error/info), title,
    pre-built body HTML (already-escaped content). Outputs: card HTML.
    Used by: selftest/dev screens (S39–S44), action results."""
    return f"{status_indicator(level, title)}\n{blockquote(body, escape=False)}"


def render_statistics_card(title: str, metrics, progress_percent=None) -> str:
    """Purpose: metric card (§12). Inputs: title, iterable of
    (label, value) pairs, optional 0–100 progress. Outputs: bold title
    + blockquote of 'label: <b>value</b>' rows + optional §12 progress
    bar. Used by: statistics screens (S08, S17, S29–S33)."""
    lines = [f"{esc(lbl)}: {b(val)}" for lbl, val in metrics]
    if progress_percent is not None:
        lines.append(progress_indicator(progress_percent))
    return f"{b(title)}\n{blockquote(chr(10).join(lines), escape=False)}"


# ── States (§5.4, §11.3, §14) ────────────────────────────────────────────

def render_success(text: str, detail: str | None = None) -> str:
    """Purpose: success message (§5.4 — icon always with words).
    Inputs: headline, optional caption detail. Outputs: 1–2 lines.
    Example: render_success("Task saved", "id 17"). Used by: every
    action result."""
    out = f"{ICONS['success']} {b(text)}"
    return f"{out}\n{caption(detail)}" if detail else out


def render_warning(text: str, detail: str | None = None) -> str:
    """Purpose: warning message (§5.4). Shape mirrors render_success.
    Used by: validation issues, partial results."""
    out = f"{ICONS['warning']} {b(text)}"
    return f"{out}\n{caption(detail)}" if detail else out


def render_error(text: str, detail: str | None = None) -> str:
    """Purpose: error message (§5.4). Shape mirrors render_success.
    Used by: failed actions, dev diagnostics."""
    out = f"{ICONS['error']} {b(text)}"
    return f"{out}\n{caption(detail)}" if detail else out


def render_info(text: str, detail: str | None = None) -> str:
    """Purpose: informational notice (§5.4). Shape mirrors
    render_success. Used by: hints, feature-unavailable notices."""
    out = f"{ICONS['info']} {b(text)}"
    return f"{out}\n{caption(detail)}" if detail else out


_LOADING_VERBS = ("Loading", "Thinking", "Processing", "Refreshing")


def render_loading(verb: str = "Loading") -> str:
    """Purpose: the §11.3 loading state — sent, then EDITED with the
    result; only for AI/network calls > ~2s, never for DB reads.
    Inputs: one of Loading/Thinking/Processing/Refreshing (closed set —
    consistent vocabulary). Outputs: '⏳ <i>Thinking…</i>'.
    Used by: AI hub screens (S23–S27), plan/vision flows."""
    if verb not in _LOADING_VERBS:
        raise ValueError(f"loading verb must be one of {_LOADING_VERBS}")
    return f"{ICONS['loading']} <i>{verb}…</i>"


def render_empty_state(icon_name: str, headline: str,
                        hint: str | None = None,
                        example: str | None = None) -> str:
    """Purpose: the §14 empty-state template — icon + headline + one
    helpful line + optional example blockquote. Inputs: vocabulary icon
    key, headline, hint line, example command text (rendered italic in
    a blockquote). Outputs: empty-state HTML (CTA buttons are the
    keyboard's job). Used by: every list screen via the canonical
    builders below."""
    lines = [f"{icon(icon_name)} {b(headline)}"]
    if hint:
        lines.append(esc(hint))
    if example:
        lines.append(blockquote(i(example), escape=False))
    return "\n".join(lines)


# §14's canonical copy, one builder per context (mandatory wording —
# screens use these, never re-write the copy):

def empty_tasks() -> str:
    """§14 Tasks. Used by: S02/S06 (CTA: ➕ Add Task)."""
    return render_empty_state(
        "task", "No tasks — you're all caught up.",
        example="add task Read chapter 4 tomorrow 6pm")


def empty_today(week_count: int | None = None) -> str:
    """§14 Today. Used by: S03. `week_count` fills the pointer caption
    when known."""
    hint = (f"{week_count} due this week" if week_count else None)
    out = render_empty_state("task", "Nothing due today.")
    return f"{out}\n{caption(hint)}" if hint else out


def empty_overdue() -> str:
    """§14 Overdue. Used by: S05 (CTA: 📋 All tasks)."""
    return f"{ICONS['success']} {b('Nothing overdue. Keep it that way!')}"


def empty_habits() -> str:
    """§14 Habits. Used by: S13 (CTA: ➕ Add Habit)."""
    return render_empty_state(
        "habit", "No habits yet — start one small daily win.",
        example="addhabit Drink water at 09:00 daily")


def empty_statistics() -> str:
    """§14 Statistics. Used by: S08/S17/S29–S33 (CTA: 📋 Tasks)."""
    return render_empty_state(
        "stats", "Not enough data yet — complete a few tasks and check back.")


def empty_search(query: str) -> str:
    """§14 Search. Used by: S07 (CTA: 🔍 Search). Escapes the query."""
    return render_empty_state(
        "search", f'No matches for "{query}".',
        hint="Try fewer words — search covers tasks, memories, habits, goals.")


def empty_ai_history() -> str:
    """§14 AI history — honest about the v15 analytics gap. Used by: S32."""
    return render_empty_state(
        "ai", "No AI activity logged.",
        hint="Usage history arrives with v15 analytics.")


def empty_projects() -> str:
    """§14 Projects. Used by: S20–S22 (CTA: 🎯 Goals)."""
    return render_empty_state(
        "goal", "No active projects — attach materials to any goal to start one.")


def empty_dev(hint: str | None = None) -> str:
    """§14 Dev pages. Used by: S39–S44; `hint` is the
    subsystem-specific line (e.g. 'bugs list is empty')."""
    return render_empty_state("info", "No entries.", hint=hint)


def render_confirmation(question: str, preview_html: str,
                         danger: bool = False) -> str:
    """Purpose: confirmation dialog body (§8; buttons come from
    confirmation_row()). Inputs: the question, a PRE-BUILT preview
    (existing builders like format_summary()/format_preview() —
    embedded unescaped, wording byte-preserved per §13.1), and danger
    (adds the irreversibility caption). Outputs: dialog HTML.
    Used by: S12 delete confirm, create/duplicate confirms."""
    head = f"{ICONS['warning'] if danger else ICONS['info']} {b(question)}"
    out = f"{head}\n{blockquote(preview_html, escape=False)}"
    if danger:
        out += f"\n{caption('This cannot be undone.')}"
    return out


# ── Buttons (§2.5, §6.2, §7, §8) ─────────────────────────────────────────

def button(text: str, callback: str) -> InlineKeyboardButton:
    """Purpose: single inline button with the §5.7 callback-size check.
    Inputs: label text (use label() for canonical actions), callback
    data. Outputs: InlineKeyboardButton. Raises ValueError over 64
    UTF-8 bytes. Used by: every keyboard."""
    if len(callback.encode("utf-8")) > _MAX_CALLBACK_BYTES:
        raise ValueError(
            f"callback_data {callback!r} is "
            f"{len(callback.encode('utf-8'))} bytes (Telegram cap 64)")
    return InlineKeyboardButton(text, callback_data=callback)


def primary_row(text: str, callback: str) -> list:
    """Purpose: row 1 — the singular primary action (§8).
    Outputs: one-button row. Used by: every screen's first row."""
    return [button(text, callback)]


def action_row(*pairs) -> list:
    """Purpose: secondary/context row (§6.2: 2 buttons default, 3 max).
    Inputs: (text, callback) pairs. Outputs: button row. Raises on
    0 or > 3. Used by: rows 2–3 everywhere."""
    if not 1 <= len(pairs) <= _MAX_ROW:
        raise ValueError(
            f"UI_SPEC_v1.md §6.2: action rows hold 1–{_MAX_ROW} buttons, "
            f"got {len(pairs)}")
    return [button(t, cb) for t, cb in pairs]


def nav_row(back_cb: str | None = None, refresh_cb: str | None = None,
            home_cb: str | None = None) -> list:
    """Purpose: THE navigation row (§2.5) — order Back · Refresh · Home
    is fixed here so callers cannot reorder it; omissions follow the
    page-class table (root: refresh only; detail: back+home; etc.).
    Inputs: callback per slot, None to omit. Outputs: button row.
    Raises if all slots are None (no keyboard may lack an exit, §2.5).
    Used by: every non-modal screen."""
    row = []
    if back_cb:
        row.append(button(LABELS["back"], back_cb))
    if refresh_cb:
        row.append(button(LABELS["refresh"], refresh_cb))
    if home_cb:
        row.append(button(LABELS["home"], home_cb))
    if not row:
        raise ValueError("UI_SPEC_v1.md §2.5: navigation row cannot be empty")
    return row


def confirmation_row(cancel_cb: str, confirm_text: str,
                      confirm_cb: str) -> list:
    """Purpose: confirmation row (§8) — safe action LEFT, destructive/
    affirmative RIGHT, fixed here. Inputs: cancel callback, confirm
    label (e.g. '🗑 Yes, delete' or label('save')), confirm callback.
    Outputs: two-button row. Used by: S12 and every confirm dialog."""
    return [button(LABELS["cancel"], cancel_cb),
            button(confirm_text, confirm_cb)]


def pagination_row(namespace: str, page: int, total_pages: int) -> list:
    """Purpose: pagination footer (§2.3): '‹ Prev · 2/5 · Next ›'; the
    indicator is a no-op button; Prev/Next omitted at the edges.
    Inputs: pg-callback namespace (e.g. 'pg:tasks:overdue'), 1-based
    page, total pages. Outputs: button row.
    Used by: every list > 8 items."""
    row = []
    if page > 1:
        row.append(button("‹ Prev", f"{namespace}:{page - 1}"))
    row.append(button(f"{page}/{total_pages}", "noop"))
    if page < total_pages:
        row.append(button("Next ›", f"{namespace}:{page + 1}"))
    return row


def keyboard(*rows) -> InlineKeyboardMarkup:
    """Purpose: assemble the final keyboard with the §6.2/§5.7 caps —
    ≤ 3 buttons per row, ≤ 12 buttons total, no empty keyboards/rows.
    Inputs: button rows (from the builders above; empty rows skipped).
    Outputs: InlineKeyboardMarkup. Used by: every screen."""
    clean = [list(r) for r in rows if r]
    if not clean:
        raise ValueError("UI_SPEC_v1.md §2.5: no keyboard may be empty")
    for r in clean:
        if len(r) > _MAX_ROW:
            raise ValueError(
                f"UI_SPEC_v1.md §6.2: row of {len(r)} buttons (cap {_MAX_ROW})")
    total = sum(len(r) for r in clean)
    if total > _MAX_BUTTONS:
        raise ValueError(
            f"UI_SPEC_v1.md §5.7: {total} buttons on one message "
            f"(cap {_MAX_BUTTONS})")
    return InlineKeyboardMarkup(clean)
