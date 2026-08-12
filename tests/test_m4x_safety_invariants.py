"""
v15.2 M4.x safety-invariant regression tests (2026-08-11 live-observation
remediation). Every test encodes one of the CRITICAL SAFETY INVARIANTS:

  1. A fresh entity name on a CREATE must NEVER mutate the active entity.
  2. An explicit-but-not-found entity name must NEVER fall back to the active
     entity for a mutation (NOT_FOUND ≠ ACTIVE).
  3. A deadline/"due date" message belongs to the GOAL domain and must never
     write a workspace entity field (e.g. Wolf's Gravestone target_level).

These cover the legacy EntityManager fallback path (what runs when the v15.2
Worker declines / falls through). Deterministic — the LLM is mocked.
"""
import calendar
from datetime import datetime
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from core.ai.entity_manager import EntityManager
from core.ai.resolution_trace import ResolutionTrace
from core.ai.tool_adapters import build_tool_registry
from core.workspace.engine import EntityEngine
from main import _is_topic_operation

import database as db

_IST = ZoneInfo("Asia/Kolkata")


def _month_end(now: datetime, months_ahead: int = 0) -> str:
    """ISO date of the last day of the month `months_ahead` from `now`."""
    idx = now.month - 1 + months_ahead
    year = now.year + idx // 12
    month = idx % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last:02d}"


def _now() -> datetime:
    return datetime.now(_IST)


def _game_ws(uid, title="Test Game"):
    """A fresh game-template workspace with the active binding set."""
    eng = EntityEngine()
    ws = eng.create_workspace(uid, title, template="game", seed_milestones=False)
    db.tg_set_active(uid, ws.id, "milestone", None)
    return eng, ws


