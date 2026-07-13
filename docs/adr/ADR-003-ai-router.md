# ADR-003: AI Router Returns Structured Data Only, Never Writes Directly

**Status:** Proposed
**Part of:** BAKA v14 Autonomous Core (`DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`)
**Depends on:** ADR-001 (Offline-First Philosophy)

## Problem

Today, `baka_brain.py`'s AI responses are interpreted and acted on
inconsistently across `main.py`'s handlers — `get_baka_response()`'s JSON
result is parsed and its `intent`/`entities` fields drive different write
paths depending on which handler branch consumes it, each with its own,
independently-written validation (or lack thereof). There's no single
place that decides "is this AI output safe/well-formed enough to write to
the database," and no single place an engineer can look to understand
every way AI-generated content can end up persisted.

Separately, `requirements.txt` already carries unused `anthropic` and
Google Gemini SDK dependencies (confirmed via `pip` inspection during this
design's research), and this project has now hardcoded-and-then-had-to-fix
its single-provider dependency three times (`CHANGELOG.md` v11.2 ×2,
`AI_DIAGNOSTIC_REPORT.md`). A multi-provider design is needed regardless of
the write-path question above — but the two problems compound: a
multi-provider router that *also* writes directly to the database would
mean validating AI output N times, once per provider adapter, instead of
once.

## Alternatives considered

1. **Multi-provider router that still writes directly** (each provider
   adapter's result flows straight into `database.py`, same as today's
   single-provider pattern). Rejected: multiplies today's
   inconsistent-validation problem by the number of providers instead of
   fixing it, and makes each new provider adapter responsible for knowing
   BAKA's data model — unnecessary coupling between "how do I talk to
   Anthropic's API" and "what does a valid `TASK` entity look like."
2. **Router returns structured data, Offline Engine persists it (chosen).**
   Every provider adapter returns the same canonical `CompletionResult`
   shape (`AI_ROUTER.md`'s Provider Interface); exactly one component (the
   Offline Engine) ever writes AI-derived data to `database.py`, using the
   same validation path regardless of which provider produced the data.
3. **A separate "validation service" between the AI Router and the Offline
   Engine.** Considered and folded into option 2 rather than kept
   separate: validation-before-write is already the Offline Engine's job
   for deterministically-sourced writes too (Command Pipeline's Validation
   stage, `COMMAND_PIPELINE.md`) — a standalone validation service would
   just be the same logic under a different name, adding an unnecessary
   architectural seam.

## Decision

The AI Router's `complete()`/`vision()`/`generate_image()`/
`generate_video()` methods return structured `CompletionResult`/
`MediaResult` values and nothing else — no provider adapter, and no part
of the Router itself, ever calls `database.py` directly. The Offline
Engine is the only component with `database.py` write access for
AI-derived content, using the same validation and confirmation-flow
discipline it already applies to deterministically-sourced writes
(`COMMAND_PIPELINE.md`'s Validation stage).

## Consequences

**Positive:**
- Exactly one validation path for AI-derived writes, regardless of
  provider — closes the inconsistent-validation gap described in
  "Problem" above.
- Provider adapters stay simple: translate to/from the canonical message
  format, make the API call, normalize errors (ADR-003's real technical
  payload is arguably this normalization requirement, not the "don't
  write directly" rule, but both serve the same goal of keeping adapters
  narrow and interchangeable).
- Makes `DATA_FLOW.md`'s cross-cutting invariant ("every flow passes
  through the Offline Engine exactly once for its write") mechanically
  true rather than a convention that could be violated by a new provider
  adapter written without full context.
- Testable in isolation: a provider adapter can be tested purely on
  "does it correctly translate and normalize," without needing a fake
  database; the Offline Engine's AI-result-persistence path can be tested
  purely on "given this structured result, does it write the right thing,"
  without needing a fake AI provider.

**Negative / accepted tradeoffs:**
- One extra hop (AI Router → Offline Engine) versus letting a provider
  adapter write directly — negligible in practice (in-process function
  call, not a network round-trip), explicitly evaluated against NFR-3
  (master spec: routing overhead must not add a network round-trip) and
  found compliant.
- Requires provider adapters to agree on a canonical result shape even
  when a provider's native response is richer or differently structured
  (e.g. Anthropic's content-block format vs. OpenAI's flatter shape) — an
  explicit adapter responsibility (`AI_ROUTER.md`'s Provider Interface),
  accepted as necessary translation cost rather than avoided by leaking
  provider-specific shapes upstream.
