"""Self-tests: core services -- settings load + scheduler availability
(category Core). Both read-only."""
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest


@selftest(name="Settings Load", category="Core")
def check_settings_load():
    import database as db
    prefs = db.get_user_prefs(SELFTEST_USER_ID)   # returns defaults, no insert
    for field in ("quiet_start", "quiet_end", "interval", "max_reminders"):
        if field not in prefs:
            raise SelfTestFail(f"prefs missing '{field}'", details=str(prefs))
    return f"prefs ok · interval {prefs['interval']}m"


@selftest(name="Scheduler Available", category="Core")
def check_scheduler_available():
    import scheduler
    due = scheduler.get_due_tasks()               # must be callable + return a list
    if not isinstance(due, list):
        raise SelfTestFail(f"get_due_tasks() returned {type(due).__name__}, not list")
    return f"scheduler ok · {len(due)} due now"
