"""
Tests for v15.1.0-alpha.10 -- Natural Language Entity Management.

EntityManager translates free-text into Entity Engine operations using an
injected AI call.  These tests mock the AI response so they are fully
offline and deterministic.
"""
from unittest.mock import Mock

import pytest

from core.ai.entity_manager import EntityManager, _extract_json
from core.workspace.engine import EntityEngine
from core.workspace.errors import EntityValidationError
from core.workspace.templates.registry import entity_field_specs


# ── _extract_json unit tests ────────────────────────────────────────────

class TestExtractJson:
    def test_extracts_simple_json(self):
        assert _extract_json('{"intent": "create"}') == {"intent": "create"}

    def test_extracts_from_markdown_fence(self):
        raw = "```json\n{\"intent\": \"update\"}\n```"
        assert _extract_json(raw) == {"intent": "update"}

    def test_extracts_from_backtick_fence_no_lang(self):
        raw = "```\n{\"intent\": \"retrieve\"}\n```"
        assert _extract_json(raw) == {"intent": "retrieve"}

    def test_returns_none_for_empty_input(self):
        assert _extract_json("") is None

    def test_returns_none_for_invalid_json(self):
        assert _extract_json("not json at all") is None

    def test_returns_none_for_bare_text(self):
        assert _extract_json("Hello, how are you?") is None

    def test_handles_nested_json(self):
        raw = '{"intent": "update", "fields": {"level": 80, "priority": "high"}}'
        result = _extract_json(raw)
        assert result == {"intent": "update", "fields": {"level": 80, "priority": "high"}}


# ── EntityManager process tests ─────────────────────────────────────────

