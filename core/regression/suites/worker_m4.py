"""Quick Release Suite: v15.2 M4 — GLM-5.2 Worker.

The Worker (core/ai/worker.py) is DORMANT behind feature_flags.WORKER and the
owner-only canary, so there is NO Telegram walk yet — these specs verify the
Worker's health from the live app: the offline pytest suites that own the
exhaustive coverage (tests/test_worker.py + tests/test_worker_parser.py) plus
a `/selftest → AI → 'AI Worker …'` probe. They exist so a live-Telegram
regression pass re-verifies that the dormant bounded loop, the confirmation
gate, the parser and the honesty guard are still intact before the owner flips
WORKER=1 for canary.

The 20 M4 user scenarios + adversarial set are each mapped to their owning
pytest cases here; they become a live-Telegram acceptance matrix ONLY after
the owner actually runs them with WORKER=1 (never claimed early — TESTING.md).
"""
from core.regression.models import (
    Priority, RegressionTest, ScenarioClass, Suite,
)
from core.regression.registry import register

_QUICK = frozenset({Suite.QUICK})
_MED = Priority.MEDIUM
_HIGH = Priority.HIGH

_PYTEST = ("python -m pytest tests/test_worker.py tests/test_worker_parser.py "
           "tests/test_worker_orchestration.py tests/test_tool_adapters.py "
           "tests/test_worker_render.py tests/test_worker_topics.py -q")

