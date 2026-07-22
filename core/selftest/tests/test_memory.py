"""Self-tests: memory write/read/overwrite (category Memory).

Both tests write under the synthetic SELFTEST_USER_ID and delete their
rows in a finally block, so production data is never touched.
"""
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest

_KEY = "__selftest_probe__"


@selftest(name="Memory Write/Read", category="Memory")
def check_memory_roundtrip():
    import database as db
    try:
        db.save_memory(SELFTEST_USER_ID, _KEY, "hello")
        got = db.get_memory(SELFTEST_USER_ID, _KEY)
        if got != "hello":
            raise SelfTestFail(f"read back {got!r}, expected 'hello'")
        return "wrote and read a memory"
    finally:
        db.delete_memory(SELFTEST_USER_ID, _KEY)


@selftest(name="Memory Overwrite", category="Memory")
def check_memory_overwrite():
    import database as db
    try:
        db.save_memory(SELFTEST_USER_ID, _KEY, "first")
        db.save_memory(SELFTEST_USER_ID, _KEY, "second")
        got = db.get_memory(SELFTEST_USER_ID, _KEY)
        if got != "second":
            raise SelfTestFail(f"overwrite kept {got!r}, expected 'second'")
        return "same key overwrites (no duplicate)"
    finally:
        db.delete_memory(SELFTEST_USER_ID, _KEY)
