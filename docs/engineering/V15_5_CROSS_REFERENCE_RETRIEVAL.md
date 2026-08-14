# v15.5 M7 — Cross-Reference Retrieval

**Status:** shipped as `v15.5.0-alpha.1`  
**Owner-run gate remaining:** live-Telegram acceptance matrix RET-001…038 (documented, not claimed offline)

---

## 1. Purpose

BAKA gains **cross-reference retrieval**: a single search that returns both **notes** and **media** (unified, mixed `_type` results), filtered by entities, tags, media type, free text, date ranges, and workspace — with deterministic AND/OR semantics.

Binding layering (unchanged from M6):
```
Worker → Tool Registry → CrossReferenceService → NoteStorage/AttachmentStorage → DB
Manual Control Plane → Tool Registry → CrossReferenceService → NoteStorage/AttachmentStorage → DB
```
**No second business-logic path.** The Search page in `/control` executes the SAME `CrossReferenceService` the AI Worker's M7 tools use.

---

## 2. Schema (No New Tables — Pure M6 Composition)

M7 adds **zero** schema changes. It composes existing M6 storage:
- `NoteStorage.search` (title/content + entity/tag/date filters via `note_entities` + `entity_tags`)
- `AttachmentStorage.search` (caption/file_name/extracted_text + entity/tag/date filters via `attachment_entities` + `entity_tags`)

No FTS5, no embeddings, no vector search — documented FUTURE extensions (spec §11, same as M6).

---

## 3. CrossReferenceService (`core/retrieval/service.py`)

Single retrieval implementation. Key properties:

| Property | Detail |
|---|---|
| **Output** | `list[RetrievalResult]` with `_type: Literal["note", "media"]` discriminator |
| **Workspace isolation** | Mandatory: every query scoped to `workspace_id`; never cross-workspace |
| **Limit** | Default 50, max 200, honest truncation (results are capped, not paginated beyond 200) |
| **Sorting** | Newest-first by `created_at` (notes + media merged, single sort) |
| **Empty results** | Returns `[]` — never fabricates, never errors on no-match |
| **AND/OR logic** | Python-side set operations over multiple underlying searches |

### 3.1 RetrievalFilters (dataclass)

```python
@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    workspace_id: int
    q: str | None = None
    entity_ids: tuple[int, ...] = ()
    entity_mode: Literal["and", "or"] = "and"
    tag_ids: tuple[int, ...] = ()
    tag_mode: Literal["and", "or"] = "and"
    media_type: str | None = None
    created_after: str | None = None
    created_before: str | None = None
    limit: int = 50
    kind: str | None = None  # notes only
```

### 3.2 RetrievalResult (dataclass)

```python
@dataclass(frozen=True, slots=True)
class RetrievalResult:
    _type: Literal["note", "media"]
    # Note fields
    note_id: int | None = None
    title: str | None = None
    content: str | None = None
    kind: str | None = None
    note_created_at: str | None = None
    # Media fields
    media_id: int | None = None
    file_type: str | None = None
    telegram_file_id: str | None = None
    file_name: str | None = None
    caption: str | None = None
    media_created_at: str | None = None
    message_id: int | None = None
    chat_id: int | None = None
    topic_id: int | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    extracted_text: str | None = None
    # Common
    workspace_id: int | None = None
```

### 3.3 Public API

```python
class CrossReferenceService:
    def __init__(self, engine: EntityEngine):
        ...

    def search(
        self,
        user_id: int,
        workspace_id: int,
        *,
        q: str | None = None,
        entities: list[str | int] | None = None,
        entity_mode: Literal["and", "or"] = "and",
        tags: list[str] | None = None,
        tag_mode: Literal["and", "or"] = "and",
        media_type: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[RetrievalResult]:
        """Unified search: notes + media."""

    def search_notes_only(...) -> list[RetrievalResult]:
        """Notes only; media_type ignored."""

    def search_media_only(...) -> list[RetrievalResult]:
        """Media only; kind ignored."""

def build_retrieval_service(engine: EntityEngine | None = None) -> CrossReferenceService:
    """Factory; uses EntityEngine() if none provided."""
```

---

## 4. AND/OR Filter Semantics (Python-Side Composition)

The underlying M6 storage searches support **single** `entity_type`+`entity_id` or `tag_id`. For multiple entities/tags, `CrossReferenceService` executes **multiple searches** and combines in Python:

| Mode | Logic | Implementation |
|---|---|---|
| `entity_mode="and"` + `tag_mode="and"` | ALL entities AND ALL tags must match | Start with first entity/tag, then Python-filter by rest |
| `entity_mode="or"` OR `tag_mode="or"` | ANY entity OR ANY tag matches | UNION of per-entity/per-tag searches, dedup by ID |
| Mixed | Conservative: treats as AND | Safety default |

**Why not SQL JOINs?** The M6 schema uses `note_entities`/`attachment_entities` junction tables. A single SQL query with multiple JOINs for AND and UNION for OR would be complex, fragile, and harder to verify. Python-side composition is explicit, testable, and uses existing indexes.

