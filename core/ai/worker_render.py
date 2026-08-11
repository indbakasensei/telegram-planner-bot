"""
worker_render.py -- v15.2 M4 -- response-format restoration (items 12/13).

WHY (PRODUCT REGRESSION, first live matrices): Worker replies came back as
raw LLM prose ("Xiao is now level 80") because main.py sent worker_result.reply
verbatim. The product rule (owner directive, M4 item 12):

    Worker decides WHAT happened. Existing BAKA formatter decides HOW it is
    displayed.

This module owns that boundary. It walks the run's step trace -- every ok
WorkerStep's ToolResult carries the ToolResult.data the tool actually produced
(ids, titles, kinds, fields) -- and maps each step onto the SAME Telegram-HTML
presentation the legacy handlers use: format_entity_card / format_entity_update
for entities, and task/goal/habit/workspace line templates matching the
dashboard cards. A Worker reply therefore comes out formatted, escaped, and
emoji'd exactly like a /use /add or dashboard reply -- never bare prose.

Offline + deterministic: imports only pure modules (fmt, core.workspace.render),
never Telegram, never a database. Entity cards need the STORED fields, which
the ToolResult.data does not carry, so main.py injects a `fetcher`
(user_id, entity_id) -> Milestone | None (engine.get_milestone); tests pass
None and get a compact typed fallback line instead of a full card.

Honesty + fallback preserved: when nothing in the trace renders (no ok steps,
or a graceful/declined termination) the original reply is returned (escaped
for HTML), so the Worker's honest summary and decline/fallback behavior are
unchanged. When steps DID render, the model's prose is NOT echoed -- the
structured blocks are the display.
"""
from __future__ import annotations

from core.workspace.render import format_entity_card, format_entity_update
from fmt import b, esc, i

# Presentation vocabulary, matching the existing dashboard/entity UI.
KIND_EMOJI = {
    "entity": "📦", "character": "🧑‍🦰", "weapon": "🗡️", "artifact": "💠",
    "goal": "🎯", "task": "📝", "habit": "🌱",
}
_DEFAULT_EMOJI = "📦"
_GROUP_EMOJI = {
    "goal": "🎯", "task": "📝", "habit": "🌱",
    "entity": "📦", "character": "🧑‍🦰", "weapon": "🗡️", "artifact": "💠",
}


def _kind_emoji(kind: str) -> str:
    return KIND_EMOJI.get((kind or "").lower(), _DEFAULT_EMOJI)


def _status_label(status: str | None) -> str:
    return esc((status or "todo").replace("_", " ").title())


# ── per-tool block renderers (each returns an HTML block or None) ─────────
def _entity_compact(data: dict) -> str:
    """Fallback card when no fetcher/card is available -- still formatted."""
    kind = (data.get("entity_type") or data.get("kind") or "entity").lower()
    title = data.get("title") or "?"
    return (f"{_kind_emoji(kind)} {b(esc(str(title)))}\n"
            f"📌 Status: {_status_label(data.get('status'))}")


def _entity_card(data: dict, user_id, fetcher) -> str | None:
    if user_id is not None and fetcher is not None and data.get("entity_id"):
        m = fetcher(user_id, data["entity_id"])
        if m is not None:
            return format_entity_card(m)
    return None


def _create_entity(data: dict, user_id, fetcher) -> str:
    title = esc(str(data.get("title") or "?"))
    kind = (data.get("entity_type") or "entity").lower()
    head = f"{_kind_emoji(kind)} {b(title)}"
    if data.get("adopted"):
        head = (f"🔀 {b(title)} is now a {esc(kind)} — one entity, one topic "
                f"(#{data.get('entity_id')}).")
        card = _entity_card(data, user_id, fetcher)
        return f"{head}\n{card}" if card else head
    head += f" created · id {data.get('entity_id')}"
    if data.get("workspace_title"):
        head += f" in {b(esc(str(data['workspace_title'])))}"
    if data.get("topic_created"):
        head += "\n🗂️ Telegram topic created"
    card = _entity_card(data, user_id, fetcher)
    return f"{head}\n{card}" if card else head


def _get_entity(data: dict, user_id, fetcher) -> str:
    card = _entity_card(data, user_id, fetcher)
    return card if card else _entity_compact(data)


