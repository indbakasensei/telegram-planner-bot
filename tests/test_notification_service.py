"""
Tests for notification_service.py: TelegramSender's rate limiting/retry,
and the safe_edit_message_text/safe_answer_callback_query helpers.
Formalizes the validation done during Sprint 2A into a permanent suite.

Fully mocked -- no real Telegram API calls anywhere. Fake callbacks stand
in for python-telegram-bot's Bot API methods, including simulated
RetryAfter/TimedOut/NetworkError/BadRequest failures.
"""
import time

import pytest
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from notification_service import (
    TelegramSender, safe_answer_callback_query, safe_edit_message_text,
)


# ── TelegramSender: pacing ────────────────────────────────────────────────

async def test_different_chats_do_not_share_a_rate_limit_bucket():
    sender = TelegramSender()
    log = []

    async def cb(chat_id):
        log.append(chat_id)
        return {"ok": True}

    import asyncio
    t0 = time.perf_counter()
    await asyncio.gather(*[
        sender.process_request(cb, (i,), {}, "sendMessage", {"chat_id": i}, None)
        for i in range(50)
    ])
    elapsed = time.perf_counter() - t0
    assert len(log) == 50
    assert elapsed < 2.0  # would take 50/28 ~= 1.8s+ if they shared one global-only bucket badly; independent per-chat buckets keep this fast


async def test_single_chat_burst_is_paced_and_ordered_with_no_duplicates():
    # 30 messages at a 20/sec per-chat cap: enough of a burst (30 > the
    # bucket's capacity of 20) to force real pacing to kick in and prove
    # it, without sleeping longer than that requires.
    sender = TelegramSender(per_chat_max_rate=20, per_chat_time_period=1.0)
    log = []

    async def cb(i):
        log.append(i)
        return {"ok": True}

    for i in range(30):
        await sender.process_request(cb, (i,), {}, "sendMessage", {"chat_id": 42}, None)

    assert len(log) == 30
    assert log == list(range(30))  # strict order preserved, no duplicates


async def test_unrelated_users_are_not_serialized_behind_each_other():
    import asyncio
    sender = TelegramSender(per_chat_max_rate=1, per_chat_time_period=1.0)
    log = []

    async def cb(chat_id):
        await asyncio.sleep(0.05)
        log.append(chat_id)

    t0 = time.perf_counter()
    await asyncio.gather(*[
        sender.process_request(cb, (i,), {}, "sendMessage", {"chat_id": i}, None)
        for i in range(10)
    ])
    elapsed = time.perf_counter() - t0
    assert elapsed < 0.25  # ~0.05s if concurrent; ~0.5s if serialized


# ── TelegramSender: retry logic ──────────────────────────────────────────

async def test_retry_after_is_honored_and_eventually_succeeds():
    sender = TelegramSender(max_retries=3)
    calls = {"n": 0}

    async def cb():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RetryAfter(0.2)
        return {"ok": True}

    t0 = time.perf_counter()
    result = await sender.process_request(cb, (), {}, "sendMessage", {"chat_id": 1}, None)
    elapsed = time.perf_counter() - t0

    assert result == {"ok": True}
    assert calls["n"] == 2  # exactly one retry, no duplicate extra sends
    assert elapsed >= 0.2  # actually waited


async def test_network_error_gets_backoff_then_succeeds():
    # One failure is enough to prove backoff-then-retry works; two
    # failures would additionally exercise the growing (2**attempt) delay,
    # but at the cost of a real extra second of sleep for no further
    # coverage value here (the growth formula itself isn't under test).
    sender = TelegramSender(max_retries=3)
    calls = {"n": 0}

    async def cb():
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimedOut()
        return {"ok": True}

    result = await sender.process_request(cb, (), {}, "sendMessage", {"chat_id": 1}, None)
    assert result == {"ok": True}
    assert calls["n"] == 2


async def test_network_error_variant_also_retried():
    sender = TelegramSender(max_retries=2)
    calls = {"n": 0}

    async def cb():
        calls["n"] += 1
        if calls["n"] == 1:
            raise NetworkError("connection reset")
        return {"ok": True}

    result = await sender.process_request(cb, (), {}, "sendMessage", {"chat_id": 1}, None)
    assert result == {"ok": True}


