"""Self-tests: habit creation round-trip (category Habits).

Habits are task rows (is_habit=1), so cleanup uses delete_task().
"""
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest


@selftest(name="Habit Creation", category="Habits")
def check_habit_creation():
    import database as db
    hid = db.add_habit(SELFTEST_USER_ID, "[selftest] temp habit")
    try:
        habits = db.get_habits(SELFTEST_USER_ID)
        if not any(h[0] == hid for h in habits):
            raise SelfTestFail(f"created habit #{hid} not in get_habits()")
        return f"created + read habit #{hid}"
    finally:
        db.delete_task(hid, SELFTEST_USER_ID)
