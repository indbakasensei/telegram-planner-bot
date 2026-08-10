"""
Tests for v15.1.0-alpha.13 -- EntityManager projection seam (M10).

The Natural Language Entity Manager must stay Telegram-agnostic: the
projection is a duck-typed object injected by the caller (main.py injects the
live one; tests inject a recorder/failing one). These tests verify that a
successful NL create/update ALSO projects to a topic (initial card /
append-only update) while a projection failure NEVER fails or rolls back the
DB operation, and that non-mutating intents (retrieve, bare reference) make
NO projection call.
"""
import database as db
from core.ai.entity_manager import EntityManager
from core.workspace.engine import EntityEngine


class RecorderProj:
    """Duck-typed projection that records every call; returns a fake topic id."""
    def __init__(self, fail_ensure=False, fail_update=False):
        self.ensured = []     # (entity_type, entity_id, title, initial_message)
        self.updates = []     # (entity_type, entity_id, title, text, initial)
        self._fail_ensure = fail_ensure
        self._fail_update = fail_update

    def ensure_entity_topic(self, user_id, workspace_id, entity_type,
                            entity_id, title, initial_message=None):
        if self._fail_ensure:
            raise RuntimeError("topic creation failed")
        self.ensured.append((entity_type, entity_id, title, initial_message))
        return 4242

    def post_entity_update(self, user_id, workspace_id, entity_type,
                           entity_id, entity_title, text,
                           initial_message=None):
        if self._fail_update:
            raise RuntimeError("topic update failed")
        self.updates.append(
            (entity_type, entity_id, entity_title, text, initial_message))
        return None


def _setup(uid, title="[test] projection", template="game"):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, title, template=template,
                              seed_milestones=False)
    db.tg_set_active(uid, ws.id, "milestone", None)
    return eng, ws


_CREATE = ('{"intent": "create", "entity_name": "Arlecchino", '
           '"fields": {}, "query": ""}')


def test_nl_create_projects_topic_initial_card_and_active(temp_db, uid):
    eng, ws = _setup(uid)
    from unittest.mock import Mock
    proj = RecorderProj()
    mgr = EntityManager(engine=eng, ai_call=Mock(return_value=_CREATE))

    handled, reply = mgr.process(uid, "Create character Arlecchino",
                                 projection=proj)

    assert handled and "Arlecchino" in reply and "topic created" in reply
    assert len(proj.ensured) == 1
    etype, eid, title, initial = proj.ensured[0]
    assert etype == "milestone" and title == "Arlecchino"
    assert "Arlecchino" in initial and "Status" in initial   # real card
    # the created entity became the active referent
    m = eng.list_milestones(uid, ws.id)[0]
    assert eid == m.id
    assert db.tg_get_active(uid)[2] == m.id


def test_nl_create_without_projection_makes_no_topic_call(temp_db, uid):
    eng, ws = _setup(uid)
    from unittest.mock import Mock
    proj = RecorderProj()
    mgr = EntityManager(engine=eng, ai_call=Mock(return_value=_CREATE))

    handled, reply = mgr.process(uid, "Create character Arlecchino")

    assert handled and "Arlecchino" in reply
    assert "topic created" not in reply          # no projection → no claim
    assert proj.ensured == [] and proj.updates == []
    assert len(eng.list_milestones(uid, ws.id)) == 1


def test_nl_create_projection_failure_keeps_entity_and_warns(temp_db, uid):
    eng, ws = _setup(uid)
    from unittest.mock import Mock
    bad = RecorderProj(fail_ensure=True)
    mgr = EntityManager(engine=eng, ai_call=Mock(return_value=_CREATE))

    handled, reply = mgr.process(uid, "Create character Arlecchino",
                                 projection=bad)

    # DB op succeeded, failure is observable in the reply, nothing raised
    assert handled
    assert "NOT created" in reply and "/topicbackfill" in reply
    ms = eng.list_milestones(uid, ws.id)
    assert [m.title for m in ms] == ["Arlecchino"]
    # and the DB entity is still the active referent
    assert db.tg_get_active(uid)[2] == ms[0].id


