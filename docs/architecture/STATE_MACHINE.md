# State Machine — Design Specification

**Part of:** `DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`. Documentation only.
**Extends, does not replace:** `conversation_state.py`'s existing
`idle`/`gathering`/`confirming`/`editing` states. `ENGINEERING_AUDIT.md`
already documents this module's one real limitation (in-memory only,
doesn't survive a process restart) — v14's state machine design keeps
that same storage model by default (§Persistence note at the end) since
fixing it is orthogonal to this architecture, not a prerequisite for it.

---

## Why extend rather than replace

`conversation_state.py`'s four states already correctly model the core
loop every multi-turn flow in this bot needs: waiting for input (`idle`),
collecting missing fields (`gathering`), waiting for yes/no
(`confirming`), and patching an existing record (`editing`). v14 doesn't
need a fundamentally different model — it needs these four states to be
reachable from more entry points (AI Router results, plugin-originated
flows) than `main.py`'s hand-written transitions currently allow.

## Core state diagram

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Gathering: Intent Engine matched intent,<br/>required entity missing<br/>(CLARIFY routing)
    Idle --> Confirming: Intent Engine or AI Router<br/>produced a complete,<br/>write-eligible result
    Idle --> Editing: "/edit &lt;id&gt;" or<br/>natural-language edit match

    Gathering --> Gathering: partial answer, still missing fields
    Gathering --> Confirming: all required fields now present
    Gathering --> Idle: /cancel

    Confirming --> Idle: "yes" -> Offline Engine executes,<br/>OR "no" -> cancelled
    Confirming --> Gathering: user supplies a correction<br/>instead of yes/no<br/>(today's "set time to 5pm" pattern)

    Editing --> Idle: edit applied or cancelled

    Idle --> AIPending: routed to AI Router
    AIPending --> Confirming: AI Router result requires<br/>confirmation before persisting
    AIPending --> Idle: AI Router result is read-only<br/>(e.g. /think has no write step)
    AIPending --> Idle: AI Router unavailable<br/>(error message, state resets)
```

The only genuinely new state relative to today is `AIPending` — today,
`main.py` blocks synchronously (via `async_bridge.py`'s `run_blocking()`)
while waiting for `baka_brain.py`, so there's no user-visible "waiting on
AI" state to model. v14's AI Router is expected to remain synchronous
from the state machine's point of view too (a request is either resolved
or it times out within its per-workload budget, `AI_ROUTER.md`) — 
`AIPending` exists in this diagram for clarity and as a hook for a future
"still thinking..." interim message (`AI_DIAGNOSTIC_REPORT.md`'s
Recommendation D, explicitly not built for v14), not because v14 requires
asynchronous, multi-message AI interactions.

## Flow examples

### Normal chat (no state change)

```
Idle --[classify: CHAT intent, route to AI Router]--> AIPending --[response]--> Idle
```

Matches today's behavior for a message like "How are you?" exactly —
`get_baka_response()`'s CHAT intent already doesn't persist anything or
change conversation state.

### Confirmation flow (task creation)

```
Idle --[TASK intent, all fields resolved]--> Confirming
    --["yes"]--> Idle (Offline Engine executes, database.py write happens)
    --["no"]--> Idle (cancelled, nothing written)
    --["set time to 5pm"]--> Confirming (entity corrected, still confirming)
```

Identical to today's `confirming` state handling in `handle_message()`
(the `positive`/`negative`/`parsed_time` branches) — v14 relocates this
logic behind the Command Pipeline's stages, it does not change the state
transitions themselves.

### Reminder flow (scheduler-initiated, no user-turn state)

Reminders don't go through the conversation state machine at all, today
or in v14 — they're scheduler-initiated (`docs/scheduler.md`), not a
response to user input, so there's no "waiting for the next message" state
involved. A reminder's *response* (tapping "Done"/"Snooze") is a callback
query, handled by the Command Pipeline's callback-ingress path
(`COMMAND_PIPELINE.md` §Ingress), which for a button tap always resolves
to a single, complete, immediately-executable `COMMAND` intent —
never `Gathering`.

### Goal creation

```
Idle --[GOAL intent via Intent Engine Tier 1<br/>("I want to X"), or AI Router<br/>for ambiguous phrasing]--> Confirming
    --["yes"]--> Idle (Offline Engine writes to goals table)
```

### Project management (multi-entity flow)

Projects are a good example of a flow that spans several *separate*
single-turn interactions rather than one long multi-state conversation —
"need 5 motor, battery", "got motor", "worklog 5 frame mounted" are each
independently a single `Idle → Confirming → Idle` (or, since most project
commands are unambiguous Tier-0 matches, often skip `Confirming` entirely
and execute directly — `got <name>`'s fuzzy-match-then-act pattern,
`docs/dashboard.md`, already works this way today). v14 does not need a
dedicated "project session" state; the existing four-state model already
covers each individual project command correctly.

### AI reasoning (`/think`)

```
Idle --[THINK intent, Tier 0]--> AIPending --[response, read-only]--> Idle
```

No `Confirming` step — matches today's `think_freely()` behavior exactly
(a `/think` response is never persisted, so there's nothing to confirm).

### Error recovery

```
AIPending --[NoProviderAvailable, AI_ROUTER.md]--> Idle
    (user-facing message explains what was understood before the
     failure, per INTENT_ENGINE.md's error-recovery section, rather
     than a generic failure message)

Gathering --[ambiguous re-answer, e.g. still no valid time]--> Gathering
    (re-prompt, same as today's "what time?" retry loop)

Confirming --[unrecognized reply, neither yes/no/correction]--> Confirming
    (today's fallback: re-show the summary and ask again --
     `main.py`'s final `else` branch in the confirming-state handler)
```

## Persistence

**Deliberately unchanged from today**: state lives in the same kind of
in-memory, module-level structure `conversation_state.py` already uses,
not a new database-backed session store. This is a conscious choice, not
an oversight — `ENGINEERING_AUDIT.md`'s G-category finding on this exact
limitation already exists and already has a documented remediation
sketch (a SQLite-backed state table) that this design does not duplicate
or preempt. If that fix ships independently, the state machine described
here adopts it transparently, since nothing in this document depends on
*where* state is stored, only on what the valid states and transitions
are.

## Relationship to the Intent Engine and Offline Engine

The state machine is consulted by the Intent Engine as **context** (a
message's classification can depend on the current state — e.g. "5pm" means
something different in `Gathering` than in `Idle`, exactly as
`main.py`'s `handle_message()` already special-cases each state before
falling through to general classification) and updated by the Command
Pipeline's Execution stage as an **effect** (a successful classification
in `Idle` may transition to `Confirming`; a successful Offline Engine
execution transitions back to `Idle`). Neither the Intent Engine nor the
Offline Engine owns state transitions directly — the Command Pipeline
does, keeping "what state are we in" and "what does this message mean
given that state" as separate, individually testable concerns.
