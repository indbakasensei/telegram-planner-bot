"""
tests/test_worker_orchestration.py -- v15.2 M4 acceptance/regression matrix.

This suite encodes the LIVE Telegram failures reported by the owner after
M4 plus the additional scenarios A-G and the 10 architectural requirements
(docs/engineering/V15_2_BAKA_BRAIN.md §M4, DEBUGGING.md). It is written
TEST-FIRST: every test asserts the CORRECT end-state / prompt contract and
runs against the CURRENT code, so pre-fix runs FAIL where the architecture
is broken and post-fix runs PASS without any test being weakened.

Failure → test mapping (see DEBUGGING.md#known-issues for the live reports):

  F1  "Create Bennet, set him to level 83" -> Hu Tao updated   test_prompt_carries_created_entity_as_typed_referent
  F2  "Create Keqing, set her level to 90, then show her"      test_run_scoped_pronoun_beats_stale_active
  F3  "Show Xiao and then update his level to 80"              test_show_then_update_then_show_chain
  F4  "Show Xiao and then show Neuvillette" -> task VIEW       test_compound_retrieve_preserves_all_requested
  F5  "Set Xiao's level to 85 and then show Xiao"              test_create_set_show_chain_executes_fully
  F6  "Add goal Read Book" + "Set its deadline" -> Xiao        test_goal_deadline_sets_only_the_goal /
                                                               test_goal_pronoun_conflict_never_mutates_character
  F7  goal deadlines via deterministic date_parser             test_goal_deadline_this_month_end /
                                                               test_goal_deadline_next_month_end_parsed
  F8  "Create artifact Golden Troupe" dup ignores type         test_create_entity_duplicate_is_type_aware
  F9  "Show all artifacts" -> "Tasks for All Pending"          test_list_entities_filters_by_entity_type /
                                                               test_worker_typed_retrieve_excludes_other_kinds
  F10 "Show all characters" mixed kinds                        test_worker_typed_retrieve_excludes_other_kinds

Scenario coverage: A (create chains), B (multi-entity), C (cross-domain
references), D (goals), E (tasks), F (typed retrieval), G (adversarial).

Architectural requirements pinned here:
  R2/R3 tool results are first-class typed context        test_prompt_carries_created_entity_as_typed_referent
  R5  no previous-turn active overriding current run      test_run_scoped_pronoun_beats_stale_active
  R6  retrieval preserves all requested operations        test_compound_retrieve_preserves_all_requested
  R7  never claim success without a backing tool result   test_ambiguous_deadline_never_mutates
  R8  type-aware retrieval                                test_list_entities_filters_by_entity_type
  R9  domains don't share unsafe active references        test_cross_domain_same_name_distinguished /
                                                          test_goal_pronoun_conflict_never_mutates_character

The TypedReferentStore-backed tests are marked `_typed_*`; they reference the
new typed-reference machinery and therefore ERROR/FAIL before the fix exists
(recorded as pre-fix failures) and pass after it lands.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import database as db
from core.ai.reference_context import ReferenceContext
from core.ai.tool_adapters import build_tool_registry
from core.ai.worker import Worker
from core.ai.worker_contract import (
    MAX_TOOL_CALLS,
    TerminationReason,
    WorkerRequest,
)
from core.workspace.engine import EntityEngine

try:  # pre-fix: module does not exist yet -> tests fail cleanly, not at collect
    from core.ai.typed_referents import TypedReferentStore
except ImportError:
    TypedReferentStore = None

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 8, 10, 9, 30, tzinfo=IST)   # fixed Monday, IST


class FakeModel:
    """Deterministic model stub (same contract as test_worker.py)."""
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, messages, timeout):
        self.calls.append((messages, timeout))
        if not self._responses:
            raise AssertionError(
                f"model called more times than expected: {len(self.calls)}")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def traces(self):
        return [" ".join(str(c) for c in msgs) for msgs, _ in self.calls]


def _final(reply):
    return json.dumps({"action": "final", "reply": reply})


def _tool(name, args=None):
    return json.dumps({"action": "tool", "tool": name, "arguments": args or {}})


def _req(uid, text, reg=None, ref_ctx=None, typed_refs=None,
         tasks=(), memory=(), history=()):
    """Build a WorkerRequest with a SHARED TypedReferentStore by default (like
    main.py's singleton): the same store is threaded into the registry AND the
    request, so tools note referents into exactly what the prompt renders."""
    if typed_refs is None:
        typed_refs = TypedReferentStore() if TypedReferentStore else None
    reg = reg or build_tool_registry(uid, ref_ctx=ref_ctx, typed_refs=typed_refs)
    return WorkerRequest(user_id=uid, text=text, registry=reg, ref_ctx=ref_ctx,
                         typed_refs=typed_refs,
                         now=NOW, tasks=tuple(tasks), memory=tuple(memory),
                         history=tuple(history))


def _worker(model, log=None):
    return Worker(model_fn=model, timeout=30.0, log=log)


def _game(uid, title="Genshin"):
    """Real game workspace + active binding (M3 harness)."""
    eng = EntityEngine()
    ws = eng.create_workspace(uid, title, template="game", seed_milestones=False)
    db.tg_set_active(uid, ws.id)
    return eng, ws


def _tstore():
    """A fresh TypedReferentStore, or a clean pre-fix failure if the module
    has not been implemented yet."""
    if TypedReferentStore is None:
        pytest.fail("TypedReferentStore not implemented yet (expected pre-fix "
                    "failure — requirement R2/R3: tool results are first-class "
                    "typed context)")
    return TypedReferentStore()


# ── R2/R3/F1/F2: typed referents are first-class context ──────────────────
def test_prompt_carries_created_entity_as_typed_referent(temp_db, uid):
    """F1/F2 root cause: after create_entity returns {entity_id, name}, the
    NEXT model call's prompt must carry that entity as a typed REFERENT with
    its exact id — not only as prose inside a step trace."""
    eng, ws = _game(uid)
    typed = _tstore()
    reg = build_tool_registry(uid, typed_refs=typed)
    m = FakeModel(
        _tool("create_entity", {"name": "Keqing"}),
        _tool("update_entity", {"entity": "Keqing", "fields": {"level": 90}}),
        _tool("get_entity", {"entity": "Keqing"}),
        _final("Keqing is level 90."))
    r = _worker(m).run(_req(uid,
        "Create Keqing, set her level to 90, then show her",
        reg=reg, typed_refs=typed))
    assert r.termination is TerminationReason.FINAL
    keqing = next(mm for mm in eng.list_milestones(uid, ws.id)
                  if mm.title == "Keqing")
    sys2 = m.calls[1][0][0]["content"]
    assert "REFERENT" in sys2                      # typed block exists
    assert f"id={keqing.id}" in sys2               # the exact created id
    assert "Keqing" in sys2                        # its display name


def test_run_scoped_pronoun_beats_stale_active(temp_db, uid):
    """R5: a referent produced by the CURRENT run wins over a stale
    active entity from a previous user turn. 'him' must reach Bennet,
    never the pre-existing active character Hu Tao."""
    eng, ws = _game(uid)
    hu_tao = eng.add_milestone(uid, ws.id, "Hu Tao")
    db.tg_set_active(uid, ws.id, "milestone", hu_tao.id)
    bennet = eng.add_milestone(uid, ws.id, "Bennet")
    typed = _tstore()
    typed.note(uid, "entity", bennet.id, "Bennet", ws.id)
    reg = build_tool_registry(uid, typed_refs=typed)
    res = reg.execute("update_entity",
                      {"entity": "him", "fields": {"level": 83}})
    assert res.ok
    assert res.data["entity_id"] == bennet.id      # Bennet, NOT Hu Tao
    hu = eng.list_milestones(uid, ws.id)[0]
    assert hu.id == hu_tao.id and not hu.fields.get("level")


# ── R4/R6/F3/F5: compound operations, dependency-aware ────────────────────
def test_create_set_show_chain_executes_fully(temp_db, uid):
    """A1 / F5: create -> update -> show in ONE run. Every requested
    operation executes and commits; the final reply is composed from the
    step trace (never one arbitrary step)."""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("create_entity", {"name": "Keqing"}),
        _tool("update_entity", {"entity": "Keqing", "fields": {"level": 90}}),
        _tool("get_entity", {"entity": "Keqing"}),
        _final("Keqing created and leveled to 90."))
    r = _worker(m).run(_req(uid,
        "Create Keqing, set her level to 90, then show her"))
    assert r.termination is TerminationReason.FINAL
    assert [s.decision.tool_name for s in r.steps] == \
        ["create_entity", "update_entity", "get_entity"]
    assert all(s.result.ok for s in r.steps)
    keqing = next(mm for mm in eng.list_milestones(uid, ws.id)
                  if mm.title == "Keqing")
    assert keqing.fields.get("level") == 90


def test_show_then_update_then_show_chain(temp_db, uid):
    """F3/F5: update happens AND the show after it also happens. The loop
    must not stop early after a mutation."""
    eng, ws = _game(uid)
    xiao = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, xiao.id, "level", 79)
    db.tg_set_active(uid, ws.id, "milestone", xiao.id)
    m = FakeModel(
        _tool("get_entity", {"entity": "Xiao"}),
        _tool("update_entity", {"entity": "Xiao", "fields": {"level": 80}}),
        _tool("get_entity", {"entity": "Xiao"}),
        _final("Xiao is now level 80."))
    r = _worker(m).run(_req(uid,
        "Show Xiao and then update his level to 80 and then show him"))
    assert r.termination is TerminationReason.FINAL
    assert [s.decision.tool_name for s in r.steps] == \
        ["get_entity", "update_entity", "get_entity"]
    assert all(s.result.ok for s in r.steps)
    xiao_after = eng.list_milestones(uid, ws.id)[0]
    assert xiao_after.fields.get("level") == 80


def test_compound_retrieve_preserves_all_requested(temp_db, uid):
    """F4 / R6: 'show A then show B' is TWO retrievals — never one
    arbitrary retrieval, never a task VIEW hijack."""
    eng, ws = _game(uid)
    eng.add_milestone(uid, ws.id, "Xiao")
    eng.add_milestone(uid, ws.id, "Neuvillette")
    m = FakeModel(
        _tool("get_entity", {"entity": "Xiao"}),
        _tool("get_entity", {"entity": "Neuvillette"}),
        _final("Xiao: level 1\nNeuvillette: level 1"))
    r = _worker(m).run(_req(uid, "Show Xiao and then show Neuvillette"))
    assert r.termination is TerminationReason.FINAL
    assert [s.decision.tool_name for s in r.steps] == \
        ["get_entity", "get_entity"]
    assert all(s.result.ok for s in r.steps)
    assert "Xiao" in r.reply and "Neuvillette" in r.reply


def test_create_two_and_show_both(temp_db, uid):
    """B / R6: multi-create + list in one run, within MAX_TOOL_CALLS."""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("create_entity", {"name": "Xiao"}),
        _tool("create_entity", {"name": "Neuvillette"}),
        _tool("list_entities", {"kind": "all"}),
        _final("Created Xiao and Neuvillette."))
    r = _worker(m).run(_req(uid, "Create Xiao and Neuvillette and show both"))
    assert r.termination is TerminationReason.FINAL
    assert [s.decision.tool_name for s in r.steps] == \
        ["create_entity", "create_entity", "list_entities"]
    assert all(s.result.ok for s in r.steps)


# ── R9/F6: goals — deadlines route to the GOAL, never the active char ─────
def test_update_goal_deadline_tool_registered(temp_db, uid):
    """F6/F7 root cause: there MUST be a goal-domain tool for setting a
    deadline. Without it the model has no honest tool and misroutes."""
    reg = build_tool_registry(uid)
    assert reg.has("update_goal_deadline")


def test_goal_deadline_sets_only_the_goal(temp_db, uid):
    """F6: 'Add goal Read Book' then 'Set its deadline to this month end'
    must set Read Book's deadline and leave the active character Xiao
    completely untouched."""
    eng, ws = _game(uid)
    xiao = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, xiao.id, "level", 22)
    db.tg_set_active(uid, ws.id, "milestone", xiao.id)

    m1 = FakeModel(_tool("create_goal", {"title": "Read Book"}),
                   _final("Goal added."))
    r1 = _worker(m1).run(_req(uid, "Add goal Read Book"))
    assert r1.termination is TerminationReason.FINAL and r1.steps[0].result.ok
    goal_id = db.get_goals_full(uid)[0][0]

    m2 = FakeModel(
        _tool("update_goal_deadline",
              {"goal": str(goal_id), "deadline": "2026-08-31"}),
        _final("Deadline set to 31 Aug."))
    r2 = _worker(m2).run(_req(uid, "Set its deadline to this month end"))
    assert r2.termination is TerminationReason.FINAL

    goals = db.get_goals_full(uid)
    book = next(g for g in goals if g[1] == "Read Book")
    assert book[2] == "2026-08-31"                 # deadline column
    xiao_after = next(mm for mm in eng.list_milestones(uid, ws.id)
                      if mm.title == "Xiao")
    assert xiao_after.fields.get("level") == 22    # untouched
    # target_level is a legit game-template DEFAULT (90) -- the corruption
    # signature would be a date leaking INTO Xiao's fields; assert no field
    # was added and no default was clobbered.
    assert xiao_after.fields.get("target_level") == 90
    assert "deadline" not in xiao_after.fields
    assert "2026-08-31" not in str(list(xiao_after.fields.values()))


def test_goal_deadline_this_month_end(temp_db, uid):
    """F7: 'this month end' -> 2026-08-31 from the deterministic parser."""
    gid = db.add_goal(uid, "Gym")
    m = FakeModel(
        _tool("update_goal_deadline",
              {"goal": str(gid), "deadline": "2026-08-31"}),
        _final("Deadline set."))
    r = _worker(m).run(_req(uid, "Set Gym deadline to this month end"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    goals = db.get_goals_full(uid)
    assert next(g for g in goals if g[1] == "Gym")[2] == "2026-08-31"
    sys_msg = m.calls[0][0][0]["content"]
    assert "2026-08-31" in sys_msg                  # PARSED, authoritative


def test_goal_deadline_next_month_end_parsed(temp_db, uid):
    """F7: 'next month end' -> 2026-09-30. date_parser must resolve it
    deterministically and the PARSED block must carry it into the prompt."""
    gid = db.add_goal(uid, "Gym")
    m = FakeModel(
        _tool("update_goal_deadline",
              {"goal": str(gid), "deadline": "2026-09-30"}),
        _final("Deadline set."))
    r = _worker(m).run(_req(uid, "Set Gym deadline to next month end"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    goals = db.get_goals_full(uid)
    assert next(g for g in goals if g[1] == "Gym")[2] == "2026-09-30"
    sys_msg = m.calls[0][0][0]["content"]
    assert "2026-09-30" in sys_msg


def test_goal_progress_update_uses_goal_domain(temp_db, uid):
    """D: increasing goal progress goes through update_goal_progress."""
    gid = db.add_goal(uid, "Gym")
    m = FakeModel(
        _tool("update_goal_progress", {"goal_id": gid, "delta": 20}),
        _final("Progress updated to 20%."))
    r = _worker(m).run(_req(uid, "Increase Gym progress by 20 percent"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    assert db.get_goals_full(uid)[0][3] == 20


def test_goal_pronoun_conflict_never_mutates_character(temp_db, uid):
    """F6 / R9: even if the model misroutes a goal request to the ENTITY
    tool with a pronoun, the entity tool must reject rather than resolve
    the pronoun to the active character and mutate it."""
    eng, ws = _game(uid)
    xiao = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, xiao.id, "level", 22)
    db.tg_set_active(uid, ws.id, "milestone", xiao.id)
    typed = _tstore()
    gid = db.add_goal(uid, "Read Book")
    typed.note(uid, "goal", gid, "Read Book")
    reg = build_tool_registry(uid, typed_refs=typed)
    res = reg.execute("update_entity",
                      {"entity": "its", "fields": {"deadline": "2026-08-31"}})
    assert not res.ok                             # rejected, never applied
    xiao_after = next(mm for mm in eng.list_milestones(uid, ws.id)
                      if mm.title == "Xiao")
    assert xiao_after.fields.get("level") == 22   # untouched
    assert "deadline" not in xiao_after.fields


def test_cross_domain_same_name_distinguished(temp_db, uid):
    """C / R9: a character named 'Xiao' and a goal named 'Xiao' coexist;
    entity ops hit the character, goal ops hit the goal — never cross."""
    eng, ws = _game(uid)
    char = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, char.id, "level", 90)
    gid = db.add_goal(uid, "Xiao")
    db.tg_set_active(uid, ws.id, "milestone", char.id)

    reg = build_tool_registry(uid)
    r = reg.execute("get_entity", {"entity": "Xiao"})
    assert r.ok and r.data["entity_id"] == char.id

    r2 = reg.execute("update_goal_deadline",
                     {"goal": "Xiao", "deadline": "2026-09-30"})
    assert r2.ok
    assert next(g for g in db.get_goals_full(uid)
                if g[0] == gid)[2] == "2026-09-30"
    # the character was not modified by the goal op
    assert not eng.list_milestones(uid, ws.id)[0].fields.get("deadline")


def test_ambiguous_deadline_never_mutates(temp_db, uid):
    """G / R7: 'Set its deadline to tomorrow' with NO goal to refer to must
    not resolve the pronoun to the active character; it asks/declines."""
    eng, ws = _game(uid)
    xiao = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, xiao.id, "level", 22)
    db.tg_set_active(uid, ws.id, "milestone", xiao.id)
    m = FakeModel(
        _tool("update_goal_deadline",
              {"goal": "its", "deadline": "2026-08-11"}),
        _final("I need to know which goal you mean."))
    r = _worker(m).run(_req(uid, "Set its deadline to tomorrow"))
    assert r.termination is TerminationReason.FINAL
    xiao_after = next(mm for mm in eng.list_milestones(uid, ws.id)
                      if mm.title == "Xiao")
    assert xiao_after.fields.get("level") == 22
    assert "deadline" not in xiao_after.fields


# ── R8/F8: kind-aware identity — duplicate detection is type-aware ────────
def test_create_entity_duplicate_is_type_aware(temp_db, uid):
    """M4 item 6 (root cause): same display name with a DIFFERENT kind is the
    SAME entity -- the kind is adopted onto the existing row (one row, one
    topic), never a second row. Same kind is an honest duplicate error."""
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    r1 = reg.execute("create_entity", {"name": "Golden Troupe"})
    assert r1.ok
    r2 = reg.execute("create_entity", {"name": "Golden Troupe"})
    assert not r2.ok and r2.error_code == "invalid_args"   # same kind dup
    r3 = reg.execute("create_entity",
                     {"name": "Golden Troupe", "entity_type": "artifact"})
    assert r3.ok and r3.data["adopted"] is True
    assert r3.data["entity_id"] == r1.data["entity_id"]    # ONE row survives
    rows = eng.list_milestones(uid, ws.id)
    assert len(rows) == 1
    assert rows[0].entity_type == "artifact"               # kind upgraded


def test_create_entity_stores_entity_type(temp_db, uid):
    """F8: the created entity's type is persisted, not lost."""
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    r = reg.execute("create_entity",
                    {"name": "Golden Troupe", "entity_type": "artifact"})
    assert r.ok and r.data.get("entity_type") == "artifact"
    m = eng.list_milestones(uid, ws.id)[0]
    assert m.entity_type == "artifact"


# ── R8/F9/F10: type-aware retrieval ───────────────────────────────────────
def test_list_entities_filters_by_entity_type(temp_db, uid):
    """F9: 'show all characters' uses a STRUCTURED kind filter — not a
    keyword hack, and it must not silently ignore the filter."""
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    r_char = reg.execute("create_entity",
                         {"name": "Xiao", "entity_type": "character"})
    r_art = reg.execute("create_entity",
                        {"name": "Golden Troupe", "entity_type": "artifact"})
    assert r_char.ok and r_art.ok
    chars = reg.execute("list_entities", {"kind": "character",
                                          "entity_type": "character"})
    assert chars.ok
    titles = [d["title"] for d in chars.data]     # data is the JSON list
    assert titles == ["Xiao"]
    arts = reg.execute("list_entities", {"kind": "artifact",
                                         "entity_type": "artifact"})
    assert [d["title"] for d in arts.data] == ["Golden Troupe"]
    all_ = reg.execute("list_entities", {"kind": "all"})
    assert len(all_.data) == 2


def test_worker_typed_retrieve_excludes_other_kinds(temp_db, uid):
    """F9/F10: the Worker's typed retrieval must NOT return mixed kinds
    ('show all characters' returned goals/artifacts/notes live)."""
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    reg.execute("create_entity", {"name": "Xiao", "entity_type": "character"})
    reg.execute("create_entity", {"name": "Furina", "entity_type": "character"})
    reg.execute("create_entity", {"name": "Golden Troupe",
                                  "entity_type": "artifact"})
    m = FakeModel(
        _tool("list_entities", {"kind": "character"}),
        _final("Characters: Xiao, Furina"))
    r = _worker(m).run(_req(uid, "Show all characters"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    titles = [d["title"] for d in r.steps[0].result.data]
    assert titles == ["Xiao", "Furina"]              # artifact excluded
    trace = " ".join(m.traces())
    assert "Golden Troupe" not in trace              # never surfaced as a char


def test_worker_uses_goal_tool_for_show_all_goals(temp_db, uid):
    """F9: 'show all goals' routes to the goal domain (list_goals), never
    to an entity listing."""
    db.add_goal(uid, "Gym")
    db.add_goal(uid, "Read Book")
    m = FakeModel(_tool("list_goals", {}), _final("Goals: Gym, Read Book"))
    r = _worker(m).run(_req(uid, "Show all goals"))
    assert r.termination is TerminationReason.FINAL
    assert [s.decision.tool_name for s in r.steps] == ["list_goals"]


# ── E: tasks stay in the task domain ──────────────────────────────────────
def test_task_completion_does_not_touch_entities(temp_db, uid):
    """E: completing a task must never hit an entity operation."""
    eng, ws = _game(uid)
    eng.add_milestone(uid, ws.id, "Xiao")
    tid = db.add_task(uid, "Buy Milk", due_date="2026-08-11", due_time="08:30")
    m = FakeModel(_tool("complete_task", {"task_id": tid}),
                  _final("Completed Buy Milk."))
    r = _worker(m).run(_req(uid, "Complete Buy Milk"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    xiao_after = eng.list_milestones(uid, ws.id)[0]
    assert not xiao_after.fields


# ── regression guard: M1 entity pronouns keep working ─────────────────────
def test_m1_entity_pronoun_unchanged(temp_db, uid):
    """Without a run-scoped store, the M1 resolver stays authoritative:
    a pronoun resolves to the active entity exactly as before."""
    eng, ws = _game(uid)
    xilonen = eng.add_milestone(uid, ws.id, "Xilonen")
    eng.update_field(uid, xilonen.id, "level", 70)
    db.tg_set_active(uid, ws.id, "milestone", xilonen.id)
    reg = build_tool_registry(uid)                  # no typed_refs -> M1 path
    res = reg.execute("update_entity",
                      {"entity": "her", "fields": {"level": 80}})
    assert res.ok
    assert res.data["entity_id"] == xilonen.id
    assert eng.list_milestones(uid, ws.id)[0].fields.get("level") == 80


# ── v15.2 M4 GENERIC INVARIANTS (S1..S30) ─────────────────────────────────
# The owner's live M4 pass failed 7 times; the forensic trace (bot.log)
# proved every one was a LEGACY-path failure because the Worker never ran
# (WORKER=0, not in .env). These tests pin the GENERIC INVARIANTS the Worker
# must uphold once WORKER=1, so the exact same live phrases can never regress
# no matter which model handles them. Every test is parameterized over
# multiple entity names/kinds (never phrase-specific): the invariant must
# hold for Bennet AND Mizuki AND a weapon AND an artifact, not one literal.
#
#   S1  create(A) -> set(A) -> show(A)              create-set-show chains
#   S2  create(A) -> set(A) -> show(B)              other-entity retrieval
#   S3  show(A) -> update(A) -> show(A)             update AND the show after
#   S4  update(A) -> show(A)                        update-then-show
#   S5  create(A) create(B) update(A) update(B)     independent multi-entity
#   S6  same name across types (char vs goal/...)   type-aware identity
#   S7  stale active + new entity, pronoun          run-scoped wins
#   S8  goal recent + character pronoun             domain conflict reject
#   S9  failed tool -> recovery                     honest failure + fix
#   S10 success + failed retrieval                  honest mixed trace
#   S11 fabricated success -> rewritten             honesty guard
#   S12 unknown referent never mutates active       fail-closed reference
#   S13 max-steps budget + broken composition       honest summary
#   S14/S21 typed list filter never mixed kinds     no task VIEW hijack (T7)
#   S16 task domain never touches entities (E)
#   S18 goal create -> progress -> list             goal chain
#   S20 task create -> retrieve                     task chain
#   S22 one bad ref then a good one recovers        not INVALID_ARGS_RECURRENT
#   S25 same name created this run beats stale      run-scoped identity
#   S27 create ok + update fail + show ok           partial success surfaces
#   S28 task + entity mixed stay in own domains
#   S29 habit create + complete                     habit chain
#   S30 goal deadline clear (null)
#   T7  artifact create + "show artifacts" retrieves it (live T7)

# ── S1/S19/S23/S24: create -> set -> show, for every kind ────────────────
@pytest.mark.parametrize("name,kind", [
    ("Bennet", "character"), ("Mizuki", "character"), ("Itto", "character"),
    ("Kaeya", "character"), ("Favonius Sword", "weapon"),
    ("Skyward Harp", "weapon"), ("Golden Troupe", "artifact"),
    ("Song of Days Past", "artifact"),
])
def test_invariant_create_set_show_all_kinds(temp_db, uid, name, kind):
    """S1: create(X) -> set(X) -> show(X) for MULTIPLE names and kinds. The
    created entity is a NEW entity of the right kind, the update lands on it,
    and the final show returns ITS id (never a stale active, never 'nothing
    found')."""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("create_entity", {"name": name, "entity_type": kind}),
        _tool("update_entity", {"entity": name, "fields": {"level": 80}}),
        _tool("get_entity", {"entity": name}),
        _final(f"{name} is level 80."))
    r = _worker(m).run(_req(uid, f"Create {name}, set level 80, show it"))
    assert r.termination is TerminationReason.FINAL
    assert [s.decision.tool_name for s in r.steps] == \
        ["create_entity", "update_entity", "get_entity"]
    assert all(s.result.ok for s in r.steps)
    created = next(mm for mm in eng.list_milestones(uid, ws.id)
                   if mm.title == name)
    assert created.entity_type == kind            # kind persisted, never lost
    assert created.fields.get("level") == 80
    shown = r.steps[2].result.data
    assert shown["entity_id"] == created.id       # the show returned THE one
    assert shown["entity_type"] == kind


# ── S2: create(A) set(A) show(B) ─────────────────────────────────────────
def test_invariant_create_set_show_other_entity(temp_db, uid):
    """S2: A's creation + update must survive AND the show must return B —
    never A, never 'couldn't find anything'. (Live T2: 'show her' collapsed
    to the updated A.)"""
    eng, ws = _game(uid)
    neuvillette = eng.add_milestone(uid, ws.id, "Neuvillette")
    db.tg_set_active(uid, ws.id, "milestone", neuvillette.id)
    m = FakeModel(
        _tool("create_entity", {"name": "Mizuki"}),
        _tool("update_entity", {"entity": "Mizuki", "fields": {"level": 90}}),
        _tool("get_entity", {"entity": "Neuvillette"}),
        _final("Mizuki created; here is Neuvillette."))
    r = _worker(m).run(_req(uid,
        "Create Mizuki, set her level to 90, then show Neuvillette"))
    assert r.termination is TerminationReason.FINAL
    assert all(s.result.ok for s in r.steps)
    mizuki = next(mm for mm in eng.list_milestones(uid, ws.id)
                  if mm.title == "Mizuki")
    assert mizuki.fields.get("level") == 90
    shown = r.steps[2].result.data
    assert shown["entity_id"] == neuvillette.id   # the OTHER entity, by name
    assert shown["title"] == "Neuvillette"


# ── S3: show(A) -> update(A) -> show(A) ──────────────────────────────────
@pytest.mark.parametrize("name", ["Xiao", "Neuvillette", "Klee", "Kaeya"])
def test_invariant_show_update_show(temp_db, uid, name):
    """S3: the update happens AND the show AFTER it also happens — the loop
    must not stop early after a mutation. (Live T3: update applied, show
    dropped.)"""
    eng, ws = _game(uid)
    ent = eng.add_milestone(uid, ws.id, name)
    eng.update_field(uid, ent.id, "level", 79)
    m = FakeModel(
        _tool("get_entity", {"entity": name}),
        _tool("update_entity", {"entity": name, "fields": {"level": 80}}),
        _tool("get_entity", {"entity": name}),
        _final(f"{name} updated."))
    r = _worker(m).run(_req(uid,
        f"Show {name} and then update level to 80 and then show it"))
    assert r.termination is TerminationReason.FINAL
    assert [s.decision.tool_name for s in r.steps] == \
        ["get_entity", "update_entity", "get_entity"]
    assert all(s.result.ok for s in r.steps)
    after = eng.list_milestones(uid, ws.id)[0]
    assert after.fields.get("level") == 80
    assert r.steps[2].result.data["entity_id"] == ent.id


# ── S4: update(A) -> show(A) ─────────────────────────────────────────────
@pytest.mark.parametrize("name", ["Xiao", "Furina"])
def test_invariant_update_then_show(temp_db, uid, name):
    """S4: update-then-show — both execute; the show returns the UPDATED
    entity. (Live T5: update happened, final show missing.)"""
    eng, ws = _game(uid)
    ent = eng.add_milestone(uid, ws.id, name)
    eng.update_field(uid, ent.id, "level", 50)
    m = FakeModel(
        _tool("update_entity", {"entity": name, "fields": {"level": 85}}),
        _tool("get_entity", {"entity": name}),
        _final(f"{name} is level 85."))
    r = _worker(m).run(_req(uid, f"Set {name} to level 85 and then show it"))
    assert r.termination is TerminationReason.FINAL
    assert [s.decision.tool_name for s in r.steps] == \
        ["update_entity", "get_entity"]
    assert all(s.result.ok for s in r.steps)
    after = eng.list_milestones(uid, ws.id)[0]
    assert after.fields.get("level") == 85
    assert r.steps[1].result.data["entity_id"] == ent.id


# ── S5: create(A) create(B) update(A) update(B) ──────────────────────────
def test_invariant_two_entities_independent_updates(temp_db, uid):
    """S5: two entities created then each updated in ONE run — updates stay
    per-entity, ids distinct, no cross-mutation. (Legacy collapsed compounds
    to a single update of the active entity.)"""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("create_entity", {"name": "Aether"}),
        _tool("create_entity", {"name": "Lumine"}),
        _tool("update_entity", {"entity": "Aether", "fields": {"level": 1}}),
        _tool("update_entity", {"entity": "Lumine", "fields": {"level": 2}}),
        _final("Both updated."))
    r = _worker(m).run(_req(uid,
        "Create Aether and Lumine, set Aether to level 1 and Lumine to 2"))
    # 4 ops = exactly MAX_TOOL_CALLS, so the run is budget-exhausted by
    # design: MAX_STEPS with the composed reply (never a dropped step).
    assert r.termination in (TerminationReason.FINAL,
                             TerminationReason.MAX_STEPS)
    assert [s.decision.tool_name for s in r.steps] == \
        ["create_entity", "create_entity", "update_entity", "update_entity"]
    assert all(s.result.ok for s in r.steps)
    aether = next(x for x in eng.list_milestones(uid, ws.id)
                  if x.title == "Aether")
    lumine = next(x for x in eng.list_milestones(uid, ws.id)
                  if x.title == "Lumine")
    assert aether.id != lumine.id
    assert aether.fields.get("level") == 1
    assert lumine.fields.get("level") == 2


# ── S6: same name across types ───────────────────────────────────────────
@pytest.mark.parametrize("name", ["Xiao", "Aether", "Klee"])
def test_invariant_cross_domain_same_name_goal(temp_db, uid, name):
    """S6: a character and a goal share a display name — the goal-deadline
    op hits the GOAL, never the character, never the other way. (Live T6:
    'Set its deadline' corrupted the character.)"""
    eng, ws = _game(uid)
    char = eng.add_milestone(uid, ws.id, name)
    eng.update_field(uid, char.id, "level", 22)
    gid = db.add_goal(uid, name)
    db.tg_set_active(uid, ws.id, "milestone", char.id)
    reg = build_tool_registry(uid)
    r = reg.execute("update_goal_deadline",
                    {"goal": name, "deadline": "2026-09-30"})
    assert r.ok
    assert next(g for g in db.get_goals_full(uid) if g[0] == gid)[2] \
        == "2026-09-30"
    char_after = eng.list_milestones(uid, ws.id)[0]
    assert char_after.fields.get("level") == 22    # untouched
    assert not char_after.fields.get("deadline")


def test_invariant_typed_identity_same_name_different_kinds(temp_db, uid):
    """S6/F8 -- M4 item 6: ONE canonical entity per name across all kinds.
    A typed row exists (character Xiao); a second create of the SAME name
    under a different kind is NOT a second row (the historical duplicate-topic
    root cause). DB priority (item 1) resolves the kind to the existing
    character → same-kind collision → honest 'already exists — update it
    instead', never a silent re-type, never a second entity."""
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    r1 = reg.execute("create_entity",
                     {"name": "Xiao", "entity_type": "character"})
    r2 = reg.execute("create_entity",
                     {"name": "Xiao", "entity_type": "artifact"})
    assert r1.ok
    assert not r2.ok and r2.error_code == "invalid_args"
    assert "already exists" in r2.output
    assert len(eng.list_milestones(uid, ws.id)) == 1     # ONE row, ONE topic
    chars = reg.execute("list_entities", {"kind": "character",
                                          "entity_type": "character"})
    arts = reg.execute("list_entities", {"kind": "artifact",
                                         "entity_type": "artifact"})
    assert [d["title"] for d in chars.data] == ["Xiao"]   # still a character
    assert [d["title"] for d in arts.data] == []          # never an artifact


# ── S7/S17/S28: stale active + fresh create, pronoun reaches the NEW one ──
@pytest.mark.parametrize("active,new_name,new_level,pronoun", [
    ("Hu Tao", "Bennet", 83, "him"),
    ("Furina", "Mizuki", 90, "her"),
    ("Kaeya", "Itto", 60, "him"),
    ("Xilonen", "Qiqi", 45, "she"),
])
def test_invariant_create_set_pronoun_vs_stale_active(
        temp_db, uid, active, new_name, new_level, pronoun):
    """S7/S17/S28: a fresh create of X THIS run + a pronoun must land on X —
    never on the pre-existing stale active entity. (Live F1/F2: 'him' reached
    Hu Tao.)"""
    eng, ws = _game(uid)
    stale = eng.add_milestone(uid, ws.id, active)
    eng.update_field(uid, stale.id, "level", 1)
    db.tg_set_active(uid, ws.id, "milestone", stale.id)
    m = FakeModel(
        _tool("create_entity", {"name": new_name}),
        _tool("update_entity", {"entity": pronoun,
                                "fields": {"level": new_level}}),
        _final(f"{new_name} leveled."))
    r = _worker(m).run(_req(uid,
        f"Create {new_name}, set {pronoun} to level {new_level}"))
    assert r.termination is TerminationReason.FINAL
    assert all(s.result.ok for s in r.steps)
    fresh = next(x for x in eng.list_milestones(uid, ws.id)
                 if x.title == new_name)
    assert fresh.fields.get("level") == new_level
    stale_after = next(x for x in eng.list_milestones(uid, ws.id)
                       if x.title == active)
    assert stale_after.fields.get("level") == 1    # never touched


@pytest.mark.parametrize("pronoun,new_name", [
    ("him", "Bennet"), ("her", "Mizuki"), ("it", "Klee"), ("this", "Itto"),
])
def test_invariant_pronoun_beats_stale_active_direct(
        temp_db, uid, pronoun, new_name):
    """S17: at the TOOL layer, a run-scoped typed referent beats the stale
    active entity for every conversational pronoun — M1 is only the fallback."""
    eng, ws = _game(uid)
    stale = eng.add_milestone(uid, ws.id, "Hu Tao")
    eng.update_field(uid, stale.id, "level", 83)
    db.tg_set_active(uid, ws.id, "milestone", stale.id)
    fresh = eng.add_milestone(uid, ws.id, new_name)
    typed = _tstore()
    typed.note(uid, "entity", fresh.id, new_name, ws.id)
    reg = build_tool_registry(uid, typed_refs=typed)
    res = reg.execute("update_entity",
                      {"entity": pronoun, "fields": {"level": 7}})
    assert res.ok and res.data["entity_id"] == fresh.id
    stale_after = eng.list_milestones(uid, ws.id)[0]
    assert stale_after.id == stale.id
    assert stale_after.fields.get("level") == 83   # stale untouched
    fresh_after = next(x for x in eng.list_milestones(uid, ws.id)
                       if x.id == fresh.id)
    assert fresh_after.fields.get("level") == 7


# ── S8: goal created this run blocks a character-pronoun op ──────────────
def test_invariant_goal_active_blocks_character_pronoun(temp_db, uid):
    """S8: a goal created THIS run is the most-recent referent; a character-
    pronoun entity op must be REJECTED (domain conflict), never mutate the
    goal, never silently cross domains."""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("create_goal", {"title": "Read Book"}),
        _tool("update_entity", {"entity": "its", "fields": {"level": 99}}),
        _final("Goal added; character update blocked."))
    r = _worker(m).run(_req(uid, "Add goal Read Book, then raise its level"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    assert not r.steps[1].result.ok                # rejected, honestly
    assert eng.list_milestones(uid, ws.id) == []   # no entity created/mutated
    goals = db.get_goals_full(uid)
    assert len(goals) == 1
    assert goals[0][1] == "Read Book"
    assert goals[0][2] is None                     # deadline intact
    assert goals[0][3] == 0                        # progress intact


@pytest.mark.parametrize("pronoun", ["its", "it", "this", "that", "him", "her"])
def test_invariant_goal_recent_pronoun_never_reaches_entity(
        temp_db, uid, pronoun):
    """S8b: whichever conversational pronoun is used, a recent GOAL referent
    blocks an entity op instead of letting it mutate the active character."""
    eng, ws = _game(uid)
    xiao = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, xiao.id, "level", 22)
    db.tg_set_active(uid, ws.id, "milestone", xiao.id)
    typed = _tstore()
    gid = db.add_goal(uid, "Read Book")
    typed.note(uid, "goal", gid, "Read Book")      # most recent = goal
    reg = build_tool_registry(uid, typed_refs=typed)
    res = reg.execute("update_entity",
                      {"entity": pronoun, "fields": {"deadline": "2026-08-31"}})
    assert not res.ok                              # domain conflict, rejected
    assert eng.list_milestones(uid, ws.id)[0].fields.get("level") == 22


# ── S9: failed tool -> recovery ──────────────────────────────────────────
def test_invariant_failed_tool_recovery(temp_db, uid):
    """S9: a tool call against a not-yet-existing entity fails HONESTLY, then
    the run recovers by creating it and completing the update. The failed step
    stays failed in the trace — never re-labeled ok."""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("update_entity", {"entity": "Klee",
                                "fields": {"level": 1}}),  # fails: no Klee
        _tool("create_entity", {"name": "Klee"}),
        _tool("update_entity", {"entity": "Klee",
                                "fields": {"level": 20}}),
        _tool("get_entity", {"entity": "Klee"}),
        _final("Klee is level 20."))
    r = _worker(m).run(_req(uid, "Set Klee to level 1, then create her and set 20"))
    # 4 steps = exactly MAX_TOOL_CALLS -> budget-exhausted (MAX_STEPS with
    # the composed reply); the invariants are the honest failure + recovery.
    assert r.termination in (TerminationReason.FINAL,
                             TerminationReason.MAX_STEPS)
    assert not r.steps[0].result.ok                # failure preserved
    assert all(s.result.ok for s in r.steps[1:])   # recovery succeeded
    klee = eng.list_milestones(uid, ws.id)[0]
    assert klee.fields.get("level") == 20


# ── S10: success + failed retrieval ──────────────────────────────────────
def test_invariant_success_and_failed_retrieval(temp_db, uid):
    """S10: show X (exists) then show Y (does not). X's retrieval succeeds;
    Y's is an honest failure in the trace — never dropped, never re-labeled
    ok, no fabricated data, and the final reply surfaces X."""
    eng, ws = _game(uid)
    eng.add_milestone(uid, ws.id, "Xiao")
    m = FakeModel(
        _tool("get_entity", {"entity": "Xiao"}),
        _tool("get_entity", {"entity": "Ghost"}),
        _final("Xiao is here; Ghost could not be found."))
    r = _worker(m).run(_req(uid, "Show Xiao and then show Ghost"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    assert not r.steps[1].result.ok
    assert r.steps[1].result.error_code == "invalid_args"
    assert r.steps[1].result.data is None          # no fabricated data
    assert "Xiao" in r.reply


# ── S11: fabricated success -> rewritten ─────────────────────────────────
def test_invariant_fabricated_success_rewritten(temp_db, uid):
    """S11/R7: a final reply claiming success with NO backing ok ToolResult
    is rewritten by the honesty guard — the Worker never fabricates success.
    (Fix policy: never claim success unless the ToolResult proves it.)"""
    m = FakeModel(_final("Klee created successfully!"))
    r = _worker(m).run(_req(uid, "Create Klee"))
    assert r.termination is TerminationReason.FINAL
    assert "nothing actually succeeded" in r.reply
    assert "created successfully" not in r.reply
    assert not r.steps


# ── S12: unknown referent never mutates active ───────────────────────────
def test_invariant_unknown_referent_never_mutates_active(temp_db, uid):
    """S12: updating a name that does not exist is REJECTED — it must never
    fall back to the active entity and silently mutate it. (Legacy T2/T3/T5
    resolved everything to the DB active entity.)"""
    eng, ws = _game(uid)
    xiao = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, xiao.id, "level", 22)
    db.tg_set_active(uid, ws.id, "milestone", xiao.id)
    m = FakeModel(
        _tool("update_entity", {"entity": "Klee",
                                "fields": {"level": 50}}),
        _final("I could not find Klee."))
    r = _worker(m).run(_req(uid, "Set Klee to level 50"))
    assert r.termination is TerminationReason.FINAL
    assert not r.steps[0].result.ok
    assert eng.list_milestones(uid, ws.id)[0].fields.get("level") == 22


# ── S13: max-steps budget + broken composition -> honest summary ─────────
def test_invariant_max_steps_honest_summary(temp_db, uid):
    """S13: when the 6-call budget is exhausted and the composition call fails
    to parse, the reply is an honest trace of what DID succeed — not a
    fabricated claim, not a bare 'try again'."""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("create_entity", {"name": "Keqing"}),
        _tool("update_entity", {"entity": "Keqing",
                                "fields": {"level": 90}}),
        _tool("get_entity", {"entity": "Keqing"}),
        _tool("list_entities", {"kind": "all"}),
        _tool("list_entities", {"kind": "all"}),
        _tool("get_entity", {"entity": "Keqing"}),
        "not-json-garbage")                        # composition call malformed
    r = _worker(m).run(_req(uid,
        "Create Keqing, level 90, show her, list everything"))
    assert r.termination is TerminationReason.MAX_STEPS
    assert all(s.result.ok for s in r.steps)
    assert len(r.steps) == MAX_TOOL_CALLS
    assert "Here's what actually happened" in r.reply
    assert "create_entity" in r.reply and "update_entity" in r.reply


# ── S14/S21: typed list filter never mixed kinds (live T7) ───────────────
def test_invariant_typed_list_filter_kinds(temp_db, uid):
    """S14/S21/F9/F10: 'show all <kind>' returns ONLY that kind — a structured
    filter, not a mixed dump and never a task VIEW. (Live T7: 'show artifacts'
    fell through to 'Tasks for All Pending'.)"""
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    reg.execute("create_entity", {"name": "Xiao", "entity_type": "character"})
    reg.execute("create_entity", {"name": "Furina", "entity_type": "character"})
    reg.execute("create_entity", {"name": "Golden Troupe",
                                  "entity_type": "artifact"})
    reg.execute("create_entity", {"name": "Skyward Harp",
                                  "entity_type": "weapon"})
    m = FakeModel(
        _tool("list_entities", {"kind": "character",
                                "entity_type": "character"}),
        _final("Characters: Xiao, Furina"))
    r = _worker(m).run(_req(uid, "Show all characters"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    titles = [d["title"] for d in r.steps[0].result.data]
    assert titles == ["Xiao", "Furina"]            # EXACTLY that kind
    assert all(d["entity_type"] == "character"
               for d in r.steps[0].result.data)


def test_invariant_artifact_retrieval_after_create(temp_db, uid):
    """T7 live: 'Add Artifact Aubade of Morningstar and Moon' then
    'show artifacts' — the created artifact MUST be retrievable by kind,
    never 'I couldn't find anything about that in your saved data.'"""
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    c = reg.execute("create_entity",
                    {"name": "Aubade of Morningstar and Moon",
                     "entity_type": "artifact"})
    assert c.ok
    m = FakeModel(
        _tool("list_entities", {"kind": "artifact",
                                "entity_type": "artifact"}),
        _final("Found the artifact."))
    r = _worker(m).run(_req(uid, "Show all artifacts"))
    assert r.termination is TerminationReason.FINAL
    titles = [d["title"] for d in r.steps[0].result.data]
    assert titles == ["Aubade of Morningstar and Moon"]


def test_invariant_weapon_retrieval_after_create(temp_db, uid):
    """S24/T7: same retrieval invariant for weapons."""
    eng, ws = _game(uid)
    reg = build_tool_registry(uid)
    c = reg.execute("create_entity",
                    {"name": "Skyward Harp", "entity_type": "weapon"})
    assert c.ok
    m = FakeModel(
        _tool("list_entities", {"kind": "weapon",
                                "entity_type": "weapon"}),
        _final("Found the weapon."))
    r = _worker(m).run(_req(uid, "Show all weapons"))
    assert r.termination is TerminationReason.FINAL
    titles = [d["title"] for d in r.steps[0].result.data]
    assert titles == ["Skyward Harp"]


# ── S16/E: task domain never touches entities ────────────────────────────
@pytest.mark.parametrize("task_title", ["Buy Milk", "Read a chapter",
                                        "Water plants"])
def test_invariant_task_domain_does_not_touch_entities(temp_db, uid,
                                                       task_title):
    """S16/E: a task operation (create/complete) never creates or mutates a
    workspace entity — domains stay isolated. (Live T7 mixed them.)"""
    eng, ws = _game(uid)
    xiao = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, xiao.id, "level", 22)
    tid = db.add_task(uid, task_title, due_date="2026-08-11")
    m = FakeModel(_tool("complete_task", {"task_id": tid}),
                  _final(f"Completed {task_title}."))
    r = _worker(m).run(_req(uid, f"Complete {task_title}"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    xiao_after = eng.list_milestones(uid, ws.id)[0]
    assert xiao_after.fields.get("level") == 22
    assert not xiao_after.fields.get("deadline")


# ── S18: goal create -> progress -> list ─────────────────────────────────
def test_invariant_goal_chain_create_progress_list(temp_db, uid):
    """S18: create goal -> bump progress -> list goals in ONE run; every op
    is a goal-domain op, progress persists."""
    m = FakeModel(
        _tool("create_goal", {"title": "Gym"}),
        _tool("update_goal_progress", {"goal_id": 1, "delta": 20}),
        _tool("list_goals", {}),
        _final("Gym is 20% done."))
    r = _worker(m).run(_req(uid,
        "Add goal Gym, increase progress by 20, show goals"))
    assert r.termination is TerminationReason.FINAL
    assert [s.decision.tool_name for s in r.steps] == \
        ["create_goal", "update_goal_progress", "list_goals"]
    assert all(s.result.ok for s in r.steps)
    goals = db.get_goals_full(uid)
    assert goals[0][1] == "Gym" and goals[0][3] == 20


# ── S20: task create -> retrieve ─────────────────────────────────────────
def test_invariant_task_create_retrieve(temp_db, uid):
    """S20: create a task then list tasks — the created task is retrievable
    with its fields; the task domain never creates entities."""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("create_task", {"title": "Buy Milk", "due_date": "2026-08-11"}),
        _tool("list_tasks", {}),
        _final("Task created."))
    r = _worker(m).run(_req(uid,
        "Add task Buy Milk due 2026-08-11 and show tasks"))
    assert r.termination is TerminationReason.FINAL
    assert all(s.result.ok for s in r.steps)
    tid = r.steps[0].result.data["task_id"]
    tasks = db.get_tasks(uid)
    assert any(t[0] == tid and t[1] == "Buy Milk" and t[2] == "2026-08-11"
               for t in tasks)
    listed = [t["title"] for t in r.steps[1].result.data]
    assert "Buy Milk" in listed
    assert eng.list_milestones(uid, ws.id) == []   # no entity was created


# ── S22: one bad ref then a good one recovers ────────────────────────────
def test_invariant_invalid_args_recovery(temp_db, uid):
    """S22: one bad reference (name not found) followed by a correct one is
    NOT 'two consecutive invalid args' — the run must recover, not terminate."""
    eng, ws = _game(uid)
    xiao = eng.add_milestone(uid, ws.id, "Xiao")
    eng.update_field(uid, xiao.id, "level", 10)
    m = FakeModel(
        _tool("update_entity", {"entity": "Klee",
                                "fields": {"level": 5}}),     # fails
        _tool("update_entity", {"entity": "Xiao",
                                "fields": {"level": 60}}),    # recovers
        _final("Xiao updated."))
    r = _worker(m).run(_req(uid, "Set Klee to 5, then Xiao to 60"))
    assert r.termination is TerminationReason.FINAL
    assert not r.steps[0].result.ok and r.steps[1].result.ok
    assert eng.list_milestones(uid, ws.id)[0].fields.get("level") == 60


# ── S25: same name created this run beats the stale active ───────────────
def test_invariant_same_name_run_scoped_wins_over_stale(temp_db, uid):
    """S25 (M4 item 6): a name that ALSO matches the stale active entity — the
    create ADOPTS the declared kind onto the single canonical row (one entity,
    one topic, the duplicate root cause is gone) and the follow-up update
    reaches exactly that row. Identity is (workspace, id), never the display
    name, never a duplicate row."""
    eng, ws = _game(uid)
    stale = eng.add_milestone(uid, ws.id, "Xiao")   # entity kind
    eng.update_field(uid, stale.id, "level", 1)
    db.tg_set_active(uid, ws.id, "milestone", stale.id)
    m = FakeModel(
        _tool("create_entity", {"name": "Xiao",
                                "entity_type": "character"}),
        _tool("update_entity", {"entity": "Xiao",
                                "fields": {"level": 80}}),
        _final("Xiao is level 80."))
    r = _worker(m).run(_req(uid, "Create Xiao as a character and set level 80"))
    assert r.termination is TerminationReason.FINAL
    assert all(s.result.ok for s in r.steps)
    rows = eng.list_milestones(uid, ws.id)
    assert len(rows) == 1                            # ONE canonical row
    assert rows[0].id == stale.id                    # adopted, not duplicated
    assert rows[0].entity_type == "character"        # kind adopted
    assert rows[0].fields.get("level") == 80         # update landed here


# ── S27: create ok + update fail + show ok (partial success surfaces) ────
def test_invariant_create_ok_update_fail_show(temp_db, uid):
    """S27: create A (ok), update B (B does not exist -> fail), show A. The
    failure is honest, A is shown, and the failed B-update NEVER touched A."""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("create_entity", {"name": "Aether"}),
        _tool("update_entity", {"entity": "Zhongli",
                                "fields": {"level": 9}}),    # fails
        _tool("get_entity", {"entity": "Aether"}),
        _final("Aether created; Zhongli not found."))
    r = _worker(m).run(_req(uid,
        "Create Aether, set Zhongli to level 9, show Aether"))
    assert r.termination is TerminationReason.FINAL
    assert r.steps[0].result.ok
    assert not r.steps[1].result.ok
    assert r.steps[2].result.ok
    aether = eng.list_milestones(uid, ws.id)[0]
    assert aether.title == "Aether"
    assert aether.fields.get("level") is None       # failed update didn't leak
    assert r.steps[2].result.data["title"] == "Aether"


# ── S28: task + entity mixed stay in their own domains ───────────────────
def test_invariant_task_entity_mixed_domains(temp_db, uid):
    """S28 (M4 item 2): task ops and entity ops in ONE run keep their own
    domains. list_tasks stays PURE tasks (never an entity); the kind=all union
    carries every object with its own kind marker -- a task object is always
    kind=task, an entity object always kind=entity, never blended."""
    eng, ws = _game(uid)
    m = FakeModel(
        _tool("create_task", {"title": "Buy Milk"}),
        _tool("create_entity", {"name": "Xiao"}),
        _tool("list_tasks", {}),
        _tool("list_entities", {"kind": "all"}),
        _final("Done."))
    r = _worker(m).run(_req(uid,
        "Add task Buy Milk, create Xiao, show tasks, show entities"))
    # 4 ops fit inside the 6-call budget, so the 5th response (FINAL) ends the
    # run; the invariant is domain isolation, not the termination enum.
    assert r.termination in (TerminationReason.FINAL,
                             TerminationReason.MAX_STEPS)
    assert [s.decision.tool_name for s in r.steps] == \
        ["create_task", "create_entity", "list_tasks", "list_entities"]
    assert all(s.result.ok for s in r.steps)
    task_titles = [t["title"] for t in r.steps[2].result.data]
    assert task_titles == ["Buy Milk"]                 # list_tasks is pure
    kinds = {d["title"]: d["kind"] for d in r.steps[3].result.data}
    assert kinds["Xiao"] == "entity"                   # entity keeps its kind
    assert kinds["Buy Milk"] == "task"                 # task stays a task


# ── S29: habit create + complete ─────────────────────────────────────────
def test_invariant_habit_chain(temp_db, uid):
    """S29: create a habit then log a completion for the returned id — the
    habit is retrievable and the streak increments (habit domain only)."""
    m = FakeModel(
        _tool("create_habit", {"title": "Meditate"}),
        _tool("complete_habit", {"habit_id": 1}),
        _final("Meditate logged."))
    r = _worker(m).run(_req(uid, "Add habit Meditate and log it today"))
    assert r.termination is TerminationReason.FINAL
    assert all(s.result.ok for s in r.steps)
    habits = db.get_habits(uid)
    assert any(h[1] == "Meditate" and h[5] >= 1 for h in habits)


# ── S30: goal deadline clear (null) ──────────────────────────────────────
def test_invariant_goal_deadline_clear(temp_db, uid):
    """S30: a deadline can be cleared (null) via the goal-domain tool; the
    goal keeps its identity and no entity is touched."""
    m = FakeModel(
        _tool("create_goal", {"title": "Gym", "deadline": "2026-08-31"}),
        _tool("update_goal_deadline", {"goal": "Gym", "deadline": None}),
        _final("Deadline cleared."))
    r = _worker(m).run(_req(uid,
        "Add goal Gym with end-of-Aug deadline, then clear it"))
    assert r.termination is TerminationReason.FINAL
    assert all(s.result.ok for s in r.steps)
    assert db.get_goals_full(uid)[0][2] is None