def test_nl_deterministic_update_posts_append_only_message(temp_db, uid):
    eng, ws = _setup(uid)
    m = eng.add_milestone(uid, ws.id, "Arlecchino")
    eng.set_fields(uid, m.id, {"level": 50})
    db.tg_set_active(uid, ws.id, "milestone", m.id)
    proj = RecorderProj()
    mgr = EntityManager(engine=eng, ai_call=lambda p: (_ for _ in ()).throw(
        AssertionError("deterministic path must not call the LLM")))

    handled, reply = mgr.process(uid, "Arlecchino is level 90",
                                 projection=proj)

    assert handled and "90" in reply
    assert eng.get_fields(uid, m.id).get("level") == 90
    assert len(proj.updates) == 1
    etype, eid, title, text, initial = proj.updates[0]
    assert etype == "milestone" and eid == m.id and title == "Arlecchino"
    # old value captured from the pre-update DB read, never invented
    assert "50 → 90" in text
    # self-healing: since the entity has no topic yet, the CURRENT card is
    # passed as the initial message for the topic that gets created first --
    # it must reflect the post-update DB state, never a stale field
    assert initial is not None and "Level: 90" in initial


def test_nl_llm_update_posts_append_only_message(temp_db, uid):
    eng, ws = _setup(uid)
    m = eng.add_milestone(uid, ws.id, "Nefer")
    eng.set_fields(uid, m.id, {"level": 10})
    db.tg_set_active(uid, ws.id, "milestone", m.id)
    from unittest.mock import Mock
    proj = RecorderProj()
    mgr = EntityManager(
        engine=eng,
        ai_call=Mock(return_value=(
            '{"intent": "update", "entity_name": "Nefer", '
            '"fields": {"level": 80}, "query": ""}')))

    handled, reply = mgr.process(uid, "boost Nefer's level to 80",
                                 projection=proj)

    assert handled and "80" in reply
    assert eng.get_fields(uid, m.id).get("level") == 80
    assert len(proj.updates) == 1
    _t, _eid, _title, text, _initial = proj.updates[0]
    assert "10 → 80" in text


def test_nl_update_projection_failure_keeps_db_update(temp_db, uid):
    eng, ws = _setup(uid)
    m = eng.add_milestone(uid, ws.id, "Arlecchino")
    eng.set_fields(uid, m.id, {"level": 50})
    db.tg_set_active(uid, ws.id, "milestone", m.id)
    bad = RecorderProj(fail_update=True)
    mgr = EntityManager(engine=eng, ai_call=lambda p: (_ for _ in ()).throw(
        AssertionError("deterministic path must not call the LLM")))

    handled, reply = mgr.process(uid, "Arlecchino is level 90",
                                 projection=bad)

    # the DB update stands even though the topic post failed
    assert handled and "Updated" in reply and "90" in reply
    assert eng.get_fields(uid, m.id).get("level") == 90


def test_bare_reference_makes_no_projection_call(temp_db, uid):
    eng, ws = _setup(uid)
    from unittest.mock import Mock
    proj = RecorderProj()
    EntityManager(engine=eng, ai_call=Mock(return_value=(
        '{"intent": "create", "entity_name": "TestRef", '
        '"fields": {}, "query": ""}'))).process(
        uid, "Create character TestRef", projection=proj)
    assert len(proj.ensured) == 1

    # a fresh manager proves the referent is DB-backed, and 'Show her' must
    # NOT touch the projection (it's a read)
    ai_never = Mock(side_effect=AssertionError("bare reference must not call LLM"))
    proj2 = RecorderProj()
    mgr2 = EntityManager(engine=eng, ai_call=ai_never)
    handled, reply = mgr2.process(uid, "Show her", projection=proj2)
    assert handled and "TestRef" in reply
    assert proj2.ensured == [] and proj2.updates == []


def test_retrieve_makes_no_projection_call(temp_db, uid):
    eng, ws = _setup(uid)
    eng.add_milestone(uid, ws.id, "Hu Tao")
    from unittest.mock import Mock
    proj = RecorderProj()
    mgr = EntityManager(
        engine=eng,
        ai_call=Mock(return_value=(
            '{"intent": "retrieve", "entity_name": "Hu Tao", '
            '"query": "Show Hu Tao"}')))
    handled, reply = mgr.process(uid, "Show Hu Tao",
                                 projection=proj)
    assert handled and "Hu Tao" in reply
    assert proj.ensured == [] and proj.updates == []
