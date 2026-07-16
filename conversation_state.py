"""
Reliable conversation state manager.
Uses module-level dicts — survives across messages reliably.
"""

_states = {}
_context = {}
_history = {}

MAX_HISTORY = 10

def get_state(user_id: int) -> str:
    return _states.get(user_id, "idle")

def get_context(user_id: int) -> dict:
    return _context.get(user_id, {})

def set_state(user_id: int, state: str, context: dict = None):
    _states[user_id] = state
    if context is not None:
        _context[user_id] = context

def update_context(user_id: int, updates: dict):
    if user_id not in _context:
        _context[user_id] = {}
    _context[user_id].update(updates)

def clear_state(user_id: int):
    _states[user_id] = "idle"
    _context[user_id] = {}

def add_history(user_id: int, role: str, content: str):
    if user_id not in _history:
        _history[user_id] = []
    _history[user_id].append({"role": role, "content": content})
    if len(_history[user_id]) > MAX_HISTORY:
        _history[user_id] = _history[user_id][-MAX_HISTORY:]

def get_history(user_id: int) -> list:
    return _history.get(user_id, [])

def clear_history(user_id: int):
    _history[user_id] = []

def set_pending_action(user_id: int, action_type: str, data: dict):
    update_context(user_id, {
        "pending_action": action_type,
        "pending_data": data
    })
    set_state(user_id, "confirming")

def get_pending_action(user_id: int) -> tuple:
    ctx = get_context(user_id)
    return ctx.get("pending_action"), ctx.get("pending_data", {})

def set_gathering(user_id: int, partial_data: dict, missing: list):
    update_context(user_id, {
        "partial_data": partial_data,
        "missing_fields": missing
    })
    set_state(user_id, "gathering")

def get_gathering(user_id: int) -> tuple:
    ctx = get_context(user_id)
    return ctx.get("partial_data", {}), ctx.get("missing_fields", [])

def set_editing(user_id: int, task_id: int):
    update_context(user_id, {"editing_task_id": task_id})
    set_state(user_id, "editing")

def get_editing_id(user_id: int) -> int:
    return get_context(user_id).get("editing_task_id")


# ── v14.12: ADR-011 Option A — state outranks intent-gated dispatch ──
# The three states that claim every incoming message outright (Legacy's
# handle_message() runs their branches before any command recognition):
#   confirming — the message is a yes/no/re-prompt answer
#   gathering  — the message fills a missing field
#   editing    — the message is the change description
# Intent-gated Offline dispatch must therefore only run in "idle".
# NOTE: this is deliberately stricter than ADR-011's illustrative
# parenthetical ("idle or editing") — Legacy's editing handler claims
# ALL editing-state messages, and the Offline editing path already has
# its own state-gated entry (continue_editing, ADR-009) that runs
# before Legacy's, so intent dispatch has no business in "editing".
INTERACTIVE_STATES = ("confirming", "gathering", "editing")


def claims_messages(state: str) -> bool:
    """True if this conversation state owns the next message outright,
    so intent-gated Offline dispatch must not run (ADR-011 Option A).
    main.py's Offline gate consults this before OfflineEngine.execute()."""
    return state in INTERACTIVE_STATES