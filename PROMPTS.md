# AI Prompt Reference

All prompts in BAKA are inline Python f-strings in `baka_brain.py` — there
are no template files and no shared prompt base class. This file is a map
of what exists and where, so a change to bot behavior can be traced to the
right prompt without re-reading the whole module. Full prompt text isn't
reproduced verbatim here (some are ~80 lines); use the line numbers to jump
to source.

## Main intent-detection prompt — `get_baka_response()`

**Where:** `baka_brain.py`, system prompt built around lines 220–302.
**Model:** `MODEL_MAIN` (see [docs/ai_system.md](docs/ai_system.md) for the
current model ID — it has changed since this prompt was first written).
**Called from:** the fallback path of every free-text message that isn't
handled by the slashless-command table or a keyword view-shortcut (see
[ARCHITECTURE.md](ARCHITECTURE.md#message-lifecycle)).

What it instructs, roughly:
- Identity/persona framing
- Injected context: current date/time, the user's profile, open tasks,
  memories, and recent conversation history
- Bilingual vocabulary hints (English/Hindi/Hinglish keywords)
- An 11-way intent taxonomy: `TASK`, `HABIT`, `EDIT`, `DELETE`, `VIEW`,
  `MEMORY_SAVE`, `MEMORY_GET`, `GOAL`, `PLAN`, `ADVICE`, `CHAT`, `MULTIPLE`
- Hardcoded disambiguation rules — e.g. any recurrence phrasing
  (every/har/daily/weekly/monthly) always resolves to `HABIT`, not `TASK`
  or `GOAL` (this was a specific bug fix, see
  [CHANGELOG.md](CHANGELOG.md#v71--log-driven-bug-fixes--rich-html-formatting));
  vague time words like "shaam" get a fixed hour mapping the AI must not
  override (`date_parser.py` enforces this regardless of what the AI
  returns — see [docs/ai_system.md](docs/ai_system.md))
- Title-extraction examples
- A strict JSON output schema the caller parses via `clean_json()`

**If you're debugging a misclassified message**, this is almost always the
prompt to look at first — check whether the disambiguation rules cover the
phrasing, and whether `date_parser.py`'s parallel deterministic parsing
(which overrides the AI for date/time) is fighting with it.

## Free-form reasoning prompt — `think_freely()`

**Where:** `baka_brain.py`, system prompt around lines 922–956.
**Model:** `MODEL_THINK`. **Called from:** `/think` and `/ask`.

Builds a shorter system prompt from the user's profile, open tasks, habits,
and memories, with an explicit instruction to not be generic and to stay
under 200 words. No JSON schema — this is the one AI path that returns
free-form conversational text intentionally.

## Everything else

`generate_daily_plan()`, `generate_weekly_plan()`, `generate_task_breakdown()`,
`suggest_reschedule_time()`, `generate_study_plan()`, `analyze_productivity()`,
`suggest_tasks()`, `chat_with_ai()` each build a short, single-purpose
user-role prompt fresh per call, with no system message and no shared
template. If you're adding a new AI-backed feature, this is the pattern to
follow unless it needs the rich user-context injection that
`get_baka_response()`/`think_freely()` do.

## Output parsing

`clean_json()` strips markdown code fences and extracts the first
`{...}`/`[...]` block before `json.loads()` — every JSON-returning prompt
above relies on this rather than strict structured-output mode, since NIM's
OpenAI-compatible endpoint is used without guaranteed JSON-mode support
confirmed. To Be Documented: whether NIM's `response_format` JSON mode is
available and would be more reliable than this strip-and-parse approach.

## Changing a prompt safely

Since there's no test harness that exercises AI output directly (see
[TESTING.md](TESTING.md) — `/selftest` is a *manual* checklist, not
automated), a prompt change should be validated against `/selftest`'s
relevant sections (particularly A–D for parsing/intent, J for habits, P for
project commands) before considering it done.
