# v15.4 M6 — Knowledge + Media + Tags

**Status:** shipped as `v15.4.0-alpha.1`  
**Owner-run gate remaining:** live-Telegram acceptance matrix KNOW-001…012 (documented, not claimed offline)

---

## 1. Purpose

BAKA becomes a persistent personal knowledge/data-dump system: **notes + media metadata + tags**, retrievable by entity/topic/tag/workspace/text/media-type/date, with **Telegram as canonical media storage**.

Binding layering (unchanged from M5):
```
Worker → Tool Registry → Domain Service → DB / Telegram projection
Manual Control Plane → Tool Registry → same Domain Service
```
**No second business-logic path.** The dashboard never writes the DB directly; it executes the SAME `ToolRegistry` the AI Worker uses.

---

## 2. Schema Extension (additive, idempotent — `database.py::init_db()`)

All `ALTER TABLE ... ADD COLUMN` run inside `try/except: pass` — the v15 convention. A fresh DB and an old DB converge to the same state on next startup.

### 2.1 `notes` (existing) — +3 columns
| Column | Type | Purpose |
|---|---|---|
| `title` | `TEXT` | Note title (was implicit from content) |
| `updated_at` | `TEXT` | IST timestamp of last update (mirrors milestones) |
| `deleted_at` | `TEXT` | Soft-delete stamp (excluded from normal queries) |

