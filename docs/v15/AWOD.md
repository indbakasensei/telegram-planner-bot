# AWOD — AI Workspace Orchestrator Design (v15.0)

*Design only.*

## 1. Principle

Natural language, no explicit commands. "I finished chapter six" should:

```
determine active workspace  →  update progress  →  update milestone  →
append timeline  →  store note  →  sync Telegram  →  refresh summary
```

The Orchestrator is a **new layer ABOVE the existing stack**, not a
replacement. Today's pipeline is:

```
message → Conversation State → Intent Engine → Routing → Offline → Legacy(AI)
```

v15 inserts workspace-awareness after intent, before action:

```
message → State → Intent → [Workspace Orchestrator] → Workspace Engine op
                                    │ (falls through unchanged when no
                                    ▼  workspace context applies)
                             existing Routing/Offline/Legacy
```

Gated by `feature_flags.WORKSPACE`: OFF ⇒ the Orchestrator is skipped and
the pipeline is exactly today's.

## 2. The orchestration pipeline (six resolvers)

Each step is a small, testable resolver; the Orchestrator chains them and
stops early when confidence is low (→ clarify).

1. **Intent recognition.** Reuse the deterministic Intent Engine +
   `baka_brain`. Add workspace-shaped intents: `WORKSPACE_UPDATE`,
   `WORKSPACE_QUERY`, `WORKSPACE_CREATE`, `MILESTONE_COMPLETE`,
   `NOTE_ADD`. Unrecognized → fall through to the existing pipeline.
2. **Workspace selection ("active workspace").** Resolve which workspace
   the utterance targets, in priority order:
   a. explicit ("in Filament Recycler, …") → exact/fuzzy title match;
   b. **conversation context** — the workspace of the current Telegram
      Topic (TWID) or the last-touched workspace (a per-user
      `active_workspace` pointer);
   c. content match — entity names in the message (a milestone/book/goal
      that belongs to exactly one workspace);
   d. none → ask ("Which workspace? Book: *Deep Work* or Project:
      *Slipstream*?").
3. **Entity resolution.** Within the chosen workspace, resolve the target
   entity: "chapter six" → the book's chapter model; "the CAD" → the
   milestone titled/aliased CAD. Fuzzy match + template awareness (a book
   resolves chapters, a project resolves milestones).
4. **Action planning.** Map (intent, entity, delta) → a concrete
   Workspace Engine operation: `milestone.complete`,
   `progress.set(60)`, `note.add(...)`, `task.complete`.
5. **Safety gate** (§4) — validate before mutating.
6. **Apply + cascade.** Execute via the Storage Facade → emit timeline
   events (KTD) → enqueue Telegram sync (TWID) → schedule summary refresh
   → reply with a confirmation card.

## 3. Automatic updates (worked example)

> "I finished chapter six of Deep Work and it changed how I think about focus."

- select → Book workspace *Deep Work* (title match);
- resolve → chapter 6 (book template's chapter model);
- plan → `progress.set` chapters=6/total; if 6 completes a milestone,
  `milestone.complete`;
- safety → non-destructive, high confidence → no confirm needed;
- apply → timeline: `task/chapter.completed`, `workspace.progress_changed`;
  the reflection ("changed how I think…") → `knowledge.added` note;
- sync → post to the *Deep Work* Topic; refresh AI summary.

One utterance, six side effects, zero commands.

## 4. Safety rules (non-negotiable)

The Orchestrator can mutate real data from fuzzy input, so it is
**conservative by construction**:

1. **Confirm the irreversible.** Deletions, archiving, and any
   cross-workspace move require an explicit yes/no (reuse the existing
   `confirming` state + ADR-010 policy). Reversible updates (progress,
   notes, completion) apply directly — matching how the Offline Engine
   already decides confirm-vs-direct.
2. **Clarify, never guess, on ambiguity.** If workspace or entity
   selection is below a confidence threshold, ask — don't pick. Silent
   wrong-workspace writes are the worst failure mode (cf. the v14 log
   audit, where a degraded model misclassified inputs).
3. **One workspace per utterance by default.** Cross-workspace effects
   require explicit intent; the Orchestrator never fans out implicitly.
4. **AI proposes, the engine validates.** The AI's structured output is
   treated as a *proposal*; the Workspace Engine re-validates entity
   existence, ownership (user_id), and state transitions before writing —
   the AI is never trusted to write directly (same "AI proposes, code
   disposes" stance as create/delete task).
5. **Degradation is graceful.** If `baka_brain` times out (a known v14
   failure mode), the Orchestrator falls through to the existing pipeline
   or asks the user to rephrase — it never applies a half-parsed action.
6. **Every mutation is timelined.** Auditability is a safety feature: a
   wrong write is visible and reversible via the journal.

## 5. Conflict handling

- **Concurrent edits:** single-user, single-process today (instance
  lock, v13.1) → conflicts are rare; last-write-wins on the entity row,
  and the timeline records both events so nothing is lost.
- **Ambiguous entity ("chapter six" in two active books):** clarify
  (§4.2).
- **Stale reference ("finish the motor milestone" after it's done):**
  detected at validation (§4.4) → informs the user, no-op, no error.
- **Contradictory update ("set progress to 40" when it's 80):** applied
  (user intent wins) but the timeline records the decrease, so it's
  auditable/undoable.

## 6. Reuse & preservation

- Reuses the Intent Engine, `baka_brain`, conversation state, the
  confirming/gathering flows, and `fmt.py` — adds a resolver chain on
  top, not a parallel AI.
- Flag OFF ⇒ the Orchestrator does not run; today's NL handling is
  unchanged. Existing AI commands (`think`, `plan`, chat) are untouched;
  workspace intents are new and additive.
- The Orchestrator is `core/workspace/orchestrator.py`, pure and
  facade-only, offline-unit-testable (resolvers tested with fixtures;
  the AI call mocked) — same testability discipline as `core/offline`.
