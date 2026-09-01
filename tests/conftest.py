"""
Shared pytest fixtures for BAKA's test suite.

Everything here runs fully offline: no Telegram, no NVIDIA API, no network,
and never touches the real planner.db/bugs.db. Database tests use a fresh
temporary SQLite file per test (see `temp_db`), monkeypatched into both
database.py and scheduler.py's module-level DB_NAME, since both modules
open their own `sqlite3.connect(DB_NAME)` per call rather than sharing a
connection.
"""
import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db
import scheduler as sched


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """A fresh, fully-initialized temporary database for one test.

    Patches database.py's and scheduler.py's DB_NAME so every function in
    both modules transparently operates on the temp file instead of
    planner.db. Cleans up any backups/ directory the test's init_db()
    calls create.
    """
    db_path = str(tmp_path / "test_planner.db")
    monkeypatch.setattr(db, "DB_NAME", db_path)
    monkeypatch.setattr(sched, "DB_NAME", db_path)
    db.init_db()
    yield db_path
    backups_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)) or ".", "backups")
    if os.path.isdir(backups_dir):
        shutil.rmtree(backups_dir, ignore_errors=True)


@pytest.fixture
def raw_db_path(monkeypatch, tmp_path):
    """Like temp_db, but does NOT call init_db() -- for tests that need
    to control that call themselves (e.g. asserting what happens on the
    very first init_db() call against a brand-new path)."""
    db_path = str(tmp_path / "test_planner.db")
    monkeypatch.setattr(db, "DB_NAME", db_path)
    monkeypatch.setattr(sched, "DB_NAME", db_path)
    yield db_path
    backups_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)) or ".", "backups")
    if os.path.isdir(backups_dir):
        shutil.rmtree(backups_dir, ignore_errors=True)


@pytest.fixture
def uid():
    """A representative user_id for tests that need one."""
    return 555000111

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
IST = ZoneInfo('Asia/Kolkata')

@pytest.fixture
def now():
    '''Injected deterministic now fixture.'''
    return datetime(2026, 8, 24, 10, 0, tzinfo=IST)

@pytest.fixture(autouse=True)
def freeze_clock(monkeypatch, now):
    '''Freeze the system clock to the exact NOW datetime used across test
    contexts.'''
    import date_parser
    monkeypatch.setattr(date_parser, '_now', lambda: now)

@pytest.fixture(autouse=True)
def disable_runner_db_patch(monkeypatch):
    # selftest.run() deletes sys.modules['database'] which causes catastrophic
    # split-brain bugs in pytest because modules imported earlier hold old refs.
    # We disable it globally here since pytest temp_db already isolates everything.
    from core.selftest import runner
    monkeypatch.setattr(runner, '_setup_temp_db', lambda: None)
