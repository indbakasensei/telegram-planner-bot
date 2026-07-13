"""
notification_service.py — BAKA's Telegram delivery reliability layer.

Sprint 2A (v13.0). Addresses ENGINEERING_AUDIT.md finding F1 (HIGH):
`check_reminders` sent one message per due task in a tight loop with no
pacing, risking Telegram's flood-control limits (~30 msg/sec global,
tighter per-chat), plus a related, previously-undocumented bug found
during this sprint's own audit: a callback query can only be answered
once, but one dashboard branch (goal-complete) answered it a second time,
which Telegram rejects.

Architecture
------------
Application
    |
    v
notification_service.py  <- this file
    |
    v
Telegram API

Two independent pieces, matching the two different problems in scope:

1. TelegramSender (a `telegram.ext.BaseRateLimiter` subclass) — registered
   once via `Application.builder().rate_limiter(TelegramSender())` in
   main.py. PTB's `ExtBot._do_post()` is the single low-level transport
   method every high-level Bot API call (send_message, edit_message_text,
   send_photo, answer_callback_query, delete_message, ...) funnels
   through; when a rate limiter is configured, EVERY one of those calls
   automatically routes through `process_request()` below. This means
   pacing, retry, and flood protection apply globally with **zero changes
   to any of the ~380 existing send/edit call sites in main.py** — the
   same "one seam, not scattered call-site edits" approach used for the
   async-offload fix in Sprint 1B and the scheduler-timezone fix in
   Sprint 1A.

   This is deliberately NOT built on the `aiolimiter`-based `AIORateLimiter`
   PTB ships, because `aiolimiter` isn't an existing project dependency and
   adding it for a personal-scale bot wasn't judged worth a new dependency
   — see the "Alternatives considered" note in the Sprint 2A report. The
   token-bucket implementation below is a small, dependency-free
   reimplementation of the same idea, informed directly by reading PTB's
   own `AIORateLimiter` reference implementation.

2. `safe_edit_message_text()` / `safe_answer_callback_query()` — plain
   helper functions (not part of the rate-limiter seam, since
   `BaseRateLimiter.process_request()` is explicitly documented as "should
   not handle any other exception raised by callback"). PTB's
   `answerCallbackQuery`/`editMessageText` can each fail for reasons that
   have nothing to do with flood control — the message was deleted, the
   edit is a no-op, the callback already expired — and those failures need
   call-site-aware handling (e.g. falling back to sending a fresh message
   when an edit target is gone). These two helpers exist so that handling
   lives in exactly one place instead of being duplicated at every call
   site; main.py's ~34 `edit_message_text` call sites and 2
   `answer_callback_query` call sites were updated to use them (Phase 4).

Why not a bespoke wrapper around every send_message/reply_text call
instead? That was considered and rejected — see the Sprint 2A report's
"Alternatives considered" section. In short: PTB already provides the
official extension point for exactly the pacing/retry problem (used
here), and duplicating that mechanism per-call-site would be the exact
"scattered retry logic" this sprint's own design goal says to avoid.

Metrics / future analytics
---------------------------
`get_stats()` exposes simple in-memory counters (messages sent, retries,
flood waits, failures). This is intentionally minimal — a hook point for
the AI-usage-analytics work already tracked in DEBUGGING.md/ROADMAP.md,
not a new subsystem of its own.
"""
import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from telegram._utils.types import JSONDict
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import BaseRateLimiter

logger = logging.getLogger(__name__)

# ── Metrics (minimal, in-memory; see module docstring) ──────────────────
_stats = {
    "sent": 0,
    "retried": 0,
    "flood_waits": 0,
    "failed": 0,
}


def get_stats() -> Dict[str, int]:
    """Snapshot of delivery counters since process start."""
    return dict(_stats)


# ── Token-bucket rate limiting (no external dependency) ──────────────────
class _TokenBucket:
    """Minimal async token bucket. `rate` tokens refill every `per` seconds."""

    __slots__ = ("rate", "per", "_tokens", "_last", "_lock")

    def __init__(self, rate: float, per: float):
        self.rate = rate
        self.per = per
        self._tokens = float(rate)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self.rate <= 0:
            return  # 0 = disabled, matches PTB's own AIORateLimiter convention
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(self.rate, self._tokens + elapsed * (self.rate / self.per))
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) * (self.per / self.rate)
                await asyncio.sleep(wait)


