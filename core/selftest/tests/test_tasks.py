"""Self-tests: task creation round-trip (category Tasks).

Creates a temporary task under SELFTEST_USER_ID and deletes it in a
finally block.
"""
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest


@selftest(name="Task Creation", category="Tasks")
def check_task_creation():
    import database as db
    tid = db.add_task(SELFTEST_USER_ID, "[selftest] temp task")
    try:
        row = db.get_task_by_id(tid, SELFTEST_USER_ID)
        if not row or row[1] != "[selftest] temp task":
            raise SelfTestFail(f"created task #{tid} not readable")
        return f"created + read task #{tid}"
    finally:
        db.delete_task(tid, SELFTEST_USER_ID)