---

## 5. Tool Registry (3 New READ_ONLY Tools)

Added to `core/ai/tool_adapters.py` via `build_tool_registry`:

| Tool | Risk | Purpose |
|---|---|---|
| `search_knowledge` | READ_ONLY | Unified search (notes + media) |
| `search_notes_cross` | READ_ONLY | Notes-only cross-reference search |
| `search_media_cross` | READ_ONLY | Media-only cross-reference search |

**Parameters (all three):**
- `workspace` (str): workspace name or `active` (required)
- `q` (str): free-text query
- `entities` (list[str]): entity names or `#id`
- `entity_mode` (str): `"and"` | `"or"` (default `"and"`)
- `tags` (list[str]): tag names
- `tag_mode` (str): `"and"` | `"or"` (default `"and"`)
- `media_type` (str): `"photo"|"video"|"document"|"audio"` (media tools only)
- `created_after` (str): ISO date (inclusive)
- `created_before` (str): ISO date (inclusive)
- `limit` (int): 1–200 (default 50)
- `kind` (str): note kind filter (notes tools only)

**Returns:** `list[RetrievalResult]` — the Worker receives structured data with `_type` discriminator and renders via `worker_render.py`.

---

## 6. Control Plane (`core/control/pages.py` + `router.py`)

New **Search** section in `/control`:

### 6.1 Pages
- `search_home(ctx)` — search form with all filters (query, entities, tags, media type, dates, scope, limit)
- `search_results(ctx)` — paginated results with `_type` badges, Open/Send/Link/Unlink actions

### 6.2 Gather Handlers (registered in `router.py`)
- `_gather_search` — free text query
- `_gather_search_ws` — workspace picker
- `_gather_search_mode` — AND/OR mode for entities/tags
- `_gather_search_dates` — created_after / created_before
- `_gather_search_mtype` — media type picker
- `_gather_search_tags` — tag picker (workspace-scoped)
- `_gather_search_scope` — scope: active workspace only (default) / all workspaces (future)

### 6.3 Action Flow
```
ctl:search:home → (gather all filters) → ctl:search:results →
  Open note    → ctl:note:view:<id>
  Open media   → ctl:media:view:<id>
  Send media   → ctl:media:send:<id>  (uses stored telegram_file_id)
  Link Entity  → ctl:note:link-ent / ctl:media:link-ent
  Link Tag     → ctl:note:link-tag / ctl:media:link-tag
  Unlink       → ctl:note:unlink-ent / etc.
```

**No-second-logic proof:** Every action delegates to the SAME `ToolRegistry` the Worker uses. The dashboard never writes the DB directly.

---

## 7. Date Boundary Fix (Critical)

**Problem:** `database.py`'s `add_note` / `add_attachment` used `DEFAULT CURRENT_TIMESTAMP` (UTC) for `created_at`, but the rest of the system operates in **IST** (`Asia/Kolkata`). This caused off-by-one-day failures in date-range filters when the UTC/IST boundary was crossed.

**Fix:** `database.py` now explicitly sets `created_at = _now_ist_str()` in both `add_note` and `add_attachment` (mirroring the milestone pattern). The column definition keeps `DEFAULT CURRENT_TIMESTAMP` as a safety net for any legacy code paths, but all production code paths use IST.

**Impact:** All M7 date filters (`created_after`, `created_before`) now work correctly against IST dates. This was verified by the M7 test matrix G (date range filters) and the selftest round-trip.

---

## 8. Tests (Fresh Names Only: `M7_Ace_Test`, `M7_TenZ_Test`, `M7_1v4_Test`, `M7_1v3_Test`, `M7_Clip_A`, `M7_Clip_B`, `M7_Book_Test`, `M7_WS_A`, `M7_WS_B`)

| File | Tests | Matrices |
|---|---|---|
| `tests/test_m7_retrieval.py` | 57 | A (mixed types), B (entity AND/OR), C (tag AND/OR), D (combined), E (media type), F (free-text), G (date range), H (workspace isolation), I (kind filter), J (limit/sort), K (empty results), L (original use cases: Ace/TenZ/1v4), M (factory), N (filters dataclass), O (result dataclass), P (edge cases) |
| `tests/test_m7_adversarial.py` | *pending* | — |
| `core/selftest/tests/test_retrieval_selftest.py` | 4 | Factory, round-trip, tool registry (3 M7 tools READ_ONLY), control plane page |
| `core/regression/suites/retrieval_m7.py` | 38 | RET-001…038 (Admin + AI, Quick suite) |

**Failure policy (binding):** never weaken/delete a failing test — investigate, fix the implementation, rerun, report.

---

## 9. Regression Suite

`core/regression/suites/retrieval_m7.py` — **RET-001…038** (Admin + AI categories, Quick suite). Live-Telegram acceptance is the remaining gate (documented, not claimed offline).