def _update_entity(data: dict, user_id, fetcher) -> str:
    if user_id is not None and fetcher is not None and data.get("entity_id"):
        m = fetcher(user_id, data["entity_id"])
        changes = data.get("changes") or {}
        if m is not None and changes:
            return format_entity_update(m, changes)
    applied = data.get("applied") or {}
    bits = "; ".join(f"{k}={v}" for k, v in applied.items()) or "fields updated"
    return f"✏️ {b(esc(str(data.get('title') or '?')))} · {esc(bits)}"


def _group_label(kind: str) -> str:
    """Dashboard-style group header: 'character' -> 'Character',
    'goal' -> 'Goals' (plural like the dashboard cards), 'entity' ->
    'Workspace Entities'."""
    plural = {"character": "characters", "weapon": "weapons",
              "artifact": "artifacts", "entity": "workspace entities",
              "goal": "goals", "task": "tasks", "habit": "habits"}
    return plural.get(kind, kind + "s").title()


def _list_entities(data: list, user_id, fetcher) -> str:
    if not data:
        return i("Nothing found.")
    groups: dict[str, list] = {}
    for d in data:
        groups.setdefault((d.get("kind") or "entity").lower(), []).append(d)
    lines: list[str] = []
    for kind, items in groups.items():
        emoji = _GROUP_EMOJI.get(kind, _DEFAULT_EMOJI)
        lines.append(f"{emoji} {b(esc(_group_label(kind)))} · {len(items)}")
        for d in items:
            ident = (d.get("entity_id") or d.get("goal_id")
                     or d.get("task_id") or d.get("habit_id"))
            extra = ""
            if d.get("status"):
                extra += f" — {_status_label(d['status'])}"
            if d.get("deadline"):
                extra += f" · 📅 {esc(str(d['deadline']))}"
            if d.get("progress") is not None and d.get("target"):
                extra += f" · {d['progress']}/{d['target']}"
            if d.get("current_streak") is not None:
                extra += f" · streak {d['current_streak']}"
            lines.append(f"• #{ident} {esc(str(d.get('title') or '?'))}{extra}")
    return "\n".join(lines)


def _create_goal(data: dict) -> str:
    title = b(esc(str(data.get("title") or "?")))
    head = f"🎯 {title} goal set"
    if data.get("deadline"):
        head += f" · 📅 {esc(str(data['deadline']))}"
    return head


def _goal_progress(data: dict) -> str:
    if data.get("completed"):
        return f"🎯 Goal #{data.get('goal_id')} reached {data.get('progress')}/{data.get('target')} — complete!"
    return f"🎯 Goal #{data.get('goal_id')} · {data.get('progress')}/{data.get('target')}"


def _goal_deadline(data: dict) -> str:
    dl = data.get("deadline")
    when = f"📅 {esc(str(dl))}" if dl else "no deadline"
    title = data.get("title") or f"goal #{data.get('goal_id')}"
    return f"🎯 {b(esc(str(title)))} · deadline → {when}"


def _list_goals(data: list, user_id=None, fetcher=None) -> str:
    if not data:
        return i("No goals yet.")
    lines = []
    for g in data:
        pct = (int(g["progress"] / g["target"] * 100)
               if g.get("target") else g.get("progress"))
        line = f"🎯 {b(esc(str(g.get('title') or '?')))} · {g.get('progress')}/{g.get('target')} ({pct}%)"
        if g.get("deadline"):
            line += f" · 📅 {esc(str(g['deadline']))}"
        lines.append(line)
    return "\n".join(lines)


def _create_task(data: dict) -> str:
    head = f"✅ {b(esc(str(data.get('title') or '?')))}" f" · task #{data.get('task_id')}"
    if data.get("due_date"):
        head += f" · 📅 {esc(str(data['due_date']))}"
        if data.get("due_time"):
            head += f" {esc(str(data['due_time']))}"
    return head


def _task_action(data: dict, verb: str, emoji: str) -> str:
    title = data.get("title") or f"task #{data.get('task_id')}"
    return f"{emoji} {b(esc(str(title)))} {verb}"


def _list_tasks(data: list, user_id=None, fetcher=None) -> str:
    if not data:
        return i("No tasks.")
    return "\n".join(
        f"• #{t.get('task_id')} {esc(str(t.get('title') or '?'))}"
        + (f" · 📅 {esc(str(t['due_date']))}" if t.get("due_date") else "")
        for t in data)


