"""
Tests for core/feature_flags.py -- v14.1C's Offline Engine rollout flags.

Two levels: the `_flag()` helper directly (fast, exhaustive over truthy/
falsy spellings), and the actual module-level constants via importlib.reload
(proving the real, exported names pick up the environment at import time --
not just that the helper function works in isolation).
"""
import importlib

import pytest

import core.feature_flags as feature_flags


# ── _flag() helper ────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "YES", "on", "On"])
def test_flag_helper_recognizes_truthy_spellings(monkeypatch, value):
    monkeypatch.setenv("TEST_FLAG_X", value)
    assert feature_flags._flag("TEST_FLAG_X") is True


@pytest.mark.parametrize("value", ["0", "false", "False", "no", "off", "", "garbage"])
def test_flag_helper_recognizes_falsy_spellings(monkeypatch, value):
    monkeypatch.setenv("TEST_FLAG_X", value)
    assert feature_flags._flag("TEST_FLAG_X") is False


def test_flag_helper_defaults_off_when_unset(monkeypatch):
    monkeypatch.delenv("TEST_FLAG_UNSET", raising=False)
    assert feature_flags._flag("TEST_FLAG_UNSET") is False


# ── Exported constants: default state ────────────────────────────────────

def test_all_flags_default_off_when_unset(monkeypatch):
    for name in ("OFFLINE_TASKS", "OFFLINE_HABITS", "OFFLINE_GOALS", "OFFLINE_PROJECTS"):
        monkeypatch.delenv(name, raising=False)
    reloaded = importlib.reload(feature_flags)
    assert reloaded.OFFLINE_TASKS is False
    assert reloaded.OFFLINE_HABITS is False
    assert reloaded.OFFLINE_GOALS is False
    assert reloaded.OFFLINE_PROJECTS is False
    importlib.reload(feature_flags)  # restore a clean module for later tests


# ── Exported constants: env override at import time ──────────────────────

def test_flag_picks_up_env_var_at_import_time(monkeypatch):
    monkeypatch.setenv("OFFLINE_TASKS", "true")
    monkeypatch.delenv("OFFLINE_HABITS", raising=False)
    monkeypatch.delenv("OFFLINE_GOALS", raising=False)
    monkeypatch.delenv("OFFLINE_PROJECTS", raising=False)
    reloaded = importlib.reload(feature_flags)
    try:
        assert reloaded.OFFLINE_TASKS is True
        assert reloaded.OFFLINE_HABITS is False
    finally:
        monkeypatch.delenv("OFFLINE_TASKS", raising=False)
        importlib.reload(feature_flags)  # restore a clean module for later tests
