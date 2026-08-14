"""
storage.py -- Storage Facade: minimum infrastructure required for the
Offline Engine (v14.1C).

Phase 0 review (see commit message / CHANGELOG.md's v14.1C entry) chose a
thin Facade over a formal Repository Layer: OFFLINE_ENGINE.md already
established that the Offline Engine should not get its own data-access
layer ("database.py's functions are already pure, already tested... and
already used exactly this way by every non-AI handler in main.py today"),
and nothing in the approved architecture calls for a swappable storage
backend. This module exists purely to give the (not-yet-built) Offline
Engine a domain-shaped entry point -- TaskStorage.add(...) instead of a
flat import list -- without adding a new abstraction over database.py.

Hard rules, enforced by construction, not just by convention:
- No SQL of any kind lives here -- every method is a one-line delegation
  to an existing database.py function.
- No business logic, no return-value reshaping, no validation beyond
  what database.py's functions already do -- a Storage Facade method's
  return value is byte-for-byte whatever the delegated-to function
  returns.
- Nothing in this module is imported or called from anywhere yet (no
  Offline Engine exists to call it) -- see DEBUGGING.md's "Storage Facade
  and feature flags are introduced but not yet consumed" entry.
"""
from __future__ import annotations

import database


class TaskStorage:
    """Delegates to database.py's task functions. See database.py for
    the authoritative signatures and behavior -- this class adds no
    logic of its own."""

    def add(self, user_id, title, due_date=None, due_time=None,
            category='General', priority='medium', recurrence_type=None,
            recurrence_weekday=None, recurrence_day=None):
        return database.add_task(
            user_id, title, due_date, due_time, category, priority,
            recurrence_type, recurrence_weekday, recurrence_day,
        )

    def get_all(self, user_id, done=0):
        return database.get_tasks(user_id, done)

    def get_by_date(self, user_id, date):
        return database.get_tasks_by_date(user_id, date)

    def get_by_week(self, user_id, start_date, end_date):
        return database.get_tasks_by_week(user_id, start_date, end_date)

    def get_by_id(self, task_id, user_id):
        return database.get_task_by_id(task_id, user_id)

    def search_by_title(self, user_id, keyword):
        return database.search_tasks_by_title(user_id, keyword)

    def mark_done(self, task_id, user_id):
        return database.mark_done(task_id, user_id)

    def delete(self, task_id, user_id):
        return database.delete_task(task_id, user_id)

    def update(self, task_id, user_id, title=None, due_date=None,
               due_time=None, category=None, priority=None):
        return database.update_task(
            task_id, user_id, title, due_date, due_time, category, priority,
        )

    def exists(self, user_id, title, due_date):
        return database.task_exists(user_id, title, due_date)

    def mark_as_deadline(self, task_id, user_id, is_deadline=True):
        return database.mark_as_deadline(task_id, user_id, is_deadline)

    def pause(self, task_id, user_id):
        return database.pause_task(task_id, user_id)

    def resume(self, task_id, user_id):
        return database.resume_task(task_id, user_id)

    def snooze(self, task_id, user_id, snooze_until):
        return database.snooze_task(task_id, user_id, snooze_until)

    def stop_reminders(self, task_id, user_id):
        return database.stop_reminders(task_id, user_id)

    def get_paused(self, user_id):
        return database.get_paused_tasks(user_id)

    def carry_forward_overdue(self, user_id, current_date):
        return database.carry_forward_overdue(user_id, current_date)


