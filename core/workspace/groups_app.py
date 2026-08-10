"""
groups_app.py -- use-case layer for "Workspace groups" (v15.1): the usable
feature that projects workspaces/entities onto private Telegram forum groups.

main.py's command + photo handlers call these functions; they orchestrate
the (Telegram-agnostic) Entity Engine, note/attachment persistence via the
Storage Facade, the per-user active context, and -- for anything that
touches Telegram -- an injected `TelegramProjection` (so this stays
offline-testable with a fake client).

Mapping (see projection.py): workspace ⇒ group, entity ⇒ topic, note/photo ⇒
message in that topic (or the General topic when no entity is active).
"""
from __future__ import annotations

from dataclasses import dataclass

from core.storage import Storage
from core.workspace.engine import EntityEngine
from core.workspace.render import format_entity_card

# Friendly command name → workspace template.
KIND_TEMPLATE = {
    "project": "project", "game": "game",
    "goal": "generic", "workspace": "generic",
}
ENTITY_TYPE = "milestone"   # a workspace entity is a milestone under the hood


@dataclass(frozen=True, slots=True)
class ActiveContext:
    workspace_id: int | None
    workspace_title: str | None
    entity_id: int | None
    entity_title: str | None
    linked: bool


@dataclass(frozen=True, slots=True)
class LogResult:
    ok: bool
    reason: str = ""
    note_id: int | None = None
    posted: bool = False
    topic_id: int | None = None
    workspace_title: str | None = None
    entity_title: str | None = None


