"""
date_parser.py — Reliable date/time parsing for JARVIS
English + Hindi + Hinglish. Tests 1-6, 10-16, 39, 40 coverage.
Bug 2 fix: bare "X baje" (no context word) is flagged as ambiguous
instead of silently defaulting to AM.
"""
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

    if re.search(r'\b(tomorrow|kal(?!\s+tha)|agal din|kal subah|kal raat|kal shaam)\b', t):
        return (now + timedelta(days=1)).strftime("%Y-%m-%d"), None

    if re.search(r'\b(parso|parson|naso|day after tomorrow)\b', t):
        return (now + timedelta(days=2)).strftime("%Y-%m-%d"), None

    if re.search(r'\b(yesterday|kal tha|kal ki|beete kal)\b', t):
        d = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        return d, "⚠️ That date (yesterday) is in the past!"

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
    return {
        "date": date_str,
        "time": time_str,
        "time_ambiguous": time_ambiguous,   # ← new field
        "recurrence": recurrence,
        "multiple_tasks": multiple,
        "errors": errors,
        "is_past": bool(date_err and "past" in date_err),
        "is_invalid_time": time_str is None and time_err is not None,
    }