class HabitStorage:
    """Delegates to database.py's habit functions (habits are recurring
    tasks with is_habit=1 -- database.py's own representation, unchanged
    here)."""

    def add(self, user_id, title, time=None, recurrence="daily",
            recurrence_weekday=None, category="Health", priority="medium"):
        return database.add_habit(
            user_id, title, time, recurrence, recurrence_weekday,
            category, priority,
        )

    def get_all(self, user_id):
        return database.get_habits(user_id)

    def is_habit(self, task_id):
        return database.is_habit(task_id)

    def log_completion(self, habit_id, user_id, log_date=None):
        return database.log_habit_completion(habit_id, user_id, log_date)

    def get_log(self, habit_id, user_id, days=30):
        return database.get_habit_log(habit_id, user_id, days)

    def get_missed_days(self, habit_id, user_id, days=30):
        return database.get_missed_days(habit_id, user_id, days)

    def reset_streak(self, habit_id):
        return database.reset_streak(habit_id)


class GoalStorage:
    """Delegates to database.py's goal functions."""

    def add(self, user_id, title, deadline=None):
        return database.add_goal(user_id, title, deadline)

    def get_all(self, user_id):
        return database.get_goals(user_id)

    def get_all_full(self, user_id):
        return database.get_goals_full(user_id)

    def update_progress(self, goal_id, user_id, delta):
        return database.update_goal_progress(goal_id, user_id, delta)

    def update_deadline(self, goal_id, user_id, deadline):
        """v15.2 M4: the goal domain owns deadlines -- a deadline request
        must never reach a workspace entity (DEBUGGING.md F6/F7)."""
        return database.update_goal_deadline(goal_id, user_id, deadline)


class MemoryStorage:
    """Delegates to database.py's memory (key/value fact) functions.
    Added by v15.2 M3 so the memory/recall tool adapters read through the
    same facade every other domain uses -- no raw database.py calls from the
    tools, and no new data-access layer."""

    def save(self, user_id, key, value):
        return database.save_memory(user_id, key, value)

    def get(self, user_id, key):
        return database.get_memory(user_id, key)

    def get_all(self, user_id):
        return database.get_all_memories(user_id)

    def search(self, user_id, query):
        return database.search_memories(user_id, query)

    def search_smart(self, user_id, query):
        return database.search_memories_smart(user_id, query)

    def delete(self, user_id, key):
        return database.delete_memory(user_id, key)


class ProjectStorage:
    """Delegates to database.py's project (materials + worklog) functions.
    Projects are goals extended with materials/worklog data -- database.py's
    own model (docs/database.md), unchanged here."""

    def add_materials(self, user_id, goal_id, names, quantity=1):
        return database.add_materials(user_id, goal_id, names, quantity)

    def get_materials(self, user_id, goal_id):
        return database.get_materials(user_id, goal_id)

    def mark_material_acquired(self, user_id, material_id, acquired=True):
        return database.mark_material_acquired(user_id, material_id, acquired)

    def delete_material(self, user_id, material_id):
        return database.delete_material(user_id, material_id)

    def find_material_by_name(self, user_id, keyword, goal_id=None):
        return database.find_material_by_name(user_id, keyword, goal_id)

    def add_worklog(self, user_id, goal_id, entry, kind="note"):
        return database.add_worklog(user_id, goal_id, entry, kind)

    def get_worklog(self, user_id, goal_id, limit=20):
        return database.get_worklog(user_id, goal_id, limit)

    def get_last_worklog_days(self, user_id, goal_id):
        return database.get_last_worklog_days(user_id, goal_id)

    def compute_progress(self, user_id, goal_id):
        return database.compute_project_progress(user_id, goal_id)

    def get_overview(self, user_id, goal_id):
        return database.get_project_overview(user_id, goal_id)

    def get_active(self, user_id):
        return database.get_active_projects(user_id)

    def get_all_pending_materials(self, user_id):
        return database.get_all_pending_materials(user_id)


