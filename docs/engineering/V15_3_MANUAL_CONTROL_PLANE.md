# v15.3 M5 — Manual Control Plane + Lifecycle

> **Status: LIVE — `/control` is admin-only, registered unconditionally (no
> new feature flag), and executes the SAME `ToolRegistry` the AI Worker
> routes through.** The directive: *"BAKA can be reliably controlled and
> repaired manually, using the same underlying tool/domain capabilities that
> AI uses."* Version: `v15.3.0-alpha.1`.

## Objective

The v15.2 M4 line (BAKA Brain — AI Worker, tool contract, typed referents,
topic projection) left the owner with **no deterministic manual path** to the
full entity/topic/workspace surface: admin control was a set of bespoke `/`
commands, workspace rename/archive/close and entity delete had **no user
surface at all**, and `render_confirmation`/`confirmation_row` (UI_SPEC §8)
were defined but unwired. M5 builds the **Manual Control Plane** on top of the
SAME tool/domain capabilities the Worker uses.

Layering (binding):

```
AI Worker ─┐
           ├─► Tool Registry (core/ai/tools.py + tool_adapters.py)
Manual     │        │
Control ───┘        ▼
Plane          Domain services (EntityEngine / WorkspaceGroups /
(core/control)  TelegramProjection / database facade)
                        │
                        ▼
              DB / Telegram topic projection
```

**Two hard rules shape every decision:**

1. **No second business-logic layer.** The dashboard never writes DB
   directly; it executes **ToolRegistry** tools that wrap the existing domain
   services. There is exactly one mutation path in the system — the registry
   — shared by the Worker and the manual plane (proved offline by
   `test_manual_path_matches_registry_domain_effects`: the same tool call
   through the manual path and the Worker path produces identical domain
   effects).
2. **No code before approval** (honoured: the plan was reviewed and the
   owner-approved decisions below were confirmed before implementation).

**Owner decisions already made (asked + approved):**
- **M5-E = minimal equipment foundation**: equip/unequip via the existing
  game-template `weapon` field + weapon/artifact entity kinds — no new schema,
  no second DB. Richer model (stats/refinement/equipped-to linkage) = M6+,
  needs a template extension.
- **Tool sharing = add thin registry tools**: the manual dashboard AND the
  Worker both execute via `ToolRegistry`. The 7 new tools expand the Worker
  catalog 30 → 37 — additive, never weakening. The pinned 30-tool selftest
  assertions were updated to 37 (deliberate, documented).

## Files changed

