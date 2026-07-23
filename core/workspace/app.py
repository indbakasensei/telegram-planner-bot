"""
app.py -- production wiring for the Workspace OS (v15.0-beta.1).

Integration glue ONLY -- no new engine, repository, or schema. It connects
the completed, flag-dormant Workspace stack into the running bot when
`feature_flags.WORKSPACE` is ON, and is inert (never even constructed) when
OFF, so behaviour stays byte-identical to v14.26.

Three seams:
  * `process_message(user_id, text)` -- the free-text entry point the
    Telegram handler calls when the flag is ON. Runs the AI Orchestrator
    (message -> Interpreter -> Proposal -> Orchestrator -> Entity Engine ->
    Timeline), managing a small confirm/active-workspace state. Returns
    (handled, reply); handled=False means "not a workspace command, let
    Legacy handle it".
  * `SyncWorker` + `register_workers(application)` -- registers a repeating
    job on the EXISTING scheduler that drains the sync outbox (Timeline ->
    Sync Engine -> Telegram) off the event loop, with retries, never
    blocking the bot, and stopping cleanly.
  * `make_telegram_sender(bot, loop)` -- the production sender injected into
    the Telegram adapter, replacing the test sender. The adapter interface
    and the (Telegram-independent) Sync Engine are unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import os

import database
from core import feature_flags
from core.workspace.engine import EntityEngine
from core.workspace.llm_interpreter import LLMInterpreter
from core.workspace.orchestrator import Action, Status, WorkspaceOrchestrator
from core.workspace.sync import SyncEngine
from core.workspace.adapters.telegram import TelegramAdapter
from core.workspace.timeline import TimelineEngine

logger = logging.getLogger(__name__)

_AFFIRM = frozenset({"yes", "y", "yeah", "yep", "confirm", "ok", "okay",
                     "sure", "do it", "go ahead"})
_NEGATE = frozenset({"no", "n", "cancel", "nope", "stop"})

# Per-user conversational glue (NOT a memory redesign -- ephemeral wiring
# state only): a pending utterance awaiting confirmation, and the
# last-touched workspace so follow-ups need no explicit "in <ws>".
_pending: dict[int, str] = {}
_active_ws: dict[int, int] = {}

_ORCHESTRATOR: WorkspaceOrchestrator | None = None


# ── message pipeline ──────────────────────────────────────────────────────
def _default_orchestrator() -> WorkspaceOrchestrator:
    """Build (once) the production orchestrator: the Entity Engine wired to
    the Timeline, driven by the AI LLMInterpreter."""
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        timeline = TimelineEngine()
        engine = EntityEngine(on_event=timeline.record)
        _ORCHESTRATOR = WorkspaceOrchestrator(
            engine=engine, interpreter=LLMInterpreter())
    return _ORCHESTRATOR


def process_message(user_id, text, orchestrator: WorkspaceOrchestrator | None = None):
    """Handle one free-text message through the Workspace OS. Returns
    (handled: bool, reply: str). handled=False => not a workspace command,
    caller should fall through to the Legacy pipeline. `orchestrator` is an
    injection seam for tests (defaults to the production one)."""
    orch = orchestrator or _default_orchestrator()
    t = (text or "").strip()
    low = t.lower()

    # Resolve a pending confirmation first.
    if user_id in _pending:
        pending_text = _pending.pop(user_id)
        if low in _AFFIRM:
            res = orch.handle(user_id, pending_text,
                              active_workspace_id=_active_ws.get(user_id),
                              confirm=True)
            return _reply(user_id, res, pending_text)
        if low in _NEGATE:
            return True, "Okay, cancelled."
        # Not a yes/no -- fall through and treat the message as a new command.

    res = orch.handle(user_id, t, active_workspace_id=_active_ws.get(user_id))
    return _reply(user_id, res, t)


def _reply(user_id, res, utterance):
    if getattr(res, "workspace", None) is not None:
        _active_ws[user_id] = res.workspace.id

    if res.status == Status.APPLIED:
        return True, res.message
    if res.status == Status.NEEDS_CONFIRMATION:
        _pending[user_id] = utterance
        return True, res.message + "\n\nReply “yes” to confirm or “no” to cancel."
    if res.status == Status.NEEDS_CLARIFICATION:
        # An unrecognized utterance is not a workspace command -> Legacy.
        if res.proposal is not None and res.proposal.action == Action.UNKNOWN:
            return False, ""
        msg = res.message
        if res.options:
            msg += "\n" + "\n".join(f"• {o}" for o in res.options)
        return True, msg
    # REJECTED / FAILED
    return True, res.message


def reset_state():
    """Clear ephemeral per-user glue + the cached orchestrator (tests)."""
    global _ORCHESTRATOR
    _pending.clear()
    _active_ws.clear()
    _ORCHESTRATOR = None


# ── production Telegram sender ─────────────────────────────────────────────
def make_telegram_sender(bot, loop, timeout=30):
    """A synchronous sender for the Telegram adapter that safely calls the
    async bot from the worker thread (via the running event loop). The
    adapter interface (sender(user_id, text, target_id) -> ref) is
    unchanged; the Sync Engine remains Telegram-independent."""
    def sender(user_id, text, target_id=None):
        kwargs = {"chat_id": user_id, "text": text, "parse_mode": "HTML"}
        if target_id is not None:
            kwargs["message_thread_id"] = target_id
        future = asyncio.run_coroutine_threadsafe(bot.send_message(**kwargs), loop)
        msg = future.result(timeout=timeout)
        return getattr(msg, "message_id", None)
    return sender


def build_sync_engine(sender) -> SyncEngine:
    """A Sync Engine with the Telegram adapter as its only target. The
    engine knows nothing about Telegram -- only the SyncAdapter contract."""
    return SyncEngine(adapters=[TelegramAdapter(sender)])


# ── background worker ──────────────────────────────────────────────────────
def worker_user_ids():
    """Users the sync worker drains for: everyone with data, plus the
    configured owner. Uses only existing infrastructure."""
    ids = set()
    try:
        ids.update(database.get_all_user_ids())
    except Exception:
        logger.exception("worker_user_ids: get_all_user_ids failed")
    owner = os.getenv("OWNER_ID", "")
    if owner.strip().isdigit():
        ids.add(int(owner.strip()))
    return ids


class SyncWorker:
    """One drain pass over the sync outbox for a set of users. Stateless
    apart from a stop flag; a failed user never aborts the pass, and once
    stopped it no-ops (clean shutdown)."""

    def __init__(self, sync_engine: SyncEngine, user_ids_fn=worker_user_ids):
        self._engine = sync_engine
        self._user_ids_fn = user_ids_fn
        self._stopped = False

    def stop(self):
        self._stopped = True

    @property
    def stopped(self) -> bool:
        return self._stopped

    def run_once(self) -> dict:
        """Enqueue backlog + drain for every user, once. Returns a report;
        never raises (per-user failures are logged and skipped)."""
        if self._stopped:
            return {"stopped": True, "users": 0, "sent": 0, "failed": 0}
        report = {"stopped": False, "users": 0, "sent": 0, "failed": 0}
        for uid in self._user_ids_fn():
            if self._stopped:               # graceful mid-pass shutdown
                report["stopped"] = True
                break
            try:
                r = self._engine.sync(uid)
                report["sent"] += r.get("sent", 0)
                report["failed"] += r.get("failed", 0)
                report["users"] += 1
            except Exception:
                logger.exception("workspace sync failed for user %s", uid)
        return report


async def _sync_worker_job(context):
    """Scheduler callback: drain the outbox off the event loop so a slow
    send never blocks the bot. Guarded by the flag so a stray registration
    is inert when OFF."""
    if not feature_flags.WORKSPACE:
        return
    try:
        loop = asyncio.get_running_loop()
        sender = make_telegram_sender(context.bot, loop)
        worker = SyncWorker(build_sync_engine(sender))
        await asyncio.to_thread(worker.run_once)
    except Exception:
        logger.exception("workspace sync worker pass failed")


def register_workers(application, interval=30, first=15) -> bool:
    """Register the sync-drain job on the EXISTING scheduler, but ONLY when
    WORKSPACE is ON. When OFF this registers nothing, so the job set is
    identical to v14.26. Returns whether it registered."""
    if not feature_flags.WORKSPACE:
        return False
    application.job_queue.run_repeating(
        _sync_worker_job, interval=interval, first=first, name="workspace_sync")
    logger.info("Workspace sync worker registered (interval=%ss).", interval)
    return True