class LearningStorage:
    """Delegates to database.py's preference-learning log functions
    (v6.0's completions_log/interaction_log tables). Added v14.6 because
    Legacy's task-completion path (main.py's done_task()) writes to both
    as a side effect, and Offline Task Completion must replicate that for
    genuine behavioral equivalence -- see core/actions/complete_task.py."""

    def log_completion(self, user_id, task_id, title, category,
                       scheduled_time, completed_at, delay_minutes=0):
        return database.log_completion(
            user_id, task_id, title, category,
            scheduled_time, completed_at, delay_minutes,
        )

    def log_interaction(self, user_id, action):
        return database.log_interaction(user_id, action)

    def log_snooze(self, user_id, task_id, title, category, snooze_minutes):
        return database.log_snooze(user_id, task_id, title, category, snooze_minutes)


class WorkspaceStorage:
    """Delegates to database.py's Workspace Foundation functions
    (v15.0-alpha.1). Like every other facade domain: one-line passthrough,
    no logic, returns exactly what database.py returns (raw tuples -- the
    Repository is what maps them to models). Dormant until
    feature_flags.WORKSPACE is on; nothing in v14 calls it."""

    def create(self, user_id, title, template="generic", icon=None,
               metadata=None, sort_order=0):
        return database.create_workspace(
            user_id, title, template, icon, metadata, sort_order)

    def get(self, workspace_id, user_id):
        return database.get_workspace(workspace_id, user_id)

    def list(self, user_id, status="active"):
        return database.get_workspaces(user_id, status)

    def get_by_title(self, user_id, title):
        return database.get_workspace_by_title(user_id, title)

    def update(self, workspace_id, user_id, **fields):
        return database.update_workspace(workspace_id, user_id, **fields)

    def archive(self, workspace_id, user_id):
        return database.archive_workspace(workspace_id, user_id)

    def ensure_default(self, user_id, title="Inbox", template="generic"):
        return database.ensure_default_workspace(user_id, title, template)

    def migrate_projects(self, user_id):
        return database.migrate_projects_to_workspaces(user_id)

    # ── Project<->Workspace bridge (v15.0-alpha.3) ──
    def goal_id_for(self, workspace_id, user_id):
        return database.get_workspace_goal_id(user_id, workspace_id)

    def workspace_id_for_goal(self, goal_id, user_id):
        return database.get_goal_workspace_id(user_id, goal_id)

    def link_goal(self, user_id, goal_id, workspace_id):
        return database.set_goal_workspace(user_id, goal_id, workspace_id)

    def verify_migration(self, user_id):
        return database.verify_project_migration(user_id)


class MilestoneStorage:
    """Delegates to database.py's milestone functions (v15.0-alpha.1)."""

    def add(self, workspace_id, title, goal_id=None, sort_order=0, fields=None,
            entity_type=None):
        """Add a milestone, optionally with structured entity fields.
        v15.1.0-alpha.9: accepts `fields` dict. v15.2 M4: accepts the
        per-entity kind `entity_type`."""
        return database.add_milestone(workspace_id, title, goal_id, sort_order,
                                      fields, entity_type)

    def get(self, milestone_id):
        return database.get_milestone(milestone_id)

    def list_for(self, workspace_id, include_archived=False):
        return database.get_milestones(workspace_id, include_archived)

    def update(self, milestone_id, status=None, progress=None, title=None):
        return database.update_milestone(milestone_id, status, progress, title)

    def soft_delete(self, milestone_id):
        return database.soft_delete_milestone(milestone_id)

    def counts(self, workspace_id):
        return database.count_milestones(workspace_id)

    # v15.1.0-alpha.9: structured entity field passthroughs.
    def set_fields(self, milestone_id, fields):
        """Store structured entity fields (dict) against a milestone."""
        return database.set_milestone_fields(milestone_id, fields)

    def get_fields(self, milestone_id):
        """Return a milestone's structured entity fields dict."""
        return database.get_milestone_fields(milestone_id)

    # v15.2 M4 canonical binding: adopt an entity kind on an existing row.
    def update_entity_type(self, milestone_id, entity_type):
        return database.update_milestone_entity_type(milestone_id, entity_type)