def _create_habit(data: dict) -> str:
    return (f"🌱 {b(esc(str(data.get('title') or '?')))}"
            f" · habit #{data.get('habit_id')}"
            + (f" · ⏰ {esc(str(data['time']))}" if data.get("time") else ""))


def _habit_action(data: dict) -> str:
    if data.get("already_logged"):
        return f"🌱 Habit #{data.get('habit_id')} already logged today."
    return (f"🌱 Habit #{data.get('habit_id')} logged"
            + (f" — streak {data.get('streak')}" if data.get("streak") is not None else ""))


def _list_habits(data: list, user_id=None, fetcher=None) -> str:
    if not data:
        return i("No habits.")
    return "\n".join(
        f"• #{h.get('habit_id')} {esc(str(h.get('title') or '?'))}"
        + (f" · streak {h['current_streak']}" if h.get("current_streak") is not None else "")
        for h in data)


def _list_workspaces(data: list, user_id=None, fetcher=None) -> str:
    if not data:
        return i("No workspaces yet.")
    return "\n".join(
        f"• #{w.get('workspace_id')} {b(esc(str(w.get('title') or '?')))}"
        + (f" ({esc(str(w.get('template')))})" if w.get("template") else "")
        for w in data)


def _get_workspace(data: dict) -> str:
    return (f"🗂️ {b(esc(str(data.get('title') or '?')))}"
            f" · workspace #{data.get('workspace_id')}"
            + (f" · {esc(str(data.get('template')))})"
               if data.get("template") else ""))


def _open_workspace(data: dict) -> str:
    return f"🗂️ Active workspace → {b(esc(str(data.get('title') or '?')))} (#{data.get('workspace_id')})"


def _inspect_workspace(data: dict) -> str:
    return f"🗂️ {b(esc(str(data.get('title') or '?')))} — see the dashboard for details."


# ── topic lifecycle (v15.2 M4 items 7/8/10) ───────────────────────────────
def _get_entity_topic(data: dict) -> str:
    title = b(esc(str(data.get("title") or "?")))
    if data.get("topic_id") is None:
        return f"🗂️ {title} has no Telegram topic yet."
    lock = " 🔒" if data.get("locked") else ""
    return f"🗂️ {title} → topic #{data['topic_id']}{lock}"


def _ensure_entity_topic(data: dict) -> str:
    title = b(esc(str(data.get("title") or "?")))
    if data.get("topic_id") is None:
        if data.get("reason") == "not_linked":
            return (f"🗂️ Workspace isn't linked to a Telegram group — "
                    f"no topic for {title}.")
        return f"🗂️ No topic ensured for {title}."
    verb = "created" if data.get("created") else "already there"
    lock = " 🔒" if data.get("locked") else ""
    return f"🗂️ {title} → topic #{data['topic_id']} ({verb}){lock}"


def _set_entity_topic_locked(data: dict) -> str:
    title = b(esc(str(data.get("title") or "?")))
    if data.get("reason") == "not_linked":
        return f"🗂️ Can't lock {title}'s topic — workspace not linked."
    state = "🔒 locked" if data.get("locked") else "🔓 unlocked"
    return f"🗂️ {title}'s topic {state}."


def _delete_entity_topic(data: dict) -> str:
    """Reached on the Worker path only for an ok=False REFUSAL (locked /
    no_topic / not_linked): a successful delete is a DESTRUCTIVE op, so the
    mechanical confirmation gate stops the run BEFORE execute and main.py
    shows the confirmation text, never this renderer."""
    title = b(esc(str(data.get("title") or "?")))
    reason = data.get("reason")
    if reason == "locked":
        return (f"🔒 {title}'s topic is locked — unlock it first or pass "
                "force=true.")
    if reason == "no_topic":
        return f"🗂️ {title} has no topic to delete."
    if reason == "not_linked":
        return f"🗂️ Can't delete {title}'s topic — workspace not linked."
    if reason == "telegram_deleted":
        return (f"🗑️ {title}'s topic binding removed (Telegram couldn't "
                "delete the topic itself).")
    return f"🗑️ {title}'s topic deleted."


