# ADR-005: "Autonomous Core" Scope — Infrastructure, Not Autonomy

**Status:** Proposed
**Part of:** BAKA v14 Autonomous Core (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`)
**Depends on:** ADR-001, ADR-002, ADR-003, ADR-004

## Problem

The name "Autonomous Core" (this sprint's own title) could reasonably be
read as a commitment to making BAKA behave more autonomously —
initiating actions without being asked, making more independent decisions
about a user's data, or generally becoming more agentic. This project
already has a real, if modest, example of that direction:
`observation_engine` (`CHANGELOG.md` v11.0), the daily job that generates
AI suggestions from a user's week and offers them via `/approve`/`/dismiss`.
Given a design document with this name, an implementer could reasonably
assume "autonomy" itself is the v14 deliverable — expanding
`observation_engine`-style proactive behavior significantly, or loosening
the confirmation-before-write discipline BAKA has maintained since its
`v1.0` "BAKA-style confirmation flow" design principle
(`feature_list.md`'s historical description, still true today per
`fmt.py`'s `confirm_box()`).

This ADR exists to record, explicitly, that this is **not** what v14
builds — and why the name doesn't mean what it might suggest.

## Alternatives considered

1. **"Autonomous Core" as expanded proactive/agentic behavior** — BAKA
   takes more actions on its own initiative, with less per-action
   confirmation. Rejected for v14: this sprint's own mission brief
   explicitly says "Do NOT add health scoring" and "Do NOT add provider
   routing" for the *preceding* hotfix sprints specifically because that
   work belongs at the architecture level — but nothing in the brief asks
   for *less* user confirmation or *more* independent action-taking.
   Expanding autonomy in that sense is a product decision with real
   trust/safety implications (BAKA "owns your tasks until they're done,"
   `README.md`'s own framing — that's a promise about persistence, not
   about acting without consent), and conflating it with this sprint's
   actual infrastructure scope would be a significant, unstated behavior
   change smuggled in under an architecture-sprint banner.
2. **"Autonomous Core" as infrastructure that makes future autonomy
   possible, without building autonomy itself (chosen).** The Intent
   Engine, Offline Engine, AI Router, and Plugin System are all
   *decision-making infrastructure* — they change how BAKA decides which
   code path to run and which provider to ask, not how much BAKA is
   willing to do without asking the user first. "Autonomous" describes the
   system's ability to autonomously choose a code path (deterministic vs.
   AI, which provider) — not autonomy over the user's data.

## Decision

v14's "Autonomous Core" refers to **infrastructure autonomy**: the system
autonomously decides whether a request needs AI (Intent Engine, ADR-001),
which provider to use when it does (AI Router, ADR-003), and what
capability handles a given command (Plugin System, ADR-004) — all without
a human operator's per-request intervention. It does **not** mean reduced
user confirmation, expanded proactive/agentic behavior, or any change to
BAKA's existing "always confirm before writing" discipline. Every write
path in every companion document (`DATA_FLOW.md`'s 8 traced flows,
`STATE_MACHINE.md`'s `Confirming` state) preserves exactly the
confirmation behavior BAKA has today.

If a future version wants to expand actual behavioral autonomy (more
`observation_engine`-style proactive suggestions, or reduced confirmation
for high-confidence actions), that is a separate, explicit, future design
decision — this ADR's purpose is to make sure it's never accidentally
implied to already be in scope by v14's name.

## Consequences

**Positive:**
- Keeps this sprint's actual, large scope (5 new architectural components)
  from silently growing further via scope creep hidden in the name.
- Preserves user trust properties this project has maintained since v1.0
  (`CHANGELOG.md`) without requiring a renewed product-level conversation
  about them as part of an infrastructure sprint.
- Gives a future team a clear, explicit place (this ADR) to *deliberately*
  revisit behavioral autonomy later, with full context on why it wasn't
  part of v14, rather than discovering the topic was silently avoided.

**Negative / accepted tradeoffs:**
- The name "Autonomous Core" remains, on its face, a little misleading
  relative to what's actually built — accepted rather than renaming the
  sprint, since the name was set by this sprint's own mission brief and
  this ADR's job is to clarify scope, not relitigate naming.
- Anyone skimming only the master spec's title without reading this ADR
  could still form the wrong impression — mitigated by
  `DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §3 Non-Goals explicitly listing
  "not a fix for any specific currently-open bug" and this ADR being
  directly linked from that document's ADR list (§13 Documentation Tree).
