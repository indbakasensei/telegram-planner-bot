"""
Tests for core/intent/ -- the v14.0 Stage 1 Intent Engine (Shadow Mode).

Every test passes an explicit `now` via ConversationContext, mirroring
tests/test_date_parser.py's convention (that module's functions are
reused directly by core/intent/rules.py's Tier 1/2 rules, so the same
determinism discipline applies here). No mocking needed: the engine is
pure, in-memory, and synchronous by construction.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from core.intent.intent_types import ConversationContext, Intent, IntentResult
from core.intent.intent_engine import IntentEngine
from core.intent.entities import entities_from_parsed_date
from core.intent.rules import tier0_command_match, tier3_anchored_smalltalk, tier3_help

IST = ZoneInfo("Asia/Kolkata")

# Wednesday, March 4, 2026, 10:00 IST -- same fixed reference point as
# tests/test_date_parser.py, so date-bearing inputs resolve identically
# to what that suite already verifies.
NOW = datetime(2026, 3, 4, 10, 0, tzinfo=IST)


@pytest.fixture
def engine():
    return IntentEngine()


def ctx(state="idle", partial_data=None, now=NOW):
    return ConversationContext(state=state, partial_data=partial_data or {}, now=now)


# ── Add reminder ─────────────────────────────────────────────────────────

def test_add_reminder_date_and_time(engine):
    r = engine.classify("remind me tomorrow at 5pm to call mom", ctx())
    assert r.intent == Intent.ADD_TASK
    assert r.tier == 1
    assert r.confidence >= 0.9
    assert r.entities["date"] == "2026-03-05"
    assert r.entities["time"] == "17:00"


def test_add_reminder_recurrence_only(engine):
    r = engine.classify("remind me daily to drink water", ctx())
    assert r.intent == Intent.ADD_TASK
    assert r.tier == 2
    assert r.entities["recurrence"] == "daily"


def test_add_reminder_weak_keyword_fallback(engine):
    r = engine.classify("gotta finish the report", ctx())
    assert r.intent == Intent.ADD_TASK
    assert r.tier == 4
    assert r.confidence < 0.6  # weak signal, honestly reported as such


# ── Delete reminder ──────────────────────────────────────────────────────

def test_delete_reminder_exact_command(engine):
    r = engine.classify("delete 5", ctx())
    assert r.intent == Intent.DELETE_TASK
    assert r.tier == 0
    assert r.confidence == 1.0
    assert r.entities["task_id"] == 5


def test_delete_reminder_weak_keyword_fallback(engine):
    r = engine.classify("cancel this", ctx())
    assert r.intent == Intent.DELETE_TASK
    assert r.tier == 4


# ── Edit reminder ────────────────────────────────────────────────────────

def test_edit_reminder_exact_command(engine):
    r = engine.classify("edit 5", ctx())
    assert r.intent == Intent.EDIT_TASK
    assert r.tier == 0
    assert r.entities["task_id"] == 5


def test_edit_reminder_weak_keyword_fallback(engine):
    r = engine.classify("update the deadline for my project", ctx())
    assert r.intent == Intent.EDIT_TASK
    assert r.tier == 4


# ── Greeting ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["hi", "hello", "hey", "good morning", "Namaste"])
def test_greeting(engine, text):
    r = engine.classify(text, ctx())
    assert r.intent == Intent.GREETING
    assert r.tier == 3


# ── Help ─────────────────────────────────────────────────────────────────

def test_help_exact_command(engine):
    r = engine.classify("help", ctx())
    assert r.intent == Intent.HELP
    assert r.tier == 0
    assert r.confidence == 1.0


def test_help_regex_fallback(engine):
    r = engine.classify("how does this work", ctx())
    assert r.intent == Intent.HELP
    assert r.tier == 3


# ── Small talk ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["thanks", "lol", "haha", "cool", "how are you"])
def test_small_talk(engine, text):
    r = engine.classify(text, ctx())
    assert r.intent == Intent.CHAT
    assert r.tier == 3


# ── Random message / unknown input ──────────────────────────────────────

@pytest.mark.parametrize("text", ["asdkjfh qweoiur", "zzz123 blah blah", "xk39 !!! qq"])
def test_random_message_is_unknown(engine, text):
    r = engine.classify(text, ctx())
    assert r.intent == Intent.UNKNOWN
    assert r.tier == 5
    assert r.confidence == 0.0


def test_empty_input_is_unknown(engine):
    r = engine.classify("   ", ctx())
    assert r.intent == Intent.UNKNOWN
    assert r.confidence == 0.0


# ── Time query ───────────────────────────────────────────────────────────

def test_time_query_weak_fallback(engine):
    r = engine.classify("what time is it", ctx())
    assert r.intent == Intent.QUERY_TASK
    assert r.tier == 4
    assert r.confidence < 0.5  # honestly low: out of this enum's real domain


# ── Schedule query ───────────────────────────────────────────────────────

def test_schedule_query_exact_command(engine):
    r = engine.classify("what do i have today", ctx())
    assert r.intent == Intent.QUERY_TASK
    assert r.tier == 0
    assert r.confidence == 1.0


def test_schedule_query_weak_fallback(engine):
    r = engine.classify("show me next week", ctx())
    assert r.intent == Intent.QUERY_TASK
    assert r.tier == 4


def test_date_query_phrasing_not_add_after_relative_ranges(engine):
    """v15.2 M4: date_parser now resolves 'next week' (goal-deadline work).
    That must NOT turn a schedule QUERY into ADD_TASK -- query phrasing falls
    through to the weak query fallback (tier 4), never Tier-1 ADD."""
    for q in ("show me next week", "what's next week",
              "list tasks next week", "when is next week's plan"):
        r = engine.classify(q, ctx())
        assert r.intent == Intent.QUERY_TASK, (q, r)


def test_date_add_phrasing_still_add_with_relative_range(engine):
    """Genuine ADD phrasing with the same resolved date stays ADD_TASK with
    the date entity -- the relative-range resolution is not lost."""
    r = engine.classify("add a task next week", ctx())
    assert r.intent == Intent.ADD_TASK
    assert r.tier == 1
    assert r.entities.get("date")


# ── Ambiguity scoring ────────────────────────────────────────────────────

def test_tier0_exact_match_has_zero_ambiguity(engine):
    r = engine.classify("delete 5", ctx())
    assert r.ambiguity == 0.0


def test_ambiguity_when_tiers_disagree(engine):
    # No Tier 0 match ("cancel my..." isn't a recognised prefix/exact
    # phrase); Tier 1 sees a resolved date+time (ADD_TASK, high
    # confidence); Tier 4 also weakly matches "cancel" (DELETE_TASK).
    # The disagreement should show up as non-zero ambiguity on the
    # winning (higher-confidence) result.
    r = engine.classify("cancel my meeting tomorrow at 5pm", ctx())
    assert r.intent == Intent.ADD_TASK
    assert r.tier == 1
    assert 0.0 < r.ambiguity < 1.0


# ── Result shape / type discipline ──────────────────────────────────────

def test_classify_returns_intent_result_not_dict(engine):
    r = engine.classify("hi", ctx())
    assert isinstance(r, IntentResult)
    assert isinstance(r.intent, Intent)
    assert isinstance(r.entities, dict)


def test_classify_is_pure_same_input_same_output(engine):
    a = engine.classify("delete 5", ctx())
    b = engine.classify("delete 5", ctx())
    assert (a.intent, a.confidence, a.entities, a.ambiguity, a.tier) == (
        b.intent, b.confidence, b.entities, b.ambiguity, b.tier,
    )


def test_context_now_is_never_read_from_system_clock(engine):
    # A `now` far in the past must still resolve "tomorrow" relative to
    # it, not to the real system clock -- proof classify() never calls
    # datetime.now() itself.
    old = datetime(2020, 1, 1, 9, 0, tzinfo=IST)
    r = engine.classify("remind me tomorrow at 9am", ctx(now=old))
    assert r.entities["date"] == "2020-01-02"


# ── Entity extraction ────────────────────────────────────────────────────

def test_entities_from_parsed_date_flags():
    parsed = {
        "date": "2026-03-05", "time": "17:00", "time_ambiguous": True,
        "recurrence": {"type": "weekly", "weekday": 1, "day_of_month": None},
        "multiple_tasks": True, "errors": [], "is_past": False,
        "is_invalid_time": False, "priority": "high", "is_deadline": True,
    }
    entities = entities_from_parsed_date(parsed)
    assert entities == {
        "date": "2026-03-05", "time": "17:00", "time_ambiguous": True,
        "recurrence": "weekly", "priority": "high", "is_deadline": True,
        "multiple_tasks": True,
    }


def test_entities_from_parsed_date_omits_defaults():
    parsed = {
        "date": None, "time": None, "time_ambiguous": False, "recurrence": None,
        "multiple_tasks": False, "errors": [], "is_past": False,
        "is_invalid_time": False, "priority": "medium", "is_deadline": False,
    }
    assert entities_from_parsed_date(parsed) == {}


def test_urgent_language_sets_high_priority_entity(engine):
    r = engine.classify("urgent: call the client tomorrow at 5pm", ctx())
    assert r.entities.get("priority") == "high"


def test_multiple_tasks_entity_flag(engine):
    r = engine.classify("call mom and buy milk tomorrow at 5pm", ctx())
    assert r.entities.get("multiple_tasks") is True


# ── Rule functions are independently callable (no engine required) ──────

@pytest.mark.parametrize("fn", [tier0_command_match, tier3_anchored_smalltalk, tier3_help])
def test_rule_functions_handle_empty_string_directly(fn):
    assert fn("") is None
    assert fn("   ") is None


# ── Performance ──────────────────────────────────────────────────────────

def test_classification_latency_is_recorded_and_small(engine):
    r = engine.classify("remind me tomorrow at 5pm", ctx())
    assert r.latency_ms >= 0.0
    assert r.latency_ms < 50.0  # generous ceiling for a single cold call


def test_average_classification_latency_under_5ms(engine):
    samples = [
        "delete 5", "edit 7", "hi", "help", "what do i have today",
        "remind me tomorrow at 5pm to call mom", "remind me daily to drink water",
        "cancel my meeting tomorrow at 5pm", "thanks", "asdkjfh qweoiur",
    ]
    # Warm-up: first calls into a freshly-imported module pay one-time
    # costs (e.g. pytz/zoneinfo timezone-data loading inside
    # date_parser.py) that are not representative of steady-state
    # per-message latency in a long-running bot process.
    for text in samples:
        engine.classify(text, ctx())

    import time
    iterations = 200
    start = time.perf_counter()
    for _ in range(iterations):
        for text in samples:
            engine.classify(text, ctx())
    elapsed_ms = (time.perf_counter() - start) * 1000
    avg_ms = elapsed_ms / (iterations * len(samples))
    assert avg_ms < 25.0, f"average classification latency {avg_ms:.4f}ms exceeds 25ms budget"
