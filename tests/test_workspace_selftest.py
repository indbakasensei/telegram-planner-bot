"""
Tests for the Workspace self-test checks + the delete_workspace primitive
(v15.0-rc.2). Confirms the live /selftest probes pass and leave no residue.
"""
import database as db
from core.selftest.models import SELFTEST_USER_ID
from core.selftest.tests.test_workspace import (
    check_workspace_engine,
    check_workspace_templates,
)
from core.workspace.engine import EntityEngine


def test_delete_workspace_hard_deletes_scoped(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Temp", template="project", seed_milestones=True)
    assert db.get_workspace(ws.id, uid) is not None
    assert db.get_milestones(ws.id)  # seeded pipeline present
    ok = db.delete_workspace(ws.id, uid)
    assert ok is True
    assert db.get_workspace(ws.id, uid) is None
    assert db.get_milestones(ws.id) == []


def test_delete_workspace_respects_ownership(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Mine", template="generic")
    assert db.delete_workspace(ws.id, uid + 999) is False   # not the owner
    assert db.get_workspace(ws.id, uid) is not None          # untouched


def test_selftest_templates_check_passes(temp_db):
    msg = check_workspace_templates()
    assert "registered" in msg


def test_selftest_engine_check_passes_and_cleans_up(temp_db):
    msg = check_workspace_engine()
    assert "100%" in msg
    # round-trip cleaned up after itself: no residue under the selftest user
    assert db.get_workspaces(SELFTEST_USER_ID) == []


def test_selftest_groups_check_passes_and_cleans_up(temp_db):
    from core.selftest.tests.test_workspace import check_workspace_groups
    msg = check_workspace_groups()
    assert "groups ok" in msg
    assert db.get_workspaces(SELFTEST_USER_ID) == []


def test_selftest_cognitive_check_passes_and_cleans_up(temp_db):
    from core.selftest.tests.test_workspace import check_cognitive_engine
    msg = check_cognitive_engine()
    assert "cognitive ok" in msg
    assert db.get_workspaces(SELFTEST_USER_ID) == []
