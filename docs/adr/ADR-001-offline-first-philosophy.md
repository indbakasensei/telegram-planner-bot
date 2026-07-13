# ADR-001: Offline-First Philosophy

**Status:** Proposed
**Part of:** BAKA v14 Autonomous Core (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`)

## Problem

BAKA's architecture today is, structurally, `Telegram → AI`: every message
that isn't an exact slash command or a hand-matched keyword phrase reaches
`baka_brain.py`'s `get_baka_response()` before anything happens. In
practice, the *majority* of BAKA's actual command surface never needs
AI at all (`OFFLINE_ENGINE.md`'s inventory: `/list`, `/done`, `/habits`,
`/goals`, every project command, every admin command, and more) — but this
is true only because each handler happens to have been written to skip
`baka_brain.py`, not because the architecture prevents an unnecessary AI
call. There is no single place where "does this need AI?" is decided as a
first-class question.

This has a real cost, demonstrated three times in production
(`CHANGELOG.md` v11.2 ×2, `AI_DIAGNOSTIC_REPORT.md`/v13.3.1/v13.3.2): when
the one AI provider has a bad day, everything downstream of it degrades,
including — before the v13.3.x hotfixes — commands that arguably never
needed to wait on AI in the first place, simply because the "is this
message maybe a task?" classification step ran before it was known whether
the message even required understanding beyond deterministic pattern
matching.

## Alternatives considered

1. **Keep AI-first, harden it further.** Continue the v13.3.x pattern
   (better timeouts, better fallback) indefinitely. Rejected as the sole
   strategy: it treats the *symptom* (a slow/unavailable provider) rather
   than the *structural cause* (every message pays an AI-availability tax
   regardless of whether it needs to). It's also strictly complementary,
   not competing, with offline-first — the AI Router (ADR-003) still needs
   exactly this hardening for the requests that genuinely do need AI.
2. **AI-first with a cache.** Cache AI classification results for
   repeated/similar messages. Rejected: BAKA's messages are highly
   user-specific and low-repetition (task titles, dates), so cache hit
   rates would likely be poor, and it doesn't address the core issue of
   *first-time* messages still depending on AI availability.
3. **Offline-first (chosen).** Classify deterministically first; escalate
   to AI only when deterministic confidence is insufficient
   (`INTENT_ENGINE.md`). This directly generalizes a pattern the codebase
   already trusts for one narrow case — `date_parser.py`'s deterministic
   date/time output already overrides the AI's own guess today, precisely
   because it's known to be more reliable for the phrasings it covers
   (`CHANGELOG.md` v7.1). Offline-first extends that same trust
   relationship from "date/time only" to "everything a deterministic rule
   can confidently resolve."

## Decision

BAKA v14 adopts offline-first classification: the Intent Engine
(`INTENT_ENGINE.md`) always runs first, is always deterministic, and
never itself calls an AI provider. AI is an explicit escalation — used
only when confidence is below threshold or the intent is inherently
generative (`/think`, planning, vision, image/video) — not a default path
every message passes through on the way to being understood.

## Consequences

**Positive:**
- FR-8 (master spec) becomes true by construction: an AI provider outage
  cannot break any command the Intent Engine can confidently classify,
  since by definition that path never touches the AI Router.
- Makes the "how much of BAKA's traffic actually needs AI" question
  answerable with real data (`INTENT_ENGINE.md`'s classification logging),
  informing future prioritization between more Offline Engine coverage
  vs. more AI Router provider investment.
- Reduces average latency for the majority of commands, since
  network-round-trip time is only paid when actually necessary.

**Negative / accepted tradeoffs:**
- Deterministic rules can misclassify edge cases an AI-first approach
  might have handled correctly by "understanding" novel phrasing. Mitigated
  by conservative confidence thresholds (`INTENT_ENGINE.md`) — anything
  uncertain still escalates to AI, it just isn't the default for
  *everything*.
- Every new deterministic rule is a piece of code to maintain and test,
  where an AI-first approach would have "handled it" (with the reliability
  and cost tradeoffs that implies). This is judged worthwhile given this
  project's own bug history shows deterministic rules, once tested
  (`tests/test_date_parser.py`'s 111 tests), are more reliable and
  auditable than trusting an LLM's classification of the same input.
- Requires migration discipline (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md` §11)
  to avoid a big-bang rewrite risk — accepted as a staged, incremental
  rollout rather than a blocker to the decision itself.