class NoteStorage:
    """Delegates to database.py's note (knowledge) functions. v15.0-alpha.1
    shipped add/list/attachment; v15.4 M6 adds full CRUD, search, and the
    many-to-many entity/tag junctions (spec §3, §4, §5)."""

    def add(self, workspace_id, content, kind="note", milestone_id=None,
            source="user", title=None):
        return database.add_note(workspace_id, content, kind, milestone_id,
                                 source, title)

    def list_for(self, workspace_id, kind=None):
        return database.get_notes(workspace_id, kind)

    def get(self, note_id):
        return database.get_note(note_id)

    def update(self, note_id, content=None, title=None, kind=None):
        return database.update_note(note_id, content, title, kind)

    def soft_delete(self, note_id):
        return database.soft_delete_note(note_id)

    def search(self, workspace_id, q=None, kind=None, entity_type=None,
               entity_id=None, tag_id=None, created_after=None,
               created_before=None, limit=50):
        return database.search_notes(
            workspace_id, q, kind, entity_type, entity_id, tag_id,
            created_after, created_before, limit)

    def link_entity(self, note_id, entity_type, entity_id):
        return database.link_note_entity(note_id, entity_type, entity_id)

    def unlink_entity(self, note_id, entity_type, entity_id):
        return database.unlink_note_entity(note_id, entity_type, entity_id)

    def entities(self, note_id):
        return database.get_note_entities(note_id)

    def ids_for_entity(self, entity_type, entity_id):
        return database.get_notes_for_entity(entity_type, entity_id)

    def link_tag(self, note_id, tag_id):
        return database.link_note_tag(note_id, tag_id)

    def unlink_tag(self, note_id, tag_id):
        return database.unlink_note_tag(note_id, tag_id)

    def tags(self, note_id):
        return database.get_note_tags(note_id)

    def add_attachment(self, workspace_id, note_id, telegram_file_id,
                       file_type="photo", file_name=None, caption=None,
                       message_id=None, chat_id=None, topic_id=None,
                       entity_type=None, entity_id=None, extracted_text=None):
        return database.add_attachment(
            workspace_id, note_id, telegram_file_id, file_type, file_name,
            caption, message_id, chat_id, topic_id, entity_type, entity_id,
            extracted_text)

    def attachments(self, workspace_id, note_id=None):
        return database.get_attachments(workspace_id, note_id)


class AttachmentStorage:
    """Delegates to database.py's media-metadata functions (v15.4 M6).
    SQLite stores metadata + Telegram identifiers ONLY; the binary blob
    stays in Telegram (spec §3)."""

    def add(self, workspace_id, note_id=None, telegram_file_id=None,
            file_type="photo", file_name=None, caption=None, message_id=None,
            chat_id=None, topic_id=None, entity_type=None, entity_id=None,
            extracted_text=None):
        return database.add_attachment(
            workspace_id, note_id, telegram_file_id, file_type, file_name,
            caption, message_id, chat_id, topic_id, entity_type, entity_id,
            extracted_text)

    def get(self, attachment_id):
        return database.get_attachment(attachment_id)

    def update(self, attachment_id, caption=None, file_name=None,
               extracted_text=None):
        return database.update_attachment(attachment_id, caption, file_name,
                                          extracted_text)

    def soft_delete(self, attachment_id):
        return database.soft_delete_attachment(attachment_id)

    def search(self, workspace_id, q=None, media_type=None, entity_type=None,
               entity_id=None, tag_id=None, created_after=None,
               created_before=None, limit=50):
        return database.search_attachments(
            workspace_id, q, media_type, entity_type, entity_id, tag_id,
            created_after, created_before, limit)

    def list_for(self, workspace_id, note_id=None):
        return database.get_attachments(workspace_id, note_id)

    def link_entity(self, attachment_id, entity_type, entity_id):
        return database.link_attachment_entity(attachment_id, entity_type,
                                               entity_id)

    def unlink_entity(self, attachment_id, entity_type, entity_id):
        return database.unlink_attachment_entity(attachment_id, entity_type,
                                                 entity_id)

    def entities(self, attachment_id):
        return database.get_attachment_entities(attachment_id)

    def ids_for_entity(self, entity_type, entity_id):
        return database.get_attachments_for_entity(entity_type, entity_id)

    def link_tag(self, attachment_id, tag_id):
        return database.link_attachment_tag(attachment_id, tag_id)

    def unlink_tag(self, attachment_id, tag_id):
        return database.unlink_attachment_tag(attachment_id, tag_id)

    def tags(self, attachment_id):
        return database.get_attachment_tags(attachment_id)


