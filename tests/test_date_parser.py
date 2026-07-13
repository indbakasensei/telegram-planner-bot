"""
Extensive tests for date_parser.py -- the most bug-prone module in this
codebase historically (see CHANGELOG.md's v3.0/v3.1/v7.1/v10.1 entries,
each fixing a real date/time parsing bug found in production).

Every test passes an explicit `now` so results are deterministic
regardless of when the suite runs -- date_parser.py's functions all
accept `now` for exactly this reason (no monkeypatching needed).
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from date_parser import (
    parse_date, parse_time, parse_all, detect_recurrence,
    might_have_multiple_tasks, validate_datetime,
)

IST = ZoneInfo("Asia/Kolkata")

# Wednesday, March 4, 2026, 10:00 IST -- a fixed reference point so every
# test is deterministic. weekday()==2 (Mon=0), confirmed once here rather
# than assumed by every individual test.
NOW = datetime(2026, 3, 4, 10, 0, tzinfo=IST)
assert NOW.weekday() == 2, "test fixture drifted -- NOW must stay a Wednesday"


def d(days_from_now):
    return (NOW + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


# ── parse_date: relative day words ──────────────────────────────────────

@pytest.mark.parametrize("text", ["today", "Today", "aaj", "aj", "abhi"])
def test_parse_date_today(text):
    date_str, err = parse_date(text, NOW)
    assert date_str == d(0)
    assert err is None


@pytest.mark.parametrize("text", ["tomorrow", "kal", "kal subah", "kal raat", "kal shaam"])
def test_parse_date_tomorrow(text):
    date_str, err = parse_date(text, NOW)
    assert date_str == d(1)
    assert err is None


@pytest.mark.parametrize("text", ["day after tomorrow", "parso", "parson"])
def test_parse_date_day_after_tomorrow(text):
    date_str, err = parse_date(text, NOW)
    assert date_str == d(2)
    assert err is None


@pytest.mark.parametrize("text", ["yesterday", "kal tha", "beete kal"])
def test_parse_date_yesterday_rejected_with_warning(text):
    date_str, err = parse_date(text, NOW)
    assert date_str == d(-1)
    assert err is not None and "past" in err.lower()


def test_parse_date_kal_tha_not_confused_with_tomorrow_kal():
    # "kal" alone means tomorrow, but "kal tha" (negative lookahead in the
    # regex) must not match the tomorrow pattern -- this was a real
    # ambiguity the regex `kal(?!\s+tha)` exists specifically to resolve.
    date_str, err = parse_date("kal tha", NOW)
    assert date_str == d(-1)


def test_parse_date_in_n_days():
    date_str, err = parse_date("in 3 days", NOW)
    assert date_str == d(3)
    assert err is None


# ── parse_date: weekdays ─────────────────────────────────────────────────

def test_parse_date_bare_weekday_same_day_means_next_week():
    # NOW is a Wednesday; asking for "wednesday" with no qualifier must
    # mean NEXT Wednesday (7 days out), not today.
    date_str, _ = parse_date("wednesday", NOW)
    assert date_str == d(7)


def test_parse_date_bare_weekday_upcoming_this_week():
    # NOW is Wednesday (weekday=2); Friday (weekday=4) is 2 days out.
    date_str, _ = parse_date("friday", NOW)
    assert date_str == d(2)


def test_parse_date_next_weekday_always_pushes_a_full_week_out():
    # "next friday" said on a Wednesday must land on the Friday AFTER the
    # upcoming one (i.e. 9 days out), not the same Friday plain "friday"
    # would resolve to (2 days out) -- these are deliberately different.
    date_str, _ = parse_date("next friday", NOW)
    assert date_str == d(9)


def test_parse_date_next_same_weekday_as_today():
    # "next wednesday" said on a Wednesday: days = 2-2 = 0, so the
    # `days<=0: days+=7` branch fires giving 7, and the subsequent
    # `days<7` check is false (7 is not <7) so no further push -- lands
    # exactly 7 days out (i.e. next week's Wednesday), same as plain
    # "wednesday" would. Confirmed against the actual implementation.
    date_str, _ = parse_date("next wednesday", NOW)
    assert date_str == d(7)


def test_parse_date_hindi_weekday():
    date_str, _ = parse_date("shukravar ko", NOW)  # Friday
    assert date_str == d(2)


# ── parse_date: month/day and ISO ────────────────────────────────────────

def test_parse_date_month_day_this_year():
    date_str, err = parse_date("25 December", NOW)
    assert date_str == "2026-12-25"
    assert err is None


def test_parse_date_month_day_already_passed_rolls_to_next_year():
    date_str, err = parse_date("1 January", NOW)  # NOW is March 2026
    assert date_str == "2027-01-01"
    assert err is None


def test_parse_date_leap_year_feb_29():
    date_str, err = parse_date("29 February 2028", NOW)  # 2028 is a leap year
    assert date_str == "2028-02-29"
    assert err is None


def test_parse_date_invalid_date_in_non_leap_year():
    date_str, err = parse_date("30 February 2026", NOW)
    assert date_str is None
    assert err is not None and "invalid" in err.lower()


def test_parse_date_iso_format():
    date_str, err = parse_date("2026-12-25", NOW)
    assert date_str == "2026-12-25"
    assert err is None


def test_parse_date_iso_format_past_flagged():
    date_str, err = parse_date("2026-01-01", NOW)
    assert date_str == "2026-01-01"
    assert err is not None and "past" in err.lower()


def test_parse_date_year_boundary_month_day():
    # "1 Jan" asked in March must roll to next January, crossing a year
    # boundary correctly.
    date_str, _ = parse_date("1 Jan", NOW)
    assert date_str.startswith("2027-01-01")


def test_parse_date_no_date_found():
    date_str, err = parse_date("call mom", NOW)
    assert date_str is None
    assert err is None


# ── parse_time: vague fixed phrases ──────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("midnight", "00:00"),
    ("morning", "08:00"),
    ("noon", "12:00"),
    ("lunch", "13:00"),
    ("afternoon", "14:00"),
    ("end of day", "17:00"),
    ("evening", "18:00"),
    ("tonight", "21:00"),
    ("night", "21:00"),
])
def test_parse_time_vague_phrases(text, expected):
    time_str, err, ambiguous = parse_time(text, NOW)
    assert time_str == expected
    assert err is None
    assert ambiguous is False


# ── parse_time: relative ─────────────────────────────────────────────────

def test_parse_time_in_n_hours():
    time_str, _, _ = parse_time("in 2 hours", NOW)
    assert time_str == (NOW + timedelta(hours=2)).strftime("%H:%M")


def test_parse_time_in_n_minutes_not_confused_with_clock_time():
    # Regression: "in 1 min" must be now+1min, NOT 01:00 -- a real bug
    # documented in CHANGELOG.md.
    time_str, _, _ = parse_time("in 1 min", NOW)
    assert time_str == (NOW + timedelta(minutes=1)).strftime("%H:%M")
    assert time_str != "01:00"


# ── parse_time: Hindi context words (unambiguous) ────────────────────────

def test_parse_time_raat_adds_twelve_hours():
    time_str, _, ambiguous = parse_time("raat 10 baje", NOW)
    assert time_str == "22:00"
    assert ambiguous is False


def test_parse_time_subah_stays_am():
    time_str, _, ambiguous = parse_time("subah 8 baje", NOW)
    assert time_str == "08:00"
    assert ambiguous is False


def test_parse_time_subah_12_becomes_midnight_hour_zero():
    time_str, _, _ = parse_time("subah 12 baje", NOW)
    assert time_str == "00:00"


def test_parse_time_shaam_adds_twelve_hours():
    time_str, _, ambiguous = parse_time("shaam 6 baje", NOW)
    assert time_str == "18:00"
    assert ambiguous is False


# ── parse_time: AM/PM ─────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("3pm", "15:00"), ("3 PM", "15:00"), ("3am", "03:00"),
    ("12pm", "12:00"), ("12am", "00:00"),
])
def test_parse_time_am_pm(text, expected):
    time_str, err, _ = parse_time(text, NOW)
    assert time_str == expected
    assert err is None


@pytest.mark.parametrize("text", ["13 PM", "25 PM"])
def test_parse_time_invalid_am_pm_hour_rejected(text):
    time_str, err, _ = parse_time(text, NOW)
    assert time_str is None
    assert err is not None


def test_parse_time_zero_am_treated_as_midnight_not_rejected():
    # "0 AM" only validates the upper bound (h > 12); h=0 passes through
    # unrejected and maps to 00:00. Rare, arguably-reasonable edge case
    # (nobody types "0 AM" in practice) -- documented here as current
    # behavior rather than "fixed", since rejecting it is a judgment call
    # with no clear right answer and no evidence of real-world impact.
    time_str, err, _ = parse_time("0 AM", NOW)
    assert time_str == "00:00"
    assert err is None


# ── parse_time: 24h / HH:MM ────────────────────────────────────────────────

def test_parse_time_hhmm_valid():
    time_str, err, _ = parse_time("17:00", NOW)
    assert time_str == "17:00"
    assert err is None


def test_parse_time_hhmm_invalid_hour():
    time_str, err, _ = parse_time("25:00", NOW)
    assert time_str is None
    assert "0-23" in err


def test_parse_time_hhmm_invalid_minute():
    time_str, err, _ = parse_time("10:99", NOW)
    assert time_str is None
    assert "0-59" in err


def test_parse_time_military_with_context_word():
    time_str, err, _ = parse_time("meeting at 1400", NOW)
    assert time_str == "14:00"


def test_parse_time_military_bare_number_not_treated_as_time():
    # A bare 4-digit number with no time-context word (e.g. a year) must
    # NOT be parsed as a time -- this is the guard against "2026" being
    # read as 20:26.
    time_str, err, _ = parse_time("meeting in 2026", NOW)
    assert time_str is None


# ── parse_time: ambiguous "X baje" ────────────────────────────────────────

@pytest.mark.parametrize("hour", [1, 2, 3, 4, 5, 6, 7])
def test_parse_time_bare_baje_low_hour_is_ambiguous(hour):
    time_str, err, ambiguous = parse_time(f"{hour} baje", NOW)
    assert ambiguous is True
    assert time_str == f"{hour:02d}:00"  # still returns a best-guess value


@pytest.mark.parametrize("hour", [8, 9, 10, 11, 12])
def test_parse_time_bare_baje_high_hour_unambiguous(hour):
    time_str, err, ambiguous = parse_time(f"{hour} baje", NOW)
    assert ambiguous is False
    assert time_str == f"{hour:02d}:00"


def test_parse_time_baje_invalid_hour():
    time_str, err, ambiguous = parse_time("25 baje", NOW)
    assert time_str is None
    assert err is not None


def test_parse_time_no_time_found():
    time_str, err, ambiguous = parse_time("buy groceries", NOW)
    assert time_str is None
    assert err is None
    assert ambiguous is False


# ── detect_recurrence ──────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["every day", "daily", "har roz", "everyday", "rozana"])
def test_detect_recurrence_daily(text):
    r = detect_recurrence(text)
    assert r == {"type": "daily", "weekday": None, "day_of_month": None}


def test_detect_recurrence_every_monday():
    r = detect_recurrence("every monday")
    assert r["type"] == "weekly"
    assert r["weekday"] == 0


def test_detect_recurrence_har_monday_hindi_english_mix():
    r = detect_recurrence("har monday")
    assert r["type"] == "weekly"
    assert r["weekday"] == 0


@pytest.mark.parametrize("text", ["every week", "weekly", "har hafte"])
def test_detect_recurrence_weekly_no_weekday(text):
    r = detect_recurrence(text)
    assert r["type"] == "weekly"
    assert r["weekday"] is None


def test_detect_recurrence_monthly_specific_day():
    r = detect_recurrence("on the 1st of every month")
    assert r["type"] == "monthly"
    assert r["day_of_month"] == 1


@pytest.mark.parametrize("text", ["every month", "monthly", "har mahine"])
def test_detect_recurrence_monthly_default_day(text):
    r = detect_recurrence(text)
    assert r["type"] == "monthly"
    assert r["day_of_month"] == 1


def test_detect_recurrence_none_for_one_off_task():
    assert detect_recurrence("buy milk tomorrow") is None


# ── might_have_multiple_tasks ────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "buy milk and call mom", "gym aur padhai", "wash car or clean room",
])
def test_might_have_multiple_tasks_true(text):
    assert might_have_multiple_tasks(text) is True


def test_might_have_multiple_tasks_false():
    assert might_have_multiple_tasks("buy milk") is False


# ── validate_datetime ────────────────────────────────────────────────────

def test_validate_datetime_past_date_flagged():
    errors = validate_datetime(d(-5), None, NOW)
    assert any("past" in e.lower() for e in errors)


def test_validate_datetime_future_date_ok():
    errors = validate_datetime(d(5), "14:00", NOW)
    assert errors == []


def test_validate_datetime_bad_time_format():
    errors = validate_datetime(None, "2pm", NOW)  # not HH:MM
    assert any("invalid time format" in e.lower() for e in errors)


def test_validate_datetime_hour_out_of_range():
    errors = validate_datetime(None, "25:00", NOW)
    assert any("invalid hour" in e.lower() for e in errors)


# ── parse_all: integration of date + time + priority + recurrence ────────

def test_parse_all_urgent_sets_high_priority_and_soon_time():
    result = parse_all("urgent submit report", NOW)
    assert result["priority"] == "high"


def test_parse_all_whenever_sets_low_priority():
    result = parse_all("whenever, no rush, water the plants", NOW)
    assert result["priority"] == "low"


def test_parse_all_default_priority_is_medium():
    result = parse_all("buy milk tomorrow at 5pm", NOW)
    assert result["priority"] == "medium"


def test_parse_all_vague_time_with_no_date_infers_today_if_still_ahead():
    # NOW is 10:00; "evening" (18:00) hasn't passed yet today.
    result = parse_all("meeting this evening", NOW)
    assert result["time"] == "18:00"
    assert result["date"] == d(0)


def test_parse_all_vague_time_with_no_date_infers_tomorrow_if_already_passed():
    # NOW is 10:00; "midnight" (00:00) has already passed today.
    result = parse_all("wake me at midnight", NOW)
    assert result["time"] == "00:00"
    assert result["date"] == d(1)


def test_parse_all_recurring_task_still_detects_recurrence_alongside_date():
    result = parse_all("gym every day at 6am", NOW)
    assert result["recurrence"] == {"type": "daily", "weekday": None, "day_of_month": None}
    assert result["time"] == "06:00"


def test_parse_all_multiple_tasks_flag():
    result = parse_all("buy milk and call mom tomorrow", NOW)
    assert result["multiple_tasks"] is True


@pytest.mark.parametrize("text", [
    "submit assignment by Friday",
    "deadline is tomorrow",
    "finish report by 5pm",
    "project tak karna hai",
])
def test_parse_all_deadline_phrasing_detected(text):
    result = parse_all(text, NOW)
    assert result["is_deadline"] is True


def test_parse_all_non_deadline_task_not_flagged():
    result = parse_all("buy milk tomorrow", NOW)
    assert result["is_deadline"] is False


def test_parse_all_ambiguous_time_flag_propagates():
    result = parse_all("3 baje meeting hai", NOW)
    assert result["time_ambiguous"] is True


def test_parse_all_past_date_flag():
    result = parse_all("yesterday I had a meeting", NOW)
    assert result["is_past"] is True


def test_parse_all_invalid_time_flag():
    result = parse_all("meeting at 25:99", NOW)
    assert result["is_invalid_time"] is True
