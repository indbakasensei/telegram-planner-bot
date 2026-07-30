# WED — Workspace Engine Design (v15.0)

*Design only. Pseudo-schema and pseudo-interfaces, not production code.*

## 1. Purpose & principle

A **Workspace** is the single top-level organizational unit. Project,
Book, Game, Course, Research, Travel, Vehicle, Inventory, Client, Study,
Personal Goal, Collection — all are Workspaces. **The only difference
between them is their Template.** Internally they share one engine, one
schema, one lifecycle.

Package: `core/workspace/` (new), gated by `feature_flags.WORKSPACE`
(default OFF — the engine ships complete and dark, then a canary
enables it, exactly like the Offline Engine).

## 2. Entity model

```
Workspace  1───*  Goal  1───*  Milestone  1───*  Task
    │                              (Tasks may also attach directly to a Workspace)
    ├── Notes / Knowledge
    ├── Attachments (files)
    ├── Tags
    ├── Timeline events (append-only; see KTD)
    └── AI Summary (derived)
```

Hierarchy for progress rollup: **Workspace → Goals → Milestones → Tasks
→ Timeline**. A Task may belong to a Milestone, a Goal, or directly to
the Workspace (Milestone/Goal optional — an Inbox task has none).

## 3. Database design (additive)

New tables + **nullable** `workspace_id`/`milestone_id` columns on
existing tables. Follows `init_db()`'s additive, idempotent
ALTER-in-try/except convention; every FK is nullable so existing rows
(and flag-OFF operation) are valid unchanged.

```sql
-- NEW
workspaces (
  id INTEGER PK, user_id INTEGER NOT NULL,
  template TEXT NOT NULL DEFAULT 'generic',     -- template key (see §6)
  title TEXT NOT NULL,
  status TEXT DEFAULT 'active',                 -- active | archived | done
  icon TEXT,                                    -- from template default, overridable
  metadata TEXT,                                -- JSON: template-specific fields
  ai_summary TEXT,                              -- derived, refreshed by AWOD
  telegram_topic_id INTEGER,                    -- nullable; set by TWID on sync
  sort_order INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  archived_at TEXT
)

milestones (
  id INTEGER PK, workspace_id INTEGER NOT NULL, goal_id INTEGER,
  title TEXT NOT NULL,
  status TEXT DEFAULT 'todo',                   -- todo | in_progress | done | blocked
  progress INTEGER DEFAULT 0,                   -- 0..100, or derived from child tasks
  sort_order INTEGER DEFAULT 0,
  fields TEXT,                                  -- JSON: per-entity structured fields (v15.1.0-alpha.9)
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT
)

notes (                                         -- unified knowledge store
  id INTEGER PK, workspace_id INTEGER NOT NULL, milestone_id INTEGER,
  kind TEXT DEFAULT 'note',                     -- note | knowledge | journal
  content TEXT NOT NULL,
  source TEXT DEFAULT 'user',                   -- user | ai
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
)

attachments (
  id INTEGER PK, workspace_id INTEGER NOT NULL, note_id INTEGER,
  telegram_file_id TEXT,                        -- Telegram is the blob store
  file_type TEXT, file_name TEXT, caption TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
)

tags (id INTEGER PK, user_id INTEGER NOT NULL, name TEXT NOT NULL)
entity_tags (tag_id INTEGER, entity_type TEXT, entity_id INTEGER)   -- generic tagging

-- timeline_events, search_index: see KTD

-- EXTENDED (nullable adds; existing rows unaffected)
ALTER TABLE tasks    ADD COLUMN workspace_id INTEGER;   -- NULL = Inbox
ALTER TABLE tasks    ADD COLUMN milestone_id INTEGER;
ALTER TABLE goals    ADD COLUMN workspace_id INTEGER;
ALTER TABLE memories ADD COLUMN workspace_id INTEGER;   -- NULL = Personal/Inbox
```

**Why not new task/goal tables?** Reusing `tasks`/`goals` means every
existing feature (reminders, recurrence, deadlines, streaks, dashboard,
Offline Engine) keeps working verbatim — a task is still a task; it just
optionally names a workspace. This is the single most important
no-regression decision.

## 3a. Entity-level structured fields (v15.1.0-alpha.9)

Each milestone can carry **template-defined structured fields** — typed,
validated attributes beyond the generic `title`/`status`/`progress`. These are
stored as a JSON `fields TEXT` column on `milestones`, the same additive NULL-safe
pattern as `workspaces.metadata`.

### Schema

```sql
ALTER TABLE milestones ADD COLUMN fields TEXT;  -- NULL → {} at read time
```

Each template declares its entity-level fields via `entity_fields` on its
`WorkspaceTemplate` registration, using the canonical `FieldSpec` dataclass
(living in `core/workspace/templates/registry.py`):

```python
@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    kind: str                    # "str" | "int" | "enum" | "json"
    required: bool = False
    default: object = None
    choices: tuple = ()
    minimum: int | None = None
    maximum: int | None = None
```

### Validation & normalization (engine-driven)

The Entity Engine's `set_fields()` / `update_field()` call the registry's
template-agnostic helpers:

- **`validate_entity_fields(template_key, fields)`** — returns a list of
  error messages (empty → valid). Checks enum membership, integer ranges,
  type conformance. Unknown keys pass through (forward-compatible).
- **`normalize_entity_fields(template_key, fields)`** — fills defaults from
  the schema, coerces int-like strings, drops explicit `None` values.

The engine is never template-aware; it delegates to these helpers with the
workspace's `template` key.

### Template field definitions