class TagStorage:
    """Delegates to database.py's tag functions (v15.4 M6 — activates the
    dormant v15.0 `tags`/`entity_tags` schema). Tags are user-scoped AND
    workspace-scoped; the same name in two workspaces stays distinct."""

    def resolve(self, user_id, workspace_id, name):
        return database.resolve_tag(user_id, workspace_id, name)

    def create(self, user_id, workspace_id, name):
        return database.create_tag(user_id, workspace_id, name)

    def get(self, tag_id):
        return database.get_tag(tag_id)

    def list_for(self, user_id, workspace_id):
        return database.get_tags(user_id, workspace_id)

    def rename(self, tag_id, name):
        return database.rename_tag(tag_id, name)

    def delete(self, tag_id):
        return database.delete_tag(tag_id)

    def links(self, tag_id):
        return database.get_tag_links(tag_id)

    def for_target(self, entity_type, entity_id):
        return database.get_tags_for_target(entity_type, entity_id)

    def for_entity(self, entity_type, entity_id):
        return database.get_tags_for_entity(entity_type, entity_id)


class TimelineStorage:
    """Delegates to database.py's append-only Knowledge Timeline functions
    (v15.0-alpha.5). One-line passthrough like every other domain."""

    def add(self, user_id, event_type, summary, entity_type=None,
            entity_id=None, workspace_id=None, payload=None, source="user"):
        return database.add_timeline_event(
            user_id, event_type, summary, entity_type, entity_id,
            workspace_id, payload, source)

    def list_for_user(self, user_id, workspace_id=None, limit=50):
        return database.get_timeline(user_id, workspace_id, limit)

    def list_for_entity(self, entity_type, entity_id, limit=50):
        return database.get_entity_timeline(entity_type, entity_id, limit)

    def count(self, user_id, workspace_id=None):
        return database.count_timeline(user_id, workspace_id)

    def unsynced(self, user_id, limit=100):
        return database.get_unsynced_timeline(user_id, limit)

    def mark_synced(self, event_id, synced_at=None):
        return database.mark_timeline_synced(event_id, synced_at)


class SyncStorage:
    """Delegates to database.py's sync-outbox functions (v15.0-alpha.6).
    One-line passthrough like every other domain."""

    def enqueue(self, user_id, adapter, payload, timeline_event_id=None,
                workspace_id=None, target_id=None):
        return database.enqueue_sync(user_id, adapter, payload,
                                     timeline_event_id, workspace_id, target_id)

    def exists(self, timeline_event_id, adapter):
        return database.sync_outbox_exists(timeline_event_id, adapter)

    def pending(self, user_id, limit=100):
        return database.get_pending_sync(user_id, limit)

    def get(self, outbox_id):
        return database.get_sync_row(outbox_id)

    def mark_sent(self, outbox_id, ref=None):
        return database.mark_sync_sent(outbox_id, ref)

    def mark_retry(self, outbox_id, error):
        return database.mark_sync_retry(outbox_id, error)

    def mark_failed(self, outbox_id, error):
        return database.mark_sync_failed(outbox_id, error)

    def remaining_for_event(self, timeline_event_id):
        return database.sync_remaining_for_event(timeline_event_id)

    def count(self, user_id, status=None):
        return database.count_sync(user_id, status)


