"""Quick Release Suite: v15.5 M7 — Cross-Reference Retrieval.

Owner-run manual tests for the v15.5.0 line — the Search/Retrieve section of
the /control dashboard that drives the SAME CrossReferenceService the AI
Worker's M7 tools use. These need a live bot (owner + Telegram), so they
live in the manual Quick Release Suite, not the offline pytest suite. The
offline equivalents of every invariant here are pinned in
tests/test_m7_retrieval.py and core/selftest/tests/test_retrieval_selftest.py.

Live-Telegram acceptance is the remaining gate on v15.5 M7 (see
V15_5_CROSS_REFERENCE_RETRIEVAL.md §Acceptance).
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


# ── M7-A: Unified Cross-Reference Search (Mixed _type results) ──────────────────
_t(
    test_id="RET-001", category=_ADMIN, feature="Unified search returns notes + media",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("The Search page returns a mixed list of notes and media "
               "with _type discriminator for each result."),
    preconditions="A workspace with at least one note and one media record.",
    steps=("Control → Search → Query 'test' → Search"),
    expected=("Results show both note and media rows",
              "Each row has _type badge (note | media)",
              "Note rows show title/kind/preview; media rows show file_type/filename/caption",
              "No fabrication — only actual DB records appear"),
    failure_conditions=("Only one _type returned when both exist",
                        "Missing _type field on any result",
                        "Results include records from other workspaces"),
)

_t(
    test_id="RET-002", category=_ADMIN, feature="Notes-only search scope",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Search → Scope: Notes returns only notes (_type=note)."),
    preconditions="A workspace with notes and media.",
    steps=("Control → Search → Scope: Notes → Query 'test' → Search"),
    expected=("All results have _type=note",
              "Media records excluded even if they match query"),
    failure_conditions=("Media appears in notes-only results",
                        "Notes missing from notes-only results"),
)

_t(
    test_id="RET-003", category=_ADMIN, feature="Media-only search scope",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Search → Scope: Media returns only media (_type=media)."),
    preconditions="A workspace with notes and media.",
    steps=("Control → Search → Scope: Media → Query 'test' → Search"),
    expected=("All results have _type=media",
              "Notes excluded even if they match query"),
    failure_conditions=("Notes appear in media-only results",
                        "Media missing from media-only results"),
)


# ── M7-B: Entity Filter AND/OR Semantics ────────────────────────────────────────
_t(
    test_id="RET-004", category=_ADMIN, feature="Entity AND mode (all must match)",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Entity Mode: AND requires ALL selected entities to be linked."),
    preconditions=("A workspace with entities M7_Ace_Test, M7_1v4_Test. "
                   "A note/media linked to BOTH. Another linked to Ace only."),
    steps=("Control → Search → Entities: M7_Ace_Test, M7_1v4_Test → Mode: AND → Search"),
    expected=("Only items linked to BOTH entities returned",
              "Items linked to only one entity excluded"),
    failure_conditions=("Ace-only item returned (OR behavior)",
                        "Both-entity item missing"),
)

_t(
    test_id="RET-005", category=_ADMIN, feature="Entity OR mode (any matches)",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Entity Mode: OR requires ANY selected entity to be linked."),
    preconditions=("A workspace with entities M7_Ace_Test, M7_TenZ_Test. "
                   "Media A linked to Ace. Media B linked to TenZ. "
                   "Media C linked to both."),
    steps=("Control → Search → Entities: M7_Ace_Test, M7_TenZ_Test → Mode: OR → Search"),
    expected=("All three media returned (each matches at least one entity)"),
    failure_conditions=("Only one entity's media returned (AND behavior)",
                        "Media C missing"),
)

_t(
    test_id="RET-006", category=_ADMIN, feature="Entity references by #id and name",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Entity filter accepts both names (M7_Ace_Test) and #id format."),
    preconditions="A workspace with entity M7_Ace_Test (id=42) and linked media.",
    steps=("Control → Search → Entities: #42 → Search",
           "Control → Search → Entities: M7_Ace_Test → Search"),
    expected=("Both queries return the same media"),
    failure_conditions=("#id format fails",
                        "Name format fails",
                        "Results differ between formats"),
)

_t(
    test_id="RET-007", category=_ADMIN, feature="Mixed entity name + #id",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Entity filter accepts mixed names and #ids in one query."),
    preconditions=("A workspace with entities M7_Ace_Test (id=42) and M7_1v4_Test (id=43). "
                   "Media linked to both."),
    steps=("Control → Search → Entities: M7_Ace_Test, #43 → Mode: AND → Search"),
    expected=("Media linked to both entities returned"),
    failure_conditions=("Mixed format fails",
                        "Only one entity filter applied"),
)


# ── M7-C: Tag Filter AND/OR Semantics ───────────────────────────────────────────
_t(
    test_id="RET-008", category=_ADMIN, feature="Tag AND mode (all tags must match)",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Tag Mode: AND requires ALL selected tags to be linked."),
    preconditions=("A workspace with tags M7_1v4_Test, M7_1v3_Test. "
                   "A note tagged with both. Another tagged with 1v4 only."),
    steps=("Control → Search → Tags: M7_1v4_Test, M7_1v3_Test → Mode: AND → Search"),
    expected=("Only items with BOTH tags returned"),
    failure_conditions=("1v4-only item returned (OR behavior)",
                        "Both-tag item missing"),
)

_t(
    test_id="RET-009", category=_ADMIN, feature="Tag OR mode (any tag matches)",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Tag Mode: OR requires ANY selected tag to be linked."),
    preconditions=("A workspace with tags M7_1v4_Test, M7_1v3_Test. "
                   "Media A tagged 1v4. Media B tagged 1v3. Media C tagged both."),
    steps=("Control → Search → Tags: M7_1v4_Test, M7_1v3_Test → Mode: OR → Search"),
    expected=("All three media returned"),
    failure_conditions=("Only one tag's media returned (AND behavior)",
                        "Media C missing"),
)


# ── M7-D: Combined Entity + Tag Filters ────────────────────────────────────────
_t(
    test_id="RET-010", category=_ADMIN, feature="Entity AND + Tag AND (all must match)",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Combined: entities=AND + tags=AND requires all entities AND all tags."),
    preconditions=("A workspace with entities M7_Ace_Test, M7_1v4_Test and tag M7_1v4_Test. "
                   "Media A: linked to Ace + 1v4 entity + tagged 1v4. "
                   "Media B: linked to Ace only + tagged 1v4. "
                   "Media C: linked to Ace + 1v4 entity, no tag."),
    steps=("Control → Search → Entities: M7_Ace_Test, M7_1v4_Test (AND) → "
           "Tags: M7_1v4_Test (AND) → Search"),
    expected=("Only Media A returned (matches all 3 filters)"),
    failure_conditions=("Media B returned (missing 1v4 entity)",
                        "Media C returned (missing tag)"),
)

_t(
    test_id="RET-011", category=_ADMIN, feature="Entity OR + Tag AND ((A or B) and C)",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Combined: entities=OR + tags=AND implements (entity OR) AND tag."),
    preconditions=("A workspace with entities M7_Ace_Test, M7_TenZ_Test and tag M7_1v4_Test. "
                   "Media A: Ace + 1v4 tag. Media B: TenZ + 1v4 tag. Media C: Ace only (no tag)."),
    steps=("Control → Search → Entities: M7_Ace_Test, M7_TenZ_Test (OR) → "
           "Tags: M7_1v4_Test (AND) → Search"),
    expected=("Media A and Media B returned (both match tag AND at least one entity)"),
    failure_conditions=("Media C returned (missing tag)",
                        "Only one of A/B returned"),
)


# ── M7-E: Media Type Filter ────────────────────────────────────────────────────
_t(
    test_id="RET-012", category=_ADMIN, feature="Media type filter (photo|video|document|audio)",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Media Type filter restricts media results by file_type."),
    preconditions=("A workspace with video media and photo media linked to same entity."),
    steps=("Control → Search → Entity: M7_Ace_Test → Media Type: video → Search",
           "Control → Search → Entity: M7_Ace_Test → Media Type: photo → Search"),
    expected=("Video filter returns only video media",
              "Photo filter returns only photo media",
              "Notes still returned regardless of media_type filter"),
    failure_conditions=("Video filter returns photos",
                        "Photo filter returns videos",
                        "Notes filtered by media_type (should not be)"),
)


# ── M7-F: Free-Text Search ─────────────────────────────────────────────────────
_t(
    test_id="RET-013", category=_ADMIN, feature="Free-text search (q) on notes",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Query parameter searches note title and content."),
    preconditions="A workspace with note titled 'Ace Strategy' content '1v4 clutch play'.",
    steps=("Control → Search → Query: 'strategy' → Search",
           "Control → Search → Query: 'clutch' → Search",
           "Control → Search → Query: 'Ace' → Search"),
    expected=("All three queries return the note"),
    failure_conditions=("Any query fails to match",
                        "Case sensitivity affects results"),
)

_t(
    test_id="RET-014", category=_ADMIN, feature="Free-text search (q) on media",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Query parameter searches media caption, file_name, extracted_text."),
    preconditions=("A workspace with media: file_name='M7_Clip_A.mp4', "
                   "caption='Ace 1v4 clutch', extracted_text='strategy guide'."),
    steps=("Control → Search → Query: 'clutch' → Search",
           "Control → Search → Query: 'clip' → Search",
           "Control → Search → Query: 'strategy' → Search"),
    expected=("All three queries return the media"),
    failure_conditions=("Any query fails to match",
                        "extracted_text not searched"),
)

_t(
    test_id="RET-015", category=_ADMIN, feature="Free-text search case-insensitive",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=20, suites=_QUICK,
    objective=("Query parameter is case-insensitive."),
    preconditions="A workspace with note titled 'Ace Strategy'.",
    steps=("Control → Search → Query: 'ACE' → Search",
           "Control → Search → Query: 'ace' → Search",
           "Control → Search → Query: 'Ace' → Search"),
    expected=("All three queries return the note"),
    failure_conditions=("Case affects results"),
)


# ── M7-G: Date Range Filters ───────────────────────────────────────────────────
_t(
    test_id="RET-016", category=_ADMIN, feature="Created after filter",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Created After returns items on or after the date."),
    preconditions="A workspace with a note created today.",
    steps=("Control → Search → Created After: tomorrow's date → Search",
           "Control → Search → Created After: today's date → Search",
           "Control → Search → Created After: yesterday's date → Search"),
    expected=("Tomorrow returns 0 results",
              "Today returns the note",
              "Yesterday returns the note"),
    failure_conditions=("Boundary off by one day",
                        "Future date returns results"),
)

_t(
    test_id="RET-017", category=_ADMIN, feature="Created before filter",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Created Before returns items on or before the date."),
    preconditions="A workspace with a note created today.",
    steps=("Control → Search → Created Before: yesterday's date → Search",
           "Control → Search → Created Before: today's date → Search",
           "Control → Search → Created Before: tomorrow's date → Search"),
    expected=("Yesterday returns 0 results",
              "Today returns the note",
              "Tomorrow returns the note"),
    failure_conditions=("Boundary off by one day",
                        "Past date returns 0 when it shouldn't"),
)


# ── M7-H: Workspace Isolation (HARD SAFETY INVARIANT) ──────────────────────────
_t(
    test_id="RET-018", category=_ADMIN, feature="Workspace isolation — no cross-leak",
    introduced_version="v15.5.0-alpha.1", priority=Priority.CRITICAL,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=45, suites=_QUICK,
    objective=("Query on Workspace A NEVER returns Workspace B data, even with identical names."),
    preconditions=("Two workspaces (WS_A, WS_B) for the same user. "
                   "Both have entity 'M7_Ace_Test' and media linked to it with same caption."),
    steps=("In WS_A: Control → Search → Entity: M7_Ace_Test → Search",
           "In WS_B: Control → Search → Entity: M7_Ace_Test → Search"),
    expected=("WS_A query returns only WS_A media",
              "WS_B query returns only WS_B media",
              "Zero cross-workspace leakage"),
    failure_conditions=("Any result from the other workspace appears",
                        "Identical entity names cause confusion"),
)

_t(
    test_id="RET-019", category=_ADMIN, feature="Workspace isolation — tags",
    introduced_version="v15.5.0-alpha.1", priority=Priority.CRITICAL,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=45, suites=_QUICK,
    objective=("Tag filter on Workspace A NEVER matches Workspace B tags with same name."),
    preconditions=("Two workspaces (WS_A, WS_B). Both have tag 'M7_1v4_Test' "
                   "and media tagged with it."),
    steps=("In WS_A: Control → Search → Tag: M7_1v4_Test → Search",
           "In WS_B: Control → Search → Tag: M7_1v4_Test → Search"),
    expected=("WS_A query returns only WS_A media",
              "WS_B query returns only WS_B media",
              "Zero cross-workspace tag leakage"),
    failure_conditions=("Any result from the other workspace appears",
                        "Same tag name across workspaces merged"),
)


# ── M7-I: Kind Filter (Notes Only) ─────────────────────────────────────────────
_t(
    test_id="RET-020", category=_ADMIN, feature="Kind filter applies only to notes",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Kind filter restricts notes by kind; media unaffected."),
    preconditions=("A workspace with notes of kind 'analysis' and 'summary', "
                   "and media linked to same entity."),
    steps=("Control → Search → Entity: M7_Ace_Test → Kind: analysis → Search"),
    expected=("Only 'analysis' notes returned",
              "Media still returned (kind filter doesn't apply to media)"),
    failure_conditions=("Media filtered by kind",
                        "'summary' notes returned"),
)


# ── M7-J: Limit and Sorting ────────────────────────────────────────────────────
_t(
    test_id="RET-021", category=_ADMIN, feature="Limit default 50, max 200",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=30, suites=_QUICK,
    objective=("Limit parameter capped at 200, default 50."),
    preconditions="A workspace with 250+ notes linked to an entity.",
    steps=("Control → Search → Entity: M7_Ace_Test → Limit: (default) → Search",
           "Control → Search → Entity: M7_Ace_Test → Limit: 200 → Search",
           "Control → Search → Entity: M7_Ace_Test → Limit: 500 → Search"),
    expected=("Default returns 50 results",
              "200 returns 200 results",
              "500 capped to 200"),
    failure_conditions=("Default not 50",
                        "Over 200 not capped"),
)

_t(
    test_id="RET-022", category=_ADMIN, feature="Results sorted newest-first",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Combined results sorted by created_at descending."),
    preconditions=("A workspace with older note and newer media linked to same entity."),
    steps=("Control → Search → Entity: M7_Ace_Test → Search"),
    expected=("Newer media appears before older note in combined list"),
    failure_conditions=("Older items appear first",
                        "Notes and media sorted independently"),
)


# ── M7-K: Empty Results (Honest Zero) ──────────────────────────────────────────
_t(
    test_id="RET-023", category=_ADMIN, feature="Zero results = empty list (no fabrication)",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=20, suites=_QUICK,
    objective=("Non-matching query returns empty list, not error, not fabricated data."),
    preconditions="A workspace with some data.",
    steps=("Control → Search → Query: 'nonexistent_term_xyz' → Search"),
    expected=("Empty results state shown (no error, no fake results)"),
    failure_conditions=("Error thrown",
                        "Fabricated results shown",
                        "Results from other workspace leak in"),
)


# ── M7-L: Original Use Cases (Ace/TenZ/1v4 Scenarios) ──────────────────────────
_t(
    test_id="RET-024", category=_ADMIN, feature="Use case: 'Show my 1v4 clips'",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Tag 1v4 + media_type=video returns video clips tagged 1v4."),
    preconditions="A workspace with video media tagged M7_1v4_Test.",
    steps=("Control → Search → Tags: M7_1v4_Test (AND) → Media Type: video → Search"),
    expected=("Video clips tagged 1v4 returned"),
    failure_conditions=("Photos returned",
                        "Untagged videos returned",
                        "Zero results when tagged video exists"),
)

_t(
    test_id="RET-025", category=_ADMIN, feature="Use case: 'Show M7_Ace_Test clips'",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Entity M7_Ace_Test returns media linked to Ace."),
    preconditions="A workspace with media linked to entity M7_Ace_Test.",
    steps=("Control → Search → Entities: M7_Ace_Test (AND) → Search"),
    expected=("Media linked to Ace returned"),
    failure_conditions=("Media not linked to Ace returned",
                        "Ace-linked media missing"),
)

_t(
    test_id="RET-026", category=_ADMIN, feature="Use case: 'Show M7_Ace_Test 1v4 clips'",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Entity Ace AND tag 1v4 returns media linked to both."),
    preconditions="A workspace with media linked to Ace entity AND tagged 1v4.",
    steps=("Control → Search → Entities: M7_Ace_Test (AND) → Tags: M7_1v4_Test (AND) → Search"),
    expected=("Media linked to Ace AND tagged 1v4 returned"),
    failure_conditions=("Ace-only media returned",
                        "1v4-only media returned",
                        "Both-linked media missing"),
)

_t(
    test_id="RET-027", category=_ADMIN, feature="Use case: 'Show M7_Ace_Test screenshots'",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Entity Ace + media_type=photo returns photos only (excludes video)."),
    preconditions="A workspace with Ace-linked video and Ace-linked photo.",
    steps=("Control → Search → Entities: M7_Ace_Test (AND) → Media Type: photo → Search"),
    expected=("Only photo media returned"),
    failure_conditions=("Video returned",
                        "Photo missing"),
)

_t(
    test_id="RET-028", category=_ADMIN, feature="Use case: TenZ 1v4 query returns only TenZ",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Query for Ace 1v4 does not return TenZ 1v4 media."),
    preconditions=("A workspace with Ace+1v4 media AND TenZ+1v4 media (both tagged 1v4)."),
    steps=("Control → Search → Entities: M7_Ace_Test (AND) → Tags: M7_1v4_Test (AND) → Search"),
    expected=("Only Ace+1v4 media returned"),
    failure_conditions=("TenZ+1v4 media returned",
                        "Ace+1v4 media missing"),
)

_t(
    test_id="RET-029", category=_ADMIN, feature="Use case: 'Ace OR TenZ 1v4 clips' returns both",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Entity OR (Ace, TenZ) + Tag AND (1v4) returns both entities' 1v4 clips."),
    preconditions=("A workspace with Ace+1v4 media AND TenZ+1v4 media (both tagged 1v4)."),
    steps=("Control → Search → Entities: M7_Ace_Test, M7_TenZ_Test (OR) → Tags: M7_1v4_Test (AND) → Search"),
    expected=("Both Ace+1v4 and TenZ+1v4 media returned"),
    failure_conditions=("Only one returned",
                        "Media without 1v4 tag returned"),
)

_t(
    test_id="RET-030", category=_ADMIN, feature="Use case: Workspace B identical names never leak",
    introduced_version="v15.5.0-alpha.1", priority=Priority.CRITICAL,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=45, suites=_QUICK,
    objective=("Identical entity/tag names in Workspace B NEVER leak into Workspace A queries."),
    preconditions=("Two workspaces (WS_A, WS_B). Both have entities M7_Ace_Test, M7_1v4_Test "
                   "and media linked to both, tagged M7_1v4_Test."),
    steps=("In WS_A: Control → Search → Entities: M7_Ace_Test, M7_1v4_Test (AND) → Tags: M7_1v4_Test (AND) → Search"),
    expected=("Only WS_A media returned"),
    failure_conditions=("Any WS_B media appears in WS_A results",
                        "Cross-workspace leakage of any kind"),
)


# ── M7-M: Worker Integration ────────────────────────────────────────────────────
_t(
    test_id="RET-031", category=_AI, feature="Worker M7 tools registered",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("The 3 M7 retrieval tools are registered in the Worker's tool registry."),
    preconditions="Owner private chat; feature_flags.WORKER enabled.",
    steps=("Ask: 'What search tools do you have?' or check /selftest"),
    expected=("search_knowledge, search_notes_cross, search_media_cross present",
              "All classified READ_ONLY",
              "Tool descriptions mention _type discriminator"),
    failure_conditions=("Any M7 tool missing",
                        "Wrong risk classification",
                        "Missing _type in description"),
)

_t(
    test_id="RET-032", category=_AI, feature="Worker search_knowledge returns mixed types",
    introduced_version="v15.5.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Worker's search_knowledge tool returns mixed note+media results with _type."),
    preconditions=("Owner private chat; feature_flags.WORKER enabled; "
                   "active workspace with notes and media."),
    steps=("Ask: 'Search my workspace for Ace 1v4'"),
    expected=("Worker calls search_knowledge tool",
              "Tool returns structured results with _type for each",
              "Worker synthesizes answer from results"),
    failure_conditions=("Tool not called",
                        "Results lack _type",
                        "Worker fabricates results not from tool"),
)

_t(
    test_id="RET-033", category=_AI, feature="Worker search_notes_cross notes-only",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Worker's search_notes_cross returns only notes."),
    preconditions=("Owner private chat; feature_flags.WORKER enabled; "
                   "active workspace with notes and media."),
    steps=("Ask: 'Search my notes for Ace'"),
    expected=("Worker calls search_notes_cross tool",
              "All results have _type=note"),
    failure_conditions=("Media in results",
                        "Tool not called"),
)

_t(
    test_id="RET-034", category=_AI, feature="Worker search_media_cross media-only",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Worker's search_media_cross returns only media."),
    preconditions=("Owner private chat; feature_flags.WORKER enabled; "
                   "active workspace with notes and media."),
    steps=("Ask: 'Search my media for 1v4 clips'"),
    expected=("Worker calls search_media_cross tool",
              "All results have _type=media"),
    failure_conditions=("Notes in results",
                        "Tool not called"),
)


# ── M7-N: Control Plane Search UI Actions ──────────────────────────────────────
_t(
    test_id="RET-035", category=_ADMIN, feature="Search page Open button",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Open button navigates to note/media detail page."),
    preconditions="Search results showing at least one note and one media.",
    steps=("Control → Search → Query 'test' → Search → Open on a note → Open on a media"),
    expected=("Note Open → ctl:note:view:<id>",
              "Media Open → ctl:media:view:<id>"),
    failure_conditions=("Open does nothing",
                        "Wrong detail page opened"),
)

_t(
    test_id="RET-036", category=_ADMIN, feature="Search page Send button (media)",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Send button resends media via stored telegram_file_id."),
    preconditions="Search results showing media with valid telegram_file_id.",
    steps=("Control → Search → Query 'test' → Search → Send on a media result"),
    expected=("Media file sent to chat via bot"),
    failure_conditions=("Send fails",
                        "Wrong file sent"),
)

_t(
    test_id="RET-037", category=_ADMIN, feature="Search page Link/Unlink buttons",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Link/Unlink buttons on search results open entity/tag linking flows."),
    preconditions="Search results showing a note/media.",
    steps=("Control → Search → Query 'test' → Search → Link Entity on a result",
           "Control → Search → Query 'test' → Search → Link Tag on a result"),
    expected=("Link Entity → entity picker → confirm → link created",
              "Link Tag → tag picker → confirm → link created",
              "Unlink removes the link"),
    failure_conditions=("Link/Unlink does nothing",
                        "Link created in wrong workspace"),
)


# ── M7-O: Pagination ───────────────────────────────────────────────────────────
_t(
    test_id="RET-038", category=_ADMIN, feature="Search results pagination",
    introduced_version="v15.5.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("Search results paginate correctly with page parameter."),
    preconditions="A workspace with 100+ notes linked to an entity.",
    steps=("Control → Search → Entity: M7_Ace_Test → Search (page 1)",
           "Control → Search → Entity: M7_Ace_Test → Next Page → Search (page 2)"),
    expected=("Page 1 shows first 50 (default limit)",
              "Page 2 shows next 50",
              "No duplicate items across pages"),
    failure_conditions=("Pagination broken",
                        "Duplicates across pages",
                        "Missing items"),
)