"""
Regression tests for bugs logged in the bug database (DBG-####), v15.1.0-alpha.5.

- DBG-0004: a goal "this year" must get a 31-Dec deadline (date parsing).
- DBG-0005: memory key spelling variants must collapse, not duplicate.
- DBG-0006: a natural-language memory question must find the keyword, not
  match nothing and dump every memory.
"""
from datetime import datetime

import database as db
from date_parser import parse_date


# ── DBG-0004: period-end deadlines ────────────────────────────────────────

def test_this_year_deadline_is_dec31():
    d, _ = parse_date("read 12 books this year", now=datetime(2026, 7, 24))
    assert d == "2026-12-31"


def test_by_month_end():
    d, _ = parse_date("finish the drone by month end", now=datetime(2026, 7, 10))
    assert d == "2026-07-31"


def test_next_year_is_next_dec31():
    d, _ = parse_date("maybe do it next year", now=datetime(2026, 7, 24))
    assert d == "2027-12-31"


def test_end_of_week_is_sunday():
    now = datetime(2026, 7, 22)
    d, _ = parse_date("submit by end of week", now=now)
    got = datetime.strptime(d, "%Y-%m-%d")
    assert got.weekday() == 6 and 0 <= (got - now).days <= 6


def test_plain_date_still_works():
    d, _ = parse_date("call mom on 8 Aug", now=datetime(2026, 7, 24))
    assert d == "2026-08-08"


# ── DBG-0005: memory key variants collapse ────────────────────────────────

def test_memory_key_variants_collapse(temp_db, uid):
    db.save_memory(uid, "favorite_color", "blue")
    db.save_memory(uid, "favorite color", "red")
    fav = [(k, v) for k, v in db.get_all_memories(uid)
           if db._normalize_memory_key(k) == "favorite color"]
    assert len(fav) == 1 and fav[0][1] == "red"     # one row, updated value


# ── DBG-0006: keyword-aware memory search ─────────────────────────────────

def test_smart_memory_search_finds_by_keyword(temp_db, uid):
    db.save_memory(uid, "exam", "on 8 Aug")
    db.save_memory(uid, "favorite color", "blue")
    # the raw question substring-matches nothing...
    assert db.search_memories(uid, "When is my exam?") == []
    # ...but the keyword-aware search finds the exam memory, and ONLY that
    res = db.search_memories_smart(uid, "When is my exam?")
    assert ("exam", "on 8 Aug") in res
    assert all("exam" in k.lower() or "exam" in v.lower() for k, v in res)


def test_smart_memory_search_empty_when_truly_absent(temp_db, uid):
    db.save_memory(uid, "exam", "on 8 Aug")
    # keywords car/registration match nothing -> empty (caller must NOT dump all)
    assert db.search_memories_smart(uid, "what is my car registration?") == []


# ── GLM 5.2 timeout fix (reasoning model needs headroom) ──────────────────

def test_chat_timeout_has_headroom_for_reasoning_model():
    # GLM 5.2 is a reasoning model whose replies exceed the old 8s cap, which
    # made every message falsely fall back to Llama-8b. Lock in the headroom.
    import baka_brain
    assert baka_brain.TIMEOUT_FAST_CHAT >= 20
    assert baka_brain.TIMEOUT_LONG_REASONING >= baka_brain.TIMEOUT_FAST_CHAT
    # the SDK ceiling must sit at/above the longest per-call tier
    assert baka_brain.client.timeout >= baka_brain.TIMEOUT_LONG_REASONING


def test_hot_chat_path_does_not_default_to_slow_main_model():
    # The interactive chat/intent path must not default to the (slow) GLM 5.2
    # main model, or every message stalls; it uses the fast model by default.
    import baka_brain
    assert baka_brain.CHAT_MODEL == baka_brain.MODEL_FAST
    # ...while reasoning still uses the main model.
    assert baka_brain.MODEL_MAIN != baka_brain.CHAT_MODEL or \
        baka_brain.MODEL_MAIN == baka_brain.MODEL_FAST
