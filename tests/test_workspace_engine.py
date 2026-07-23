"""
Tests for the v15.0-alpha.2 Workspace Entity Engine
(core/workspace/engine.py + lifecycle.py + errors.py).

All offline against the temp_db fixture. Covers validation, ownership
scoping, lifecycle enforcement, the event seam, template-driven creation
and progress, and the lifecycle state machines themselves.
"""
import pytest

import database as db
from core.workspace import templates
from core.workspace.engine import (
    EV_MILESTONE_ADDED,
    EV_MILESTONE_STATUS,
    EV_NOTE_ADDED,
    EV_WORKSPACE_CREATED,
    EntityEngine,
)
from core.workspace.errors import (
    EntityNotFound,
    EntityValidationError,
    InvalidTransition,
)
from core.workspace import lifecycle
from core.workspace.models import (
    MS_BLOCKED,
    MS_DONE,
    MS_IN_PROGRESS,
    MS_TODO,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_DONE,
)


OTHER = 999888777  # a second user, to prove ownership scoping


def make_engine():
    events = []
    eng = EntityEngine(on_event=lambda ev: events.append((ev.event_type, ev.entity_type)))
    return eng, events


# ── Lifecycle state machine (pure) ────────────────────────────────────────

def test_workspace_lifecycle_transitions():
    lc = lifecycle.WORKSPACE_LIFECYCLE
    assert lc.can(STATUS_ACTIVE, STATUS_ARCHIVED)
    assert lc.can(STATUS_ACTIVE, STATUS_DONE)
    assert lc.can(STATUS_ARCHIVED, STATUS_ACTIVE)
    assert lc.can(STATUS_DONE, STATUS_ACTIVE)
    assert not lc.can(STATUS_ARCHIVED, STATUS_DONE)  # illegal
    assert lc.can(STATUS_ACTIVE, STATUS_ACTIVE)      # staying put is fine


def test_milestone_lifecycle_transitions():
    lc = lifecycle.MILESTONE_LIFECYCLE
    assert lc.can(MS_TODO, MS_IN_PROGRESS)
    assert lc.can(MS_IN_PROGRESS, MS_DONE)
    assert lc.can(MS_DONE, MS_IN_PROGRESS)   # reopen
    assert lc.can(MS_TODO, MS_BLOCKED)
    assert not lc.can(MS_TODO, "nonsense")   # unknown target unreachable


def test_lifecycle_validate_raises():
    with pytest.raises(InvalidTransition):
        lifecycle.WORKSPACE_LIFECYCLE.validate(STATUS_ARCHIVED, STATUS_DONE)


def test_lifecycle_states_complete():
    # 'archived' joined the milestone machine in alpha.4.
    assert lifecycle.MILESTONE_LIFECYCLE.states() == frozenset(
        {MS_TODO, MS_IN_PROGRESS, MS_DONE, MS_BLOCKED, "archived"})


# ── create_workspace ──────────────────────────────────────────────────────

def test_create_validates_empty_title(temp_db, uid):
    eng = EntityEngine()
    with pytest.raises(EntityValidationError):
        eng.create_workspace(uid, "   ")


