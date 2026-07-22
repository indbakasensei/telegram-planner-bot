"""Self-tests: goal creation round-trip (category Goals).

database.py has no delete_goal(), so this test cleans up its temporary
row with a direct DELETE in the finally block -- acceptable here (test
infrastructure, under the synthetic user id), and it never touches a
real user's goals.
"""
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest


@selftest(name="Goal Creation", category="Goals")
def check_goal_creation():
    import database as db
    gid = db.add_goal(SELFTEST_USER_ID, "[selftest] temp goal")
    try:
        goals = db.get_goals(SELFTEST_USER_ID)
        if not any(g[0] == gid for g in goals):
            raise SelfTestFail(f"created goal #{gid} not in get_goals()")
        return f"created + read goal #{gid}"
    finally:
        import sqlite3
        conn = sqlite3.connect(db.DB_NAME)
        conn.execute("DELETE FROM goals WHERE id=? AND user_id=?",
                     (gid, SELFTEST_USER_ID))
        conn.commit()
        conn.close()
