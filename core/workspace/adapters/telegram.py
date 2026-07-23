"""
telegram.py -- the Telegram synchronization adapter (v15.0-alpha.6,
docs/v15/TWID.md), the first SyncAdapter.

It renders a timeline event to Telegram HTML and delivers it through an
INJECTED sender callable -- it never imports python-telegram-bot or the
live bot. That keeps the offline test suite Telegram-free and lets the
real bot's send function be wired in later (a user-facing step, out of
scope for this milestone). With no sender injected the adapter degrades
gracefully (a clean failure, never a crash), so an unconfigured engine is
harmless.

    sender(user_id, text, target_id) -> message_ref | None
"""
from __future__ import annotations

from typing import Callable

import fmt
from core.workspace.sync import SyncAdapter, SyncItem, SyncResult
from core.workspace.timeline import TimelineEvent

# sender(user_id: int, text: str, target_id: int | None) -> str | int | None
TelegramSender = Callable[[int, str, "int | None"], "str | int | None"]


class TelegramAdapter(SyncAdapter):
    """Delivers timeline events to Telegram. Stateless apart from the
    injected sender."""

    name = "telegram"

    def __init__(self, sender: TelegramSender | None = None):
        self._send = sender

    def render(self, event: TimelineEvent) -> str:
        """Telegram HTML for one event: the summary in bold. fmt.b escapes
        its content, so user content (workspace/milestone titles) can't
        break the markup -- the project's standard message-building path."""
        return fmt.b(event.summary or event.event_type)

    def deliver(self, item: SyncItem) -> SyncResult:
        if self._send is None:
            # Not configured (dormant) -- fail cleanly, do not raise.
            return SyncResult.failure("telegram sender not configured")
        try:
            ref = self._send(item.user_id, item.payload, item.target_id)
        except Exception as e:  # network/transport error -> retryable
            return SyncResult.failure(repr(e))
        return SyncResult.success(ref=str(ref) if ref is not None else None)