def test_create_applies_template_and_seeds_milestones(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Robot", template="project")
    assert ws.icon == "🛠"
    titles = [m.title for m in eng.list_milestones(uid, ws.id)]
    assert titles == list(templates.get("project").default_milestones)


def test_create_unknown_template_falls_back(temp_db, uid):
    ws = EntityEngine().create_workspace(uid, "X", template="nope")
    assert ws.template == "generic"


def test_create_emits_events(temp_db, uid):
    eng, events = make_engine()
    eng.create_workspace(uid, "P", template="project")  # 5 milestones
    assert events[0] == (EV_WORKSPACE_CREATED, "workspace")
    assert events.count((EV_MILESTONE_ADDED, "milestone")) == 5


def test_create_strips_title(temp_db, uid):
    ws = EntityEngine().create_workspace(uid, "  Padded  ")
    assert ws.title == "Padded"


# ── ownership / get ───────────────────────────────────────────────────────

def test_get_workspace_raises_when_missing(temp_db, uid):
    with pytest.raises(EntityNotFound):
        EntityEngine().get_workspace(uid, 4242)


def test_get_workspace_or_none(temp_db, uid):
    assert EntityEngine().get_workspace_or_none(uid, 4242) is None


def test_ownership_is_scoped_by_user(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Mine")
    # Another user must not be able to read or mutate it.
    with pytest.raises(EntityNotFound):
        eng.get_workspace(OTHER, ws.id)
    with pytest.raises(EntityNotFound):
        eng.add_milestone(OTHER, ws.id, "sneaky")
    with pytest.raises(EntityNotFound):
        eng.transition_workspace(OTHER, ws.id, STATUS_ARCHIVED)


# ── workspace lifecycle via engine ────────────────────────────────────────

def test_transition_workspace_valid(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "W")
    done = eng.complete_workspace(uid, ws.id)
    assert done.status == STATUS_DONE
    archived = eng.archive_workspace(uid, ws.id)
    assert archived.status == STATUS_ARCHIVED
    assert archived.archived_at is not None


def test_transition_workspace_illegal_raises(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "W")
    eng.archive_workspace(uid, ws.id)
    with pytest.raises(InvalidTransition):
        eng.transition_workspace(uid, ws.id, STATUS_DONE)  # archived -> done


def test_transition_workspace_noop_emits_nothing(temp_db, uid):
    eng, events = make_engine()
    ws = eng.create_workspace(uid, "W")
    events.clear()
    same = eng.transition_workspace(uid, ws.id, STATUS_ACTIVE)  # already active
    assert same.status == STATUS_ACTIVE
    assert events == []


def test_rename_workspace(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Old")
    renamed = eng.rename_workspace(uid, ws.id, "New")
    assert renamed.title == "New"
    with pytest.raises(EntityValidationError):
        eng.rename_workspace(uid, ws.id, "")


# ── milestones via engine ─────────────────────────────────────────────────

def test_add_milestone_increments_sort_order(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "W")
    a = eng.add_milestone(uid, ws.id, "A")
    b = eng.add_milestone(uid, ws.id, "B")
    assert a.sort_order == 0 and b.sort_order == 1


def test_add_milestone_validates_title(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "W")
    with pytest.raises(EntityValidationError):
        eng.add_milestone(uid, ws.id, "")


def test_milestone_flow_and_completion(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "W")
    ms = eng.add_milestone(uid, ws.id, "M")
    ip = eng.transition_milestone(uid, ms.id, MS_IN_PROGRESS)
    assert ip.status == MS_IN_PROGRESS
    done = eng.complete_milestone(uid, ms.id)
    assert done.status == MS_DONE
    assert done.progress == 100
    assert done.completed_at is not None


def test_milestone_illegal_transition_raises(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "W")
    ms = eng.add_milestone(uid, ws.id, "M")
    with pytest.raises(InvalidTransition):
        eng.transition_milestone(uid, ms.id, "nonsense")


def test_milestone_reopen(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "W")
    ms = eng.add_milestone(uid, ws.id, "M")
    eng.complete_milestone(uid, ms.id)
    reopened = eng.transition_milestone(uid, ms.id, MS_IN_PROGRESS)
    assert reopened.status == MS_IN_PROGRESS


def test_milestone_ownership_enforced(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "W")
    ms = eng.add_milestone(uid, ws.id, "M")
    with pytest.raises(EntityNotFound):
        eng.transition_milestone(OTHER, ms.id, MS_DONE)


def test_milestone_status_event(temp_db, uid):
    eng, events = make_engine()
    ws = eng.create_workspace(uid, "W")
    ms = eng.add_milestone(uid, ws.id, "M")
    events.clear()
    eng.complete_milestone(uid, ms.id)
    assert (EV_MILESTONE_STATUS, "milestone") in events


# ── notes via engine ──────────────────────────────────────────────────────

def test_add_note_validation_ownership_and_event(temp_db, uid):
    eng, events = make_engine()
    ws = eng.create_workspace(uid, "W")
    events.clear()
    note = eng.add_note(uid, ws.id, "hello", kind="knowledge")
    assert note.content == "hello"
    assert (EV_NOTE_ADDED, "note") in events
    with pytest.raises(EntityValidationError):
        eng.add_note(uid, ws.id, "   ")
    with pytest.raises(EntityNotFound):
        eng.add_note(OTHER, ws.id, "nope")
    assert len(eng.list_notes(uid, ws.id, kind="knowledge")) == 1


# ── progress rollup ───────────────────────────────────────────────────────

def test_progress_milestones(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "P", template="project")  # 5 milestones
    assert eng.workspace_progress(uid, ws.id) == 0
    ms = eng.list_milestones(uid, ws.id)
    eng.complete_milestone(uid, ms[0].id)
    assert eng.workspace_progress(uid, ws.id) == 20  # 1/5


def test_progress_chapters(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "Book", template="book",
                              seed_milestones=False,
                              metadata={"total_chapters": 4, "current_chapter": 1})
    assert eng.workspace_progress(uid, ws.id) == 25


def test_progress_manual_and_missing(temp_db, uid):
    eng = EntityEngine()
    ws = eng.create_workspace(uid, "R", template="research",
                              metadata={"progress": 60})
    assert eng.workspace_progress(uid, ws.id) == 60
    # Missing workspace -> 0, never raises (progress is a read).
    assert eng.workspace_progress(uid, 4242) == 0


# ── default no-op event hook doesn't error ────────────────────────────────

def test_default_engine_has_noop_hook(temp_db, uid):
    eng = EntityEngine()  # no on_event
    ws = eng.create_workspace(uid, "W", template="project")
    assert ws.id  # no exception from emitting into the no-op sink
