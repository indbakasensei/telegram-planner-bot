# ADR-004: Lightweight Manifest-Based Plugin System, Proof of Concept via Projects

**Status:** Proposed
**Part of:** BAKA v14 Autonomous Core (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`)

## Problem

`ENGINEERING_AUDIT.md` finding J1 documents `main.py`'s `handle_message()`
at 841 lines and `main()` at 806 lines, both god-functions largely because
every new command's logic has always been added directly into `main.py` —
13 major versions of features (`CHANGELOG.md`), all in one file. There is
currently no way to add a new capability to BAKA without editing that
file, which is both the immediate cause of its size and a growing barrier
to future feature work (the audit explicitly recommends splitting
`main.py` as a "larger, deliberate refactor," §10 priority item 10, not
yet done).

Separately, this design needs a concrete way to *validate* the plugin
architecture before committing to it broadly — building a plugin system
and only then discovering it doesn't fit the codebase's real features
would be an expensive mistake.

## Alternatives considered

1. **Full dependency-injection framework** (e.g. a formal DI container,
   entry-points-based discovery via `setuptools`, a plugin marketplace with
   remote installation). Rejected for v14: this project's own documented
   engineering values (`CLAUDE.md`: "Don't add features, refactor, or
   introduce abstractions beyond what the task requires") argue against
   building for a third-party-plugin-marketplace future that isn't a
   stated v14 goal (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §2 Goal 4 is
   "extensibility without touching `main.py`," not "an ecosystem"). A
   heavier framework is also strictly harder to validate cheaply, which
   matters for the proof-of-concept requirement below.
2. **No formal plugin system — just better internal module organization**
   (split `main.py` into per-feature files, still all imported and wired
   together manually). Rejected as insufficient: this addresses the
   god-file *size* problem but not FR-5 (new capability without touching
   the Intent Engine/Offline Engine core) — manually wiring a new file
   into the core registries is still "editing shared infrastructure for
   every new feature," just spread across more files.
3. **Lightweight manifest + two registration calls (chosen).** A plugin
   declares what it provides (`manifest.yaml`) and the Intent
   Engine/Offline Engine expose narrow `register_*` extension points a
   plugin calls into. No dependency injection, no remote installation, no
   marketplace — just enough structure to satisfy FR-5 without over-building.

## Decision

Adopt the manifest + registration-call plugin design in
`PLUGIN_SYSTEM.md`. Validate it by extracting one real, already-shipped
feature — **Projects** (`CHANGELOG.md` v12.0) — into the plugin format as
a proof of concept (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §11 Stage 5),
before opening the system for genuinely new plugins.

**Why Projects specifically:** it is the newest, most self-contained
feature in the codebase — its data (`project_materials`,
`project_worklog` tables), its commands (`need`/`got`/`worklog`/`project`/
`shopping`), and its data flow (`DATA_FLOW.md` §4) don't entangle with any
other feature's tables or logic the way, say, habits (which share the
`tasks` table via `is_habit`) or goals-vs-projects (projects *are*
extended goals, `docs/database.md`) do. It's also entirely offline
(`OFFLINE_ENGINE.md`'s inventory), so the proof of concept validates the
plugin system's Intent Engine/Offline Engine integration without also
needing to validate AI Router integration in the same step — a smaller,
more isolated first test.

## Consequences

**Positive:**
- FR-5 becomes achievable without a disproportionate infrastructure
  investment — the manifest schema and two registration calls are a small
  surface area to design, build, and review.
- The Projects extraction is a real, low-risk validation: if it reveals
  the plugin design doesn't fit (e.g. a capability the manifest schema
  didn't anticipate), that's discovered against a feature the team already
  understands completely, not against an unfamiliar new feature being
  built for the first time under a new, unproven system simultaneously.
- Keeps `main.py`'s growth bounded going forward — every feature added via
  the plugin system after v14 doesn't add to the god-file problem
  `ENGINEERING_AUDIT.md` already flagged.

**Negative / accepted tradeoffs:**
- Deliberately not built for a third-party plugin ecosystem (no sandboxing
  beyond the permission-declaration model, no remote installation, no
  marketplace) — acceptable because that's not a stated v14 goal; revisiting
  this decision if/when external plugin authorship becomes an actual
  requirement is explicitly anticipated (`PLUGIN_SYSTEM.md` §Future,
  implicitly — the versioning scheme is designed with that future in
  mind even though v14 doesn't need it yet).
- The proof-of-concept step (extracting Projects) is itself a nontrivial
  piece of work that produces no *new* user-facing capability — it's
  validation cost, not feature delivery. Accepted because the alternative
  (shipping the plugin system's first real use on a brand-new, unproven
  feature) risks conflating "is the plugin system broken" with "is the new
  feature's logic broken," which would be harder to debug.
- `main.py`'s other ~85 handlers are *not* migrated to the plugin format
  as part of v14 — only Projects, and only as proof of concept. The
  broader god-file-splitting effort `ENGINEERING_AUDIT.md` recommends
  remains a separate, larger, future undertaking this ADR does not
  resolve on its own.