_SCENARIOS = (
    # (test_id, scenario, objective, cases that own it)
    ("WKR-001", "S1: entity create by name through the Worker",
     "A named entity create ('create Xiao') runs create_entity via the "
     "ToolRegistry, commits, and drives the SAME alpha.13 projection "
     "(topic+card) -- never a second topic mechanism.",
     "test_entity_create_projection_preserved, test_conversational_reference_"
     "resolves_via_m1"),
    ("WKR-002", "S2: entity update via conversational reference",
     "'level her to 80' resolves 'her' through the SHARED M1 ReferenceContext "
     "to the active entity (never resolved by the Worker itself).",
     "test_conversational_reference_resolves_via_m1"),
    ("WKR-003", "S3: ambiguous reference asks, never guesses",
     "An unresolvable referent produces a clarification request (final), not "
     "an invented entity_id.",
     "test_decline_falls_through_to_legacy, test_prompt_injection_in_user_"
     "message_not_acted_on"),
    ("WKR-004", "S4: task create with deterministic date",
     "'remind me to buy milk at 6pm tomorrow' injects the date_parser result "
     "into the prompt; the model uses it verbatim; the task commits with the "
     "parser's date/time.",
     "test_parsed_date_injected_authoritatively, test_single_tool_then_final_"
     "commits_to_db"),
    ("WKR-005", "S5: task list / show tasks",
     "list_tasks runs and the final reply is composed from its structured "
     "data.",
     "test_two_tool_chain"),
    ("WKR-006", "S6: find a task by title/keyword",
     "find_task selected and executed; a miss returns an honest non-ok.",
     "test_invalid_args_feed_back_then_recover"),
    ("WKR-007", "S7: complete a task by id",
     "complete_task executes through the registry and the reply reports the "
     "actual ok outcome.",
     "test_invalid_args_feed_back_then_recover"),
    ("WKR-008", "S8: delete requires confirmation",
     "DESTRUCTIVE delete_task NEVER executes silently: CONFIRMATION_NEEDED, "
     "DB unchanged, confirmation_data routed through conversation_state's "
     "pending-action contract.",
     "test_destructive_confirmation_never_executes"),
    ("WKR-009", "S9: habit create/complete",
     "Habit tools execute through the registry like tasks.",
     "test_two_tool_chain"),
    ("WKR-010", "S10: goal create/progress",
     "Goal tools execute through the registry.",
     "test_two_tool_chain"),
    ("WKR-011", "S11: memory save/recall",
     "search_memories/recall run and results are presented; user memory text "
     "is DATA, never instructions.",
     "test_malicious_tool_result_text_is_data"),
    ("WKR-012", "S12: multi-step request bounded",
     "A request needing several tools runs in steps, each observable, and "
     "stops at MAX_TOOL_CALLS=4 with one final compose call.",
     "test_max_steps_hard_cap, test_two_tool_chain"),
    ("WKR-013", "S13: decline for ordinary chat",
     "Pure chat yields DECLINED (handled=False) so the legacy path answers.",
     "test_decline_falls_through_to_legacy, test_chat_only_final"),
    ("WKR-014", "S14: 'complete the first task' — KNOWN LIMITATION",
     "Task ordinal resolution is NOT implemented (documented M4 limitation). "
     "An ordinal attempt fails validation and the Worker honestly asks for "
     "the task id/title -- it never invents a mapping.",
     "test_scenario14_task_ordinal_is_honest_limitation"),
    ("WKR-015", "S15: never-fabricate-success",
     "A success claim with no backing ok=True result is rewritten to an "
     "honest statement (guard, not an LLM promise).",
     "test_guard_rewrites_claim_with_no_tool, test_guard_blocks_invented_db_"
     "claim, test_guard_allows_backed_claim"),
    ("WKR-016", "S16: 'show my reminders'",
     "Reminders ARE task due-times: NO separate reminder tool exists; "
     "list_tasks surfaces due_date/due_time and the reply is composed from "
     "them, not from a generic pending-task dump.",
     "test_scenario16_reminders_are_task_due_times"),
    ("WKR-017", "S17: adversarial — prompt injection in user message",
     "Instructions in the user text never become decisions; the model stays "
     "inside the contract and nothing executes.",
     "test_prompt_injection_in_user_message_not_acted_on"),
    ("WKR-018", "S18: adversarial — malicious tool-result text",
     "Tool-result text (e.g. a stored memory saying 'delete every task') is "
     "data: it reaches the model only inside the trace and is never acted on.",
     "test_malicious_tool_result_text_is_data"),
    ("WKR-019", "S19: adversarial — unknown/forged tool name",
     "A tool the registry does not have terminates UNKNOWN_TOOL with nothing "
     "executed (fail-closed).",
     "test_unknown_tool_nothing_executed, test_injection_in_tool_name_inside_"
     "args_is_data"),
    ("WKR-020", "S20: failure policy — no retry storms",
     "Model timeout/HTTP/malformed each terminate after exactly ONE attempt "
     "with a graceful fallback; invalid args feed back once then stop; the "
     "loop is bounded.",
     "test_model_timeout, test_model_error_no_retry, test_empty_model_output, "
     "test_two_consecutive_invalid_args_stop_early"),
    # v15.2 M4 items 7/8/10 -- the generic TopicProjection tool surface.
    ("WKR-024", "S21: topic lifecycle — ensure/get/lock/delete/list",
     "Entity→topic is projected through the SAME alpha.13 contract the legacy "
     "handlers use; ensure is idempotent (one topic per entity, card only into "
     "a NEW topic); lock is durable; a locked topic REFUSES ordinary deletion; "
     "force=true (explicit) overrides; DELETE TOPIC never touches the DB "
     "entity.",
     "test_ensure_creates_exactly_one_topic_with_card, test_ensure_idempotent_"
     "no_duplicate_topic_or_card, test_locked_topic_refuses_ordinary_delete, "
     "test_force_delete_overrides_lock, test_delete_topic_leaves_entity_with_"
     "fields, test_delete_topic_confirmation_gate_fires_before_execute, "
     "test_lock_is_durable_across_registry_and_projection, test_list_entity_"
     "topics_reports_bindings_and_locks"),
    # v15.2 M4 item 9 -- self-heal repair.
    ("WKR-025", "S22: topic repair collapses duplicates",
     "repair_topics (and the /topicrepair command) collapse logical duplicates "
     "(one normalized title → ONE entity → ONE topic), adopt a concrete kind "
     "onto the canonical row, report created/existing/duplicates/errors, and "
     "a re-run is a no-op. The duplicate row is skipped, never deleted.",
     "test_repair_collapses_duplicates_one_topic_one_entity, test_repair_is_"
     "idempotent_no_new_topics_on_rerun, test_repair_reports_unlinked_"
     "workspace_and_no_topic_calls"),
    # v15.2 M4 item 11 -- workspace lifecycle symmetry audit.
    ("WKR-026", "S23: workspace lifecycle — no silent destructive path",
     "The Worker surface is read+open only for workspaces; delete/archive "
     "workspace is NOT reachable from NL (workspace deletion cascades and is "
     "effectively irreversible). The invariant pins the surface and guards "
     "that any future delete/archive workspace tool is DESTRUCTIVE with "
     "confirmation.",
     "test_workspace_lifecycle_has_no_silent_destructive_path"),
    # v15.2 M4 items 12/13 -- response-format restoration.
    ("WKR-027", "S24: Worker replies are BAKA-formatted, not prose",
     "Worker decides WHAT happened; the existing BAKA formatter decides HOW it "
     "is displayed. render_run_reply maps each ok step onto the same "
     "Telegram-HTML the legacy handlers use (entity cards via a fetcher, "
     "task/goal/habit/workspace lines), escapes user content, preserves "
     "honesty (failed steps ⚠️, MAX_STEPS budget note, zero-render falls back "
     "to the worker's own text).",
     "test_render_create_entity_full_card_via_fetcher, test_render_create_"
     "entity_escapes_html_in_title, test_render_update_entity_old_to_new, "
     "test_render_failed_step_is_honest_not_fabricated, test_render_max_steps_"
     "budget_note, test_render_every_list_tool_accepts_the_3arg_dispatch"),
)


