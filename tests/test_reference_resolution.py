"""
Tests for M1 -- Reference Resolution + Active Entity (v15.1.0-alpha.12).

A conversational reference ("show her", "the first one", "set it to 90")
resolves deterministically against the context already established in the
conversation: the DB-backed active entity, the recent-mention stack, and
the last ordered list shown. The resolver never calls the LLM and never
mutates the database; EntityManager's existing handlers perform the actual
operation, now aware of the resolved referent.

All tests are offline and deterministic: the LLM is mocked, and the tests
assert that bare references never reach the LLM at all.
"""
import json
from unittest.mock import Mock

import database as db
from core.ai.entity_manager import EntityManager
from core.ai.reference_context import ReferenceContext
from core.ai.reference_resolver import ReferenceResolver
from core.workspace.engine import EntityEngine


def _ai(intent, entity_name="", fields=None, query=""):
    return json.dumps({"intent": intent, "entity_name": entity_name,
                       "fields": fields or {}, "query": query})


def _mk_workspace(uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Test Game", template="game",
                              seed_milestones=False)
    db.tg_set_active(uid, ws.id, "milestone", None)
    return eng, ws


def _by_title(eng, uid, ws, title):
    return next(m for m in eng.list_milestones(uid, ws.id)
                if m.title == title)


# ── 1 & 2. Create entity, then "show her"/"show him" (bare reference) ─────