| Section | Tests | Focus |
|---|---|---|
| M7-A | 3 | Unified search returns mixed types |
| M7-B | 4 | Entity AND/OR semantics |
| M7-C | 2 | Tag AND/OR semantics |
| M7-D | 2 | Combined entity + tag |
| M7-E | 1 | Media type filter |
| M7-F | 3 | Free-text search |
| M7-G | 2 | Date range filters |
| M7-H | 2 | Workspace isolation (CRITICAL) |
| M7-I | 1 | Kind filter (notes only) |
| M7-J | 2 | Limit + sorting |
| M7-K | 1 | Empty results (honest) |
| M7-L | 7 | Original use cases (Ace/TenZ/1v4) |
| M7-M | 4 | Worker integration |
| M7-N | 3 | Control plane UI actions |
| M7-O | 1 | Pagination |

---

## 10. Version

**`v15.5.0-alpha.1`** (existing `v15.N.0-alpha.M` convention). Bump `BAKA_VERSION` at `main.py:216`. No commit, no push.

---

## 11. Verification (End-to-End)

1. **Full `pytest`** — pass count ≥ 1887 with only the 5 known date-flakes (pre-existing, unrelated to M7).
2. **Offline `/selftest`** — all 4 M7 probes pass + existing probes.
3. **`py_compile`** on every changed module; `git diff --check` clean.
4. **Offline drill:** each M7 tool + control callback on temp DB with recording FakeClient; manual path and Worker path produce identical domain effects (no-second-logic proof).
5. **Regression spec runnable;** selftest probes green.
6. **Live acceptance deferred** to the consolidated pass (M5+M6+M7) per spec §14.

---

## 12. Control Plane Search UI (Stateful Filter Builder — v15.5.0-alpha.1+fix1)

**Critical bug fix (2026-08-14):** The initial M7 Control Plane search UI had a **state management bug** that prevented compound searches. Each gather handler called `clear_state()` and passed only its own filter, losing all previously set filters.

**Root cause:** No persistent search context between filter selections.

**Fix:** Added stateful search builder pattern via `conversation_state.py`:
- `get_search_state(user_id)` — retrieve accumulated filters
- `set_search_state(user_id, **updates)` — merge new filters with existing state
- `clear_search_state(user_id)` — reset all filters (wired to Clear button)

**All 8 gather handlers now accumulate state:**
1. `_gather_search` (query) — sets `q`
2. `_gather_search_entities` (NEW) — sets `entities`
3. `_gather_search_ws` (workspace) — sets `workspace`/`scope`
4. `_gather_search_mode` (AND/OR) — sets `entity_mode`/`tag_mode`
5. `_gather_search_dates` (date range) — sets `created_after`/`created_before`
6. `_gather_search_mtype` (media type) — sets `media_type`
7. `_gather_search_tags` (tags) — sets `tags`
8. `_gather_search_scope` (scope) — sets `scope`

**UI changes:**
- Added **📦 Entities** button (was missing)
- Reorganized filter buttons for clarity (3 rows: Search/Clear, Workspace/Entities/Tags, Mode/Dates/Media, Scope)
- **✕ Clear** button now routes to `ctl:search:clear` (explicitly resets state) instead of `ctl:search:home`

**Result:** Users can now build compound searches incrementally (e.g., select entities → select tags → set AND/OR mode → add query → search).

---

## 13. Acceptance Criteria (Live Matrix — Ready for Owner Execution)

| ID | Scenario | Expected |
|---|---|---|
| RET-001 | Search "test" in workspace with note+media | Mixed `_type` results, badges visible |
| RET-004 | Entities: Ace, 1v4 (AND) | Only items linked to BOTH |
| RET-005 | Entities: Ace, TenZ (OR) | Items linked to either |
| RET-008 | Tags: 1v4, 1v3 (AND) | Only items with BOTH tags |
| RET-009 | Tags: 1v4, 1v3 (OR) | Items with either tag |
| RET-010 | Entities AND + Tags AND | All three filters must match |
| RET-011 | Entities OR + Tags AND | (Ace OR TenZ) AND 1v4 |
| RET-012 | Media Type: video | Only video media; notes unaffected |
| RET-013 | Query "strategy" on note | Note found in title/content |
| RET-016 | Created After: tomorrow | 0 results |
| RET-018 | Workspace A query | Zero WS_B leakage (CRITICAL) |
| RET-024 | "Show my 1v4 clips" | Video media tagged 1v4 |
| RET-026 | "Show Ace 1v4 clips" | Media linked to Ace AND tagged 1v4 |
| RET-028 | Ace 1v4 query | Only Ace (not TenZ) |
| RET-030 | WS_A query | Zero WS_B media (CRITICAL) |
| RET-031 | Worker tools registered | 3 M7 tools, READ_ONLY |
| RET-032 | Worker search_knowledge | Mixed results with `_type` |
| RET-038 | Pagination 100+ items | Page 1: 50, Page 2: next 50, no dups |