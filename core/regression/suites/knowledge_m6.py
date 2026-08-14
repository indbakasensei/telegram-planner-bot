"""Quick Release Suite: v15.4 M6 — Knowledge + Media + Tags.

Owner-run manual tests for the v15.4.0 line — the Knowledge, Media and Tags
sections of the /control dashboard that drive the SAME ToolRegistry the AI
Worker uses (note CRUD, media metadata, tag management). These need a live
bot (admin + Telegram), so they live in the manual Quick Release Suite, not
the offline pytest suite. The offline equivalents of every invariant here are
pinned in tests/test_m6_knowledge.py, tests/test_m6_adversarial.py and
core/selftest/tests/test_knowledge_selftest.py probes.

Live-Telegram acceptance is the remaining gate on v15.4 M6 (see
V15_4_KNOWLEDGE_MEDIA.md §Acceptance).
"""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})
_ADMIN = "Admin"
_AI = "AI"


def _t(**kw):
    register(RegressionTest(**kw))


# ── M6-A: Knowledge (Notes) ──────────────────────────────────────────────────
_t(
    test_id="KNOW-001", category=_ADMIN, feature="Note CRUD via Control Plane",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective=("Create, view, edit, and soft-delete a note through the "
               "Knowledge section of /control."),
    preconditions="A workspace is active (/control open).",
    steps=("Knowledge → Add → title 'M6 Note' / content 'Body' / kind 'general' → confirm",
           "View the note (content + links + tags + edit/delete/post buttons)",
           "Edit the note content and confirm",
           "Delete the note and confirm"),
    expected=("Each step shows the shared Result page (one confirm flow)",
              "Delete is soft — the note disappears from list but get_note "
              "by ID still returns it (deleted_at stamped)",
              "The confirm wording says 'soft-deletes'"),
    failure_conditions=("Delete hard-removes the row",
                        "Edit doesn't update updated_at",
                        "Confirm cancelling executes the action anyway"),
)

_t(
    test_id="KNOW-002", category=_ADMIN, feature="Note entity links",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective=("Link and unlink workspace entities to a note from the "
               "note detail page."),
    preconditions="A workspace with an entity (e.g. 'M6 Hero') and a note.",
    steps=("Knowledge → View note → Link Entity → send 'M6 Hero' → confirm",
           "Verify entity appears in the note's linked entities",
           "Unlink the entity and confirm"),
    expected=("Link resolves name or #id to the entity",
              "Unlink removes only that link; the note and entity persist",
              "Deleting the entity (CTRL-004 equivalent) cascades to "
              "remove the note link (no ghost ref)"),
    failure_conditions=("Link fails on valid entity",
                        "Unlink deletes the entity or note",
                        "Ghost link remains after entity deletion"),
)

_t(
    test_id="KNOW-003", category=_ADMIN, feature="Note tag links",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Link and unlink tags to a note; unknown tags are created "
               "on-the-fly (the 'dump under 1v4' contract)."),
    preconditions="A workspace with a note.",
    steps=("Knowledge → View note → Link Tag → send 'M6_NEW_TAG' → confirm",
           "Verify tag appears in the note's tags",
           "Unlink the tag and confirm"),
    expected=("New tag is created in this workspace and linked",
              "Unlink removes only the link; the tag persists for reuse",
              "The tag appears in Knowledge → Tags list"),
    failure_conditions=("New tag creation fails",
                        "Unlink deletes the tag entirely"),
)

_t(
    test_id="KNOW-004", category=_AI, feature="Note search + filters",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("The Knowledge list page supports search (q), entity filter, "
               "tag filter, and date range via the control plane."),
    preconditions="A workspace with 3+ notes across entities/tags/dates.",
    steps=("Knowledge → List → search 'body' → verify hits",
           "Knowledge → List → filter by entity → verify isolation",
           "Knowledge → List → filter by tag → verify isolation",
           "Knowledge → List → date range → verify boundary"),
    expected=("All filters combine with AND logic",
              "Results paginated (page parameter works)",
              "Empty results show a clear empty-state, not an error"),
    failure_conditions=("Filters don't combine",
                        "Cross-workspace leak in results"),
)

# ── M6-B: Media ──────────────────────────────────────────────────────────────
_t(
    test_id="KNOW-005", category=_ADMIN, feature="Media metadata CRUD",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective=("Store, view, edit, and delete media metadata records (never "
               "the Telegram file) through the Media section of /control."),
    preconditions="A workspace is active.",
    steps=("Media → Add → file_id 'AgAA-TEST' / type 'photo' / caption 'Test' → confirm",
           "View the media (metadata + file_id + resend + link/delete buttons)",
           "Edit caption and confirm",
           "Delete the media record and confirm"),
    expected=("Media record stores: file_id, media_type, caption, "
              "message_id, chat_id, topic_id, extracted_text, "
              "entity links, tag links, updated_at",
              "Delete is soft — record disappears from list but get_media "
              "by ID still returns it (deleted_at stamped)",
              "The confirm wording says 'metadata record'"),
    failure_conditions=("Delete attempts to remove the Telegram file",
                        "Caption edit doesn't update updated_at",
                        "File_id is used as a unique key (duplicates blocked)"),
)

