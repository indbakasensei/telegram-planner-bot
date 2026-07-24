# v15.0-rc.1 — Engineering Audit Report

The final Release Candidate before v15 Stable. This pass made the
repository production-ready for open source: it consolidated documentation,
removed tracked junk, reorganized the folder layout, rewrote the README,
polished the help system, and added hygiene regression tests — **with zero
Workspace-OS behavior changes and no public import-path changes**. The full
suite stays green (**1117 passing**: 1115 + 2 hygiene tests).

---

## Part 1–2 · Documentation audit & cleanup

27 root-level Markdown files were classified. Guiding rule: CLAUDE.md's
permanent-docs map + standard OSS root files stay at root; v14-era
subsystem and point-in-time records move under `docs/`; only provably
obsolete stubs/logs are deleted. Nothing with long-term engineering value
was deleted — historical records were **relocated, not removed**.

| Decision | Files |
|---|---|
| **KEEP (root)** | README, CHANGELOG, ROADMAP, CLAUDE, ARCHITECTURE, API, PROJECT, PROMPTS, TESTING, DEBUGGING, UI_SPEC_v1, QA_SYSTEM_DESIGN, MEMORY |
| **MOVE → `docs/architecture/`** | AI_ROUTER, COMMAND_PIPELINE, DATA_FLOW, INTENT_ENGINE, OFFLINE_ENGINE, PLUGIN_SYSTEM, STATE_MACHINE |
| **MOVE → `docs/history/`** | DESIGN_SPEC_v14_AUTONOMOUS_CORE, DRG-001_Intent_Aware_Routing, ENGINEERING_AUDIT, AI_DIAGNOSTIC_REPORT, RC_v14_ARCHITECTURE_VALIDATION, TEST_CHECKLIST, feature_list |
| **DELETE** | `REPOSITORY_CLEANUP.md` (a completed v14 cleanup checklist — a stale, done TODO list); `VERSION.md` (a 364-byte stub already superseded by CHANGELOG's header note) |

All `](...)` Markdown links to moved/renamed targets were rewritten to the
correct relative path (verified by the link checker below). `docs/v15/` and
`docs/adr/` were already organized and were left in place.

## Part 3 · Repository cleanup

Removed **7 tracked runtime artifacts** that should never have been
committed (verified unreferenced by any script, test, doc, or import):
`planner1.err` `planner2.err` `planner3.err` `planner1.out` `planner2.out`
`planner3.out` `planner.lock`. Added matching patterns to `.gitignore`
(`planner*.out`, `planner*.err`, `planner.lock`) so they cannot return.

Local-only files (`bot.log`, `debugbot.log*`, `planner.db`, `bugs.db`,
`.coverage`, `__pycache__/`, `.pytest_cache/`, `backups/`) were already
gitignored — they never reach a clone, so the repository is clean for
contributors without touching a developer's working tree.

## Part 4 · Folder organization

Top-level Markdown dropped from **27 → 13** files (the permanent docs +
standard OSS root files). v14 subsystem deep-dives and point-in-time design/
audit records now live under `docs/architecture/` and `docs/history/`. No
source module moved; **no public import path changed**.

## Part 5 · README rewrite

Rewritten for a public GitHub audience, now covering: overview, features,
architecture diagram, Workspace OS overview, **Supported Workspace
Templates** table, installation, configuration, quick start, **Feature
Flags** section, screenshots (placeholder — no broken image links), example
workflows, project structure (updated to the new `docs/` layout), testing,
roadmap, contributing, license, and acknowledgements. Version → `v15.0-rc.1`.

## Part 6 · Help system

`ui.help_cards` already covers every user command, grouped by domain with
examples. Added a concise **Workspace mode** note to the admin-only card
explaining the `WORKSPACE` env flag (operator-facing; there are no
end-user Workspace commands yet, so it is intentionally not shown to
regular users).

## Part 7 · Testing

Added `tests/test_repo_hygiene.py` (2 tests) encoding this audit as
regressions: **no broken Markdown links** and **no tracked runtime
artifacts**. Both degrade gracefully (skip) if run from a non-git tarball.
The existing 1115-test suite already gives strong coverage across every
milestone; no gaps required new behavioral tests this pass.

## Part 8 · Code quality

Removed genuinely unused imports from files touched this cycle
(`templates/game.py`, `templates/registry.py`, a test import). The
`templates/__init__.py` "unused import" warnings are intentional public
re-exports (`# noqa: F401`).

**Documented follow-up (not done here, by design):** `main.py` (248 KB, the
behavior-critical handler hot path) and `baka_brain.py` carry pre-existing
pyflakes noise — unused names in large `from … import (…)` lists, a few
dead locals, and f-strings without placeholders. These are **not** touched
in the final RC: the risk/reward of editing the hot path for cosmetic lint
is poor, and "provably unused" needs per-symbol verification. Track as a
post-Stable lint sprint.

## Part 9 · Documentation consistency

Version (`v15.0-rc.1`), the four+four template set, the `WORKSPACE` flag
semantics, the folder layout, and the roadmap were reconciled across
README, ROADMAP, CHANGELOG, and CLAUDE's documentation map.

## Part 10 · Final audit checklist

| Check | Status |
|---|---|
| No broken imports | ✅ suite imports clean; 1117 passing |
| No broken Markdown links | ✅ link checker clean (asserted by `test_repo_hygiene`) |
| No orphan documentation | ✅ each doc reachable from README/CLAUDE map or docs index |
| No unused templates | ✅ all 8 templates registered and tested |
| No duplicate Markdown | ✅ obsolete stubs deleted; overlaps relocated, not duplicated |
| No dead utilities | ✅ no tracked dead scripts (run/reset scripts are live) |
| No tracked logs / temp / generated files | ✅ removed + gitignored (asserted by `test_repo_hygiene`) |
| Consistent naming | ✅ docs grouped; `docs/{architecture,history,adr,v15}` |
| No outdated roadmap entries | ✅ ROADMAP through rc.1 |
| No Workspace-OS behavior change | ✅ engine/orchestrator/timeline/sync untouched; flag-OFF byte-identical |

**Acceptance:** all prior tests green in both flag states; repository is
smaller and better-organized; documentation is internally consistent;
README and help are production-ready.