class TelegramSender(BaseRateLimiter):
    """Paces, retries, and rate-limits every outbound Telegram Bot API call.

    Two levels of throttling, same shape as PTB's own reference
    `AIORateLimiter`: an overall bucket (global cap across the whole bot)
    and a per-chat bucket (keyed by chat_id, so a burst of reminders to
    one chat can never starve — or be starved by — unrelated chats).
    Different users' interactions never share a bucket, so ordinary
    traffic is never serialized against other users (see the Sprint 2A
    report's "Performance impact" section for the measured effect).

    Handles:
      - RetryAfter: waits exactly as long as Telegram asks, then retries.
      - TimedOut / NetworkError: exponential backoff, bounded retries.
      - Any other exception: NOT handled here (by design — see module
        docstring); propagates to the caller / global error_handler.
    """

    __slots__ = ("_overall", "_per_chat_rate", "_per_chat_period", "_chat_buckets", "_max_retries")

    def __init__(
        self,
        overall_max_rate: float = 28,
        overall_time_period: float = 1.0,
        per_chat_max_rate: float = 1,
        per_chat_time_period: float = 1.0,
        max_retries: int = 3,
    ):
        self._overall = _TokenBucket(overall_max_rate, overall_time_period)
        self._per_chat_rate = per_chat_max_rate
        self._per_chat_period = per_chat_time_period
        self._chat_buckets: Dict[Any, _TokenBucket] = {}
        self._max_retries = max_retries

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def _bucket_for_chat(self, chat_id: Any) -> _TokenBucket:
        bucket = self._chat_buckets.get(chat_id)
        if bucket is None:
            bucket = _TokenBucket(self._per_chat_rate, self._per_chat_period)
            self._chat_buckets[chat_id] = bucket
            # Same minimal-effort cleanup approach PTB's own AIORateLimiter
            # uses -- avoid unbounded growth across many distinct chats.
            if len(self._chat_buckets) > 512:
                for key, b in list(self._chat_buckets.items()):
                    if key != chat_id and b._tokens >= b.rate:
                        del self._chat_buckets[key]
        return bucket

    async def process_request(
        self,
        callback: Callable[..., Coroutine[Any, Any, Union[bool, JSONDict, List[JSONDict]]]],
        args: Any,
        kwargs: Dict[str, Any],
        endpoint: str,
        data: Dict[str, Any],
        rate_limit_args: Optional[Any],
    ) -> Union[bool, JSONDict, List[JSONDict]]:
        chat_id = data.get("chat_id")

        for attempt in range(self._max_retries + 1):
            try:
                await self._overall.acquire()
                if chat_id is not None:
                    await self._bucket_for_chat(chat_id).acquire()
                result = await callback(*args, **kwargs)
                _stats["sent"] += 1
                return result
            except RetryAfter as e:
                _stats["flood_waits"] += 1
                if attempt == self._max_retries:
                    _stats["failed"] += 1
                    logger.error(f"{endpoint}: gave up after RetryAfter x{attempt + 1}")
                    raise
                logger.warning(f"{endpoint}: flood control, waiting {e.retry_after}s")
                _stats["retried"] += 1
                await asyncio.sleep(e.retry_after + 0.1)
            except (TimedOut, NetworkError) as e:
                if attempt == self._max_retries:
                    _stats["failed"] += 1
                    logger.error(f"{endpoint}: gave up after {type(e).__name__} x{attempt + 1}")
                    raise
                backoff = min(2 ** attempt, 10)
                logger.warning(f"{endpoint}: {type(e).__name__}, retrying in {backoff}s")
                _stats["retried"] += 1
                await asyncio.sleep(backoff)
        return None  # unreachable; loop always returns or raises


# ── Edit / callback-answer safety (Phase 4) ──────────────────────────────
async def safe_edit_message_text(query, text: str, **kwargs):
    """Edit a callback query's message, handling the common failure modes:
    the message was deleted, the edit is a no-op ("message is not
    modified"), or the message can no longer be edited. Falls back to
    sending a fresh message so the content still reaches the user when an
    in-place edit isn't possible. Never raises for these expected cases;
    logs and swallows anything else so a single bad edit can't be an
    uncaught exception for the whole callback handler.
    """
    try:
        return await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        msg = str(e).lower()
        if "not modified" in msg:
            return None  # content is already correct on screen -- no-op
        # message deleted / can't be edited / edit target not found -> send fresh
        try:
            chat_id = query.message.chat_id if query.message else query.from_user.id
            return await query.get_bot().send_message(chat_id=chat_id, text=text, **kwargs)
        except TelegramError as send_err:
            logger.error(f"safe_edit_message_text: edit AND fallback send both failed: {send_err}")
            return None
    except TelegramError as e:
        logger.error(f"safe_edit_message_text: unexpected error: {e}")
        return None


async def safe_answer_callback_query(query, *args, **kwargs):
    """Answer a callback query, swallowing the expected failure mode of
    answering a query that already expired or was already answered
    (Telegram allows exactly one answer per callback query id).
    """
    try:
        return await query.answer(*args, **kwargs)
    except TelegramError as e:
        logger.warning(f"safe_answer_callback_query: could not answer (likely expired): {e}")
        return None