_t(
    test_id="KNOW-006", category=_ADMIN, feature="Media entity/tag links",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Link and unlink workspace entities and tags to a media "
               "record from the media detail page."),
    preconditions="A workspace with an entity and a media record.",
    steps=("Media → View → Link Entity → send entity name → confirm",
           "Media → View → Link Tag → send tag name → confirm",
           "Unlink both and confirm"),
    expected=("Links work identically to note links (same domain methods)",
              "Entity deletion cascades to remove media links (no ghost refs)"),
    failure_conditions=("Link/unlink behaves differently from notes",
                        "Ghost link remains after entity deletion"),
)

_t(
    test_id="KNOW-007", category=_AI, feature="Media search + filters",
    introduced_version="v15.4.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("The Media list page supports search (q on caption/filename/extracted_text), "
               "media_type filter, entity filter, and tag filter."),
    preconditions="A workspace with 3+ media records across types/entities/tags.",
    steps=("Media → List → search 'caption' → verify hits",
           "Media → List → filter by media_type 'photo' → verify isolation",
           "Media → List → filter by entity → verify isolation",
           "Media → List → filter by tag → verify isolation"),
    expected=("All filters combine with AND logic",
              "Results paginated",
              "Search matches caption, file_name, extracted_text"),
    failure_conditions=("Search doesn't match extracted_text",
                        "Filters don't combine"),
)

# ── M6-C: Tags ───────────────────────────────────────────────────────────────
_t(
    test_id="KNOW-008", category=_ADMIN, feature="Tag CRUD",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Create, rename, and delete tags through the Tags section "
               "of /control."),
    preconditions="A workspace is active.",
    steps=("Tags → Add → 'M6_TAG_A' → confirm",
           "Tags → View 'M6_TAG_A' → Rename → 'M6_TAG_B' → confirm",
           "Tags → View 'M6_TAG_B' → Delete → confirm"),
    expected=("Create is idempotent (same name in same workspace returns existing)",
              "Rename changes the tag name everywhere it's linked",
              "Delete is DESTRUCTIVE with confirm; cascades to remove "
              "all entity_tag links (notes, media, entities)"),
    failure_conditions=("Duplicate tag created in same workspace",
                        "Rename doesn't update existing links",
                        "Delete leaves orphaned entity_tag rows"),
)

_t(
    test_id="KNOW-009", category=_AI, feature="Tag workspace isolation",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=45, suites=_QUICK,
    objective=("Tags are scoped to workspaces — same name in different "
               "workspaces are distinct tags."),
    preconditions="Two workspaces (WS_A, WS_B) for the same user.",
    steps=("In WS_A: Tags → Add → 'SHARED_NAME' → confirm",
           "In WS_B: Tags → Add → 'SHARED_NAME' → confirm",
           "Verify they have different tag_ids and independent link sets"),
    expected=("Tag list in WS_A shows 1 tag; WS_B shows 1 tag; different ids",
              "Linking a note in WS_A to 'SHARED_NAME' doesn't affect WS_B"),
    failure_conditions=("Single global tag across workspaces",
                        "Cross-workspace tag leakage"),
)

_t(
    test_id="KNOW-010", category=_ADMIN, feature="Tag view shows all links",
    introduced_version="v15.4.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("The tag detail page lists linked notes, media, and entities."),
    preconditions="A workspace with a tag linked to a note, a media record, "
                  "and an entity.",
    steps=("Tags → View the tag"),
    expected=("Page shows three sections: Notes / Media / Entities",
              "Each item links to its detail page"),
    failure_conditions=("Missing link type",
                        "Ghost links from deleted entities/notes/media"),
)

# ── M6-D: Cross-cutting (Worker + Manual parity) ────────────────────────────
_t(
    test_id="KNOW-011", category=_AI, feature="Worker uses M6 tools",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective=("The AI Worker can invoke all 22 M6 tools via the shared "
               "registry (no second logic path)."),
    preconditions="Owner private chat; an active workspace with an entity.",
    steps=("Ask: 'Create a note titled \"Worker Note\" linked to M6 Hero'",
           "Ask: 'Store a photo with file_id AgAA-WORKER caption \"Worker Media\"'",
           "Ask: 'Tag the note with WORKER_TAG'",
           "Ask: 'List notes tagged WORKER_TAG'"),
    expected=("Each tool call returns ToolResult.ok with data",
              "The created note/media/tag are visible in /control",
              "No tool fabricates success on failure"),
    failure_conditions=("Worker invents a tool not in the registry",
                        "Tool fails silently or crashes"),
)

_t(
    test_id="KNOW-012", category=_AI, feature="Manual path == Worker path",
    introduced_version="v15.4.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective=("Creating a note via /control Knowledge→Add and via the Worker "
               "produces identical domain effects (no second business logic)."),
    preconditions="Owner private chat; an active workspace with an entity.",
    steps=("Via Worker: 'Create note titled \"WorkerPath\" content \"w\"'",
           "Via /control: Knowledge → Add → 'ControlPath' / 'c' → confirm",
           "Compare both notes in /control Knowledge list"),
    expected=("Both notes have identical structure: title, content, kind, "
              "created_at, updated_at, deleted_at, entity links, tag links",
              "Both appear in the same list_notes result"),
    failure_conditions=("Different default kind or timestamps",
                        "One path omits entity/tag links"),
)