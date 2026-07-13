# ADR-002: Intent Engine — Rule-Based, Not ML-Based

**Status:** Accepted — Stage 1 implemented and shipped, v14.0
(`core/intent/`, commit `afcd7a4`)
**Part of:** BAKA v14 Autonomous Core (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`)
**Depends on:** ADR-001 (Offline-First Philosophy)

## Problem

Given ADR-001's decision to classify deterministically before considering
AI, the Intent Engine needs a concrete classification strategy. The
obvious alternatives are a rule-based system (pattern matching + confidence
heuristics) or a lightweight local ML classifier (e.g. a small trained
intent-classification model, run locally, no network call).

## Alternatives considered

1. **Local ML classifier** (e.g. a small fine-tuned model or classical
   ML like a Naive Bayes/SVM intent classifier, run in-process). Rejected
   for v14: it would require a training pipeline, labeled data (this
   project has none — `debug_system.py`'s `SELFTEST_MESSAGES` and
   `TEST_CHECKLIST.md` are manual test checklists, not a labeled training
   set), and a model artifact to version and ship — real infrastructure
   this project doesn't have today and the mission brief explicitly
   excludes ("Do NOT introduce health scoring" for the AI Router applies
   in spirit here too: don't add a new class of "hard to reason about"
   automated decision-making where a simpler mechanism suffices). It also
   reintroduces exactly the opacity problem offline-first classification
   is trying to get away from — a misclassification from a small local
   model is not meaningfully easier to debug than a misclassification
   from a cloud LLM, just cheaper and offline.
2. **Rule-based, flat pattern list** (continue today's `date_parser.py`
   style — an ordered list of regexes, first match wins). Rejected as
   the *sole* mechanism: this is exactly the design that produced the
   "noon"-inside-"afternoon" bug `tests/test_date_parser.py` found
   (`CHANGELOG.md`'s "First Automated Regression Test Suite" entry) — a
   flat list with no explicit priority tiers is fragile precisely because
   nothing stops a broad, early pattern from silently shadowing a more
   specific, later one.
3. **Rule-based, tiered priority with confidence scoring** (chosen). Keeps
   the deterministic, auditable, offline-testable properties of a
   rule-based approach, while directly fixing the flat-list fragility that
   already caused a real, shipped bug in this codebase — by making
   priority an explicit property of each rule (its tier) rather than an
   emergent property of list order.

## Decision

The Intent Engine uses tiered, confidence-scored rule matching
(`INTENT_ENGINE.md`): Tier 0 (exact commands, confidence 1.0) → Tier 1
(structured patterns, reusing `date_parser.py`'s existing functions
verbatim) → Tier 2 (keyword heuristics) → no match. Confidence bands and
per-intent-class thresholds (read-only vs. reversible-write vs.
destructive-write) determine whether a classification is acted on
directly, triggers a clarifying re-prompt, or escalates to the AI Router.

## Consequences

**Positive:**
- Every rule is independently unit-testable with zero mocking, extending
  the precedent `tests/test_date_parser.py` already set for
  `date_parser.py`'s functions — the Intent Engine's test suite can follow
  the same shape.
- Tier assignment makes priority conflicts a design-time decision (which
  tier does this rule belong in?) rather than a code-review-time accident
  (where in the list did I insert this?) — directly closing the root cause
  of the bug class this project already found once.
- Zero runtime cost beyond regex/string matching — satisfies NFR-2 (Intent
  Engine classification latency must stay in the single-digit-millisecond
  range, since it runs on every message including ones that will still
  need AI).
- No training data, no model artifact, no new infrastructure dependency.

**Negative / accepted tradeoffs:**
- Cannot generalize to phrasing not covered by an explicit rule the way a
  trained classifier or an LLM can — this is the same tradeoff ADR-001
  already accepts at the architecture level, restated here at the
  component level. Uncovered phrasing correctly falls through to the AI
  Router rather than being silently misclassified.
- Rule authoring is manual work — adding support for a new phrasing
  pattern means writing and testing a new rule, not retraining a model.
  Judged acceptable given this project's existing `date_parser.py` already
  demonstrates this is tractable at the scale BAKA operates (a few hundred
  lines of regex covering English/Hindi/Hinglish date-time phrasing,
  `docs/ai_system.md`).
- A future revisit is plausible if rule count grows large enough that
  tier/priority management itself becomes unwieldy — not a concern at
  v14's scope (formalizing ~40 existing slashless commands plus
  `date_parser.py`'s existing rule set, not inventing hundreds of new
  ones), noted here for future architects to reassess if the rule set
  grows substantially past that.

## Implementation Note (added post-Stage-1, v14.0)

Stage 1 shipped as `core/intent/` (`intent_types.py`, `entities.py`,
`rules.py`, `intent_engine.py`) in Shadow Mode — `main.py`'s
`handle_message()` classifies every message and logs the result, but
nothing acts on it yet, exactly as this ADR's Decision describes.
`tests/test_intent_engine.py` (40 tests, 100% coverage of `core/intent/`)
follows the same offline, zero-mocking shape `tests/test_date_parser.py`
already established, confirming the "Positive" consequence above held in
practice.

Two things worth recording that weren't fully settled at proposal time:

1. **This ADR's own predicted failure mode reproduced itself, once, inside
   the new code.** The "Alternatives considered" section above cites the
   real `date_parser.py` "noon"-inside-"afternoon" bug as the reason for
   tiered priority over a flat list. During Stage 1's own test-writing, a
   bare `"good morning"` was initially misclassified as `ADD_TASK`
   (confidence 0.95) — `date_parser.py` resolves the vague-time word
   "morning" to a default clock time, which a naive "date parser tier
   before regex tier" ordering trusted over an obviously-just-a-greeting
   message. Fixed by making anchored, whole-message pattern matches
   (greeting/small-talk) authoritative and checked before the date
   parser, entirely within `core/intent/rules.py`'s own tiering — the
   same lesson this ADR already drew from `date_parser.py`, needing to be
   applied a second time at the component level it predicted might be
   needed ("Rule authoring is manual work," Consequences, above).
2. **Tier 0's command table is duplicated, not shared**, because
   `main.py`'s `_starts_with_handlers`/`_exact_handlers` are local
   variables inside `handle_message()`, not importable, and `main.py`
   importing `core.intent` for Shadow Mode makes the reverse import
   circular. This wasn't explicitly anticipated in this ADR's "Positive"
   consequences ("every rule is independently unit-testable... extending
   the precedent `tests/test_date_parser.py` already set") — that
   precedent held for Tiers 1/2 (genuine `date_parser.py` reuse) but not
   for Tier 0. Tracked as accepted architectural debt, not a defect — see
   [DEBUGGING.md](../../DEBUGGING.md#known-issues).
