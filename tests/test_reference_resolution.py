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
        ai = Mock(side_effect=[_ai("create", "Furina")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create character Furina")
        # "her" resolves to the active entity; the update applies to it via the
        # deterministic pre-extractor (NO LLM call) — "set her level to 90".
        handled, reply = mgr.process(uid, "Set her level to 90")
        assert handled is True
        assert ai.call_count == 1
        furina = _by_title(eng, uid, ws, "Furina")
        assert furina.fields.get("level") == 90

        # Follow-up pronoun still resolves to Furina (update kept it active).
        handled, reply = mgr.process(uid, "Show her")
        assert ai.call_count == 1
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
        ai = Mock(side_effect=[_ai("create", "Furina")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create Furina")
        # "Furina is level 80" is a deterministic single-field update — the
        # extractor applies it without the LLM and keeps Furina active.
        handled, reply = mgr.process(uid, "Furina is level 80")
        assert handled is True
        assert ai.call_count == 1
        furina = _by_title(eng, uid, ws, "Furina")
        assert furina.fields.get("level") == 80

        handled, reply = mgr.process(uid, "Show her")
        assert ai.call_count == 1
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


# ── 13. Deterministic single-field updates (M1 acceptance fix) ─────────────
# "Sucrose is level70" was previously misclassified by the fast LLM as
# `retrieve`, so the update never happened. These prove the deterministic
# pre-extractor applies the field (persisted + retrievable) with NO LLM call.

class TestDeterministicFieldUpdate:
    def test_field_persisted_as_70(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        m = eng.add_milestone(uid, ws.id, "Sucrose")
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        # The exact manual message: no space between field and value.
        handled, reply = mgr.process(uid, "Sucrose is level70")
        assert handled is True
        assert ai.call_count == 0              # deterministic, never hit the LLM
        sucrose = _by_title(eng, uid, ws, "Sucrose")
        assert sucrose.fields.get("level") == 70

        # The value is actually retrievable: "Show her" resolves to the now
        # active Sucrose and its card shows 70.
        handled, reply = mgr.process(uid, "Show her")
        assert handled is True and "70" in reply

    def test_space_form_with_connector(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Sucrose")
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "Sucrose level is 70")
        assert handled is True and ai.call_count == 0
        assert _by_title(eng, uid, ws, "Sucrose").fields.get("level") == 70

    def test_possessive_field_is_value(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Sucrose")
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "Sucrose's priority is high")
        assert handled is True and ai.call_count == 0
        assert _by_title(eng, uid, ws, "Sucrose").fields.get("priority") == "high"

    def test_set_verb_with_explicit_title(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Sucrose")
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "Set Sucrose's level to 90")
        assert handled is True and ai.call_count == 0
        assert _by_title(eng, uid, ws, "Sucrose").fields.get("level") == 90

    def test_pronoun_form_against_active_entity(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Sucrose")
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        # First deterministic update makes Sucrose the active entity.
        mgr.process(uid, "Sucrose is level 50")
        # Pronoun form routes the update to the active entity (preferred).
        handled, reply = mgr.process(uid, "Set her level to 90")
        assert handled is True and ai.call_count == 0
        assert _by_title(eng, uid, ws, "Sucrose").fields.get("level") == 90

    def test_question_is_never_treated_as_update(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Sucrose")
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "What level is Sucrose?")
        assert not handled and reply == ""     # fell through, nothing mutated
        assert _by_title(eng, uid, ws, "Sucrose").fields.get("level") is None
        assert ai.call_count == 1              # went through the normal path

    def test_unknown_field_falls_through(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Sucrose")
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        # "a hydro character" is not a <field> <value> pattern → LLM decides.
        handled, reply = mgr.process(uid, "Sucrose is a hydro character")
        assert not handled
        assert ai.call_count == 1

    def test_clause_is_not_a_value(self, temp_db, uid):
        # "the level of the game is high" must NOT become level="of the ...".
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Game")
        ai = Mock(side_effect=[_ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "the level of the game is high")
        assert not handled
        assert _by_title(eng, uid, ws, "Game").fields.get("level") is None
        assert ai.call_count == 1


# ── 14. Ordinals resolve against CognitiveEngine list output (M1 fix) ──────
# "Show all characters" goes through the broad-recall branch which shows the
# entity list via the list_entities tool; that list is now recorded so
# "the first one"/"the last one"/"the second one" resolve deterministically.

class TestOrdinalViaCognitiveList:
    def test_first_and_last_after_show_all_characters(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        for name in ("Alpha", "Beta", "Gamma"):
            eng.add_milestone(uid, ws.id, name)
        ai = Mock(side_effect=[_ai("retrieve", query="show all characters")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        handled, reply = mgr.process(uid, "Show all characters")
        assert handled is True
        assert "Alpha" in reply                 # CognitiveEngine list shown

        # "the first one" resolves deterministically (no LLM) to Alpha.
        handled, reply = mgr.process(uid, "Show the first one")
        assert ai.call_count == 1
        assert handled is True
        assert "Alpha" in reply

        # "the last one" → Gamma (the actual third entity, by identity).
        handled, reply = mgr.process(uid, "Show the last one")
        assert ai.call_count == 1
        assert handled is True
        assert "Gamma" in reply
        assert "Beta" not in reply

    def test_second_one_after_show_all_characters(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        for name in ("Alpha", "Beta", "Gamma"):
            eng.add_milestone(uid, ws.id, name)
        ai = Mock(side_effect=[_ai("retrieve", query="show all characters")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Show all characters")
        handled, reply = mgr.process(uid, "Show the second one")
        assert ai.call_count == 1
        assert handled is True
        assert "Beta" in reply
        assert "Alpha" not in reply


# ── 15. Ordinal edge cases: 1-entity list, replaced list, empty/stale list ─

class TestOrdinalEdgeCases:
    def test_list_of_one_entity(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Solo")
        ai = Mock(side_effect=[_ai("retrieve", query="show all characters"),
                               _ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Show all characters")
        handled, reply = mgr.process(uid, "Show the first one")
        assert handled is True
        assert "Solo" in reply

        # "the second one" is out of range → unresolved, falls through.
        handled, reply = mgr.process(uid, "Show the second one")
        assert not handled
        assert ai.call_count == 2

    def test_new_list_replaces_old_list(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        a = eng.add_milestone(uid, ws.id, "Alpha")
        b = eng.add_milestone(uid, ws.id, "Beta")
        g = eng.add_milestone(uid, ws.id, "Gamma")
        for m in (a, b):
            eng.update_field(uid, m.id, "element", "hydro")
        eng.update_field(uid, g.id, "element", "pyro")
        ai = Mock(side_effect=[
            _ai("retrieve", query="show all hydro"),
            _ai("retrieve", query="show all pyro"),
        ])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Show all hydro")     # list = [Alpha, Beta]
        mgr.process(uid, "Show all pyro")      # list replaced = [Gamma]

        handled, reply = mgr.process(uid, "Show the first one")
        assert ai.call_count == 2
        assert handled is True
        assert "Gamma" in reply                # the NEW list, not the old
        assert "Alpha" not in reply

    def test_stale_list_with_deleted_entities_does_not_resolve(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        a = eng.add_milestone(uid, ws.id, "Alpha")
        b = eng.add_milestone(uid, ws.id, "Beta")
        ai = Mock(side_effect=[_ai("retrieve", query="show all characters"),
                               _ai("none")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Show all characters")  # ordered = [Alpha, Beta]
        eng.delete_milestone(uid, a.id)
        eng.delete_milestone(uid, b.id)

        # The recorded list now refers to deleted entities — the ordinal must
        # NOT resolve to a ghost, and must not crash.
        handled, reply = mgr.process(uid, "Show the first one")
        assert not handled or "Alpha" not in reply
        assert ai.call_count == 2


# ── 16. Precedence chain (explicit name > active > recent > ambiguous) ─────

class TestPrecedence:
    def test_explicit_name_beats_active_entity(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[
            _ai("create", "Furina"),
            _ai("create", "Zhongli"),
            _ai("retrieve", query="Show Furina"),
        ])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create Furina")
        mgr.process(uid, "Create Zhongli")
        assert db.tg_get_active(uid)[2] == _by_title(eng, uid, ws, "Zhongli").id

        # Explicit name wins over the active entity (Zhongli).
        handled, reply = mgr.process(uid, "Show Furina")
        assert handled is True and "Furina" in reply
        # ...and repoints the active entity to Furina.
        assert db.tg_get_active(uid)[2] == _by_title(eng, uid, ws, "Furina").id
        assert ai.call_count == 3

    def test_active_entity_beats_single_recent_mention(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        ai = Mock(side_effect=[_ai("create", "Furina"),
                               _ai("create", "Zhongli")])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create Furina")
        mgr.process(uid, "Create Zhongli")

        # Both are recent mentions, but the DB active entity (Zhongli) is the
        # strongest deictic signal.
        handled, reply = mgr.process(uid, "Show him")
        assert ai.call_count == 2
        assert handled is True
        assert "Zhongli" in reply and "Furina" not in reply

    def test_ordinal_requires_ordered_context_even_with_active(self, temp_db, uid):
        # "the first one" with no list shown must NOT silently resolve to the
        # active entity — it falls through (never guesses).
        eng, ws = _mk_workspace(uid)
        eng.add_milestone(uid, ws.id, "Zhongli")
        ai = Mock(side_effect=[
            _ai("create", "Zhongli"),
            _ai("none"),
        ])
        mgr = EntityManager(engine=eng, ai_call=ai)

        mgr.process(uid, "Create Zhongli")     # active = Zhongli, no list shown
        handled, reply = mgr.process(uid, "Show the first one")
        assert not handled
        assert ai.call_count == 2              # fell through, never guessed


# ── 17. Ambiguity: no active + two candidates + weak reference → clarify ───

class TestAmbiguityStrictness:
    def test_weak_reference_ambiguous_clarifies(self, temp_db, uid):
        eng, ws = _mk_workspace(uid)
        a = eng.add_milestone(uid, ws.id, "Furina")
        b = eng.add_milestone(uid, ws.id, "Raiden Shogun")
        ctx = ReferenceContext()
        from core.ai.reference_context import Referent
        ctx.note_mention(uid, Referent(kind="milestone", id=a.id,
                                       title="Furina", workspace_id=ws.id))
        ctx.note_mention(uid, Referent(kind="milestone", id=b.id,
                                       title="Raiden Shogun", workspace_id=ws.id))
        ai = Mock(side_effect=[_ai("none")])
        # Share the pre-seeded context so the resolver sees both candidates;
        # no DB active entity, so neither candidate has priority.
        mgr = EntityManager(engine=eng, ai_call=ai, ref_context=ctx)

        handled, reply = mgr.process(uid, "Show it")
        assert handled is True
        assert "which one" in reply.lower()
        assert "Furina" in reply and "Raiden Shogun" in reply
        assert ai.call_count == 0              # clarified, never guessed