class TestCreateThenPronoun:
    def test_create_then_show_her(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[_ai("create", "Furina")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "Create character Furina")
        assert handled is True
        furina = _by_title(eng, uid, ws, "Furina")

        # "Show her" is a bare reference → resolved deterministically,
        # NO LLM call.
        handled, reply = mgr.process(uid, "Show her")
        assert ai.call_count == 1
        assert handled is True
        assert "Furina" in reply
        # Create populated the active entity.
        assert db.tg_get_active(uid)[2] == furina.id

    def test_create_then_show_him(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[_ai("create", "Zhongli")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "Create character Zhongli")
        assert handled is True

        handled, reply = mgr.process(uid, "Show him")
        assert ai.call_count == 1
        assert handled is True
        assert "Zhongli" in reply


# ── 3. Create entity, then a full-sentence pronoun query ──────────────────

class TestFullSentencePronoun:
    def test_create_then_what_weapon_does_she_use(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[
            _ai("create", "Furina"),
            _ai("retrieve", query="what weapon does she use?"),
        ])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, _ = mgr.process(uid, "Create character Furina")
        assert handled is True

        # Not a bare reference → the LLM still classifies, but the prompt
        # tells it the active entity (Furina).
        handled, reply = mgr.process(uid, "What weapon does she use?")
        assert ai.call_count == 2
        assert handled is True
        assert "Furina" in reply
        assert "Active entity: Furina" in ai.call_args_list[1][0][0]


# ── 4. Update entity, then pronoun follow-up ──────────────────────────────

class TestUpdateThenPronoun:
    def test_update_entity_then_pronoun_followup(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[
            _ai("create", "Furina"),
            _ai("update", fields={"level": 90}),
        ])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create character Furina")
        # "her" resolves to the active entity; the update applies to it even
        # though the LLM returned an empty entity_name.
        handled, reply = mgr.process(uid, "Set her level to 90")
        assert handled is True
        furina = _by_title(eng, uid, ws, "Furina")
        assert furina.fields.get("level") == 90

        # Follow-up pronoun still resolves to Furina (update kept it active).
        handled, reply = mgr.process(uid, "Show her")
        assert ai.call_count == 2
        assert handled is True
        assert "Furina" in reply


# ── 5. Retrieve entity, then pronoun follow-up ────────────────────────────

class TestRetrieveThenPronoun:
    def test_retrieve_entity_then_pronoun_followup(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Raiden")   # exists, not yet active
        ai = Mock(side_effect=[
            _ai("create", "Furina"),
            _ai("retrieve", query="Show Raiden"),
        ])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create character Furina")
        # Name-based retrieve → Raiden becomes the active entity (explicit
        # selection per lifecycle).
        handled, reply = mgr.process(uid, "Show Raiden")
        assert handled is True
        assert "Raiden" in reply
        raiden = _by_title(eng, uid, ws, "Raiden")
        assert db.tg_get_active(uid)[2] == raiden.id

        # Pronoun now resolves to the newly active entity.
        handled, reply = mgr.process(uid, "Show her")
        assert ai.call_count == 2
        assert handled is True
        assert "Raiden" in reply and "Furina" not in reply


# ── 6. Switching active entity: last create wins ──────────────────────────

class TestSwitchActiveEntity:
    def test_create_two_show_him_gets_latest(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[_ai("create", "Furina"),
                               _ai("create", "Zhongli")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create Furina")
        mgr.process(uid, "Create Zhongli")

        zhongli = _by_title(eng, uid, ws, "Zhongli")
        assert db.tg_get_active(uid)[2] == zhongli.id

        handled, reply = mgr.process(uid, "Show him")
        assert ai.call_count == 2
        assert handled is True
        assert "Zhongli" in reply and "Furina" not in reply


# ── 7. Active entity persists across an update ────────────────────────────

class TestActiveEntityAfterUpdate:
    def test_show_her_after_update_returns_furina(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[
            _ai("create", "Furina"),
            _ai("update", "Furina", fields={"level": 80}),
        ])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create Furina")
        handled, reply = mgr.process(uid, "Furina is level 80")
        assert handled is True

        handled, reply = mgr.process(uid, "Show her")
        assert ai.call_count == 2
        assert handled is True
        assert "Furina" in reply


# ── 8. Deleted active entity must not resolve ─────────────────────────────

class TestDeletedActiveEntity:
    def test_reference_does_not_resolve_to_deleted(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[_ai("create", "Furina"),
                               _ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create character Furina")
        furina = _by_title(eng, uid, ws, "Furina")
        eng.delete_milestone(uid, furina.id)

        # Must not crash, must not resolve to the deleted entity.
        handled, reply = mgr.process(uid, "Show her")
        assert not handled or "Furina" not in reply
        # The dangling active pointer was cleared (self-heal, done by the
        # caller, never by the resolver).
        active = db.tg_get_active(uid)
        assert active is None or active[2] is None


# ── 9. Ambiguous pronoun → clarify, never guess ───────────────────────────

class TestAmbiguousPronoun:
    def test_ambiguous_show_her_clarifies(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[_ai("create", "Furina"),
                               _ai("create", "Raiden Shogun")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create Furina")
        mgr.process(uid, "Create Raiden Shogun")
        # Clear the active ENTITY (keep the workspace) so both candidates
        # are equally plausible.
        db.tg_set_active(uid, ws.id)

        handled, reply = mgr.process(uid, "Show her")
        assert handled is True
        assert "which one" in reply.lower()
        assert "Furina" in reply and "Raiden Shogun" in reply
        assert ai.call_count == 2   # never guessed via the LLM


# ── 10. No active entity → no crash, no invented entity ───────────────────

class TestNoActiveEntity:
    def test_show_her_without_context_falls_through(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)          # workspace, but no entities
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "Show her")
        assert not handled
        assert reply == ""
        assert ai.call_count == 1             # fell through to normal path


# ── 11. Ordinal reference with an available ordered context ───────────────

class TestOrdinalReference:
    def test_show_the_first_one_after_a_list(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        for name in ("Alpha", "Beta", "Gamma"):
            m = eng.add_milestone(uid, ws.id, name)
            eng.update_field(uid, m.id, "element", "hydro")

        ai = Mock(side_effect=[_ai("retrieve", query="show all hydro")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        # A list is shown → the ordered context is recorded.
        handled, reply = mgr.process(uid, "Show all hydro")
        assert handled is True

        # "the first one" resolves to the first entity of that list.
        handled, reply = mgr.process(uid, "Show the first one")
        assert ai.call_count == 1             # ordinal resolved, no LLM
        assert handled is True
        assert "Alpha" in reply


# ── 12. Unsupported / unknown reference fails gracefully ──────────────────

class TestUnknownReference:
    def test_ordinal_without_ordered_context_falls_through(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)          # workspace, no entities shown
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        # No ordered context has been established → must NOT resolve.
        handled, reply = mgr.process(uid, "Show the first one")
        assert not handled
        assert reply == ""
        assert ai.call_count == 1             # fell through, no crash

    def test_unsupported_ordinal_word_falls_through(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "Show the tenth one")
        assert not handled
        assert reply == ""
        assert ai.call_count == 1


# ── Resolver unit tests: deterministic detection / no false positives ─────

class TestResolverDetection:
    def test_no_reference_token_is_none(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ctx = ReferenceContext()
        res = ReferenceResolver(engine=eng, context=ctx)
        ents = eng.list_milestones(uid, ws.id)
        r = res.resolve(uid, "the sky is blue", ws.id, ents)
        assert r.kind == "none" and r.had_reference is False

    def test_active_entity_wins(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        m = eng.add_milestone(uid, ws.id, "Furina")
        db.tg_set_active(uid, ws.id, "milestone", m.id)
        ctx = ReferenceContext()
        res = ReferenceResolver(engine=eng, context=ctx)
        ents = eng.list_milestones(uid, ws.id)
        r = res.resolve(uid, "show her", ws.id, ents)
        assert r.kind == "entity" and r.entity.id == m.id

    def test_recent_mention_resolves_when_no_active(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        m = eng.add_milestone(uid, ws.id, "Furina")
        ctx = ReferenceContext()
        from core.ai.reference_context import Referent
        ctx.note_mention(uid, Referent(kind="milestone", id=m.id,
                                       title="Furina", workspace_id=ws.id))
        res = ReferenceResolver(engine=eng, context=ctx)
        ents = eng.list_milestones(uid, ws.id)
        r = res.resolve(uid, "show him", ws.id, ents)
        assert r.kind == "entity" and r.entity.id == m.id

    def test_ordinal_without_ordered_context_is_unresolved(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        res = ReferenceResolver(engine=eng, context=ReferenceContext())
        r = res.resolve(uid, "show the first one", ws.id,
                        eng.list_milestones(uid, ws.id))
        assert r.kind == "none" and r.had_reference is True

    def test_ambiguous_when_two_recent_mentions(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        a = eng.add_milestone(uid, ws.id, "Furina")
        b = eng.add_milestone(uid, ws.id, "Raiden")
        ctx = ReferenceContext()
        from core.ai.reference_context import Referent
        ctx.note_mention(uid, Referent(kind="milestone", id=a.id,
                                       title="Furina", workspace_id=ws.id))
        ctx.note_mention(uid, Referent(kind="milestone", id=b.id,
                                       title="Raiden", workspace_id=ws.id))
        res = ReferenceResolver(engine=eng, context=ctx)
        r = res.resolve(uid, "show her", ws.id,
                        eng.list_milestones(uid, ws.id))
        assert r.ambiguous is True and len(r.candidates) == 2