def _t(**kw):
    register(RegressionTest(**kw))


def _spec(test_id, scenario, objective, owning_cases):
    _t(
        test_id=test_id, category="AI", feature="AI Worker",
        introduced_version="v15.1.0-alpha.13", priority=_HIGH,
        scenario=ScenarioClass.NORMAL, estimated_seconds=10, suites=_QUICK,
        objective=objective,
        preconditions=("Worker is DORMANT (WORKER=0). Offline — no Telegram, "
                       "no live GLM call."),
        steps=(f"Run: {_PYTEST} "
               f"(owns: {owning_cases})",
               "Run /selftest → AI → 'AI Worker (dormant)' and "
               "'AI Worker Deterministic Round-trip'"),
        expected=("All owning pytest cases pass",
                  "Both AI Worker selftest probes report ok"),
    )


# The 20 M4 user scenarios.
for _n, (_sid, _sc, _obj, _cases) in enumerate(_SCENARIOS, start=1):
    _spec(_sid, _sc, _obj, _cases)

# Safety-critical invariants get their own regression specs.
_t(
    test_id="WKR-021", category="AI", feature="AI Worker",
    introduced_version="v15.1.0-alpha.13", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=10, suites=_QUICK,
    objective="Confirmation is MECHANICAL, before execute: a DESTRUCTIVE tool "
              "or any tool with a confirmation_message never runs silently -- "
              "the run ends CONFIRMATION_NEEDED and main.py re-routes the "
              "yes/no through the EXISTING conversation_state pending-action "
              "machine (no second confirmation system).",
    preconditions="Offline.",
    steps=(f"Run: {_PYTEST} (owns: test_destructive_confirmation_never_"
           "executes, test_mutating_executes_without_confirmation)",
           "Confirm main.py still has exactly one confirming state (state == "
           "'confirming') and the worker_confirm branch re-executes through a "
           "fresh ToolRegistry on yes"),
    expected=("delete_task never executes before confirmation; DB unchanged",
              "MUTATING tools still execute directly"),
)

