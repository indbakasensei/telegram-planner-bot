"""
fmt.py — Telegram HTML formatting helpers (v7.1)

Telegram's HTML parse mode is far more robust than Markdown because only
three characters need escaping (< > &). Task titles with dots, dashes,
parentheses, plus signs etc. break Markdown but are safe in HTML.

Usage:
    from fmt import b, i, code, esc, HTML
    msg = f"{b('Task saved!')}\\n{esc(user_title)}"
    await update.message.reply_text(msg, parse_mode=HTML, ...)

Reference: https://core.telegram.org/bots/api#html-style
"""

HTML = "HTML"


def esc(text) -> str:
    """Escape the 3 HTML-special characters so user content can't break parsing."""
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def b(text) -> str:
    """Bold. Escapes content automatically."""
    return f"<b>{esc(text)}</b>"


def i(text) -> str:
    """Italic. Escapes content automatically."""
    return f"<i>{esc(text)}</i>"


def code(text) -> str:
    """Inline monospace. Escapes content automatically."""
    return f"<code>{esc(text)}</code>"


def u(text) -> str:
    """Underline."""
    return f"<u>{esc(text)}</u>"


def pre(text) -> str:
    """Preformatted block."""
    return f"<pre>{esc(text)}</pre>"


# ── Reusable UI components for consistent message styling ──

DIVIDER = "━━━━━━━━━━━━━━"


def header(title, emoji="") -> str:
    """A bold header line with optional emoji prefix."""
    prefix = f"{emoji} " if emoji else ""
    return f"{prefix}{b(title)}"


def task_line(task_id, title, time=None, date=None, priority="medium",
              done=False, recurrence=None) -> str:
    """
    Render a single task as a clean HTML line.
    Example: 🟡 [5] Study Physics · ⏰ 20:00 · 📅 Today
    """
    pri_emoji = "🔴" if priority == "high" else "🟢" if priority == "low" else "🟡"
    check = "✅ " if done else ""
    rec_icon = ""
    if recurrence == "daily":
        rec_icon = " 🔁"
    elif recurrence == "weekly":
        rec_icon = " 📆"
    elif recurrence == "monthly":
        rec_icon = " 🗓"

    line = f"{check}{pri_emoji} {code('[' + str(task_id) + ']')} {esc(title)}{rec_icon}"
    meta = []
    if time:
        meta.append(f"⏰ {esc(time)}")
    if date:
        meta.append(f"📅 {esc(date)}")
    if meta:
        line += "\n   <i>" + " · ".join(meta) + "</i>"
    return line


def confirm_box(title, date=None, time=None, category=None,
                priority=None, recurrence=None) -> str:
    """A clean confirmation card for a pending task."""
    lines = [f"📋 {b('Confirm this task')}", ""]
    lines.append(f"📌 {b(title)}")
    detail = []
    if date:
        detail.append(f"📅 Date: {esc(date)}")
    if time:
        detail.append(f"⏰ Time: {esc(time)}")
    if category:
        detail.append(f"🏷 Category: {esc(category)}")
    if priority:
        pri_emoji = "🔴" if priority == "high" else "🟢" if priority == "low" else "🟡"
        detail.append(f"{pri_emoji} Priority: {esc(priority)}")
    if recurrence:
        detail.append(f"🔁 Repeats: {esc(recurrence)}")
    lines.extend(detail)
    return "\n".join(lines)


def bullet(text, emoji="•") -> str:
    """A bullet line."""
    return f"{emoji} {text}"