class TestUnknownEntityNeverMutatesActive:
    """Invariant: fresh/not-found entity name must never mutate active."""

    def test_create_intent_fresh_name_never_mutates_active(self, temp_db, uid):
        """'Create Citlali and set her level to 83' — active is Diona; the
        LLM (correctly) classifies CREATE. Citlali is created; Diona's
        level is untouched."""
        eng, ws = _game_ws(uid)
        diona = eng.add_milestone(uid, ws.id, "Diona")
        eng.update_field(uid, diona.id, "level", 80)

        ai_mock = Mock(return_value='{"intent": "create", "entity_name": "Citlali", '
                                     '"fields": {}, "query": ""}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Create Citlali and set her level to 83")
        assert handled is True
        assert "Citlali" in reply
        assert "Diona" not in reply

        titles = [m.title for m in eng.list_milestones(uid, ws.id)]
        assert "Citlali" in titles
        assert "Diona" in titles
        diona_fresh = next(m for m in eng.list_milestones(uid, ws.id)
                           if m.title == "Diona")
        assert diona_fresh.fields.get("level") == 80   # untouched

    def test_update_intent_not_found_never_mutates_active(self, temp_db, uid):
        """Worst-case: the LLM misclassifies 'Create Citlali and set her
        level to 83' as UPDATE on 'Citlali'. The explicit-but-not-found name
        must produce a not-found reply, NOT an update of the active Diona."""
        eng, ws = _game_ws(uid)
        diona = eng.add_milestone(uid, ws.id, "Diona")
        eng.update_field(uid, diona.id, "level", 80)

        ai_mock = Mock(return_value='{"intent": "update", "entity_name": "Citlali", '
                                     '"fields": {"level": 83}, "query": ""}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Create Citlali and set her level to 83")
        assert handled is True
        assert "Citlali" in reply
        assert "Diona" not in reply

        diona_fresh = next(m for m in eng.list_milestones(uid, ws.id)
                           if m.title == "Diona")
        assert diona_fresh.fields.get("level") == 80   # untouched

    def test_pronoun_update_still_resolves_active(self, temp_db, uid):
        """The guard must NOT break the legitimate pronoun path: 'set her
        level to 83' with Diona active still updates Diona."""
        eng, ws = _game_ws(uid)
        diona = eng.add_milestone(uid, ws.id, "Diona")
        eng.update_field(uid, diona.id, "level", 70)
        db.tg_set_active(uid, ws.id, "milestone", diona.id)   # active entity

        ai_mock = Mock(return_value='{"intent": "update", "entity_name": "", '
                                     '"fields": {"level": 83}, "query": ""}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)

        handled, reply = mgr.process(uid, "Set her level to 83")
        assert handled is True
        assert "Diona" in reply
        diona_fresh = next(m for m in eng.list_milestones(uid, ws.id)
                           if m.title == "Diona")
        assert diona_fresh.fields.get("level") == 83   # updated via referent


class TestWorkspaceContextRules:
    """The 5 workspace-context rules the Worker tool adapters must satisfy
    (M4.x spec). All go through _require_workspace / _find_workspace."""

    def test_explicit_workspace_wins_over_active(self, temp_db, uid):
        """Rule 1: an explicit workspace name/#id is used even when a
        different workspace is active."""
        eng = EntityEngine()
        genshin = eng.create_workspace(uid, "Genshin", template="game",
                                       seed_milestones=False)
        honkai = eng.create_workspace(uid, "Honkai", template="game",
                                      seed_milestones=False)
        db.tg_set_active(uid, genshin.id)
        reg = build_tool_registry(uid)

        by_name = reg.execute("get_workspace", {"workspace": "Honkai"})
        assert by_name.ok and by_name.data["workspace_id"] == honkai.id
        by_id = reg.execute("get_workspace", {"workspace": str(honkai.id)})
        assert by_id.ok and by_id.data["workspace_id"] == honkai.id

    def test_active_workspace_used_when_omitted(self, temp_db, uid):
        """Rule 2: omitting the workspace arg resolves to the active one."""
        eng = EntityEngine()
        genshin = eng.create_workspace(uid, "Genshin", template="game",
                                       seed_milestones=False)
        db.tg_set_active(uid, genshin.id)
        reg = build_tool_registry(uid)

        r = reg.execute("get_workspace", {})
        assert r.ok and r.data["workspace_id"] == genshin.id

    def test_entity_lands_in_its_explicit_workspace(self, temp_db, uid):
        """Rule 3: a create targeting workspace B (while A is active) puts
        the entity in B, and B becomes the active workspace context."""
        eng = EntityEngine()
        genshin = eng.create_workspace(uid, "Genshin", template="game",
                                       seed_milestones=False)
        honkai = eng.create_workspace(uid, "Honkai", template="game",
                                      seed_milestones=False)
        db.tg_set_active(uid, genshin.id)
        reg = build_tool_registry(uid)

        r = reg.execute("create_entity", {"name": "Mona", "workspace": "Honkai"})
        assert r.ok and r.data["workspace_id"] == honkai.id
        assert [m.title for m in eng.list_milestones(uid, honkai.id)] == ["Mona"]
        assert eng.list_milestones(uid, genshin.id) == []

    def test_no_workspace_at_all_asks(self, temp_db, uid):
        """Rule 4: with NO active workspace and no explicit ref, a workspace
        tool must ask/error — never guess a workspace."""
        eng = EntityEngine()
        eng.create_workspace(uid, "Genshin", template="game",
                             seed_milestones=False)   # exists but NOT active
        # no tg_set_active call
        reg = build_tool_registry(uid)

        r = reg.execute("create_entity", {"name": "Mona"})
        assert not r.ok
        assert "no active workspace" in r.output
        assert eng.list_milestones(uid, eng.list_workspaces(uid)[0].id) == []

    def test_bad_ref_falls_back_to_authoritative_active(self, temp_db, uid):
        """Rule 5: with an authoritative active workspace, an unresolvable
        explicit ref falls back to it instead of asking."""
        eng = EntityEngine()
        genshin = eng.create_workspace(uid, "Genshin", template="game",
                                       seed_milestones=False)
        db.tg_set_active(uid, genshin.id)
        reg = build_tool_registry(uid)

        r = reg.execute("create_entity",
                        {"name": "Mona", "workspace": "DefinitelyNotAWorkspace"})
        assert r.ok
        assert r.data["workspace_id"] == genshin.id   # fell back to active


class TestCreateVsUpdateSemantics:
    """CREATE never silently becomes UPDATE; a compound 'create X, set X to N,
    create Y, set Y to M, then show X and Y' chain executes every distinct
    operation in order at the tool layer (the Worker is just a caller)."""

    def _game_reg(self, uid):
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Genshin", template="game",
                                  seed_milestones=False)
        db.tg_set_active(uid, ws.id)
        return eng, ws, build_tool_registry(uid)

    def test_create_then_set_then_show_compound_chain(self, temp_db, uid):
        """The exact live sequence: create Lauma, set level 90, create Nefer,
        set level 80, show both. Each operation is independent and ordered;
        CREATE on a fresh name is never reinterpreted as an update."""
        eng, ws, reg = self._game_reg(uid)

        c1 = reg.execute("create_entity", {"name": "Lauma"})
        assert c1.ok and c1.data["entity_id"] > 0
        s1 = reg.execute("update_entity", {"entity": "Lauma",
                                           "fields": {"level": 90}})
        assert s1.ok and s1.data["applied"].get("level") == 90
        c2 = reg.execute("create_entity", {"name": "Nefer"})
        assert c2.ok and c2.data["entity_id"] != c1.data["entity_id"]
        s2 = reg.execute("update_entity", {"entity": "Nefer",
                                           "fields": {"level": 80}})
        assert s2.ok and s2.data["applied"].get("level") == 80

        both = eng.list_milestones(uid, ws.id)
        by_title = {m.title: m.fields.get("level") for m in both}
        assert by_title == {"Lauma": 90, "Nefer": 80}
        assert len(both) == 2        # no duplicate entity from the update step

    def test_create_duplicate_reports_already_exists(self, temp_db, uid):
        """CREATE on an existing name returns 'already exists' (so the Worker
        can continue with update_entity per prompt rule 12) — it never
        silently turns into an update of the existing row, and never creates
        a second row."""
        eng, ws, reg = self._game_reg(uid)
        reg.execute("create_entity", {"name": "Lauma"})

        dup = reg.execute("create_entity", {"name": "Lauma"})
        assert not dup.ok and dup.error_code == "invalid_args"
        assert "already exists" in dup.output
        assert len(eng.list_milestones(uid, ws.id)) == 1

    def test_update_rejected_when_entity_missing(self, temp_db, uid):
        """UPDATE on a name that does not exist errors — it never creates a
        row, so a fresh-name CREATE can never be misinterpreted."""
        _, ws, reg = self._game_reg(uid)
        r = reg.execute("update_entity",
                        {"entity": "NoSuchEntity", "fields": {"level": 90}})
        assert not r.ok
        assert "no entity matches" in r.output
        eng = EntityEngine()
        assert eng.list_milestones(uid, ws.id) == []


class TestWorkspaceLifecycleAudit:
    """M4 item 11 invariant, re-pinned for v15.3 M5: the M5 control plane
    shares the lifecycle with the Worker, so archive_workspace and
    delete_entity are now reachable registry tools. The invariant that MUST
    hold: the cascade op `delete_workspace` never exists, and every
    DESTRUCTIVE tool declares a confirmation_message so the Worker AND the
    control plane route it through the shared confirmation mechanism (never
    execute it directly)."""

    def test_no_destructive_workspace_tool(self, temp_db, uid):
        _, ws = _game_ws(uid)
        reg = build_tool_registry(uid)
        names = reg.names()
        assert "delete_workspace" not in names   # the cascade op stays off-surface
        # M5: archive/delete exist as soft ops, but each is DESTRUCTIVE and
        # carries a confirmation_message (asserted below).
        assert "archive_workspace" in names
        assert "delete_entity" in names

    def test_every_destructive_tool_has_confirmation(self, temp_db, uid):
        _, ws = _game_ws(uid)
        reg = build_tool_registry(uid)
        bad = [s.name for s in reg.specs()
               if s.risk.value == "destructive" and not s.confirmation_message]
        assert bad == []


class TestResolutionTraceDiagnostics:
    """The in-memory ResolutionTrace + /diag card. It must record newest-first,
    never hold secrets, and render the 'Requested → Resolved' decision."""

    def test_trace_records_newest_first(self):
        t = ResolutionTrace()
        t.record(user_id=1, workspace_id=1, action="create",
                 requested="Citlali", kind="character",
                 resolution="NOT_FOUND", fallback="NONE")
        t.record(user_id=1, workspace_id=1, action="update",
                 requested="Citlali", kind="character",
                 resolution="FOUND", fallback="EXACT",
                 entity_title="Citlali", entity_id=7)
        entries = t.recent(1)
        assert [e.action for e in entries] == ["update", "create"]
        assert entries[0].entity_id == 7
        # Per-user isolation
        assert t.recent(2) == []

    def test_diag_card_renders_resolution_trace(self):
        from ui import diagnostics_card
        t = ResolutionTrace()
        t.record(user_id=1, workspace_id=1, action="update",
                 requested="Citlali", kind="character",
                 resolution="NOT_FOUND", fallback="NONE")
        text, kb = diagnostics_card(t.recent(1))
        assert "Requested: Citlali" in text
        assert "Resolved:" in text
        assert "NOT_FOUND" in text
        assert "fallback=NONE" in text
        assert kb is None
        # The card renders its empty state too.
        empty, _ = diagnostics_card([])
        assert "no entity resolutions recorded" in empty

    def test_diag_card_cannot_leak_secrets(self):
        from ui import diagnostics_card
        t = ResolutionTrace()
        t.record(user_id=1, workspace_id=1, action="update",
                 requested="X", kind="entity",
                 resolution="FOUND", fallback="EXACT",
                 entity_title="Y", entity_id=1)
        text, _ = diagnostics_card(t.recent(1))
        for secret in ("BOT_TOKEN", "AI_API_KEY", "NVIDIA_API_KEY", "12345token"):
            assert secret.lower() not in text.lower()

    def test_entity_tools_record_trace_entries(self, temp_db, uid):
        """A real create + a not-found update both land in the shared trace."""
        eng, ws = _game_ws(uid)
        from core.ai.resolution_trace import get_resolution_trace
        get_resolution_trace().clear(uid)
        reg = build_tool_registry(uid)
        c = reg.execute("create_entity", {"name": "Citlali"})
        assert c.ok
        miss = reg.execute("update_entity",
                           {"entity": "NoSuchEntity", "fields": {"level": 90}})
        assert not miss.ok
        by_action = {e.action: e for e in get_resolution_trace().recent(uid)}
        assert by_action["create"].resolution == "NOT_FOUND"
        assert by_action["create"].requested == "Citlali"
        assert by_action["update"].resolution == "NOT_FOUND"
        assert by_action["update"].entity_title is None   # no fallback to active


class TestLiveScenarioMatrix:
    """One deterministic regression per live failure (2026-08-11), using
    FRESH names (not the screenshot phrases). Each asserts the INVARIANT,
    never a phrase."""

    def test_s01_create_fresh_name_never_mutates_active(self, temp_db, uid):
        """Live #1/#7: fresh name on a create/mutate must not touch active."""
        eng, ws = _game_ws(uid)
        active = eng.add_milestone(uid, ws.id, "ActiveChamp")
        eng.update_field(uid, active.id, "level", 50)
        db.tg_set_active(uid, ws.id, "milestone", active.id)
        ai_mock = Mock(return_value='{"intent": "create", "entity_name": '
                                     '"BrandNewChar", "fields": {}, "query": ""}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)
        handled, reply = mgr.process(uid, "Create BrandNewChar and set her level to 83")
        assert handled and "BrandNewChar" in reply and "ActiveChamp" not in reply
        fresh = next(m for m in eng.list_milestones(uid, ws.id)
                     if m.title == "BrandNewChar")
        assert fresh.fields.get("level") is None     # create carries no fields
        active_fresh = next(m for m in eng.list_milestones(uid, ws.id)
                            if m.title == "ActiveChamp")
        assert active_fresh.fields.get("level") == 50

    def test_s02_create_uses_active_workspace(self, temp_db, uid):
        """Live #2/#12/#13: create with no workspace arg uses the active one
        (never 'Please specify the workspace')."""
        eng, ws = _game_ws(uid)
        db.tg_set_active(uid, ws.id)
        reg = build_tool_registry(uid)
        r = reg.execute("create_entity", {"name": "Mona"})
        assert r.ok and r.data["workspace_id"] == ws.id
        assert [m.title for m in eng.list_milestones(uid, ws.id)] == ["Mona"]

    def test_s03_goal_deadline_never_writes_entity_field(self, temp_db, uid):
        """Live #7/#8: 'set its deadline' routes to the goal domain."""
        eng, ws = _game_ws(uid)
        wp = eng.add_milestone(uid, ws.id, "BladeOfMight")
        eng.update_field(uid, wp.id, "target_level", 30)
        db.tg_set_active(uid, ws.id, "milestone", wp.id)
        mgr = EntityManager(engine=eng, ai_call=Mock())
        mgr._s.goals.add(uid, "Read Books")
        handled, reply = mgr.process(uid, "Set its deadline to this month end")
        assert handled and "Read Books" in reply and "BladeOfMight" not in reply
        fresh = next(m for m in eng.list_milestones(uid, ws.id)
                     if m.title == "BladeOfMight")
        assert fresh.fields.get("target_level") == 30

    def test_s04_topic_delete_not_task_delete(self):
        """Live #9: 'Delete X's topic' is a topic op, never a task delete."""
        assert _is_topic_operation("delete columbina's topic") is True
        assert _is_topic_operation("delete milk") is False
        assert _is_topic_operation("lock columbina's topic") is True

    def test_s05_compound_create_set_show_ordered(self, temp_db, uid):
        """Live #11/#12: create X, set X, create Y, set Y, show both — all
        four ops execute in order, no duplicate row, no cross-update."""
        eng = EntityEngine()
        ws = eng.create_workspace(uid, "Genshin", template="game",
                                  seed_milestones=False)
        db.tg_set_active(uid, ws.id)
        reg = build_tool_registry(uid)
        assert reg.execute("create_entity", {"name": "Lauma"}).ok
        assert reg.execute("update_entity", {"entity": "Lauma",
                                             "fields": {"level": 90}}).ok
        assert reg.execute("create_entity", {"name": "Nefer"}).ok
        assert reg.execute("update_entity", {"entity": "Nefer",
                                             "fields": {"level": 80}}).ok
        by_title = {m.title: m.fields.get("level")
                    for m in eng.list_milestones(uid, ws.id)}
        assert by_title == {"Lauma": 90, "Nefer": 80}
        assert len(by_title) == 2

    def test_s06_artifact_typed_create_and_list(self, temp_db, uid):
        """Live #4-6: artifact/weapon create + typed list stay typed."""
        eng, ws = _game_ws(uid)
        db.tg_set_active(uid, ws.id)
        reg = build_tool_registry(uid)
        a = reg.execute("create_entity",
                        {"name": "ArtifactOfDawn", "entity_type": "artifact"})
        assert a.ok and a.data["entity_type"] == "artifact"
        w = reg.execute("create_entity",
                        {"name": "WeaponOfDawn", "entity_type": "weapon"})
        assert w.ok and w.data["entity_type"] == "weapon"
        kinds = reg.execute("list_entities", {"kind": "artifact"})
        assert kinds.ok and len(kinds.data) == 1
        assert kinds.data[0]["title"] == "ArtifactOfDawn"

    def test_s07_pronoun_deadline_uses_most_recent_goal(self, temp_db, uid):
        """Live #8: 'Set its deadline to next month end' → most recent goal."""
        eng, ws = _game_ws(uid)
        mgr = EntityManager(engine=eng, ai_call=Mock())
        mgr._s.goals.add(uid, "OldGoal")
        mgr._s.goals.add(uid, "NewGoal")
        handled, reply = mgr.process(uid, "Set its deadline to next month end")
        assert handled and "NewGoal" in reply and "OldGoal" not in reply
        rows = {r[1]: r[2] for r in mgr._s.goals.get_all_full(uid)}
        assert rows["NewGoal"] == _month_end(_now(), 1)
        assert rows["OldGoal"] is None

    def test_s08_ambiguous_goal_asks(self, temp_db, uid):
        """No pronoun/title + several goals → ask, never guess a domain."""
        eng, ws = _game_ws(uid)
        mgr = EntityManager(engine=eng, ai_call=Mock())
        mgr._s.goals.add(uid, "GoalA")
        mgr._s.goals.add(uid, "GoalB")
        handled, reply = mgr.process(uid, "Set the deadline to this month end")
        assert handled and "Which goal" in reply
        rows = mgr._s.goals.get_all_full(uid)
        assert all(r[2] is None for r in rows)


class TestTopicOpNlGate:
    """The topic-vocabulary NL seam (main._is_topic_operation): a topic
    message must be routed to the Worker's entity-topic tools, NEVER to the
    task-delete NL-map gate (live failure: "Delete Columbina's topic" →
    "Usage: /delete <id>")."""

    @pytest.mark.parametrize("msg", [
        "delete columbina's topic",
        "Delete Columbina's topic",
        "lock xiao's topic",
        "unlock raiden's topic",
        "remove the topic of yelan",
        "what is furina's topic",
        "what's neuvillette's topic",
        "show the artifact's topic",
        "create a topic for alhaitham",
    ])
    def test_topic_operations_flagged(self, msg):
        assert _is_topic_operation(msg.lower()) is True

    @pytest.mark.parametrize("msg", [
        "delete milk",
        "remove tag work",
        "done task 3",
        "del reminder groceries",
        "lock the door",
        "show my tasks",
    ])
    def test_non_topic_messages_not_flagged(self, msg):
        assert _is_topic_operation(msg.lower()) is False


class TestGoalDeadlineDomainGuard:
    """Invariant: a deadline/due-date message is a GOAL/TASK operation and
    must never write a workspace-entity field (Wolf's Gravestone bug)."""

    def _setup_goal(self, uid, title):
        mgr = EntityManager(engine=EntityEngine())
        return mgr._s.goals.add(uid, title)

    def test_pronoun_deadline_resolves_most_recent_goal(self, temp_db, uid):
        """'Set its deadline to this month end' after 'Read5 Books' → the
        most recent goal gets this-month-end; no milestone touched."""
        eng, ws = _game_ws(uid)
        wolf = eng.add_milestone(uid, ws.id, "Wolf's Gravestone")
        eng.update_field(uid, wolf.id, "target_level", 30)
        self._setup_goal(uid, "Read5 Books")

        ai_mock = Mock(return_value='{"intent": "none", "entity_name": "", '
                                     '"fields": {}, "query": ""}')
        mgr = EntityManager(engine=eng, ai_call=ai_mock)
        handled, reply = mgr.process(uid, "Set its deadline to this month end")
        assert handled is True
        assert "Read5 Books" in reply
        assert _month_end(_now()) in reply
        assert "Gravestone" not in reply

        # The milestone's target_level is untouched by a goal operation.
        wolf_fresh = next(m for m in eng.list_milestones(uid, ws.id)
                          if m.title == "Wolf's Gravestone")
        assert wolf_fresh.fields.get("target_level") == 30
        # The goal really got the deadline.
        rows = mgr._s.goals.get_all_full(uid)
        assert rows[0][1] == "Read5 Books"
        assert rows[0][2] == _month_end(_now())

    def test_explicit_title_beats_recency(self, temp_db, uid):
        """'Set the deadline of Gym Strength to next month end' — Gym
        Strength is the older goal but explicit name wins over the newer
        'Read5 Books'."""
        eng, ws = _game_ws(uid)
        self._setup_goal(uid, "Gym Strength")          # older
        self._setup_goal(uid, "Read5 Books")           # newer

        mgr = EntityManager(engine=eng, ai_call=Mock())
        handled, reply = mgr.process(
            uid, "Set the deadline of Gym Strength to next month end")
        assert handled is True
        assert "Gym Strength" in reply
        assert _month_end(_now(), 1) in reply
        assert "Read5 Books" not in reply

        rows = {r[1]: r for r in mgr._s.goals.get_all_full(uid)}
        assert rows["Gym Strength"][2] == _month_end(_now(), 1)
        assert rows["Read5 Books"][2] is None          # untouched

    def test_clear_deadline(self, temp_db, uid):
        """'clear its deadline' clears the most recent goal's deadline."""
        eng, ws = _game_ws(uid)
        self._setup_goal(uid, "Read5 Books")
        self._setup_goal(uid, "Study Math")

        mgr = EntityManager(engine=eng, ai_call=Mock())
        handled, reply = mgr.process(uid, "clear its deadline")
        assert handled is True
        assert "Cleared" in reply
        rows = {r[1]: r for r in mgr._s.goals.get_all_full(uid)}
        assert rows["Study Math"][2] is None

    def test_iso_deadline(self, temp_db, uid):
        """An explicit ISO date resolves through the parser."""
        eng, ws = _game_ws(uid)
        self._setup_goal(uid, "Read5 Books")

        mgr = EntityManager(engine=eng, ai_call=Mock())
        handled, reply = mgr.process(
            uid, "Set the deadline of Read5 Books to 2026-09-30")
        assert handled is True
        assert "2026-09-30" in reply
        rows = mgr._s.goals.get_all_full(uid)
        assert rows[0][2] == "2026-09-30"

    def test_name_collision_goal_wins(self, temp_db, uid):
        """A goal whose title collides with a workspace entity name: the
        deadline guard owns the goal domain, so 'Set the deadline of Read5
        Books…' hits the GOAL row, and the entity named 'Read5 Books' is
        untouched."""
        eng, ws = _game_ws(uid)
        ent = eng.add_milestone(uid, ws.id, "Read5 Books")    # workspace entity
        eng.update_field(uid, ent.id, "level", 10)
        self._setup_goal(uid, "Read5 Books")                  # goal, same title

        mgr = EntityManager(engine=eng, ai_call=Mock())
        handled, reply = mgr.process(
            uid, "Set the deadline of Read5 Books to 2026-09-30")
        assert handled is True
        assert "2026-09-30" in reply
        # The workspace entity kept its level; only the goal got a deadline.
        ent_fresh = next(m for m in eng.list_milestones(uid, ws.id)
                         if m.title == "Read5 Books")
        assert ent_fresh.fields.get("level") == 10
        rows = mgr._s.goals.get_all_full(uid)
        assert rows[0][1] == "Read5 Books"
        assert rows[0][2] == "2026-09-30"

    def test_no_goals_asks_to_create(self, temp_db, uid):
        """No goals → the guard explains, never mutates anything."""
        eng, ws = _game_ws(uid)
        wolf = eng.add_milestone(uid, ws.id, "Wolf's Gravestone")
        eng.update_field(uid, wolf.id, "target_level", 30)

        mgr = EntityManager(engine=eng, ai_call=Mock())
        handled, reply = mgr.process(uid, "Set its deadline to this month end")
        assert handled is True
        assert "goals yet" in reply
        wolf_fresh = next(m for m in eng.list_milestones(uid, ws.id)
                          if m.title == "Wolf's Gravestone")
        assert wolf_fresh.fields.get("target_level") == 30   # untouched

    def test_ambiguous_asks_which_goal(self, temp_db, uid):
        """No explicit title and no pronoun ('Set the deadline to this month
        end') with several goals → ask, never guess a domain."""
        eng, ws = _game_ws(uid)
        self._setup_goal(uid, "Read5 Books")
        self._setup_goal(uid, "Study Math")

        mgr = EntityManager(engine=eng, ai_call=Mock())
        handled, reply = mgr.process(uid, "Set the deadline to this month end")
        assert handled is True
        assert "Which goal" in reply
        rows = mgr._s.goals.get_all_full(uid)
        assert all(r[2] is None for r in rows)               # nothing mutated
