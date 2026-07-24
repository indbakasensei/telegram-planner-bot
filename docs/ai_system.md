# AI System

## AI foundation (`core/ai/`, v15.1.0-alpha.2)

Provider/model configuration is resolved centrally by
`core/ai/provider.py` — `resolve_config(env)` returns a `ProviderConfig`
from the environment, filling gaps from a named **preset**
(`nvidia-nim`, `glm`, `local`). `baka_brain.py` consumes this behind a
guard (a resolution failure falls back to the historical NIM constants, so
startup can never break). An empty/NIM environment reproduces the old
defaults byte-for-byte.

**GLM 5.2 migration is configuration only:** `MODEL_MAIN=z-ai/glm-5.2`
(GLM 5.2 hosted on NVIDIA NIM) or `AI_PROVIDER=glm` + `GLM_API_KEY`
(GLM-native Zhipu endpoint). Verify offline via `/selftest → AI → AI
Configuration`.

Also shipped as **foundation** (interfaces only, consumed by later
milestones — not yet wired into the planner):
- `core/ai/reliability.py` — typed errors (`AITimeout`/`AIRateLimited`/
  `AIUnavailable`/`AIBadRequest`), `classify_status()`, and
  `call_with_retry()` (exponential backoff + jitter, injectable sleep).
- `core/ai/retrieval.py` — `Retriever` interface + `NullRetriever`.
- `core/ai/tools.py` — `Tool`/`ToolSpec`/`ToolRegistry` (with `to_openai()`).

The live chat path below still uses `baka_brain.py`'s own retry/fallback
loop; adopting `core/ai/reliability.py` there is a later step.

## Provider

Single provider: **NVIDIA NIM**, accessed through the OpenAI-compatible
`openai` Python SDK with `base_url="https://integrate.api.nvidia.com/v1"`.
Env var: `NVIDIA_API_KEY` (loaded via `dotenv`, with a manual `.env` parse
fallback in `baka_brain.py` in case `dotenv` doesn't pick it up).

Image and video generation bypass the chat-completions client entirely and
hit NIM's `genai` REST endpoints directly via raw `httpx`
(`https://ai.api.nvidia.com/v1/genai/{model}`), since those aren't
chat-completion calls.

**Retry behavior:** the OpenAI client itself is created with
`max_retries=0` — the SDK's built-in retry is deliberately disabled,
because it used to block the event loop for several minutes on a NVIDIA 504
(per an in-code comment describing the incident). Instead, the app wraps
every call in its own retry loop: 3 attempts, 2s sleep between, with
automatic MAIN→FAST model fallback if the model signals it's dead (HTTP
410, "DEGRADED" status, 504, or timeout).

## Models currently in use

`baka_brain.py`'s model constants — **these differ from what `README.md`
and several `CHANGELOG.md` entries originally said**, because NVIDIA
retired the originally-chosen model partway through the project:

| Role | Constant | Current model ID | Note |
|---|---|---|---|
| Main brain | `MODEL_MAIN` | `meta/llama-3.3-70b-instruct` | `z-ai/glm-5.1` was EOL'd by NVIDIA (HTTP 410); its successor `glm-5.2` was "DEGRADED" at time of switch, so Llama 3.3 70B was chosen as the stable option |
| Fast/cheap | `MODEL_FAST` | `meta/llama-3.1-8b-instruct` | Unused in practice — see `ENABLE_FAST_ROUTING` below |
| Deep reasoning | `MODEL_THINK` | `meta/llama-3.3-70b-instruct` | Same model as MAIN currently (not a separate GLM instance as originally designed) |
| Vision | `MODEL_VISION` | `meta/llama-3.2-90b-vision-instruct` | Unchanged since v11.0 |
| Image gen | `MODEL_IMAGE` | `black-forest-labs/flux.1-schnell` | Changed from `flux.1-dev`; the official API spec required a plain `"prompt"` string body and `cfg_scale=0`, not the Stable-Diffusion-style `text_prompts` array originally used |
| Video gen | `MODEL_VIDEO` | `stabilityai/stable-video-diffusion` | Changed from `nvidia/cosmos-1.0-7b-text2world` — Cosmos has no hosted NIM endpoint. SVD is image-to-video, so video generation is actually a two-step pipeline: FLUX generates a frame, then SVD animates it |

**If you're relying on a model name from `README.md`, `feature_list.md`, or
an older `CHANGELOG.md` entry, verify against `baka_brain.py` directly —
this table reflects the constants as read during the 2026-07 documentation
pass.**

## Feature flags (`baka_brain.py`, top of file)

| Flag | Value at time of writing | Effect |
|---|---|---|
| `ENABLE_FAST_ROUTING` | `False` | If enabled, `MODEL_FAST` would pre-classify simple intents before escalating to `MODEL_MAIN` (saves API calls). Currently every message goes straight to MAIN |
| `ENABLE_VISION` | `True` | Photo messages get routed to the vision pipeline |
| `ENABLE_IMAGE_GEN` | `True` | `/image` is live (originally opt-in/off in v11.0; flipped on in a later revision) |
| `ENABLE_VIDEO_GEN` | `True` | `/video` is live (same — originally opt-in) |

## Async boundary (v12.3, Sprint 1B)