class TestEntityManagerDecision:
    """EntityManager.process() routing decisions: correct intent based on
    mocked AI responses."""

    def test_create_intent(self, temp_db, uid):
        """Create intent routes to _handle_create and returns a response."""
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        import database as db
        db.tg_set_active(uid, ws.id, "milestone", None)

        ai_mock = Mock(return_value='{"intent": "create", "entity_name": "Furina", "fields": {}, "query": ""}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Create character Furina")
        assert handled is True
        assert "Furina" in reply
        # Verify entity was actually created.
        ms = eng.list_milestones(uid, ws.id)
        assert any(m.title == "Furina" for m in ms)

    def test_update_intent(self, temp_db, uid):
        """Update intent routes to _handle_update and changes the field."""
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        import database as db
        db.tg_set_active(uid, ws.id, "milestone", None)
        m = eng.add_milestone(uid, ws.id, "Hu Tao")

        ai_mock = Mock(return_value='{"intent": "update", "entity_name": "Hu Tao", "fields": {"level": 80}, "query": ""}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Hu Tao is level 80")
        assert handled is True
        assert "level" in reply.lower() or "80" in reply

    def test_retrieve_intent(self, temp_db, uid):
        """Retrieve intent routes to _handle_retrieve and returns info."""
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        import database as db
        db.tg_set_active(uid, ws.id, "milestone", None)
        eng.add_milestone(uid, ws.id, "Hu Tao")
        eng.add_milestone(uid, ws.id, "Furina")

        ai_mock = Mock(return_value='{"intent": "retrieve", "entity_name": "", "fields": {}, "query": "show all characters"}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Show all characters")
        assert handled is True
        assert reply  # non-empty

    def test_none_intent_falls_through(self, temp_db, uid):
        """None intent returns (False, "") so the caller falls through."""
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        import database as db
        db.tg_set_active(uid, ws.id, "milestone", None)

        ai_mock = Mock(return_value='{"intent": "none", "entity_name": "", "fields": {}, "query": ""}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "What's the weather?")
        assert handled is False
        assert reply == ""

    def test_no_active_workspace_falls_through(self, temp_db, uid):
        """No active workspace → return (False, "") without calling AI."""
        import database as db
        db.tg_clear_active(uid)

        ai_mock = Mock(side_effect=AssertionError("should not be called"))
        mgr = EntityManager(ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Create character Furina")
        assert handled is False
        assert reply == ""

    def test_ai_failure_falls_through_gracefully(self, temp_db, uid):
        """AI call failure → return (False, "") — never crash."""
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        import database as db
        db.tg_set_active(uid, ws.id, "milestone", None)

        ai_mock = Mock(side_effect=RuntimeError("API down"))
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Create character Furina")
        assert handled is False
        assert reply == ""

    def test_create_duplicate_entity(self, temp_db, uid):
        """Creating an entity with an existing name should explain."""
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        import database as db
        db.tg_set_active(uid, ws.id, "milestone", None)
        eng.add_milestone(uid, ws.id, "Furina")

        ai_mock = Mock(return_value='{"intent": "create", "entity_name": "Furina", "fields": {}, "query": ""}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Create character Furina")
        assert handled is True
        assert "already" in reply.lower()

    def test_pre_check_bypasses_ai_for_irrelevant_text(self, temp_db, uid):
        """Text with no entity keywords should skip the AI call entirely."""
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        import database as db
        db.tg_set_active(uid, ws.id, "milestone", None)

        ai_mock = Mock(side_effect=AssertionError("should not be called"))
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Hello! Good morning!")
        assert handled is False
        assert reply == ""


# ── Helper unit tests ───────────────────────────────────────────────────

class TestFindEntity:
    def test_exact_match(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test", template="generic", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Hu Tao")
        entities = [m]
        result = EntityManager._find_entity("Hu Tao", entities)
        assert result is not None
        assert result.title == "Hu Tao"

    def test_case_insensitive_match(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test", template="generic", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Hu Tao")
        entities = [m]
        result = EntityManager._find_entity("hu tao", entities)
        assert result is not None

    def test_partial_match(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test", template="generic", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Staff of Homa")
        entities = [m]
        result = EntityManager._find_entity("Homa", entities)
        assert result is not None

    def test_no_match(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test", template="generic", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Hu Tao")
        entities = [m]
        result = EntityManager._find_entity("Furina", entities)
        assert result is None


class TestFieldInfo:
    def test_returns_known_fields(self):
        info = EntityManager._field_info("game")
        assert "level" in info
        assert "element" in info
        assert "priority" in info

    def test_handles_unknown_template(self):
        info = EntityManager._field_info("nonexistent")
        assert "no custom entity fields" in info


class TestFindEntityReversePartial:
    """_find_entity: query contains entity name ("Show Furina" → find Furina)."""

    def test_query_contains_entity_name(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test", template="generic", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Furina")
        entities = [m]
        result = EntityManager._find_entity("Show Furina", entities)
        assert result is not None
        assert result.title == "Furina"

    def test_query_contains_partial_name(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test", template="generic", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Furina de Fontaine")
        entities = [m]
        result = EntityManager._find_entity("View Furina de Fontaine's details", entities)
        assert result is not None

    def test_reverse_partial_no_match(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test", template="generic", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Furina")
        entities = [m]
        result = EntityManager._find_entity("Show Focalors", entities)
        assert result is None


class TestFilterEntitiesByQuery:
    """_filter_entities_by_query: field-value matching."""

    def test_matches_field_value_verbatim(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        m1 = eng.add_milestone(uid, ws.id, "Furina")
        eng.update_field(uid, m1.id, "level", 90)
        eng.update_field(uid, m1.id, "element", "Hydro")
        m2 = eng.add_milestone(uid, ws.id, "Hu Tao")
        eng.update_field(uid, m2.id, "level", 70)
        eng.update_field(uid, m2.id, "element", "Pyro")
        entities = eng.list_milestones(uid, ws.id)
        specs = entity_field_specs(ws.template)
        em = EntityManager(engine=eng)

        result = em._filter_entities_by_query("Show Hydro characters", entities, specs)
        assert result is not None
        assert len(result) == 1
        assert result[0].title == "Furina"

    def test_matches_enum_choice_in_query(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        m1 = eng.add_milestone(uid, ws.id, "Furina")
        eng.update_field(uid, m1.id, "priority", "high")
        m2 = eng.add_milestone(uid, ws.id, "Hu Tao")
        eng.update_field(uid, m2.id, "priority", "medium")
        entities = eng.list_milestones(uid, ws.id)
        specs = entity_field_specs(ws.template)
        em = EntityManager(engine=eng)

        result = em._filter_entities_by_query("Show all high priority characters", entities, specs)
        assert result is not None
        assert len(result) == 1
        assert result[0].title == "Furina"

    def test_no_match_returns_none(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        m1 = eng.add_milestone(uid, ws.id, "Furina")
        eng.update_field(uid, m1.id, "level", 90)
        entities = [m1]
        specs = entity_field_specs(ws.template)
        em = EntityManager(engine=eng)

        result = em._filter_entities_by_query("Tell me a joke", entities, specs)
        assert result is None

    def test_matches_numeric_value_in_query(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        m1 = eng.add_milestone(uid, ws.id, "Furina")
        eng.update_field(uid, m1.id, "level", 90)
        # Set target_level to a different value so he doesn't match on that field.
        m2 = eng.add_milestone(uid, ws.id, "Hu Tao")
        eng.update_field(uid, m2.id, "level", 50)
        eng.update_field(uid, m2.id, "target_level", 50)
        entities = eng.list_milestones(uid, ws.id)
        specs = entity_field_specs(ws.template)
        em = EntityManager(engine=eng)

        result = em._filter_entities_by_query("level 90", entities, specs)
        assert result is not None
        assert len(result) == 1
        assert result[0].title == "Furina"

    def test_matches_token_overlap(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        m1 = eng.add_milestone(uid, ws.id, "Furina")
        eng.update_field(uid, m1.id, "weapon", "Fleuve Cendre Ferryman")
        m2 = eng.add_milestone(uid, ws.id, "Xiao")
        eng.update_field(uid, m2.id, "weapon", "Primordial Jade Winged-Spear")
        entities = eng.list_milestones(uid, ws.id)
        specs = entity_field_specs(ws.template)
        em = EntityManager(engine=eng)

        result = em._filter_entities_by_query("Who uses Fleuve Cendre Ferryman?", entities, specs)
        assert result is not None
        assert len(result) == 1
        assert result[0].title == "Furina"


class TestFormatEntityCard:
    def test_basic_card_format(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Furina")
        eng.update_field(uid, m.id, "level", 90)
        eng.update_field(uid, m.id, "element", "Hydro")
        eng.update_field(uid, m.id, "priority", "high")
        entities = eng.list_milestones(uid, ws.id)
        em = EntityManager(engine=eng)
        card = em._format_entity_card(entities[0])

        assert "<b>Furina</b>" in card
        assert "Level" in card
        assert "90" in card
        assert "Hydro" in card
        assert "high" in card

    def test_card_without_fields(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test", template="generic", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Plain Entity")
        entities = eng.list_milestones(uid, ws.id)
        em = EntityManager(engine=eng)
        card = em._format_entity_card(entities[0])

        assert "<b>Plain Entity</b>" in card


class TestQueryTokens:
    def test_filters_stop_words(self):
        tokens = EntityManager._query_tokens("show all the characters")
        assert "show" not in tokens
        assert "all" not in tokens
        assert "the" not in tokens
        assert "characters" not in tokens

    def test_keeps_content_words(self):
        tokens = EntityManager._query_tokens("level 90 hydro characters")
        assert "level" in tokens
        assert "hydro" in tokens

    def test_filters_short_tokens(self):
        tokens = EntityManager._query_tokens("a b c level")
        assert "level" in tokens
        assert "a" not in tokens
        assert "b" not in tokens
        assert "c" not in tokens

    def test_handles_apostrophes(self):
        tokens = EntityManager._query_tokens("who's using it")
        assert "who's" in tokens or "whos" in tokens


class TestRetrieveByName:
    """_handle_retrieve: entity-by-name queries."""

    def test_show_entity_by_name(self, temp_db, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Furina")
        eng.update_field(uid, m.id, "level", 90)
        eng.update_field(uid, m.id, "element", "Hydro")
        em = EntityManager(engine=eng)

        reply = em._handle_retrieve(uid, ws.id, "Show Furina")
        assert "<b>Furina</b>" in reply
        assert "Level" in reply
        assert "90" in reply

    def test_show_nonexistent_entity_filters(self, temp_db, uid):
        """Query for a non-existent entity name still tries field filter."""
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Test Game", template="game", seed_milestones=False)
        m = eng.add_milestone(uid, ws.id, "Furina")
        eng.update_field(uid, m.id, "level", 90)
        eng.update_field(uid, m.id, "element", "Hydro")
        em = EntityManager(engine=eng)

        reply = em._handle_retrieve(uid, ws.id, "Show Focalors")
        assert reply is not None
        assert len(reply) > 0
