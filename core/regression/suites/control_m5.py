"""Quick Release Suite: v15.3 M5 — Manual Control Plane + Lifecycle.

Owner-run manual tests for the v15.3.0 line — the /control dashboard that
drives the SAME ToolRegistry the AI Worker uses (create/close/archive
workspace, entity CRUD per kind, the topic control center, identity
inspector, minimal equipment). These need a live bot (admin + Telegram), so
they live in the manual Quick Release Suite, not the offline pytest suite.
The offline equivalents of every invariant here are pinned in
tests/test_control_panel.py, tests/test_m5_adversarial.py and the
core/selftest/tests/test_control_panel.py probes.

Live-Telegram acceptance is the remaining gate on v15.3 M5 (see
V15_3_MANUAL_CONTROL_PLANE.md §Acceptance).
"""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})
_ADMIN = "Admin"


def _t(**kw):
    register(RegressionTest(**kw))


# ── M5-A: workspace control ────────────────────────────────────────────────
_t(
    test_id="CTRL-001", category=_ADMIN, feature="Control Plane entry",
    introduced_version="v15.3.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("The owner opens the Manual Control Plane and sees the state "
               "header + section navigation; non-owners are denied silently."),
    preconditions="Private chat with the bot as the owner.",
    steps=("Send: /control", "In a non-owner chat, send: /control"),
    expected=("The control home page renders: Current workspace header (or a "
              "no-active state) + Workspace / Entities / Topics / Identity / "
              "Equipment sections",
              "A non-owner gets the ordinary 'Unknown command' reply "
              "(deliberate obscurity, CLAUDE.md)"),
    failure_conditions=("No reply or a crash on /control",
                        "A non-owner reaches the control plane"),
)

_t(
    test_id="CTRL-002", category=_ADMIN, feature="Workspace lifecycle",
    introduced_version="v15.3.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective=("Create, rename, open/switch, close and archive a workspace "
               "through the control plane."),
    preconditions="Owner private chat; /control open.",
    steps=("Workspaces → Create → send 'CTRL Test | game' → confirm",
           "Workspaces → Inspect the new workspace",
           "Rename it and confirm",
           "Close it and confirm",
           "Re-open it and confirm",
           "Archive it and confirm"),
    expected=("Each step shows the shared Result page (one confirm flow)",
              "Close clears the active context but the workspace row remains "
              "listed and re-openable",
              "Archive transitions the workspace to archived (soft — nothing "
              "is deleted); the confirm wording says so"),
    failure_conditions=("Close deletes the workspace row (must never happen)",
                        "Archive hard-deletes entities",
                        "Confirm cancelling executes the action anyway"),
)

_t(
    test_id="CTRL-003", category=_ADMIN, feature="No-active state",
    introduced_version="v15.3.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=30, suites=_QUICK,
    objective=("With no active workspace, the control plane says so plainly "
               "and every entity/topic page guides back instead of crashing."),
    preconditions="Owner private chat; no active workspace.",
    steps=("Send: /control", "Open Entities, Topics, Equipment"),
    expected=("Home shows an explicit 'No workspace active' state",
              "Entities/Topics/Equipment render a clear no-active prompt "
              "with a Workspaces shortcut — no crash, no empty lists"),
    failure_conditions=("A crash on any page with no active workspace",
                        "A page silently pretending a workspace is active"),
)

# ── M5-B: entity control ───────────────────────────────────────────────────
_t(
    test_id="CTRL-004", category=_ADMIN, feature="Entity CRUD per kind",
    introduced_version="v15.3.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective=("Add, view, edit and delete Character / Weapon / Artifact "
               "entities through the generic entity pages (no Genshin "
               "hardcoding)."),
    preconditions="A workspace is active (CTRL-002 or an existing one).",
    steps=("Entities → Add Character → send 'CTRL Character' → confirm",
           "Add a Weapon 'CTRL Weapon' and an Artifact 'CTRL Artifact'",
           "View the character (fields from the template's schema)",
           "Edit its level via name=value lines and confirm",
           "Delete the artifact via its detail page and confirm"),
    expected=("Each kind page lists only that kind",
              "Fields offered match the workspace template "
              "(schema-permitting)",
              "Delete asks for confirmation (soft-delete; any topic stays)",
              "The entity list reflects every change"),
    failure_conditions=("A character appears under Weapons",
                        "A field not in the schema is written",
                        "Delete removes the Telegram topic too"),
)

_t(
    test_id="CTRL-005", category=_ADMIN, feature="Entity duplicate guard",
    introduced_version="v15.3.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.REPEATED, estimated_seconds=30, suites=_QUICK,
    objective=("Adding the same entity name twice never creates a second row "
               "or a second topic."),
    preconditions="A linked workspace; CTRL Character already exists.",
    steps=("Entities → Add Character → send 'CTRL Character' again",),
    expected=("The flow refuses ('already exists' / adopts the kind) and no "
              "second row or topic appears",
              "Exactly one topic named 'CTRL Character' exists in the group"),
    failure_conditions=("A duplicate row or duplicate topic is created"),
)