class WorkspaceGroups:
    def __init__(self, storage: Storage | None = None, engine: EntityEngine | None = None):
        self._s = storage or Storage()
        self._eng = engine or EntityEngine()

    # ── creation / navigation (no Telegram) ────────────
    def create(self, user_id, kind, title):
        """Create a workspace of a friendly kind and make it active."""
        template = KIND_TEMPLATE.get(kind, "generic")
        ws = self._eng.create_workspace(user_id, title, template=template)
        self._s.tg_bindings.set_active(user_id, ws.id)
        return ws

    def list_workspaces(self, user_id):
        return self._eng.list_workspaces(user_id)

    def has_active(self, user_id) -> bool:
        """Fast check (one indexed read) for whether the user has an active
        workspace -- used by the photo hook to decide whether a photo is a
        progress log."""
        a = self._s.tg_bindings.get_active(user_id)
        return bool(a and a[0] is not None)

    def open_workspace(self, user_id, ref):
        ws = self._resolve_workspace(user_id, ref)
        if ws is None:
            return None
        self._s.tg_bindings.set_active(user_id, ws.id)   # clears active entity
        return ws

    def add_entity(self, user_id, name, projection=None):
        """Add an entity to the ACTIVE workspace (the /add command path):
        create it, ensure its Telegram topic (+ initial card on a new topic),
        and make it the active entity. Returns (milestone, topic_id)."""
        active = self._s.tg_bindings.get_active(user_id)
        if not active or active[0] is None:
            return None, None
        return self.create_entity(user_id, active[0], name, projection)

    def create_entity(self, user_id, ws_id, name, projection=None):
        """The single entity/projection contract: create the milestone, ensure
        its Telegram topic (posting the current entity card into a NEWLY
        created topic), and make it the active entity. Returns
        (milestone, topic_id).

        Every path that creates an entity which may carry a Telegram topic --
        /add, natural-language creation -- goes through this same contract, so
        there is exactly one entity-creation + topic-creation sequence
        (engine.add_milestone + projection.ensure_entity_topic). Re-running is
        safe: ensure_entity_topic is idempotent and never duplicates a topic
        or an initial card. Does NOT check duplicate titles -- callers that
        need a guard keep their own."""
        m = self._eng.add_milestone(user_id, ws_id, name)
        topic_id = None
        if projection is not None:
            topic_id = projection.ensure_entity_topic(
                user_id, ws_id, ENTITY_TYPE, m.id, m.title,
                initial_message=format_entity_card(m, with_timestamp=True))
        self._s.tg_bindings.set_active(user_id, ws_id, ENTITY_TYPE, m.id)
        return m, topic_id

    def backfill_topics(self, user_id, projection) -> dict:
        """Ensure a Telegram topic + initial card for EVERY non-deleted entity
        in every of the user's Telegram-linked workspaces. Generic -- it
        operates on whatever workspaces/bindings exist, never hardcoding a
        domain or entity list.

        Idempotent: entities that already have a binding are untouched (their
        initial card is NOT re-posted); re-running creates nothing. Unlinked
        workspaces are reported linked:False and trigger no Telegram call.
        Soft-deleted entities are excluded (list_milestones). No entity,
        field, or existing binding is ever modified -- only missing
        tg_entity_topics rows (+ a fresh Telegram topic) are added.

        Returns {workspace_id: {title, linked, created[], existing[],
        errors[]}} so the caller can report exactly what happened."""
        report = {}
        for ws in self._eng.list_workspaces(user_id):
            if self._s.tg_bindings.get_binding(ws.id) is None:
                report[ws.id] = {"title": ws.title, "linked": False}
                continue
            created, existing, errors = [], [], []
            for m in self._eng.list_milestones(user_id, ws.id):
                had = self._s.tg_bindings.get_entity_topic(ENTITY_TYPE, m.id)
                try:
                    topic_id = projection.ensure_entity_topic(
                        user_id, ws.id, ENTITY_TYPE, m.id, m.title,
                        initial_message=format_entity_card(
                            m, with_timestamp=True))
                except Exception as exc:
                    errors.append(f"{m.title}: {type(exc).__name__}: {exc}")
                    continue
                if topic_id is None:
                    continue
                if had is None:
                    created.append(m.title)
                else:
                    existing.append(m.title)
            report[ws.id] = {
                "title": ws.title, "linked": True,
                "created": created, "existing": existing, "errors": errors,
            }
        return report

    def open_entity(self, user_id, ref):
        active = self._s.tg_bindings.get_active(user_id)
        if not active or active[0] is None:
            return None
        ws_id = active[0]
        m = self._resolve_entity(user_id, ws_id, ref)
        if m is None:
            return None
        self._s.tg_bindings.set_active(user_id, ws_id, ENTITY_TYPE, m.id)
        return m

    def current(self, user_id) -> ActiveContext:
        active = self._s.tg_bindings.get_active(user_id)
        if not active or active[0] is None:
            return ActiveContext(None, None, None, None, False)
        ws_id, _etype, eid = active
        ws = self._eng.get_workspace_or_none(user_id, ws_id)
        linked = self._s.tg_bindings.get_binding(ws_id) is not None
        entity_title = None
        if eid is not None:
            m = self._find_milestone(user_id, ws_id, eid)
            entity_title = m.title if m else None
        return ActiveContext(
            ws_id, ws.title if ws else None, eid, entity_title, linked)

    # ── Telegram-touching ──────────────────────────────
    def link_group(self, user_id, chat_id, projection):
        """Link the active workspace to the Telegram group `chat_id`."""
        active = self._s.tg_bindings.get_active(user_id)
        if not active or active[0] is None:
            return None
        ws_id = active[0]
        projection.link_group(user_id, ws_id, chat_id)
        return self._eng.get_workspace_or_none(user_id, ws_id)

    def log_progress(self, user_id, text, projection, photo_file_id=None) -> LogResult:
        """Persist a progress note (+ optional photo) against the active
        workspace/entity and post it to the matching Telegram topic."""
        active = self._s.tg_bindings.get_active(user_id)
        if not active or active[0] is None:
            return LogResult(False, reason="no_active")
        ws_id, etype, eid = active
        ws = self._eng.get_workspace_or_none(user_id, ws_id)
        if ws is None:
            return LogResult(False, reason="no_active")

        body = (text or "").strip() or "(photo)"
        note_id = self._s.notes.add(ws_id, body, kind="progress", milestone_id=eid)
        if photo_file_id:
            self._s.notes.add_attachment(ws_id, note_id, photo_file_id,
                                         file_type="photo", caption=text)

        entity_title = None
        if eid is not None:
            m = self._find_milestone(user_id, ws_id, eid)
            entity_title = m.title if m else None

        result = projection.post_note(
            user_id, ws_id, body, entity_type=etype or ENTITY_TYPE,
            entity_id=eid, entity_title=entity_title, photo_file_id=photo_file_id)
        return LogResult(
            ok=True, note_id=note_id, posted=result.ok, topic_id=result.topic_id,
            workspace_title=ws.title, entity_title=entity_title)

    # ── resolution helpers ─────────────────────────────
    def _resolve_workspace(self, user_id, ref):
        ref = str(ref).strip()
        wss = self._eng.list_workspaces(user_id, status=None)
        if ref.isdigit():
            wid = int(ref)
            return next((w for w in wss if w.id == wid), None)
        low = ref.lower()
        exact = [w for w in wss if w.title.lower() == low]
        if exact:
            return exact[0]
        partial = [w for w in wss if low in w.title.lower()]
        return partial[0] if len(partial) == 1 else None

    def _resolve_entity(self, user_id, ws_id, ref):
        ref = str(ref).strip()
        ms = self._eng.list_milestones(user_id, ws_id)
        if ref.isdigit():
            mid = int(ref)
            return next((m for m in ms if m.id == mid), None)
        low = ref.lower()
        exact = [m for m in ms if m.title.lower() == low]
        if exact:
            return exact[0]
        partial = [m for m in ms if low in m.title.lower()]
        return partial[0] if len(partial) == 1 else None

    def _find_milestone(self, user_id, ws_id, mid):
        return next((m for m in self._eng.list_milestones(user_id, ws_id)
                     if m.id == mid), None)
