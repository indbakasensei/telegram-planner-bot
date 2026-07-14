"""
action_result.py -- the Offline Engine's output contract (v14.2).

No Telegram objects. `message` is a plain, already Telegram-HTML-safe
string (built via fmt.py's helpers, which have zero imports of their own
-- confirmed before reuse here) -- a str, not a telegram.Message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ActionResult:
    """
    success: did the action complete as requested. False covers both
        "this action doesn't support what was asked" (e.g. an
        unrecognized read-only task action) and a genuine internal
        failure -- `warnings` distinguishes which, see OfflineEngine.execute().
    message: a plain, pre-formatted, Telegram-HTML-safe string ready to
        send as-is. Built here (not by the caller) so every Action owns
        its own user-facing wording, the same way main.py's handlers
        already do today.
    data: the underlying structured result (e.g. the raw task list),
        for a future caller that wants more than the rendered message --
        unused by v14.2's own main.py integration, which only reads
        `message`, but kept because DRG-001's own IntentResult/
        RoutingDecision precedent shows this project consistently designs
        result types for their next consumer, not just the first one.
    warnings: non-fatal issues that don't make the action fail outright
        (currently unused by any of v14.2's four read-only actions;
        reserved for e.g. a future action that partially succeeds).
    metadata: unlike RoutingDecision's deliberate rejection of a generic
        metadata bag (DRG-001 Open Question 1 -- resolved there with a
        named field, because every RoutingDecision needed the exact same
        single concept), ActionResult's metadata bag IS justified: the
        set of actions is open-ended and each action's supplementary data
        genuinely differs (a list action might report a count, a search
        action might report its query) -- there's no single shared named
        concept to extract the way `recommended_destination` was.
    """

    success: bool
    message: str
    data: Any = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