# ── M5-C: topic control center ─────────────────────────────────────────────
_t(
    test_id="CTRL-006", category=_ADMIN, feature="Topic lifecycle",
    introduced_version="v15.3.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=60, suites=_QUICK,
    objective=("Ensure, lock, unlock and delete an entity's Telegram topic "
               "from the Topic Center; a locked topic shows [Unlock] [Force "
               "delete] [Back]."),
    preconditions="A linked workspace with an entity (CTRL-004).",
    steps=("Topics → pick 'CTRL Character' → Ensure",
           "Lock the topic",
           "Try Delete on the locked topic",
           "Unlock it",
           "Delete it and confirm"),
    expected=("Ensure creates the topic + the canonical binding (one topic)",
              "Deleting a locked topic offers Force delete instead of a plain "
              "confirm; Force delete keeps the entity",
              "Ordinary delete removes ONLY the topic — the entity stays "
              "listed and re-ensurable"),
    failure_conditions=("Delete removes the DB entity",
                        "Two topics for one entity",
                        "A locked topic is deleted without force"),
)

_t(
    test_id="CTRL-007", category=_ADMIN, feature="Topic repair",
    introduced_version="v15.3.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.RECOVERY, estimated_seconds=90, suites=_QUICK,
    objective=("Repair reconciles missing topics and title-duplicates onto one "
               "canonical topic, preserving locks, and is idempotent."),
    preconditions=("A linked workspace; optionally a deliberately missing "
                   "topic or a duplicated entity row."),
    steps=("Topics → Repair and confirm",
           "Run Repair again immediately"),
    expected=("Repair reports Healthy/Missing/Duplicate state and creates only "
              "missing topics / collapses duplicates",
              "A second run reports existing state (idempotent)",
              "Locks survive repair"),
    failure_conditions=("Repair deletes data",
                        "Repair duplicates a topic",
                        "A second run re-creates topics"),
)

# ── M5-D: identity inspector ───────────────────────────────────────────────
_t(
    test_id="CTRL-008", category=_ADMIN, feature="Identity Inspector",
    introduced_version="v15.3.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=30, suites=_QUICK,
    objective=("The inspector shows exactly the 8 identity rows for an entity "
               "and never leaks secrets or raw note text."),
    preconditions="An active workspace with an entity.",
    steps=("Identity → pick 'CTRL Character' (or the active entity)",),
    expected=("Rows: Name / Entity ID / Kind / Workspace / Topic ID / Topic "
              "status / Lock status / Active",
              "A deleted entity reads as 'not found' (no ghost row)"),
    failure_conditions=("More or fewer than the 8 identity rows",
                        "Secrets, notes or raw content rendered"),
)

# ── M5-E: equipment foundation ─────────────────────────────────────────────
_t(
    test_id="CTRL-009", category=_ADMIN, feature="Equipment (minimal)",
    introduced_version="v15.3.0-alpha.1", priority=Priority.MEDIUM,
    scenario=ScenarioClass.NORMAL, estimated_seconds=45, suites=_QUICK,
    objective=("Equip and unequip a Weapon onto a Character via the "
               "character's 'weapon' field (M5-E minimal — no second "
               "database)."),
    preconditions="A workspace with CTRL Character and CTRL Weapon.",
    steps=("Equipment → pick CTRL Character → Equip CTRL Weapon",
           "Equipment → pick CTRL Character → Unequip"),
    expected=("The character's weapon field now reads CTRL Weapon",
              "Unequip clears it; an Artifact can never be equipped"),
    failure_conditions=("Equipping an artifact or equipping onto a weapon "
                        "succeeds",
                        "The weapon field accepts a non-weapon"),
)

# ── M5-F: shared confirm flow ──────────────────────────────────────────────
_t(
    test_id="CTRL-010", category=_ADMIN, feature="Shared confirmation (M5-F)",
    introduced_version="v15.3.0-alpha.1", priority=Priority.HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=45, suites=_QUICK,
    objective=("Every destructive / data-entry action uses ONE confirm flow "
               "with spec-driven wording; Cancel discards without executing."),
    preconditions="An active workspace with an entity.",
    steps=("Entities → Delete 'CTRL Artifact' → Cancel",
           "Workspaces → Archive → Cancel",
           "Repeat one destructive action and choose Confirm"),
    expected=("Cancel returns to the prior page and nothing changed",
              "The confirm question wording comes from the tool spec",
              "Confirm executes and shows a Result page with Back"),
    failure_conditions=("Cancel executes the action",
                        "Different actions use different confirm UIs"),
)
