"""
render.py -- shared entity-card / activity-message rendering (v15.1.0-alpha.13).

The ONE place that turns a Workspace entity (a milestone under the hood) into
the Telegram HTML shown BOTH in the bot chat and inside the entity's forum
topic. The EntityManager (chat reply), the WorkspaceGroups create path, and
the Telegram projection's initial/update messages all render through here so
a topic's initial state can never drift from what the user sees in chat.

Hard rule: only ACTUAL stored field values are rendered. Missing/NULL fields,
dicts and lists are skipped -- nothing is ever invented, and every user value
is escaped through fmt.esc so it can't break the HTML.

Timestamps use IST (Asia/Kolkata) per CLAUDE.md -- never a bare
datetime.now(). Every module that needs "now" defines its own IST-aware
helper; this module's lives here.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from fmt import esc

IST = ZoneInfo("Asia/Kolkata")


def ist_stamp() -> str:
    """A user-facing IST timestamp, e.g. '10 Aug 2026, 18:42 IST'."""
    return datetime.now(IST).strftime("%d %b %Y, %H:%M IST")


def format_entity_card(entity, with_timestamp: bool = False) -> str:
    """HTML card for a single entity: title, status, then each stored field.

    Identical shape to the EntityManager's chat card (extracted verbatim in
    alpha.13 so the topic's initial message and the chat reply can never
    diverge). ``with_timestamp`` appends an IST stamp -- used for the topic
    initial card, never for the chat reply (which stays unchanged).
    """
    title = entity.title
    status = entity.status.replace("_", " ").title()

    lines = [f"<b>{esc(title)}</b>\n📌 Status: {status}"]

    # Structured fields, only what is actually stored.
    if entity.fields:
        for fname, fvalue in entity.fields.items():
            if fvalue is None or isinstance(fvalue, (dict, list)):
                continue
            display_name = fname.replace("_", " ").title()
            lines.append(f"{display_name}: {esc(str(fvalue))}")

    if with_timestamp:
        lines.append(f"Updated: {ist_stamp()}")

    return "\n".join(lines)


def format_entity_update(entity, changes: dict) -> str:
    """HTML append-only activity message after an entity field update.

    ``changes`` maps field name -> (old_value, new_value). The previous value
    is shown ONLY when the caller could capture it safely (old is not None);
    otherwise just the new value. Never rewrites or deletes anything.
    """
    title = entity.title
    lines = [f"<b>{esc(title)}</b> updated"]
    for fname, (old, new) in changes.items():
        display = fname.replace("_", " ").title()
        if old is None:
            lines.append(f"• {display} → {esc(str(new))}")
        else:
            lines.append(f"• {display}: {esc(str(old))} → {esc(str(new))}")
    lines.append(f"Updated: {ist_stamp()}")
    return "\n".join(lines)