_t(
    test_id="WKR-022", category="AI", feature="AI Worker",
    introduced_version="v15.1.0-alpha.13", priority=_MED,
    scenario=ScenarioClass.NORMAL, estimated_seconds=10, suites=_QUICK,
    objective="Observability: one structured INFO line per run with "
              "request_id, user/workspace, termination, total_ms, model_calls, "
              "per-step tool+args, reply_len -- with NO raw user text and "
              "secret-keyed args redacted. Live Telegram acceptance is NOT "
              "claimed until actually run.",
    preconditions="Offline.",
    steps=(f"Run: {_PYTEST} (owns: test_structured_log_no_raw_text_secrets_"
           "redacted, test_log_includes_steps_and_termination)",
           "Run /selftest → AI → 'AI Worker (dormant)'"),
    expected=("Logs never contain the user message body or secret values",
              "Args are redacted on secret-like keys; request_id present"),
)

# ── v15.2 M4 orchestration fixes (the 10 live-failure acceptance matrix) ───
# Each live failure / architectural requirement maps to the pytest cases that
# own it in tests/test_worker_orchestration.py; those are the offline proof.
_V15 = "v15.2"


def _spec15(test_id, scenario, objective, owning_cases):
    _t(
        test_id=test_id, category="AI", feature="AI Worker orchestration",
        introduced_version=_V15, priority=_HIGH,
        scenario=ScenarioClass.NORMAL, estimated_seconds=15, suites=_QUICK,
        objective=objective,
        preconditions=("Offline. Worker DORMANT (WORKER=0) unless the owner "
                       "flips it for the live matrix."),
        steps=(f"Run: {_PYTEST} (owns: {owning_cases})",
               "Run /selftest → AI → 'AI Worker (dormant)'"),
        expected=("All owning pytest cases pass",
                  "The selftest probe reports the 25-tool M4 surface ok"),
    )


