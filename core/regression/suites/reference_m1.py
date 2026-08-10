"""Quick Release Suite: M1 conversational entity references (v15.1.0-alpha.12).

Manual Telegram acceptance tests for reference resolution + active entity:
pronouns ("show her"), ordinals ("show the first one"), deterministic
single-field updates ("Xiao is level 70"), ambiguity clarification, and
stale/deleted-entity self-heal. These need a live bot, so they live in the
manual Quick Release Suite, not the offline pytest suite (the deterministic
resolver logic itself is covered offline by tests/test_reference_resolution.py).

Acceptance characters (Genshin test workspace): Xiao, Kinich, Xilonen,
Nefer, Lauma, Columbina.
"""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})
_HIGH = Priority.HIGH
_MED = Priority.MEDIUM


def _t(**kw):
    register(RegressionTest(**kw))


# ── Create + active entity ─────────────────────────────────────────────────
_t(
    test_id="REF-001", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=20, suites=_QUICK,
    objective="Creating an entity makes it the active entity.",
    preconditions="Active Genshin workspace; Xiao not already created (or use "
                  "a fresh name).",
    steps=("Send: Create character Xiao",),
    expected=("Confirms Xiao was created and shows its (empty) detail card",
              "Send: current — shows Xiao as the active entity"),
    failure_conditions=("Xiao not created", "Active entity is not Xiao"),
)

_t(
    test_id="REF-002", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=15, suites=_QUICK,
    objective="A bare pronoun reference resolves to the active entity without "
              "an LLM call.",
    preconditions="An entity is active (REF-001 leaves Xiao active).",
    steps=("Send: Show her", "Send: Show him", "Send: Show it"),
    expected=("Each shows Xiao's detail card — the active entity, by pronoun, "
              "not a name", "The reply names Xiao"),
    failure_conditions=("Any pronoun is treated as an unrelated message",
                        "Different entities shown per pronoun"),
)

_t(
    test_id="REF-003", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=15, suites=_QUICK,
    objective="A deterministic single-field update applies without the LLM.",
    preconditions="Xiao is the active entity (REF-002).",
    steps=("Send: Xiao is level 70", "Send: Xiao's level is 70",
           "Send: Set Xiao level to 70"),
    expected=("Each updates level to the stated value and confirms it",
              "Send: Show Xiao — card shows the final level, no duplicate "
              "entities"),
    failure_conditions=("Update treated as a retrieve (level not changed)",
                        "Level stored under a wrong field"),
)

_t(
    test_id="REF-004", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=15, suites=_QUICK,
    objective="Pronoun forms of deterministic updates resolve against the "
              "active entity.",
    preconditions="Xiao is the active entity.",
    steps=("Send: Set her level to 90", "Send: his level is 80"),
    expected=("Xiao's level changes to 90 then 80",
              "The update is applied to Xiao, not a new entity"),
    failure_conditions=("A new entity named 'her'/'his' is created",
                        "Nothing is updated"),
)

_t(
    test_id="REF-005", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_MED,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=30, suites=_QUICK,
    objective="Explicitly switching to another entity re-bases the active "
              "entity and references follow it.",
    preconditions="Xiao is the active entity.",
    steps=("Send: Create character Kinich", "Send: Show her"),
    expected=("Kinich becomes the active entity",
              "Show her now shows Kinich, not Xiao"),
    failure_conditions=("Show her still shows Xiao after the switch",
                        "Kinich not created"),
)

_t(
    test_id="REF-006", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=15, suites=_QUICK,
    objective="A named entity in the message beats the active entity "
              "(explicit reference wins).",
    preconditions="Kinich is the active entity (REF-005); Xiao exists.",
    steps=("Send: Show Xiao"),
    expected=("Shows Xiao's card even though Kinich is active",
              "The active entity is unchanged by a pure view"),
    failure_conditions=("The active entity overrides the explicit name",
                        "Shows Kinich instead of Xiao"),
)

# ── Ordered list + ordinals ────────────────────────────────────────────────
_t(
    test_id="REF-007", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=15, suites=_QUICK,
    objective="A list retrieve records the ordered list for later ordinals.",
    preconditions="Several characters exist (REF-001…REF-005).",
    steps=("Send: Show all characters",),
    expected=("A numbered list of the workspace's characters is returned",
              "Send: Show the first one — resolves to the first listed entity"),
    failure_conditions=("No list is produced",
                        "Show the first one fails after the list"),
)

