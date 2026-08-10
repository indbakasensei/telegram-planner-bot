# M1 — Reference Resolution & Active Entity Context (v15.1.0-alpha.12)

**Date:** 2026-08-10
**Milestone status:** implementation complete; live Telegram acceptance
outstanding (offline suite green).
**Head when written:** `993150f` (M1 completion change-set).

---

## Objective

Make conversational references work against real context instead of being
re-guessed by the LLM or swallowed by unrelated handlers. After the user
creates, views, or updates an entity, the bot should understand:

- **Pronouns** — "show her", "show him", "show it", "what level is she?"
- **Ordinals** — "show the first one", "show the second one", "show the last one"
- **Bare references** — "her", "the current one"
- **Deterministic updates** — "Sucrose is level 70" must not be misclassified
  as a retrieve by a weak classifier.

Resolution must be **deterministic** (no LLM call for the resolution itself),
**safe** (never a random guess, never an invented entity), and **conservative**
(genuinely ambiguous references ask for clarification).

## Architecture changes

Three new/moved pieces, all in the existing EntityManager path — no new
framework, no Workspace OS changes, no Telegram changes.

### 1. `core/ai/reference_context.py` (new) — conversational memory

- **`Referent`** — identity is `(kind, workspace_id, id)`, never a
  display-name substring, so renames/deletes never alias. `title` is only for
  rendering and clarification.
- **`ReferenceContext`** — per-user in-memory state:
  - recent-mention stack (last `MAX_RECENT = 10` per user), and
  - last ordered list per user.
- Ephemeral, mirroring `conversation_state.py`. The authoritative *active
  entity* lives in the DB-backed `tg_active_context` row; this module only
  supplements it with mention order and ordered-list context the DB does not
  model.

### 2. `core/ai/reference_resolver.py` (new) — deterministic resolution

`ReferenceResolver.resolve(user_id, text, workspace_id, entities)` returns a
`Resolution` and **never mutates the DB and never calls the LLM**. Precedence
(audit §4.3):

1. **Ordinal phrase** ("the first one") → the last ordered list shown in this
   workspace. Out-of-range or no-list → `kind="none", had_reference=True`
   (caller degrades gracefully, never guesses).
2. **Active entity** (DB `tg_active_context`) → strongest deictic signal.
   A dangling id is reported as `stale_active` for the caller to clear.
3. **Exactly one distinct recent mention** in the workspace.
4. **Several distinct mentions** → `ambiguous=True` with the candidates; the
   caller asks which one, never guesses.
5. Nothing usable → `kind="none"` and the caller falls through to the normal
   pipeline.

Reference detection is deliberate:
- **Strong**: gendered/plural pronouns (he/him/she/her/they), deictic phrases
  ("this one", "the current one"), ordinals.
- **Weak** ("it", "its", "this", "that"): only treated as a reference when the
  message also carries an entity-intent signal — so "what time is it?" is
  never hijacked.

`entities` is the caller's fresh non-deleted milestone list, so resolution
can never target a soft-deleted row (see stale handling below).

### 3. `core/ai/entity_manager.py` — wired in

- `process()` runs `resolve()` **before** the keyword pre-check and the LLM.
  A resolved referent with a signal — or a bare reference — forces the gate
  open; a `kind="none"` reference falls through untouched.
- **Active entity tracking:** create/update/retrieve all call
  `_activate_entity()` which persists the resolved entity to
  `tg_active_context`. This closes audit F2/F3's root cause: previously
  *nothing* set an active entity from the NL path.
- **Ordered-list tracking:** `_note_list()` records the ordered list whenever
  a retrieve produces one — including lists produced through the
  CognitiveEngine fallback. Activating a single entity no longer wipes the
  list (fixes the "show all → first one → last one" failure).
- **Bare-reference retrieve:** a message that is exactly a pronoun/deictic
  phrase goes straight to `_handle_retrieve(..., preferred=active_entity)` —
  no LLM call.
- **Deterministic single-field update** (`_try_extract_update`): recognises
  "Sucrose is level 70", "Sucrose is level70", "Sucrose's level is 70",
  "Set Sucrose level to 70", and safe active/pronoun forms ("set her level to
  90") without the LLM. Field names come from the active template's field
  specs — never hardcoded. Fixes the observed failure where the fast LLM
  classified "Sucrose is level 70" as `intent=retrieve` and the update never
  ran.
- **Ambiguity:** a genuinely ambiguous reference returns
  `_clarify_message(resolved)` naming the candidates.
- **Stale active entity:** a dangling active-entity id is cleared; a deleted
  entity is never resurrected (resolution is re-validated against the live
  entity list).

## Files changed (M1)

| File | Change |
|---|---|
| `core/ai/reference_context.py` | new — `Referent`, `ReferenceContext` |
| `core/ai/reference_resolver.py` | new — `ReferenceResolver`, `Resolution`, ordinal helpers |
| `core/ai/entity_manager.py` | resolver wiring, `_activate_entity`, `_note_list`, `_is_bare_reference`, `_try_extract_update`, `_clarify_message` |
| `tests/test_reference_resolution.py` | new — 35 offline tests |

## Tests

- **Offline unit tests** (`tests/test_reference_resolution.py`, 35): create →
  pronoun, pronoun variants, ordinals (first/second/last), ordinal-via-
  CognitiveEngine list, list persistence across activation, full-sentence
  pronoun retrieval, ambiguity + clarification, explicit-name-beats-active
  precedence, stale/deleted-entity self-heal, deterministic field updates,
  workspace isolation. The LLM is mocked and bare references are asserted to
  never reach it.
- **EntityManager suite** (`tests/test_ai_entity_manager.py`, 37) — unchanged,
  still green.
- **Targeted result:** `72 passed` (37 + 35).
- **Full suite:** `1269 passed` (was 1234 at alpha.11).
- **M1 regression specs** (`core/regression/suites/reference_m1.py`, REF-001…
  REF-014): manual Telegram acceptance for the Xiao/Kinich/Xilonen/Nefer/
  Lauma/Columbina matrix.
- **Self-test** (`core/selftest/tests/test_workspace.py` → "Reference
  Resolution"): creates an entity, resolves "show her" to it with no AI call,
  cleans up.

## Known limitations (deliberately not fixed in M1)

1. **Strong-pronoun non-bare queries without a keyword still fall through**
   ("Can she ascend further?"). The resolver *would* resolve it, but the
   EntityManager pre-check gate requires a keyword or a bare reference.
   Fixing this needs either expanding the keyword vocabulary (domain coupling)
   or widening the gate (hijack risk) — deferred.
2. The deterministic extractor handles **single-field updates only**;
   multi-field updates still go through the LLM classifier.
3. References resolve **workspace entities only**; task-level references
   ("delete the first one") remain legacy-routed (the `delete ` prefix handler
   pre-empts EntityManager) — scheduled for M4.
4. **NL entity creation still bypasses the Telegram topic projection** — no
   topic is created for an entity created via natural language. Scoped as M10;
   see `M10_TOPIC_BACKFILL.md`.

## Remaining work

- Live Telegram acceptance of REF-001…REF-014 (manual).
- **M2:** robust JSON decoding with clarification instead of silent
  fall-through — a misclassified intent must not masquerade as success.
- M3 field-aware retrieval; M4 task lookup; M5 reminder/view semantics; M6
  confirmation truthfulness; M7 deterministic dates; M8 unified tool surface +
  bounded AI worker loop; M9 field semantics/schema validation; M10 Telegram
  topic wiring (see `AI_WORKER_AUDIT.md` §4–§5 for the full plan).
