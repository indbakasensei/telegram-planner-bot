# Project Memory (dev/AI context)

A running log of decisions, gotchas, and context for whoever (human or AI
assistant) works on this codebase next. Not the bot's own in-app "remember
X" feature — that's the `memories` table, documented in
[docs/database.md](docs/database.md) and [API.md](API.md).

Keep entries short and dated. Prune entries once they're fully absorbed
into the permanent docs (ARCHITECTURE.md, API.md, etc.) — this file is for
context that doesn't have a clean permanent home yet, not a duplicate of
the changelog.

## 2026-07-13 — v14.0 Stage 1 (Intent Engine, Shadow Mode) shipped

Implemented `core/intent/` per the approved `INTENT_ENGINE.md`/ADR-002
design, in Shadow Mode (observes every message, doesn't affect routing).
Two things worth knowing before touching this code or repeating the
pattern elsewhere:

- **A new deterministic classifier can reproduce `date_parser.py`'s own
  historical bug class if you're not careful about tier ordering.** A
  bare `"good morning"` was initially misclassified as `ADD_TASK`
  (confidence 0.95) because `date_parser.py` resolves the vague-time word
  "morning" to a default clock time — correct for "remind me in the
  morning," wrong when "morning" is just the tail of a greeting. Fixed by
  making anchored, whole-message pattern matches authoritative and
  evaluated *before* the date parser. If you add a new deterministic rule
  anywhere in this codebase that reuses `date_parser.py`'s output, check
  whether a more specific, whole-message signal should outrank it before
  assuming "more tiers checked = more thorough."
- **`main.py`'s command tables (`_starts_with_handlers`/`_exact_handlers`)
  are not importable** — they're local variables inside `handle_message()`,
  not module-level. Anything outside `main.py` that wants to know "is this
  text a recognized command" has to maintain its own copy (as
  `core/intent/rules.py` now does, documented as accepted debt) or wait
  for the `main.py` god-function split `ENGINEERING_AUDIT.md` already
  recommends. Don't assume these tables can be imported without checking
  first — this cost real time to discover during Stage 1.
- Also found and fixed during this pass: `README.md` and `PROJECT.md`'s
  "current version" banners had said **v12.0** since before v13.0 shipped
  — several releases stale, never caught because nothing enforces these
  banners match `CHANGELOG.md`'s actual top entry. No automated check
  exists for this; if you notice it's drifted again, it probably has.

## 2026-07-11 — Documentation pass

A full documentation system was created (this file plus CLAUDE.md,
PROJECT.md, ARCHITECTURE.md, ROADMAP.md, CHANGELOG.md, TESTING.md,
DEBUGGING.md, API.md, PROMPTS.md, and `docs/*.md`), derived entirely from
reading the code — no application logic was changed. Highlights worth
knowing before touching this repo:

- **`VERSION.md` and `feature_list.md` are retired.** Their content moved
  into `CHANGELOG.md`/`ROADMAP.md` (VERSION.md) and `PROJECT.md`/`API.md`
  (feature_list.md). Both old files now carry a pointer notice rather than
  being deleted outright.
- **The `analytics` package doesn't exist.** This is the single biggest gap
  found — `/usage`, `/performance`, `/errors` all silently return empty
  data because `import analytics` fails everywhere it's attempted. Full
  detail in [DEBUGGING.md](DEBUGGING.md#known-issues). This is a
  self-contained, low-risk fix (packaging only) if picked up.
  **Status: documented, not fixed** (out of scope for the doc pass by the
  repo owner's choice).
  <!-- update this line to "fixed <date>" once addressed -->
- **`ai_helper.py:9` has a hardcoded-looking real NVIDIA API key**, written
  as a broken `os.getenv()` call. Flagged to the repo owner directly;
  recommended rotating the key since it's committed to git. **Status:
  flagged, not yet confirmed rotated or removed** — check before assuming
  this is resolved.
  <!-- update this line once confirmed -->
- **Model IDs drifted from what comments/README used to say.** `z-ai/glm-5.1`
  was EOL'd by NVIDIA (per `baka_brain.py`'s own comments,
  2026-07-02, HTTP 410). Current models: `meta/llama-3.3-70b-instruct`
  (main+think), `flux.1-schnell` (image), `stabilityai/stable-video-diffusion`
  (video). If NVIDIA ships a stable `glm-5.2`, `MODEL_MAIN`/`MODEL_THINK`
  are the constants to check in `baka_brain.py`.
- **Two independent "Section P" test lists exist** and collide in name —
  `TEST_CHECKLIST.md`'s Section P (edge cases) vs. `debug_system.py`'s
  `/selftest` Section P (v12.0 project tests). See
  [TESTING.md](TESTING.md#two-checklists--read-this-first).
- **In-memory state does not survive restarts**, despite a docstring in
  `conversation_state.py` claiming otherwise. If you're chasing a bug where
  users report losing their place mid-conversation, check bot uptime first.

## How to use this file

- Add an entry when you make a non-obvious decision, discover something
  surprising, or leave something intentionally unfinished — future you (or
  another AI session) needs the "why," not just the "what" (git log covers
  the "what").
- Don't log routine feature additions here — that's what `CHANGELOG.md` is
  for.
- Don't duplicate anything that already has a stable home in
  `ARCHITECTURE.md`/`API.md`/`docs/*.md` — link to it instead.