def _list_entity_topics(data: list, user_id=None, fetcher=None) -> str:
    if not data:
        return i("No entity topics in this workspace.")
    return "\n".join(
        f"• #{t.get('entity_id')} {b(esc(str(t.get('title') or '?')))}"
        f" — topic #{t.get('topic_id')}"
        + (" 🔒" if t.get("locked") else "")
        for t in data)


# tool name -> (block renderer, is_list)
_RENDERERS: dict[str, callable] = {
    "create_entity": _create_entity,
    "get_entity": _get_entity,
    "update_entity": _update_entity,
    "list_entities": _list_entities,
    "create_goal": _create_goal,
    "list_goals": _list_goals,
    "update_goal_progress": _goal_progress,
    "update_goal_deadline": _goal_deadline,
    "create_task": _create_task,
    "list_tasks": _list_tasks,
    "find_task": _list_tasks,
    "update_task": lambda d: _task_action(d, "updated", "✏️"),
    "complete_task": lambda d: _task_action(d, "done", "✅"),
    "delete_task": lambda d: _task_action(d, "deleted", "🗑️"),
    "create_habit": _create_habit,
    "list_habits": _list_habits,
    "complete_habit": _habit_action,
    "list_workspaces": _list_workspaces,
    "get_workspace": _get_workspace,
    "open_workspace": _open_workspace,
    "inspect_workspace": _inspect_workspace,
    # topic lifecycle (v15.2 M4 items 7/8/10)
    "get_entity_topic": _get_entity_topic,
    "ensure_entity_topic": _ensure_entity_topic,
    "set_entity_topic_locked": _set_entity_topic_locked,
    "delete_entity_topic": _delete_entity_topic,
    "list_entity_topics": _list_entity_topics,
}

# tools that render a LIST from a data list (data is the list itself).
_LIST_TOOLS = {"list_entities", "list_tasks", "list_goals", "list_habits",
               "list_workspaces", "find_task", "list_entity_topics"}
# topic tools whose ok=False result is a REFUSAL (locked / no_topic /
# not_linked), never an internal failure -- render the refusal text through
# the data renderer instead of a generic "failed" line.
_TOPIC_REFUSAL_RENDERERS = {"delete_entity_topic"}
# entity tools need (data, user_id, fetcher) to re-fetch the stored card;
# every other renderer takes just (data).
_ENTITY_FETCH_RENDERERS = {"create_entity", "get_entity", "update_entity"}


def render_run_reply(run, *, user_id=None, fetcher=None) -> str:
    """Compose the final Telegram-HTML reply from a run's step trace.

    ``run`` is a WorkerRunResult; ``fetcher(user_id, entity_id) -> Milestone|None``
    is injected by main.py to re-fetch entities so cards render with the full
    stored fields (tests pass None for compact lines). When no ok step renders,
    the original reply (escaped for HTML) is returned unchanged -- honesty and
    fallback behavior are preserved.
    """
    blocks: list[str] = []
    rendered = 0
    for s in run.steps:
        r = s.result
        if r is None:
            continue
        name = s.decision.tool_name
        renderer = _RENDERERS.get(name)
        if renderer is None:
            continue
        if r.ok:
            data = r.data
            if name in _LIST_TOOLS:
                block = (renderer(data, user_id, fetcher) if data
                         else i("Nothing found."))
            elif name in _ENTITY_FETCH_RENDERERS:
                block = renderer(data, user_id, fetcher)
            else:
                block = renderer(data)
            if block:
                blocks.append(block)
                rendered += 1
        elif name in _TOPIC_REFUSAL_RENDERERS and r.data:
            # A refused topic deletion (locked / no_topic / not_linked) is a
            # deliberate non-action, not an internal failure -- render the
            # refusal text (which says exactly why) instead of a generic
            # "failed" line.
            block = renderer(r.data)
            if block:
                blocks.append(block)
        else:
            # Honest failure line -- never hide a failed op.
            code = r.error_code or "tool_error"
            blocks.append(f"⚠️ {esc(str(name))} failed ({esc(str(code))})")

    if rendered == 0:
        # Nothing structured to show -- the worker's own reply (graceful
        # fallback, honest summary, or chat text) carries the message.
        return esc(run.reply or "")

    body = "\n\n".join(blocks)
    from core.ai.worker_contract import TerminationReason
    if run.termination is TerminationReason.MAX_STEPS:
        body = (f"⚠️ I could only fit part of that in one go — "
                f"here's what actually completed:\n\n{body}")
    return body