_SPECS15 = (
    ("WKR-023", "Compound create→set→show chains (A1–A7, F3/F5)",
     "A multi-operation request ('create X, set its level to 90, then show "
     "it') executes EVERY operation in order, one tool per step, using the "
     "CURRENT run's ids/results -- never stopping early after a mutation and "
     "never collapsing steps into one arbitrary call.",
     "test_create_set_show_chain_executes_fully, test_show_then_update_then_"
     "show_chain, test_create_two_and_show_both"),
    ("WKR-024", "Typed referents are first-class context (R2/R3/R5)",
     "Tool results carry typed identity: after create_entity returns "
     "{entity_id, name}, the NEXT prompt lists it as a KNOWN REFERENT with "
     "its exact id, and a run-scoped referent beats a stale active entity "
     "from a previous turn.",
     "test_prompt_carries_created_entity_as_typed_referent, test_run_scoped_"
     "pronoun_beats_stale_active"),
    ("WKR-025", "Goal deadlines owned by the goal domain (F6/F7)",
     "'Set its deadline…' on a goal routes to update_goal_deadline; 'this "
     "month end'→last day, 'next month end'→last day of next month via the "
     "deterministic parser; the goal's deadline column changes and a "
     "character is never mutated.",
     "test_update_goal_deadline_tool_registered, test_goal_deadline_sets_only_"
     "the_goal, test_goal_deadline_this_month_end, test_goal_deadline_next_"
     "month_end_parsed, test_goal_progress_update_uses_goal_domain"),
    ("WKR-026", "Cross-domain reference safety (R9)",
     "Goal/entity/task never share unsafe references: a pronoun pointed at a "
     "different kind is REJECTED (never reaches across), same-named entities "
     "of different kinds stay distinct, and an ambiguous referent asks "
     "instead of mutating.",
     "test_goal_pronoun_conflict_never_mutates_character, test_cross_domain_"
     "same_name_distinguished, test_ambiguous_deadline_never_mutates"),
    ("WKR-027", "Type-aware identity + typed retrieval (F8/F9/F10)",
     "Entity identity is (workspace, entity_type, id), not display name: "
     "'create artifact Golden Troupe' coexists with a character of the same "
     "name; list_entities filters by entity_type so 'show all characters' "
     "returns ONLY characters (never mixed kinds), and goal/task operations "
     "stay in their own domain.",
     "test_create_entity_duplicate_is_type_aware, test_create_entity_stores_"
     "entity_type, test_list_entities_filters_by_entity_type, test_worker_"
     "typed_retrieve_excludes_other_kinds, test_worker_uses_goal_tool_for_show_"
     "all_goals, test_task_completion_does_not_touch_entities"),
    ("WKR-028", "Generic compound-request invariants (S1–S5, S27)",
     "The create→set→show family is GENERIC: parametrized over many entity "
     "names and kinds (character/weapon/artifact), the invariants hold for "
     "create(A)→set(A)→show(A), create(A)→set(A)→show(B), show→update→show, "
     "update→show, and two independent entities — never phrase-specific.",
     "test_invariant_create_set_show_all_kinds, test_invariant_create_set_show_"
     "other_entity, test_invariant_show_update_show, test_invariant_update_then_"
     "show, test_invariant_two_entities_independent_updates, test_invariant_"
     "create_ok_update_fail_show"),
    ("WKR-029", "Generic reference-safety + honesty invariants (S6–S13, S17, "
     "S22, S25)",
     "Cross-domain same-name identity, run-scoped pronouns beating stale "
     "actives, goal-referent domain conflicts, honest failure recovery, "
     "success+failed retrieval traces, the never-fabricate-success guard, "
     "unknown referents never mutating the active entity, the max-steps "
     "honest summary, and one-bad-ref recovery — all parametrized over "
     "multiple names/pronouns.",
     "test_invariant_cross_domain_same_name_goal, test_invariant_typed_identity_"
     "same_name_different_kinds, test_invariant_create_set_pronoun_vs_stale_"
     "active, test_invariant_pronoun_beats_stale_active_direct, test_invariant_"
     "goal_active_blocks_character_pronoun, test_invariant_goal_recent_pronoun_"
     "never_reaches_entity, test_invariant_failed_tool_recovery, test_invariant_"
     "success_and_failed_retrieval, test_invariant_fabricated_success_rewritten, "
     "test_invariant_unknown_referent_never_mutates_active, test_invariant_max_"
     "steps_honest_summary, test_invariant_invalid_args_recovery, test_invariant_"
     "same_name_run_scoped_wins_over_stale"),
    ("WKR-030", "Generic domain isolation + typed retrieval + deadline clear "
     "(S14/S16/S18/S20/S21/S24/S28/S29/S30, T7)",
     "Typed list filters return exactly one kind (never a task VIEW — live "
     "T7), artifacts/weapons are retrievable after create, task and habit "
     "chains stay in their domain, and update_goal_deadline can CLEAR a "
     "deadline (None) without falsely reporting 'not found'.",
     "test_invariant_typed_list_filter_kinds, test_invariant_artifact_"
     "retrieval_after_create, test_invariant_weapon_retrieval_after_create, "
     "test_invariant_task_domain_does_not_touch_entities, test_invariant_goal_"
     "chain_create_progress_list, test_invariant_task_create_retrieve, test_"
     "invariant_task_entity_mixed_domains, test_invariant_habit_chain, test_"
     "invariant_goal_deadline_clear"),
)

for _sid, _sc, _obj, _cases in _SPECS15:
    _spec15(_sid, _sc, _obj, _cases)