Legacy single `milestone_id` column is **kept** (the note's "primary entity") so existing entity-note features keep working. The many-to-many `note_entities` is ADDITIONAL (0..N links).

### 2.2 `attachments` (existing) — +8 columns
| Column | Type | Purpose |
|---|---|---|
| `message_id` | `INTEGER` | Telegram message ID |
| `chat_id` | `INTEGER` | Telegram chat ID |
| `topic_id` | `INTEGER` | Telegram topic ID |
| `entity_type` | `TEXT` | Stable discriminator (`milestone`/`note`/`attachment`) |
| `entity_id` | `INTEGER` | Target entity ID |
| `extracted_text` | `TEXT` | OCR/transcript for search |
| `updated_at` | `TEXT` | IST timestamp |
| `deleted_at` | `TEXT` | Soft-delete stamp |

### 2.3 `tags` (existing) — +1 column + index
| Column | Type | Purpose |
|---|---|---|
| `workspace_id` | `INTEGER` (nullable) | Workspace scoping; NULL = legacy global tag |

**Partial unique index:** `(workspace_id, name) WHERE workspace_id IS NOT NULL` — same name in different workspaces = distinct tags.

### 2.4 New: `note_entities` (junction table)
```
note_entities(id, note_id, entity_type, entity_id, created_at)
```
Indexes: `note_id` and `(entity_type, entity_id)`.  
**Stable discriminator:** `entity_type` = `ENTITY_TYPE` constant (`"milestone"`) — not the semantic `milestone.entity_type` (e.g. `"character"`).

### 2.5 New: `attachment_entities` (junction table)
```
attachment_entities(id, attachment_id, entity_type, entity_id, created_at)
```
Same indexes and discriminator convention.

### 2.6 Tag link table: REUSED
`entity_tags(tag_id, entity_type, entity_id)` (legacy global tag table) now serves as the generic tag-link table for `milestone` + `note` + `attachment`. No per-resource tag junction tables. This is why `TagStorage.for_entity()` and `.for_target()` exist.

---

## 3. Domain Service (`core/workspace/`)

Extended the existing facade + engine (WED pattern), no new package.

### 3.1 `core/storage/storage.py`
- **`NoteStorage`** — `get/update/soft_delete/search/link_entity/unlink_entity/link_tag/unlink_tag`
- **`AttachmentStorage`** (new) — `add/get/update/soft_delete/list/search/link_entity/unlink_entity/link_tag/unlink_tag`
- **`TagStorage`** (new) — `create/rename/delete/list/for_entity/for_target`

### 3.2 `core/workspace/repository.py`
Model-shaped CRUD for all M6 resources (notes, media, tags, entity/tag links).

### 3.3 `core/workspace/engine.py` — `EntityEngine`
Ownership-checked methods for all M6 tools:
- **Notes:** `create_note/update_note/delete_note/get_note/list_notes/link_note_entity/unlink_note_entity/link_note_tag/unlink_note_tag`
- **Media:** `store_media/update_media/delete_media/get_media/list_media/link_media_entity/unlink_media_entity/link_media_tag/unlink_media_tag`
- **Tags:** `create_tag/rename_tag/delete_tag/list_tags`

**Cascade on entity soft-delete:** `delete_milestone` now removes all `note_entities` and `attachment_entities` rows for that entity (no ghost refs). This is the single choke-point; the storage layer's `soft_delete_milestone` is untouched.

**Timeline events (KTD):** emit `knowledge.added` / `file.uploaded` on create (cheap, matches the existing engine `_emit` discipline).

---

## 4. Tool Registry (37 → 60, additive, thin wrappers)

Every tool wraps the SAME domain method the control plane and Worker call. DESTRUCTIVE tools carry `confirmation_message` → the existing mechanical gate (Worker `CONFIRMATION_NEEDED` + M5-F manual flow).

### 4.1 Notes (10)
| Tool | Risk | Confirmation |
|---|---|---|
| `create_note` | MUTATING | — |
| `update_note` | MUTATING | — |
| `delete_note` | DESTRUCTIVE | ✅ "Soft-deletes the note..." |
| `get_note` | READ_ONLY | — |
| `list_notes` | READ_ONLY | — |
| `link_note_entity` | MUTATING | — |
| `unlink_note_entity` | MUTATING | — |
| `link_note_tag` | MUTATING | — |
| `unlink_note_tag` | MUTATING | — |
| `post_note` | MUTATING | — |

**Resolution contracts (deterministic):**
- `note` arg = integer id (Worker lists/searches first; never invents one)
- `tag` arg = name string resolved within the workspace (link tools resolve-or-create — "dump this under 1v4" creates the tag in one call)
- `entity` arg = name or `#id` via the existing entity resolver

### 4.2 Media (9)
| Tool | Risk | Confirmation |
|---|---|---|
| `store_media` | MUTATING | — |
| `update_media` | MUTATING | — |
| `delete_media` | DESTRUCTIVE | ✅ "Soft-deletes the media metadata record..." |
| `get_media` | READ_ONLY | — |
| `list_media` | READ_ONLY | — |
| `link_media_entity` | MUTATING | — |
| `unlink_media_entity` | MUTATING | — |
| `link_media_tag` | MUTATING | — |
| `unlink_media_tag` | MUTATING | — |

**Media metadata recorded:** `file_id`, `media_type` (`photo|video|document|audio`), `caption`, `message_id`, `chat_id`, `topic_id`, `entity_type`, `entity_id`, `extracted_text`, `updated_at`, `deleted_at`. The Telegram file itself is NEVER touched.

### 4.3 Tags (4)
| Tool | Risk | Confirmation |
|---|---|---|
| `create_tag` | MUTATING | — (idempotent) |
| `rename_tag` | MUTATING | — |
| `delete_tag` | DESTRUCTIVE | ✅ "Permanently deletes the tag and all its links..." |
| `list_tags` | READ_ONLY | — |

---

## 5. Media Capture (additive, documented)

New `MessageHandler(filters.VIDEO | filters.DOCUMENT | filters.AUDIO | filters.VOICE)` in `main.py` that, when a media message arrives, records metadata via the domain service — linked to the active workspace + active entity (or the topic's entity via `tg_entity_topics` when in a thread). Purely additive (no existing handler for these types). Replies a short confirmation; errors never crash the message.

**Photos are NOT re-routed** — `handle_photo` keeps its progress-log/vision priority. Photo→media recording is a documented follow-up (needs a priority decision for the consolidated live pass).

Media resend from the dashboard uses the stored `file_id` via the existing projection client (view action, not a new business path).

---

## 6. Control Plane (`core/control/`)

Extended `pages.py` + `router.py` with three sections (all pure renderers → tools → domain; same M5-F confirm; `_ctl` gathering for data entry):

### 6.1 Knowledge
- `ctl:note:list` — per-workspace note list w/ search box
- `ctl:note:view:<id>` — content + links + tags + edit/delete/post buttons
- `ctl:note:add` — gather title/content
- `ctl:note:edit` — gather edits
- `ctl:note:del` — confirm (shared M5-F flow, reads tool spec's `confirmation_message`)
- `ctl:note:link-ent` / `ctl:note:link-tag` — gather

### 6.2 Media
- `ctl:media:list` — filter by type/entity/tag/search
- `ctl:media:view:<id>` — metadata + file_id + resend + link/delete buttons
- `ctl:media:del` — confirm
- `ctl:media:link-*` — gather

### 6.3 Tags
- `ctl:tag:list` — per workspace
- `ctl:tag:view:<id>` — linked notes/media/entities
- `ctl:tag:add` / `ctl:tag:rename` / `ctl:tag:del` — confirm

`/control` home gains the three new section nav entries; `/help` updated.

---

## 7. Worker Integration

The 23 M6-related tools register in the same `build_tool_registry` → the Worker inherits them (catalog renders from `registry.specs()` — no prompt change needed). Confirmation gate, never-fabricate-success guard, and tool-result-authoritative rules apply automatically. `MAX_TOOL_CALLS=6` unchanged.

---

## 8. Topic Integration Decision (spec §8 — documented)

Notes/media are **DB-first**. Projection to Telegram is **OPTIONAL and explicit**, reusing the existing canonical topic system:

- **A)** A note/media linked to an entity is projected to that entity's topic via the existing `TelegramProjection.post_entity_update` (append message) — the "Arlecchino build notes" flow. `create_note`/`store_media` accept an optional `project=True` (or the control-plane "Post to topic" action).
- **B/C)** A knowledge category never auto-creates a new Telegram topic. A "knowledge entity" is an ordinary workspace entity (the knowledge template); creating it goes through the existing entity flow.
- **D)** By default a note/media is a DB record only.
- `delete_note`/`delete_media` remove the DB record + links; they **NEVER** delete the Telegram topic or message (matching M5's delete≠topic rule).

---

## 9. Search Foundation (deterministic LIKE)

- `NoteStorage.search` and `AttachmentStorage.search` use `LIKE` on `title/content` (notes) and `caption/file_name/extracted_text` (media) + filter JOINs.
- FTS5 (KTD §7) and embeddings/vector are documented **FUTURE** extensions — not built in M6 (spec §11).

---

## 10. Tests (fresh names only: `M6_Book_Test`, `M6_Ace_Test`, `M6_1v4_Test`, `M6_Arlecchino_Test`, `M6_Clip_Test`, `M6_Note_Test`, `M6_WS_A/B`)

| File | Tests | Matrices |
|---|---|---|
| `tests/test_m6_knowledge.py` | 35 | A (note CRUD), B (entity/tag links, deleted entity no ghost link), C (media metadata), D (search + combined filters), E (workspace/entity/tag isolation) |
| `tests/test_m6_adversarial.py` | 21 | F (confirmation gates), G (Worker integration), H (manual=Worker path), I (abuse/hostile input) |
| `tests/test_tool_adapters.py` | +M6 | M6 tool surface + risk classification tests added |
| `tests/test_control_panel.py` | 38 | M5 control plane + M6 Knowledge/Media/Tags pages |
| `core/selftest/tests/test_knowledge_selftest.py` | 3 | M6 registry risk/surface, round-trip note+media+tag, control pages render |

**Failure policy (binding):** never weaken/delete a failing test — investigate, fix the implementation, rerun, report.

---

## 11. Regression Suite

`core/regression/suites/knowledge_m6.py` — **KNOW-001…012** (Admin + AI categories, Quick suite). Live-Telegram acceptance is the remaining gate (documented, not claimed offline).

---

## 12. Version

**`v15.4.0-alpha.1`** (existing `v15.N.0-alpha.M` convention). Bump `BAKA_VERSION` at `main.py:216`. No commit, no push.

---

## 13. Verification (end-to-end)

1. Full `pytest` — pass count ≥ 1769 with only the 5 known date-flakes.
2. Offline `/selftest` — ≥ 30 pass with only the 2 known date-flakes.
3. `py_compile` on every changed module; `git diff --check` clean.
4. Offline drill: each new tool + control callback on a temp DB with a recording FakeClient; manual path and Worker path produce identical domain effects (no-second-logic proof).
5. Regression spec runnable; selftest probes green.
6. Live acceptance deferred to the consolidated pass (M5+M6+later) per spec §14.