| File | Change |
|---|---|
| `core/ai/tool_adapters.py` | 7 new thin tools: `create_workspace`, `rename_workspace`, `close_workspace` (MUTATING), `archive_workspace`, `delete_entity` (DESTRUCTIVE + confirmation), `repair_topics` (MUTATING), `equip_item` (MUTATING, M5-E). Registry 30 → 37. |
| `core/control/__init__.py` | Package exports. |
| `core/control/pages.py` | **New.** Pure renderers returning `(text, keyboard)` built from `ui_components`/`fmt` (unit-testable without Telegram): `control_home` (M5-A state header + section nav), `workspace_page` (Open/Switch/Close/Inspect/Edit + explicit "No workspace active" state), `entity_page(kind)` (generic, fields from the template's FieldSpecs — no Genshin hardcoding), `topic_center`, `identity_inspector` (exactly 8 rows, no secrets), `entity_list`, `equip_page`. |
| `core/control/registry.py` | **New.** `ControlContext` (frozen dataclass, `with_projection` freeze), `build_context`, `build_control_registry` (= `build_tool_registry(..., projection=...)`), `execute_tool` / `execute_tool_async` (async-safe: projection resolved before `asyncio.to_thread`). |
| `core/control/actions.py` | **New.** ONE shared M5-F confirm flow: `begin_confirm` (question reads `spec.confirmation_message`), `confirm_yes` (executes via the registry), `confirm_no` / `cancel_all`. No per-feature confirm logic. |
| `core/control/router.py` | **New.** `control_cmd` (admin-only `/control`, silent denial) + `route_control_callback` for the `ctl:` namespace (`ctl:home`, `ctl:ws:*`, `ctl:ent:*`, `ctl:topic:*`, `ctl:ident:*`, `ctl:eq:*`), data-entry via `set_gathering`/`get_gathering` with the `_ctl` marker. |
| `core/workspace/groups_app.py` | **New.** `WorkspaceGroups.close_workspace(user_id)` — 1 line over `tg_bindings.clear_active(user_id)`. Row survives. |
| `main.py` | `ctl:` branch in `handle_callback` (2105), `route_control_gathering` branch (1139), `control_cmd` (4329), CommandHandler `control` (5356), help entry. |
| `ui.py` `help_cards` | Control Plane section in `/help`. |
| `core/selftest/tests/test_control_panel.py` | **New.** 2 offline probes: "Control Plane (offline registry)" + "Control Plane (pages + confirm flow)". |
| `core/selftest/tests/test_tool_adapters_selftest.py` | Pinned 30 → 37; DESTRUCTIVE confirmation check loops over all 4 destructive tools. |
| `core/selftest/tests/test_worker_selftest.py` | Pinned 30 → 37; M5 tools present + DESTRUCTIVE confirmation checks. |
| `core/ai/worker_prompt.py` | Docstring: "bounded (37 tools as of v15.3 M5; catalog rendered from `request.registry.specs()`, never a hand-written list)". |
| `core/regression/suites/control_m5.py` | **New.** CTRL-001…010 Quick-suite regression specs (category "Admin"). |
| `tests/test_control_panel.py` | **New.** 38 tests — pages/router/confirm/new-tool resolution. |
| `tests/test_m5_adversarial.py` | **New.** 41 tests — the M5-H 14-scenario × every-feature matrix, fresh names only. |
| `docs/engineering/V15_3_MANUAL_CONTROL_PLANE.md` | This document. |

**Deliberately untouched:** the second-topic/CRUD layers (there are none to
add — the registry is the single path), `database.py` schema (no new columns;
equip reuses the game `weapon` FieldSpec), `core/ai/worker*.py` logic (the
Worker gains the 7 tools for free via the shared registry), and every existing
command's behavior. `topicbackfill`/`topicrepair` were NOT given `is_admin`
gates in this change-set (see DEBUGGING.md — tracked follow-up, no silent
behavior change).

## The new tools (all thin wrappers)

| Tool | Risk | Wraps |
|---|---|---|
| `create_workspace` | MUTATING | `WorkspaceGroups.create` (creates + activates) |
| `rename_workspace` | MUTATING | `engine.rename_workspace` |
| `close_workspace` | MUTATING | `WorkspaceGroups.close_workspace` → `tg_bindings.clear_active` — **never deletes the row** |
| `archive_workspace` | DESTRUCTIVE + confirm | `engine.archive_workspace` (soft lifecycle transition) |
| `delete_entity` | DESTRUCTIVE + confirm | `engine.delete_milestone` (soft-delete — **never the topic**) |
| `repair_topics` | MUTATING | `WorkspaceGroups.repair_topics` (idempotent report dict) |
| `equip_item` | MUTATING | resolve item (kind weapon/artifact), validate, `engine.update_field(character, "weapon", item.title)`; `item` omitted clears the field (unequip) |

Every one wraps the SAME domain method a Worker/manual command already calls.
The DESTRUCTIVE pair carries `confirmation_message` and is therefore
mechanical-confirmation-gated in BOTH the Worker (`core/ai/worker.py`) and the
manual M5-F flow.

## Design decisions

### The no-second-logic rule (M5 core)

The dashboard is a **view + router**, never a second implementation. `pages.py`
is pure rendering; `actions.py` only decides whether to confirm and then calls
`execute_tool_async` → `registry.execute`; `router.py` maps `ctl:` callbacks to
pages/tools. The proof is structural: `build_control_registry` is
`build_tool_registry` with a projection — literally the same object graph the
Worker runs through. `WorkerRequest` and the manual flow differ only in *who
decides* (a model vs. the owner), never in *what runs*.

### Threading contract (core/control/registry.py)

`TelegramProjection` must be built in async context. `ControlContext` freezes
the projection: `with_projection(projection)` sets `_projection` and clears
the factory; `ctx.projection()` returns the frozen projection if set, else
builds from the factory, else None. `build_control_registry` and
`execute_tool_async` MUST use `ctx.projection()` unconditionally — never the
raw factory. This is the two bug fixes from the prior session, now pinned by
tests.

### Topic invariants preserved

- ONE canonical topic per `(workspace_id, entity_type, entity_id)`.
- `delete_entity` (soft-deletes the DB row) and `delete_entity_topic` (removes
  the Telegram topic) are DISTINCT tools — deleting a topic never deletes the
  entity, and vice versa (pinned by the M4 + M5 tests).
- Locked topics refuse ordinary deletes; the topic_center shows
  `[Unlock][Force Delete][Cancel]` for a locked topic, and force-delete goes
  through the M5-F confirm flow.

### M5-E equipment boundary

Minimal on purpose: `equip_item` writes the game template's existing `weapon`
string field. A character is equippable; an item is a weapon/artifact-kind
entity; a weapon cannot be equipped onto a weapon (wrong-kind refused, nothing
written). Stats, refinement, and an equipped-to *linkage* are M6+ — they need a
template extension, not a second DB, and are explicitly out of scope here.

### M5-F: one shared confirm flow

Every confirmation-gated operation — archive/delete entity, force-delete topic,
DESTRUCTIVE tasks — routes through `actions.py`'s `begin_confirm`/`confirm_yes`/
`confirm_no`. The question text comes from the tool spec's
`confirmation_message`, so there is exactly one confirm implementation and zero
per-feature confirm logic.

## Tests

- `tests/test_m5_adversarial.py` (41) — the M5-H matrix: 14 scenarios × every
  feature (workspace control, entity CRUD per kind, topic lifecycle, identity
  inspector, equip, task/goal/habit foundation), fresh names only
  (`M5_Test_Character_A/B`, `M5_Test_Weapon_A`, `M5_Test_Artifact_A`,
  `M5_Test_Adopt_A`, `M5_Test_WS_A/B`).
- `tests/test_control_panel.py` (38) — pages render offline, the confirm flow
  sets/clears pending actions without executing, `execute_tool_async` matches
  the Worker's registry, new tools resolve, `ctl:` dispatch.
- M5 tool tests in `tests/test_tool_adapters.py`.
- Selftest probes: `core/selftest/tests/test_control_panel.py` (2 new) +
  30→37 pin updates in the two worker/registry probes.
- Regression specs: `core/regression/suites/control_m5.py` (CTRL-001…010).

## Remaining gate

The **live-Telegram acceptance matrix** (owner-run, WKR-style): CTRL-001…010
drive `/control`, the workspace lifecycle (incl. the no-active state), entity
CRUD per kind, topic center, identity inspector, equip, and the shared confirm
flow against the real bot. This is documented as the remaining gate in
ROADMAP/README — offline coverage proves the surface is healthy, but live
acceptance is the owner's call.