_t(
    test_id="REF-008", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=10, suites=_QUICK,
    objective="Ordinal references resolve deterministically against the last "
              "ordered list.",
    preconditions="A list was just shown (REF-007).",
    steps=("Send: Show the first one", "Send: Show the second one",
           "Send: Show the last one"),
    expected=("first/second/last resolve to the matching list entries",
              "Resolved entities are the list's entities, in order"),
    failure_conditions=("Ordinals resolve to wrong entities",
                        "Ordinals are ignored/fall through"),
)

_t(
    test_id="REF-009", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_MED,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=20, suites=_QUICK,
    objective="The ordered list survives activating a single entity "
              "(list is not wiped by a focus).",
    preconditions="A list was just shown (REF-007).",
    steps=("Send: Show the first one",   # activates the first entity
           "Send: Show the last one"),
    expected=("After focusing the first entity, the last ordinal still "
              "resolves to the list's last entry",
              "The list context is preserved"),
    failure_conditions=("Show the last one fails after focusing the first one",
                        "The ordered list is cleared by activation"),
)

_t(
    test_id="REF-010", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_MED,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=15, suites=_QUICK,
    objective="A new list replaces the old one (no cross-list ordinals).",
    preconditions="Two retrieves produce different ordered lists.",
    steps=("Send: Show all characters", "Send: Show all level 90 characters",
           "Send: Show the first one"),
    expected=("The first ordinal resolves against the SECOND list (level 90), "
              "not the earlier full list"),
    failure_conditions=("The first ordinal uses the stale full list",
                        "The old list persists after a new list is shown"),
)

_t(
    test_id="REF-011", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.INVALID, estimated_seconds=20, suites=_QUICK,
    objective="A genuinely ambiguous reference asks for clarification and "
              "never guesses.",
    preconditions="An ambiguous state exists (e.g. several entities referenced "
                  "in recent context with no clear active entity).",
    steps=("Create two distinct entities in quick succession so recent "
           "mentions are ambiguous", "Send: Show it"),
    expected=("The bot asks which one you mean, naming the candidates",
              "It does NOT pick one at random"),
    failure_conditions=("A candidate is silently chosen",
                        "The bot falls through without acknowledging the "
                        "reference"),
)

_t(
    test_id="REF-012", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_MED,
    scenario=ScenarioClass.BOUNDARY, estimated_seconds=15, suites=_QUICK,
    objective="An ordinal with no recorded list degrades gracefully.",
    preconditions="No list has been shown this conversation.",
    steps=("Send: Show the first one"),
    expected=("The bot does not crash and does not invent an entity",
              "It either says it has no list context or falls through to a "
              "helpful reply"),
    failure_conditions=("A random entity is returned",
                        "An exception is surfaced to the user"),
)

# ── Stale/deleted entities ────────────────────────────────────────────────
_t(
    test_id="REF-013", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.RECOVERY, estimated_seconds=30, suites=_QUICK,
    objective="A deleted/stale active entity is never resurrected; context "
              "self-heals.",
    preconditions="An entity exists and is active (e.g. Nefer).",
    steps=("Delete the active entity via the workspace delete command",
           "Send: Show her"),
    expected=("The bot clears the dangling active reference and does NOT "
              "re-create or ghost Nefer",
              "It reports the entity is gone / falls through cleanly"),
    failure_conditions=("Nefer is resurrected from the old active reference",
                        "An error is thrown instead of a graceful reply"),
)

# ── Combined update + retrieval ───────────────────────────────────────────
_t(
    test_id="REF-014", category="Workspace Groups", feature="Entity References",
    introduced_version="v15.1.0-alpha.12", priority=_HIGH,
    scenario=ScenarioClass.MULTI_STEP, estimated_seconds=30, suites=_QUICK,
    objective="Create + field update + field-filtered retrieve work together "
              "across the M1 path.",
    preconditions="Active Genshin workspace.",
    steps=("Send: Create character Columbina",
           "Send: Columbina is level 90",
           "Send: Show all level 90 characters"),
    expected=("Columbina created, level set to 90 deterministically",
              "The level-90 list includes Columbina"),
    failure_conditions=("Level update misclassified as retrieve (level not set)",
                        "Columbina missing from the level-90 filter"),
)