`baka_brain.py` is entirely synchronous — the OpenAI-compatible client, the
raw `httpx` calls for image/video generation, and the app-level retry loop's
`time.sleep()` calls are all blocking. Nothing inside this file was changed
to fix that (deliberately — see below); instead, every call site in
`main.py` that invokes one of `baka_brain.py`'s public functions goes
through `async_bridge.py`'s `run_blocking()`, which runs the call on a
worker thread via `asyncio.to_thread()`:

```python
result = await run_blocking(generate_image, prompt, user_id=user_id)
# instead of: result = generate_image(prompt, user_id=user_id)
```

**Why the wrapping lives outside `baka_brain.py`, not inside it:**
`generate_video()` calls `generate_image()` internally, synchronously, by
name (`baka_brain.py` — `generate_video`'s body). If `generate_image` were
independently converted to an `async def` in place, that internal call
would silently return an unawaited coroutine instead of the actual image.
Routing through one external boundary function means `baka_brain.py`'s
internal call graph — `generate_video`→`generate_image`,
`call_fast`→`call_main`, every `call_*` wrapper→`_call_model`/`call_nvidia`
— keeps working exactly as before, entirely within whichever single worker
thread `run_blocking()` handed the outermost call to. No prompt, no
business logic, and no line inside `baka_brain.py` changed for this fix.

**Not in scope:** `database.py` calls. Benchmarked directly against the
live `planner.db`: 0.3-0.4ms per call (connect+query+close included) —
negligible for event-loop purposes given this bot's scale (252 call sites
in `main.py`, vs. 19 for the AI/media layer where a single call can take
seconds to minutes). See `ENGINEERING_AUDIT.md`/`CHANGELOG.md`'s v12.3
entry for the full reasoning.

**Migration path:** when/if `baka_brain.py` is migrated to a native async
client (`AsyncOpenAI`, `httpx.AsyncClient`), `async_bridge.py` is the one
place to update — call sites using `run_blocking()` would not need to
change individually.

## Function inventory

See [API.md](../API.md#bakabrainpy-grouped-by-purpose) for the grouped list
of every public function. The two dispatch paths worth understanding:
- `call_nvidia()` — the original, single-model call path. Despite being
  labeled "legacy" in its own docstring, it's still actively used by
  `chat_with_ai`, `suggest_tasks`, `analyze_productivity`,
  `generate_daily_plan`, `generate_weekly_plan`, `generate_task_breakdown`,
  `suggest_reschedule_time`, `generate_study_plan`, `extract_memory_key`,
  and `get_baka_response` — i.e. most of the codebase still goes through it
- `_call_model()` — the v11.0 generic dispatcher, used by the newer
  `call_main()`/`call_fast()`/`call_think()`/`call_vision()` wrappers

Both paths attempt to log to the analytics pipeline (see below); both are
currently silently failing to do so.

## Prompts

See [PROMPTS.md](../PROMPTS.md) for the full prompt map.

## Diagnostics

Three overlapping-but-distinct diagnostic functions:
- `check_api_status()` — single-call online/offline check, powers `/status`
- `benchmark_ai()` — 3-test (`status`) or 6-test (`status full`) graded
  benchmark (A+ to F)
- `benchmark_all_models()` — per-model liveness probe, powers `/models`

## Usage/analytics pipeline — currently non-functional

**Intended design:** every AI call in `baka_brain.py` calls
`from analytics import log_ai_request` (or `log_image_request`), which
pushes a row onto an in-process `queue.Queue`; a daemon thread in
`usage_logger.py` drains the queue and does the actual SQLite insert into
`ai_usage` (WAL mode, so logging never blocks the AI response path).
`usage_service.py`, `model_metrics.py`, and `performance_tracker.py` are
pure `SELECT`-based query layers over that table, surfaced by `/usage`,
`/performance`, `/errors`, and the usage portion of `/models`.

**Actual current state:** there is no `analytics` package in the repo —
`usage_logger.py` and friends sit flat at the project root with no
`__init__.py` wiring them together, and `usage_logger.py` uses a
package-relative import (`from .token_counter import ...`) that only
resolves inside an actual package. Every `import analytics` call site (in
`baka_brain.py`, `database.py`, and `main.py`) is wrapped in a bare
`try/except: pass`/`except Exception`, so:
- the `ai_usage` table is never created
- every AI call's logging attempt silently no-ops
- `/usage`, `/performance`, `/errors` return empty stats instead of erroring

Full remediation detail: [DEBUGGING.md](../DEBUGGING.md#known-issues) and
[ROADMAP.md](../ROADMAP.md#fix-it-list-found-during-the-2026-07-documentation-pass).

`token_counter.py`'s `MODEL_COSTS` table (15 priced models) also still
references the old model IDs (`z-ai/glm-5.1`, `flux.1-dev`,
`cosmos-1.0-7b-text2world`) rather than the current ones above — cost
lookups for current models fall through to a fuzzy substring-match fallback
or return `$0.00`/`"Unknown"`, independent of the packaging fix.

## Dead code

`ai_helper.py` is not imported anywhere in the codebase (confirmed via
repo-wide search). It also has a hardcoded-looking real API key committed
in source — see [DEBUGGING.md](../DEBUGGING.md#known-issues).
