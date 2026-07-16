"""
Tests for conversation_state.py -- first covered in v14.12, when
ADR-011 Option A made the state machine part of the Offline dispatch
decision (claims_messages()). Pins both the state machine's basic
contracts (which every Offline write flow already relies on:
set_pending_action/confirming for create+delete, set_editing/editing
for update) and the ADR-011 dispatch-priority rule itself.

main.py's gate is
    (OFFLINE_TASKS or OFFLINE_HABITS) and intent is not None
        and not claims_messages(state)
-- so the truth table pinned here IS the regression test for "a
mid-confirmation 'done 5' re-prompts rather than completes": with
claims_messages("confirming") True, OfflineEngine.execute() is never
consulted and the message reaches Legacy's confirming branch unchanged,
in both flag states. (main.py itself is not importable from the test
suite -- module-level Telegram/instance-lock side effects -- so the
predicate, which is the entire change, is pinned here instead;
TESTING.md's manual smoke checklist covers the live path.)
"""
import pytest

import conversation_state as cs


@pytest.fixture(autouse=True)
def _fresh_state():
    uid = 555000111
    cs.clear_state(uid)
    cs.clear_history(uid)
    yield
    cs.clear_state(uid)
    cs.clear_history(uid)


UID = 555000111


# ── ADR-011 Option A: which states claim messages ────────────────────────

@pytest.mark.parametrize("state,claims", [
    ("idle", False),          # only state where intent dispatch may run
    ("confirming", True),     # message is a yes/no answer
    ("gathering", True),      # message fills a missing field
    ("editing", True),        # message is the change description
])
def test_claims_messages_truth_table(state, claims):
    assert cs.claims_messages(state) is claims


def test_interactive_states_constant_matches():
    assert set(cs.INTERACTIVE_STATES) == {"confirming", "gathering", "editing"}


def test_mid_confirmation_blocks_offline_dispatch():
    # The ADR-011 scenario: user has a pending save ("Shall I save
    # this?") and types "done 5". The state is confirming, so the gate
    # predicate is False and OfflineEngine.execute() is never reached --
    # Legacy's confirming branch re-prompts, identical to flag-OFF.
    cs.set_pending_action(UID, "add_task", {"title": "x"})
    assert cs.get_state(UID) == "confirming"
    assert cs.claims_messages(cs.get_state(UID)) is True


def test_mid_gathering_blocks_offline_dispatch():
    cs.set_gathering(UID, {"title": "x"}, ["date"])
    assert cs.get_state(UID) == "gathering"
    assert cs.claims_messages(cs.get_state(UID)) is True


def test_mid_editing_blocks_offline_dispatch():
    cs.set_editing(UID, 42)
    assert cs.get_state(UID) == "editing"
    assert cs.claims_messages(cs.get_state(UID)) is True


def test_idle_allows_offline_dispatch_including_after_clear():
    assert cs.claims_messages(cs.get_state(UID)) is False    # default idle
    cs.set_pending_action(UID, "add_task", {})
    cs.clear_state(UID)                                      # cancel/finish
    assert cs.get_state(UID) == "idle"
    assert cs.claims_messages(cs.get_state(UID)) is False


# ── State-machine contracts the Offline flows rely on ────────────────────

def test_default_state_is_idle():
    assert cs.get_state(999999999) == "idle"


def test_pending_action_roundtrip():
    cs.set_pending_action(UID, "offline_add_task", {"title": "Buy milk"})
    action, data = cs.get_pending_action(UID)
    assert action == "offline_add_task"
    assert data == {"title": "Buy milk"}


def test_gathering_roundtrip():
    cs.set_gathering(UID, {"title": "x"}, ["date", "time"])
    partial, missing = cs.get_gathering(UID)
    assert partial == {"title": "x"} and missing == ["date", "time"]


def test_editing_roundtrip():
    cs.set_editing(UID, 42)
    assert cs.get_editing_id(UID) == 42


def test_clear_state_resets_context():
    cs.set_pending_action(UID, "x", {"a": 1})
    cs.clear_state(UID)
    action, data = cs.get_pending_action(UID)
    assert action is None and data == {}


def test_history_caps_at_max():
    for k in range(cs.MAX_HISTORY + 5):
        cs.add_history(UID, "user", f"m{k}")
    history = cs.get_history(UID)
    assert len(history) == cs.MAX_HISTORY
    assert history[-1]["content"] == f"m{cs.MAX_HISTORY + 4}"