| Template | Fields |
|---|---|
| **Game** | `level` (int), `element` (str), `weapon_type` (str), `talent_domain` (str), `materials` (json), `ascension_phase` (int, 0–6), `target_level` (int, 1–100), `priority` (enum) |
| **Knowledge** | `difficulty` (enum), `review_count` (int), `mastery_level` (int, 0–100), `source_type` (str), `key_concepts` (json), `next_review` (str) |
| **Asset** | `component_type` (str), `specifications` (json), `install_date` (str), `lifecycle_status` (enum), `maintenance_interval_days` (int), `last_service_date` (str) |
| **Project** | `effort_hours` (int), `priority` (enum), `dependencies` (json), `phase_status` (enum), `assignee` (str), `target_date` (str) |

### Retrieval integration

`WorkspaceRetriever._candidates()` appends scalar field values to each
milestone's searchable text, so a query like "Pyro character level 80"
discovers the entity through its fields — no special query syntax needed.

### Future scalability note

The `fields TEXT` JSON column works well for per-entity storage and
retrieval, but **querying individual field values in SQL** (e.g. "find all
entities with `level >= 80`") is not efficient — JSON extraction in
SQLite uses a table scan. This is the right trade-off today: the AI
retrieval layer answers "what has high level" through searching, and
schema complexity stays low. If structured queries against individual
fields become a bottleneck (e.g. leaderboards, sorted listings), a future
milestone should migrate the most-queried fields to indexed columns.

## 4. Storage Facade extension

New facade domains under `core/storage/` (thin one-line delegations to a
new `database.py` section — same discipline as `TaskStorage`/
`HabitStorage` etc.):

```
WorkspaceStorage:  add/get/list/update/archive/set_topic/set_summary
MilestoneStorage:  add/get/list_for/complete/reorder/progress
NoteStorage:       add/list_for/search
AttachmentStorage: add/list_for
TagStorage:        tag/untag/for_entity/entities_for_tag
```

`Storage()` gains `.workspaces / .milestones / .notes / .attachments /
.tags`. The Workspace Engine calls only the facade — never raw SQL, never
`database.py` directly — matching the AST-enforced purity of `core/`.

## 5. Entity lifecycle

```
Workspace:  create(active) ──▶ progress via milestones ──▶ done | archived
Goal:       create ──▶ milestones complete ──▶ met
Milestone:  todo ──▶ in_progress ──▶ done (or blocked)
Task:       (unchanged) open ──▶ done ; optionally tied to a milestone
```

- **Progress rollup** (derived, never hand-entered): milestone progress
  = % of its done tasks (if it has tasks) else its explicit `progress`;
  goal progress = % done milestones; workspace progress = weighted goal
  progress. Computed on read (cheap) or cached in `metadata`.
- **Every transition emits a Timeline event** (KTD) — create workspace,
  add/complete milestone, change progress, add note, attach file.
- **Completion is natural-language-driven** (AWOD): "I finished the CAD"
  → resolve workspace → find milestone "CAD" → mark done → timeline →
  refresh summary → sync. No explicit command required.

## 6. Template system (composition, not inheritance)

A **Template** is a registered config object, not a Workspace subclass.
Registration mirrors `ActionRegistry`/selftest/regression:

```
core/workspace/templates/
    registry.py         @template("book") / register(WorkspaceTemplate(...))
    project.py  book.py  course.py  game.py  research.py  workout.py
    vehicle.py  travel.py  inventory.py  client.py  study.py  generic.py
```

```python
@dataclass(frozen=True)
class WorkspaceTemplate:
    key: str                       # "book", "project", ...
    label: str                     # "Book"
    icon: str                      # "📖"
    sections: tuple[str, ...]      # which views this template shows
    default_milestones: tuple[str, ...]   # seeded on create
    metadata_fields: tuple[str, ...]      # template-specific metadata keys
    progress_model: str            # "milestones" | "chapters" | "checklist" | "manual"
```

Examples:
- **book**: 📖, sections `(chapters, notes, quotes, summary)`,
  metadata `(author, total_chapters, current_chapter)`,
  progress_model `chapters`.
- **project**: 🛠, sections `(goals, milestones, tasks, materials,
  worklog, files)`, seeded milestones `(Research, Design, Prototype,
  Testing, Documentation)`, progress_model `milestones`.
- **course/study**: 🎓, sections `(modules, notes, deadlines)`.
- **generic**: the fallback (what an unclassified "workspace" gets).

The engine is template-agnostic: it stores the `template` key and asks
the registry for the config when rendering a view or seeding defaults.
Adding a template = one file; the engine never changes (Open/Closed).

## 7. Views

A Template's `sections` select which read-models the UI renders — all
composed from the same engine data (Workspaces/Milestones/Tasks/Notes/
Timeline). No template gets its own storage or engine path. UI is a v15
implementation-phase concern (design in a later milestone); the engine
exposes the data, the Template names the sections.

## 8. What this preserves (constraints check)

- **Tasks/Habits/Reminders/Deadlines/Recurrence:** untouched tables +
  behaviour; gain an optional `workspace_id` (NULL = Inbox).
- **Projects:** become Workspaces of template `project`; `project_materials`
  / `project_worklog` map to the project template's material/worklog
  sections (see MIGRATION) — no data moved, referenced by `workspace_id`.
- **Goals:** gain `workspace_id`; standalone goals live in Inbox.
- **Memory:** gains `workspace_id`; unassigned memories are Personal/Inbox
  knowledge; the memory commands keep working.
- **Offline Engine / Intent / Routing / Storage Facade:** unchanged;
  Workspace is a *new* facade domain + engine beside them.
- **Flag OFF ⇒ zero behavioural change.** Regression suite is the proof.