# ── v15.2 M4 live-matrix TOOL-CONTRACT fixes (the Llama live run, 2026-08-11) ──
# Three tool-argument contract bugs surfaced on the 31-message Llama live
# matrix (all ARCHITECTURE, not model capability) and were fixed generically:
#  * C3: KNOWN REFERENTS renders workspace ids as ints (ws=1) and tells the
#    model to pass exact ids, but the workspace schema only accepted strings.
#  * C8: '' optional filters (status='') mean "no filter" but the enum
#    rejected them -- the tool's own run() already treats '' as falsy.
#  * A2: an unmatched workspace name like 'default' (meaning "use the active
#    one", per the spec text) failed the call instead of falling back.
_t(
    test_id="WKR-031", category="AI", feature="AI Worker tool contract",
    introduced_version="v15.2", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=15, suites=_QUICK,
    objective="Tool-argument contract matches what the model legitimately "
              "emits (the live-matrix C3/C8/A2 class): integer workspace ids "
              "are accepted by every workspace-taking tool; empty strings on "
              "OPTIONAL args mean 'no filter', never a schema error; an "
              "unmatched workspace name falls back to the active workspace "
              "but a missing active workspace still errors.",
    preconditions="Offline.",
    steps=(f"Run: {_PYTEST} (owns: test_entity_tools_accept_integer_workspace_"
           "id, test_list_entities_accepts_integer_workspace, test_list_"
           "entities_empty_optional_strings_mean_all, test_create_entity_"
           "unmatched_workspace_name_falls_back_to_active, test_create_entity_"
           "unmatched_name_no_active_still_rejected, test_worker_accepts_"
           "llama_shaped_workspace_args)",
           "Run /selftest → AI → 'AI Worker (dormant)' and 'AI Worker "
           "Deterministic Round-trip'"),
    expected=("The owning pytest cases pass (int workspace, '' optionals, "
              "unmatched-name fallback, no-active still rejected)",
              "Both AI Worker selftest probes report ok"),
)

# v15.2 M4 item 12/13: response-format restoration is a PRODUCT REGRESSION
# (first live matrices came back as raw LLM prose) -- its own invariant spec.
_t(
    test_id="WKR-028", category="AI", feature="AI Worker",
    introduced_version="v15.2", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=15, suites=_QUICK,
    objective="The product rule 'Worker decides WHAT happened; the existing "
              "BAKA formatter decides HOW it is displayed' is restored: "
              "main.py renders Worker runs through render_run_reply (entity "
              "cards re-fetched from stored fields, task/goal/habit/workspace "
              "lines matching the dashboards, HTML-escaped, emoji'd) -- never "
              "raw model prose. Honesty preserved: failed steps show ⚠️, "
              "MAX_STEPS shows only what completed, zero-render falls back to "
              "the worker's own text.",
    preconditions="Offline.",
    steps=(f"Run: {_PYTEST} (owns: the matrix-H cases in tests/test_worker_"
           "render.py + test_render_every_list_tool_accepts_the_3arg_dispatch)",
           "Run /selftest → AI → 'AI Worker (dormant)' + 'AI Worker "
           "Deterministic Round-trip'"),
    expected=("Every matrix-H render case passes (cards, escaping, update "
              "old→new, typed list grouping, budget note, fallbacks)",
              "The list-dispatch regression (1-arg vs 3-arg list renderers) "
              "stays pinned"),
)

# v15.2 M4 items 7/8/9/10: the topic lifecycle + repair command invariants,
# probed live from /selftest (Workspace category) even while WORKER is dormant.
_t(
    test_id="WKR-029", category="Workspace Groups", feature="Topic Lifecycle",
    introduced_version="v15.2", priority=_HIGH,
    scenario=ScenarioClass.NORMAL, estimated_seconds=15, suites=_QUICK,
    objective="Entity→topic is one-topic-per-entity: ensure creates exactly "
              "one topic+card; the lock is durable; a locked topic refuses "
              "ordinary delete; force overrides; delete_topic never touches "
              "the entity; /topicrepair collapses logical duplicates onto one "
              "canonical topic and is idempotent. Verifiable from /selftest "
              "while the feature flag gates the NL routing.",
    preconditions="Offline.",
    steps=(f"Run: {_PYTEST} (owns: tests/test_worker_topics.py, "
           "test_delete_entity_topic_carries_confirmation_message)",
           "Run /selftest → Workspace → 'Topic Lifecycle Tools' and "
           "'Topic Repair'"),
    expected=("All topic-lifecycle pytest cases pass",
              "Both Workspace selftest probes report ok"),
)