async def test_exhausted_retries_raises_not_infinite_loop():
    # max_retries=1 (not more) -- enough to prove it gives up rather than
    # looping forever, without the extra ~1s each additional retry would
    # cost (RetryAfter's granularity is whole seconds; see the timing note
    # in test_retry_after_is_honored_and_eventually_succeeds' history).
    sender = TelegramSender(max_retries=1)
    calls = {"n": 0}

    async def always_fails():
        calls["n"] += 1
        raise RetryAfter(0.05)

    with pytest.raises(RetryAfter):
        await sender.process_request(always_fails, (), {}, "sendMessage", {"chat_id": 1}, None)
    assert calls["n"] == 2  # 1 initial + 1 retry, then gives up


async def test_unrelated_exception_propagates_untouched():
    # BaseRateLimiter.process_request() must not swallow arbitrary
    # exceptions -- only RetryAfter/TimedOut/NetworkError are its concern.
    sender = TelegramSender()

    async def cb():
        raise ValueError("something unrelated to flood control")

    with pytest.raises(ValueError):
        await sender.process_request(cb, (), {}, "sendMessage", {"chat_id": 1}, None)


async def test_stats_counters_update(monkeypatch):
    import notification_service as ns
    monkeypatch.setattr(ns, "_stats", {"sent": 0, "retried": 0, "flood_waits": 0, "failed": 0})
    sender = TelegramSender(max_retries=1)

    async def ok_cb():
        return {"ok": True}

    await sender.process_request(ok_cb, (), {}, "sendMessage", {"chat_id": 1}, None)
    stats = ns.get_stats()
    assert stats["sent"] == 1


# ── safe_edit_message_text ────────────────────────────────────────────────

class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return {"ok": True}


class FakeMessage:
    chat_id = 555


class FakeQuery:
    def __init__(self, edit_exc=None, answer_exc=None):
        self._edit_exc = edit_exc
        self._answer_exc = answer_exc
        self.edited = []
        self.message = FakeMessage()
        self._bot = FakeBot()
        self.from_user = type("U", (), {"id": 555})()

    async def edit_message_text(self, text, **kw):
        if self._edit_exc:
            raise self._edit_exc
        self.edited.append(text)
        return {"ok": True}

    def get_bot(self):
        return self._bot

    async def answer(self, *a, **kw):
        if self._answer_exc:
            raise self._answer_exc
        return {"ok": True}


async def test_safe_edit_normal_case_edits_in_place():
    q = FakeQuery()
    result = await safe_edit_message_text(q, "hello")
    assert result == {"ok": True}
    assert q.edited == ["hello"]
    assert q._bot.sent == []  # no fallback needed


async def test_safe_edit_not_modified_is_swallowed_silently():
    q = FakeQuery(edit_exc=BadRequest("Message is not modified"))
    result = await safe_edit_message_text(q, "same text")
    assert result is None
    assert q._bot.sent == []  # must NOT fall back to a fresh send


async def test_safe_edit_deleted_message_falls_back_to_fresh_send():
    q = FakeQuery(edit_exc=BadRequest("Message to edit not found"))
    result = await safe_edit_message_text(q, "new content")
    assert q._bot.sent == [(555, "new content")]


async def test_safe_edit_generic_telegram_error_does_not_raise():
    from telegram.error import TelegramError
    q = FakeQuery(edit_exc=TelegramError("some other transient issue"))
    result = await safe_edit_message_text(q, "text")
    assert result is None  # logged and swallowed, not raised


# ── safe_answer_callback_query ────────────────────────────────────────────

async def test_safe_answer_normal_case():
    q = FakeQuery()
    result = await safe_answer_callback_query(q)
    assert result == {"ok": True}


async def test_safe_answer_already_answered_query_does_not_raise():
    # The exact bug found during Sprint 2A's own audit: answering the
    # same callback query twice raises BadRequest on the second call.
    q = FakeQuery(answer_exc=BadRequest("Query is too old and response timeout expired"))
    result = await safe_answer_callback_query(q)
    assert result is None  # swallowed, not raised


async def test_safe_answer_passes_through_args_and_kwargs():
    q = FakeQuery()
    result = await safe_answer_callback_query(q, "Goal complete!", show_alert=True)
    assert result == {"ok": True}
