"""
date_parser.py — Reliable date/time parsing for BAKA
English + Hindi + Hinglish. Tests 1-6, 10-16, 39, 40 coverage.
Bug 2 fix: bare "X baje" (no context word) is flagged as ambiguous
instead of silently defaulting to AM.
"""
import calendar
import re
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")

def _now():
    """Always return IST-aware current time (system clock is UTC)."""
    return datetime.now(IST)

WEEKDAY_MAP = {
    "monday": 0, "mon": 0, "somvar": 0,
    "tuesday": 1, "tue": 1, "mangalvar": 1,
    "wednesday": 2, "wed": 2, "budhvar": 2,
    "thursday": 3, "thu": 3, "thur": 3, "guruvar": 3,
    "friday": 4, "fri": 4, "shukravar": 4,
    "saturday": 5, "sat": 5, "shanivar": 5,
    "sunday": 6, "sun": 6, "ravivar": 6, "itwar": 6,
}

MONTH_MAP = {
    "january": 1, "jan": 1, "janvari": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3, "mart": 3,
    "april": 4, "apr": 4,
    "may": 5, "mai": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def parse_date(text: str, now: datetime = None) -> tuple:
    """Returns (date_str YYYY-MM-DD or None, error_msg or None)"""
    if now is None:
        now = _now()
    t = text.lower().strip()

    if re.search(r'\b(today|aaj|aj|tonight|abhi|is raat|is shaam|aaj raat)\b', t):
        return now.strftime("%Y-%m-%d"), None

    # Period-end phrases → the LAST day of that period (v15.1.0-alpha.5,
    # DBG-0004). "read 12 books this year" means a deadline of 31 Dec; "by
    # month end" → last day of the month; "by end of week" → Sunday. Placed
    # early so a bare year/number elsewhere can't misparse first.
    if re.search(r'\bnext year\b', t):
        return now.replace(year=now.year + 1, month=12, day=31).strftime("%Y-%m-%d"), None
    if re.search(r'\b(this year|by (the )?year[ -]?end|end of (the |this )?year)\b', t):
        return now.replace(month=12, day=31).strftime("%Y-%m-%d"), None
    # "next month end" → last day of NEXT month (v15.2 M4). Must run BEFORE
    # the this-month pattern below: "next month end" contains the word
    # "month", and the correct reading is end-of-next-month, never a
    # this-month value.
    if re.search(r'\b(next month|end of (the |this )?next month)\b', t):
        y, mo = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
        last = calendar.monthrange(y, mo)[1]
        return datetime(y, mo, last, tzinfo=IST).strftime("%Y-%m-%d"), None
    if re.search(r'\b(this month|by (the )?month[ -]?end|end of (the |this )?month)\b', t):
        last = calendar.monthrange(now.year, now.month)[1]
        return now.replace(day=last).strftime("%Y-%m-%d"), None
    if re.search(r'\b(this week|by (the )?week[ -]end|end of (the |this )?week)\b', t):
        return (now + timedelta(days=6 - now.weekday())).strftime("%Y-%m-%d"), None
    # "next weekend" → the Saturday one week after the upcoming weekend
    # (v15.2 M4). MUST run before the bare-weekend pattern below, which would
    # otherwise swallow it.
    if re.search(r'\bnext weekend\b', t):
        days = (5 - now.weekday()) % 7 + 7
        return (now + timedelta(days=days)).strftime("%Y-%m-%d"), None
    # "weekend" / "this weekend" → the upcoming Saturday (the start of the
    # nearest weekend; on Sat/Sun the current weekend has started, so the
    # upcoming Saturday is today / next Saturday). Never a past date.
    if re.search(r'\b(this |a )?weekend\b', t):
        return (now + timedelta(days=(5 - now.weekday()) % 7)).strftime("%Y-%m-%d"), None
    # "next week" → one week from today (v15.2 M4). Aligned with the Worker
    # prompt's NextWeek block so a bare "next week" never falls through
    # unparsed and forces the user to type an explicit date.
    if re.search(r'\bnext week\b', t):
        return (now + timedelta(days=7)).strftime("%Y-%m-%d"), None

    # NOTE: these three checks must run in this order, before the plain
    # "tomorrow" check below. "day after tomorrow" contains the substring
    # "tomorrow", and "beete kal"/"kal ki" contain bare "kal" with nothing
    # following it that the tomorrow pattern's negative lookahead
    # `kal(?!\s+tha)` excludes -- either one falling through to the
    # tomorrow check first would silently misparse a 2-days-out or
    # 1-day-in-the-past phrase as "tomorrow". Found by tests/test_date_parser.py.
    if re.search(r'\b(parso|parson|naso|day after tomorrow)\b', t):
        return (now + timedelta(days=2)).strftime("%Y-%m-%d"), None

    if re.search(r'\b(yesterday|kal tha|kal ki|beete kal)\b', t):
        d = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        return d, "⚠️ That date (yesterday) is in the past!"

    if re.search(r'\b(tomorrow|kal(?!\s+tha)|agal din|kal subah|kal raat|kal shaam)\b', t):
        return (now + timedelta(days=1)).strftime("%Y-%m-%d"), None

    m = re.search(r'\bin\s+(\d+)\s+days?\b', t)
    if m:
        return (now + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d"), None

    m = re.search(r'\bnext\s+(\w+)', t)
    if m and m.group(1) in WEEKDAY_MAP:
        target = WEEKDAY_MAP[m.group(1)]
        days = target - now.weekday()
        if days <= 0:
            days += 7
        if days < 7:
            days += 7
        return (now + timedelta(days=days)).strftime("%Y-%m-%d"), None

    for day_name, day_num in sorted(WEEKDAY_MAP.items(), key=lambda x: -len(x[0])):
        if re.search(rf'\b{day_name}\b', t):
            days = day_num - now.weekday()
            if days <= 0:
                days += 7
            return (now + timedelta(days=days)).strftime("%Y-%m-%d"), None

    for month_name, month_num in MONTH_MAP.items():
        m = re.search(rf'\b(\d{{1,2}})\s+{month_name}(?:\s+(\d{{4}}))?\b', t)
        if not m:
            m = re.search(rf'\b{month_name}\s+(\d{{1,2}})(?:\s+(\d{{4}}))?\b', t)
        if m:
            day = int(m.group(1))
            year = int(m.group(2)) if m.lastindex >= 2 and m.group(2) else now.year
            try:
                target = datetime(year, month_num, day)
                if target.date() < now.date():
                    target = datetime(year + 1, month_num, day)
                return target.strftime("%Y-%m-%d"), None
            except ValueError:
                return None, f"⚠️ Invalid date: {day} {month_name}"

    m = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', t)
    if m:
        try:
            target = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if target.date() < now.date():
                return target.strftime("%Y-%m-%d"), "⚠️ That date is in the past!"
            return target.strftime("%Y-%m-%d"), None
        except ValueError:
            return None, "⚠️ Invalid date format"

    return None, None


def parse_time(text: str, now: datetime = None) -> tuple:
    """
    Returns (time_str HH:MM or None, error_msg or None, ambiguous bool).
    ambiguous=True means "X baje" with no AM/PM context — caller should ask.
    """
    if now is None:
        now = _now()
    t = text.lower().strip()

    # Relative time
    m = re.search(r'\bin\s+(\d+)\s+hours?\b', t)
    if m:
        return (now + timedelta(hours=int(m.group(1)))).strftime("%H:%M"), None, False

    m = re.search(r'\bin\s+(\d+)\s+(?:minutes?|mins?)\b', t)
    if m:
        return (now + timedelta(minutes=int(m.group(1)))).strftime("%H:%M"), None, False

    m = re.search(r'\bafter\s+(\d+)\s+(?:minutes?|mins?)\b', t)
    if m:
        return (now + timedelta(minutes=int(m.group(1)))).strftime("%H:%M"), None, False

    m = re.search(r'\bafter\s+(\d+)\s+hours?\b', t)
    if m:
        return (now + timedelta(hours=int(m.group(1)))).strftime("%H:%M"), None, False

    # ── v3.0: Vague time phrases ─────────────────────
    _vague_fixed = [
        ('midnight|aadhi raat', '00:00'),
        ('breakfast|naashta', '08:00'),
        ('morning', '08:00'),
        ('noon|dupehr|baarah baje', '12:00'),
        ('lunch|dopahar ka khana', '13:00'),
        ('afternoon', '14:00'),
        ('end of day|eod|shaam tak', '17:00'),
        ('evening|shaam ko|shaam mein', '18:00'),
        ('tonight', '21:00'),
        ('night', '21:00'),
    ]
    for _pat, _fixed in _vague_fixed:
        # Word-boundary-wrapped: without this, "noon" (checked earlier in
        # the list) matches as a bare substring inside "afternoon",
        # misparsing every "afternoon" mention as 12:00 instead of 14:00.
        # Found by tests/test_date_parser.py.
        if re.search(rf'\b(?:{_pat})\b', t):
            return _fixed, None, False
            # Note: date inference for vague times happens in parse_all() below
    if re.search(r'asap|immediately|right now|abhi karo|jaldi se', t):
        return (now + timedelta(minutes=30)).strftime('%H:%M'), None, False
    if re.search(r'\bsoon\b|thodi der baad|thoda der', t):
        return (now + timedelta(minutes=30)).strftime('%H:%M'), None, False
    if re.search(r'\blater\b|baad mein|kuch der baad', t):
        return (now + timedelta(hours=2)).strftime('%H:%M'), None, False

    # Hindi context words — unambiguous
    m = re.search(r'\braat\s+(\d{1,2})(?::(\d{2}))?\s*(?:baje|bajey)?\b', t)
    if m:
        h = int(m.group(1))
        mn = int(m.group(2)) if m.group(2) else 0
        if h < 12: h += 12
        return f"{h:02d}:{mn:02d}", None, False

    m = re.search(r'\bsubah\s+(\d{1,2})(?::(\d{2}))?\s*(?:baje|bajey)?\b', t)
    if m:
        h = int(m.group(1))
        mn = int(m.group(2)) if m.group(2) else 0
        if h == 12: h = 0
        return f"{h:02d}:{mn:02d}", None, False

    m = re.search(r'\bshaam\s+(\d{1,2})(?::(\d{2}))?\s*(?:baje|bajey)?\b', t)
    if m:
        h = int(m.group(1))
        mn = int(m.group(2)) if m.group(2) else 0
        if h < 12: h += 12
        return f"{h:02d}:{mn:02d}", None, False

    m = re.search(r'\bdopahar\s+(\d{1,2})(?::(\d{2}))?\s*(?:baje|bajey)?\b', t)
    if m:
        h = int(m.group(1))
        mn = int(m.group(2)) if m.group(2) else 0
        if h < 12: h += 12
        return f"{h:02d}:{mn:02d}", None, False

    # Military time '1400' -> 14:00, ONLY with a time context word
    # (at/by/around before, or hrs/hours after) so years like 2026 don't match.
    m = re.search(r'\b(?:at|by|around)\s+(\d{4})\b', t)
    if not m:
        m = re.search(r'\b(\d{4})\s*(?:hrs|hours|hr)\b', t)
    if m:
        digits = m.group(1)
        h, mn = int(digits[:2]), int(digits[2:])
        if h <= 23 and mn <= 59:
            return f"{h:02d}:{mn:02d}", None, False

    # HH:MM — always unambiguous
    m = re.search(r'\b(\d{1,2}):(\d{2})\b', t)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if h > 23:
            return None, f"⚠️ Invalid time: {h}:{mn:02d} (hours must be 0-23)", False
        if mn > 59:
            return None, f"⚠️ Invalid time: {h}:{mn:02d} (minutes must be 0-59)", False
        return f"{h:02d}:{mn:02d}", None, False

    # X pm / X am — unambiguous
    m = re.search(r'\b(\d{1,2})\s*(pm|am)\b', t)
    if m:
        h, period = int(m.group(1)), m.group(2)
        if h > 12:
            return None, f"⚠️ Invalid: {h} {period.upper()} — use 1-12 with AM/PM", False
        if period == "pm" and h != 12: h += 12
        elif period == "am" and h == 12: h = 0
        return f"{h:02d}:00", None, False

    # BUG 2 FIX: bare "X baje" — ambiguous if hour < 8 and no context word present
    m = re.search(r'\b(\d{1,2})\s*(?:baje|bajey)\b', t)
    if m:
        h = int(m.group(1))
        if h > 23:
            return None, f"⚠️ Invalid time: {h} baje", False
        # Hours 8-12 are almost always morning, 13-23 are 24hr — unambiguous
        if h >= 8:
            return f"{h:02d}:00", None, False
        # Hours 1-7 are ambiguous without context (could be 01:00 or 13:00 etc.)
        return f"{h:02d}:00", None, True   # ← ambiguous flag

    return None, None, False


def detect_recurrence(text: str) -> dict | None:
    t = text.lower()
    if re.search(r'\b(every\s*day|daily|har\s*roz|roz|har\s*din|everyday|rozana)\b', t):
        return {"type": "daily", "weekday": None, "day_of_month": None}
    for day_name, day_num in WEEKDAY_MAP.items():
        if re.search(rf'\bevery\s+{day_name}\b', t) or re.search(rf'\bhar\s+{day_name}\b', t):
            return {"type": "weekly", "weekday": day_num, "day_of_month": None}
    if re.search(r'\b(every\s*week|weekly|har\s*hafte|hafte\s*mein)\b', t):
        return {"type": "weekly", "weekday": None, "day_of_month": None}
    m = re.search(r'\b(?:on the|every month on|har mahine)\s*(\d{1,2})(?:st|nd|rd|th)?\b', t)
    if m:
        return {"type": "monthly", "weekday": None, "day_of_month": int(m.group(1))}
    if re.search(r'\b(every\s*month|monthly|har\s*mahine|mahine\s*mein)\b', t):
        return {"type": "monthly", "weekday": None, "day_of_month": 1}
    return None


def might_have_multiple_tasks(text: str) -> bool:
    return bool(re.search(r'\b(and|aur|or|also|&)\b', text.lower()))


def validate_datetime(date_str, time_str, now: datetime = None) -> list:
    if now is None:
        now = _now()
    errors = []
    if date_str:
        try:
            target = datetime.strptime(date_str, "%Y-%m-%d")
            if target.date() < now.date():
                errors.append(f"⚠️ Date {date_str} is in the past!")
        except ValueError:
            errors.append(f"⚠️ Invalid date: {date_str}")
    if time_str:
        m = re.match(r'^(\d{2}):(\d{2})$', time_str)
        if m:
            h, mn = int(m.group(1)), int(m.group(2))
            if h > 23: errors.append(f"⚠️ Invalid hour: {h}")
            if mn > 59: errors.append(f"⚠️ Invalid minutes: {mn}")
        else:
            errors.append(f"⚠️ Invalid time format: {time_str}")
    return errors


def parse_all(text: str, now: datetime = None) -> dict:
    if now is None:
        now = _now()
    date_str, date_err = parse_date(text, now)
    time_str, time_err, time_ambiguous = parse_time(text, now)
    recurrence = detect_recurrence(text)
    multiple = might_have_multiple_tasks(text)
    errors = []
    if date_err: errors.append(date_err)
    if time_err:  errors.append(time_err)
    # ── v3.1 Bug 18 fix: infer date when vague time was used but no date given ──
    # If parser returned a clock time but no date, and the clock time has already
    # passed today, schedule it for tomorrow. Otherwise today.
    if time_str and not date_str:
        try:
            current_hm = now.strftime("%H:%M")
            target_hm = time_str
            if target_hm < current_hm:
                # Time already passed today — use tomorrow
                date_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                # Still ahead today
                date_str = now.strftime("%Y-%m-%d")
        except Exception:
            pass

    # v3.0: detect urgency and priority from language
    t_lower = text.lower()
    if re.search(r'\burgent\b|\basap\b|\bjaldi\b|\bimmediately\b|\bright now\b|\bcritical\b|\bimportant\b|\bzaruri\b', t_lower):
        priority = "high"
    elif re.search(r'\bwhenever\b|\bno rush\b|\bkoi jaldi nahi\b|\bkab bhi\b|\bsomeday\b', t_lower):
        priority = "low"
    else:
        priority = "medium"

    # v10.1: detect deadline phrasing (parser fallback in case AI misses it)
    # Catches: "due X", "submit by X", "deliver X by Y", "finish X by Y", "deadline...", "tak"
    is_deadline = bool(re.search(
        r'\b(due|deadline)\b'
        r'|\b(submit|deliver|finish|complete|done|hand in|hand over|turn in)\b[^.]*\bby\b'
        r'|\bby the end of\b|\bbefore (the )?(deadline|due date)\b'
        r'|\b(submission|deadline hai)\b'
        r'|\btak (karna hai|hai)?\b',
        t_lower
    ))

    return {
        "date": date_str,
        "time": time_str,
        "time_ambiguous": time_ambiguous,
        "recurrence": recurrence,
        "multiple_tasks": multiple,
        "errors": errors,
        "is_past": bool(date_err and "past" in date_err),
        "is_invalid_time": time_str is None and time_err is not None,
        "priority": priority,
        "is_deadline": is_deadline,
    }