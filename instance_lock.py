"""
instance_lock.py — prevents more than one BAKA process from running at
once against the same database and bot token.

Sprint 2B (v13.1). Addresses ENGINEERING_AUDIT.md finding D5/ARCH-6:
`run.sh` is a bare crash-loop restarter with no duplicate-instance guard.
Two live instances polling the same bot token would double-fire every
reminder and scheduled job, race on SQLite writes, and duplicate AI
processing — see the audit for the full reasoning.

Locking strategy
-----------------
An advisory file lock via `fcntl.flock(fd, LOCK_EX | LOCK_NB)` on
`bot.pid`, held for the entire process lifetime. This was chosen over a
plain "does bot.pid exist" check specifically because it survives crashes
correctly with no extra logic needed: `flock` is released by the kernel
the instant the holding process's file descriptor closes, which happens
unconditionally when a process dies — clean exit, uncaught exception, or
`kill -9`. A PID-file-existence check alone cannot tell a live instance
apart from a stale file left by a crash without an extra liveness probe
(and even then, PID reuse makes that probe imperfect); `flock` doesn't
have this ambiguity because the OS itself is the source of truth.

`bot.pid` also stores the holding process's PID as plain text, purely for
the diagnostic messages this module prints/logs (which process is running,
which PID was reclaimed after a crash) — the actual lock/block decision
never depends on that stored text, only on whether `flock()` succeeds.

Explicit cleanup (closing the fd, deleting the file) is additionally
registered via `atexit` for a tidy shutdown and clear logging — see
`release()`. This is a courtesy, not the safety mechanism: the safety
guarantee comes from the OS releasing the lock automatically, which is why
this module does not install its own SIGINT/SIGTERM handlers.
`python-telegram-bot`'s `Application.run_polling()` already installs
handlers for SIGINT/SIGTERM/SIGABRT (verified in the installed PTB 20.7
source: they raise `SystemExit`, which PTB catches internally to shut
down gracefully before `run_polling()` returns normally) — installing a
second, competing handler for the same signals risks breaking that
existing graceful-shutdown behavior. `atexit` fires after `run_polling()`
returns from a signal-triggered shutdown, and after both `sys.exit()`
paths already in main.py's `if __name__ == "__main__":` block, so it
covers every voluntary exit path without touching PTB's own signal
handling at all.

Same relative-path convention as the project's other runtime state files
(`planner.db`, `bugs.db`, `admin_id.txt`, `bot.log`) — `bot.pid` is
resolved relative to the process's working directory, matching (not
introducing) an existing, already-documented limitation (see
DEBUGGING.md/ENGINEERING_AUDIT.md finding A3/RB-4).
"""
import atexit
import fcntl
import logging
import os

logger = logging.getLogger(__name__)

LOCK_PATH = "bot.pid"

_lock_fd = None
_lock_path_in_use = None


class InstanceAlreadyRunningError(RuntimeError):
    """Raised when another BAKA process already holds the instance lock."""


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, just owned by someone else
    return True


def acquire(lock_path: str = LOCK_PATH) -> None:
    """Acquire the single-instance lock or raise InstanceAlreadyRunningError.

    Must be called once, as early as possible in startup (before any other
    initialization), so a blocked duplicate instance exits immediately
    without touching the database or the Telegram API.
    """
    global _lock_fd, _lock_path_in_use

    file_existed_before = os.path.exists(lock_path)
    existing_pid = None
    if file_existed_before:
        try:
            with open(lock_path) as f:
                existing_pid = int(f.read().strip())
        except (ValueError, OSError):
            existing_pid = None

    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        holder = f" (PID {existing_pid})" if existing_pid else ""
        logger.critical(f"Another BAKA instance is already running{holder}. Refusing to start.")
        print(f"❌ Another BAKA instance is already running{holder}. Exiting.")
        raise InstanceAlreadyRunningError(holder)

    # Reaching here means flock succeeded. If a lock file already existed,
    # whatever process wrote it is no longer holding the lock -- it either
    # shut down without cleaning up, or crashed. Either way, from this
    # process's perspective the old file was stale; report it clearly.
    if file_existed_before:
        alive_note = "" if existing_pid and _pid_is_alive(existing_pid) else " (process no longer running)"
        who = f"PID {existing_pid}" if existing_pid else "an unreadable/corrupt lock file"
        logger.warning(f"Stale lock from {who}{alive_note} reclaimed — previous instance "
                        f"likely crashed or was killed without cleanup.")
        print(f"⚠️ Stale lock from {who}{alive_note} reclaimed.")

    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    os.fsync(fd)
    _lock_fd = fd
    _lock_path_in_use = lock_path

    logger.info(f"🔒 Instance lock acquired (PID {os.getpid()}, {lock_path}).")
    print(f"🔒 Instance lock acquired (PID {os.getpid()}).")

    atexit.register(release)


def release() -> None:
    """Release the lock and remove the lock file. Safe to call more than
    once (e.g. once explicitly and once again via atexit) and safe to
    call even if the lock was never acquired."""
    global _lock_fd, _lock_path_in_use
    if _lock_fd is None:
        return
    fd = _lock_fd
    path = _lock_path_in_use or LOCK_PATH
    _lock_fd = None
    _lock_path_in_use = None
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        os.close(fd)
    try:
        os.remove(path)
    except OSError:
        pass
    logger.info("🔓 Instance lock released (clean shutdown).")
    print("🔓 Instance lock released.")