class TelegramBindingStorage:
    """Delegates to database.py's Telegram-adapter binding functions
    (v15.1). One-line passthrough. These map Workspace entities to Telegram
    groups/topics and hold the user's active context -- read only by the
    Telegram projection adapter, never by the Workspace OS."""

    def link_workspace(self, user_id, workspace_id, chat_id, general_topic_id=None):
        return database.tg_link_workspace(user_id, workspace_id, chat_id, general_topic_id)

    def get_binding(self, workspace_id):
        return database.tg_get_binding(workspace_id)

    def workspace_for_chat(self, chat_id):
        return database.tg_get_workspace_for_chat(chat_id)

    def set_general_topic(self, workspace_id, topic_id):
        return database.tg_set_general_topic(workspace_id, topic_id)

    def unlink_workspace(self, workspace_id):
        return database.tg_unlink_workspace(workspace_id)

    def set_entity_topic(self, user_id, workspace_id, entity_type, entity_id, topic_id):
        return database.tg_set_entity_topic(user_id, workspace_id, entity_type,
                                            entity_id, topic_id)

    def get_entity_topic(self, entity_type, entity_id):
        return database.tg_get_entity_topic(entity_type, entity_id)

    def get_workspace_entity_topic(self, workspace_id, entity_type, entity_id):
        """Canonical binding lookup keyed by (workspace_id, entity_id)."""
        return database.tg_get_workspace_entity_topic(
            workspace_id, entity_type, entity_id)

    def get_entity_topics(self, workspace_id):
        return database.tg_get_entity_topics(workspace_id)

    # v15.2 M4 topic lifecycle (items 7/8/9/10).
    def delete_entity_topic(self, workspace_id, entity_type, entity_id):
        return database.tg_delete_entity_topic(workspace_id, entity_type, entity_id)

    def set_entity_topic_locked(self, workspace_id, entity_type, entity_id, locked):
        return database.tg_set_entity_topic_locked(
            workspace_id, entity_type, entity_id, locked)

    def get_entity_topic_locked(self, workspace_id, entity_type, entity_id):
        return database.tg_get_entity_topic_locked(
            workspace_id, entity_type, entity_id)

    def set_active(self, user_id, workspace_id, entity_type=None, entity_id=None):
        return database.tg_set_active(user_id, workspace_id, entity_type, entity_id)

    def get_active(self, user_id):
        return database.tg_get_active(user_id)

    def clear_active(self, user_id):
        return database.tg_clear_active(user_id)


class Storage:
    """
    The Storage Facade's single entry point: one Storage() instance
    exposes every domain as an attribute (storage.tasks.add(...),
    storage.habits.get_all(...), ...). Stateless -- holds no connection,
    no cache; every call still opens/closes its own sqlite3 connection
    exactly as database.py already does (docs/database.md's existing
    per-call connection pattern, unchanged).
    """

    def __init__(self):
        self.tasks = TaskStorage()
        self.habits = HabitStorage()
        self.goals = GoalStorage()
        self.projects = ProjectStorage()
        self.learning = LearningStorage()
        # v15.0-alpha.1 Workspace Foundation domains (dormant while
        # feature_flags.WORKSPACE is OFF).
        self.workspaces = WorkspaceStorage()
        self.milestones = MilestoneStorage()
        self.notes = NoteStorage()
        # v15.4 M6 Knowledge + Media + Tags domains.
        self.media = AttachmentStorage()
        self.tags = TagStorage()
        # v15.0-alpha.5 Knowledge Timeline.
        self.timeline = TimelineStorage()
        # v15.0-alpha.6 outbound sync outbox.
        self.sync = SyncStorage()
        # v15.1 Telegram-adapter-owned bindings (entity↔topic, active context).
        self.tg_bindings = TelegramBindingStorage()
        # v15.2 M3 memory (key/value facts) domain for the recall tools.
        self.memory = MemoryStorage()
