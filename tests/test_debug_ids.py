"""
Tests for debug_system's independent bug-id presentation (v14.21,
Maintenance sprint). Storage was ALWAYS independent (bugs.db has its
own AUTOINCREMENT; task ids live in planner.db) — these pin the new
DBG-prefixed display form and the tolerant /resolve parsing. Pure
helpers only: nothing here touches bugs.db.
"""
import pytest

from debug_system import format_bug_id, parse_bug_id


def test_format_bug_id_zero_padded():
    assert format_bug_id(18) == "DBG-0018"
    assert format_bug_id(3) == "DBG-0003"
    assert format_bug_id(12345) == "DBG-12345"      # grows past 4 digits


@pytest.mark.parametrize("text,expected", [
    ("18", 18),
    ("#18", 18),
    ("DBG-0018", 18),
    ("dbg-18", 18),
    ("DBG18", 18),
    ("  DBG-0007  ", 7),
    ("abc", None),
    ("DBG-", None),
    ("", None),
    (None, None),
])
def test_parse_bug_id_accepts_all_display_forms(text, expected):
    assert parse_bug_id(text) == expected


def test_roundtrip():
    for n in (1, 18, 9999, 10001):
        assert parse_bug_id(format_bug_id(n)) == n
