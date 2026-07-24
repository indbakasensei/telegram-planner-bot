# AI Diagnostic Report

**Date:** 2026-07-13
**Type:** Diagnostic investigation only — no code, configuration, or
documentation changes were made as part of this report or the
investigation it documents.
**Status:** Root cause identified with high-confidence, direct empirical
evidence. Fixes are recommended but **not implemented**.

---

## 1. Executive Summary

- **What was investigated:** two related but distinct performance
  complaints — a simple chat message ("Hey") taking around one minute to
  get a reply, and the `/selftest` command becoming noticeably slower than
  it used to be. The investigation also compared behavior against a
  previous machine where the project reportedly ran faster.
- **Why the investigation was started:** the bot is functional but AI
  responses had become slow enough to be user-visible and disruptive,
  with no corresponding code change in the areas a user would suspect
  (reminders, scheduling, Telegram delivery all still work normally).
- **Final conclusion (short):** two separate, independent causes were
  found and confirmed with direct measurement, not inferred:
  1. The bot's main AI model (`meta/llama-3.3-70b-instruct`) is currently
     **unresponsive on NVIDIA's hosted infrastructure** — 5 out of 5 raw,
     direct test requests timed out at 30 seconds with zero successful
     replies, while a smaller model on the identical account, key, and
     network responded correctly in 676ms. This is external to the
     project; it is not caused by anything in this codebase.
  2. The bot's own fallback mechanism, built specifically to survive a
     model going bad (and already used twice before for exactly this
     kind of NVIDIA-side issue), **does not currently trigger for this
     particular failure mode** — its error-text matching does not
     recognize a plain client-side timeout, so the bot keeps retrying the
     broken model instead of automatically switching to the healthy one.
  3. Separately, `/selftest`'s slowdown is fully explained by a working-
     as-designed side effect of the Telegram delivery rate limiter added
     in a recent sprint (Sprint 2A): `/selftest` sends 18 messages in a
     row to the same chat, and the rate limiter now paces same-chat
     messages to about one per second, adding roughly 17–20 seconds versus
     before that rate limiter existed.

---

## 2. Problem Statement

Reported symptoms, as given at the start of the investigation:

- A simple message like **"Hey" takes around one minute** to receive a
  reply.
- **`/selftest` now takes much longer than before** to finish sending its
  output.
- **This same project previously ran significantly faster on another PC.**
- **Telegram API is functioning normally** — messages are delivered,
  buttons work, no connectivity complaints.
- **The scheduler is functioning normally** — reminders fire, no reports
  of missed or delayed scheduled jobs.

The scope of this investigation was narrowed accordingly: since Telegram
delivery and the scheduler were both reported as healthy, the
investigation focused on the AI request path (for the "Hey" symptom) and
on the interaction between `/selftest`'s own behavior and any recent
delivery-layer changes (for the `/selftest` symptom), rather than
re-auditing Telegram or scheduler internals from scratch.

---

## 3. Investigation Methodology

The following areas were inspected, each described in more detail in its
own section below:

- **AI request flow** — traced the exact call path from an incoming
  Telegram message through intent detection, AI routing, and the outbound
  HTTP call to NVIDIA, by reading `main.py` and `baka_brain.py` directly.
- **HTTP client** — inspected how the `openai` SDK client is constructed
  in `baka_brain.py`, including timeout, retry, and base URL
  configuration.
- **Retry logic** — read `call_nvidia()`'s attempt loop, sleep intervals,
  and its "model dead" fallback-detection logic line by line.
- **Timeout handling** — confirmed the configured client-side timeout and
  cross-referenced it against a documented prior incident (see §9).
- **NVIDIA model configuration** — read the model constants and feature
  flags directly from `baka_brain.py`, and cross-referenced them against
  `git log` to understand how they got to their current values.
- **Notification rate limiter** — read `notification_service.py`'s
  `TelegramSender` defaults and `main.py`'s `selftest_cmd()` to count
  exactly how many messages that command sends and how they're paced.
- **Environment comparison** — captured exact installed versions of
  Python, `httpx`, `openai`, `python-telegram-bot`, and OpenSSL on the
  current machine, compared against `requirements.txt`'s pinned versions.
- **Network diagnostics** — measured DNS resolution and raw TCP connect
  time to both the NVIDIA API host and the Telegram API host, directly,
  outside of any application code.
- **Raw NVIDIA benchmark** — wrote a small temporary script (deleted
  immediately after use, per instruction) that calls NVIDIA's API
  directly, bypassing Telegram and the rest of the bot entirely, using
  the exact same client configuration `baka_brain.py` uses. Ran it 5
  times against `MODEL_MAIN`, then once against `MODEL_FAST` to isolate
  whether the problem was model-specific or account/network-wide.

No code was changed at any point during this process. The one temporary
script used for the raw NVIDIA benchmark was deleted immediately after
producing its output and was never committed.

---

## 4. Request Timeline

```
Telegram Update
    ↓
main.py: handle_message()
    ↓  (slashless-command table checked and missed; keyword view-shortcut checked and missed)
Intent Detection / AI Routing
    ↓
await run_blocking(get_baka_response, ...)     [async_bridge.py — offloads to a worker thread
    ↓                                            so this doesn't block other users; does not
                                                  itself add meaningful latency for one message]
baka_brain.py: get_baka_response()
    ↓
baka_brain.py: call_nvidia()                    [up to 3 attempts, 2s sleep between]
    ↓
openai SDK → httpx → HTTPS request
    ↓
NVIDIA NIM (integrate.api.nvidia.com)
    ↓
Response (or timeout)
    ↓
Telegram reply, via notification_service.py's TelegramSender
```

**Correction to an assumption in the original investigation brief:** the
brief's expected flow included `baka_brain.py → ai_helper.py → HTTP
request`. This does not match the actual code. `ai_helper.py` is
confirmed dead code — it is not imported by `main.py` or by
`baka_brain.py`, and has no role in any live request path. `main.py`
calls `baka_brain.py` directly, and `baka_brain.py` itself makes the
HTTP call via the `openai` SDK. This is noted here as a factual
correction, not a finding about performance.

**Where time is actually spent:** overwhelmingly in the NVIDIA API call
itself (§8), specifically when it hangs. Every other stage in this
timeline — Telegram update delivery, intent-detection dispatch, the
thread-offload hop, and the final reply send — was measured or reasoned
about and found to add at most low hundreds of milliseconds combined. The
one exception is `/selftest`'s own reply-sending stage, which has its own
separate, fully-explained delay (§7 in the prior investigation turn; see
§9 and §10 here).

---

## 5. Environment Information

Captured directly from the running virtual environment on the machine
where this investigation was performed:

| Component | Value |
|---|---|
| Python | 3.12.13 |
| httpx | 0.25.2 |
| openai (SDK) | 2.41.0 |
| python-telegram-bot | 20.7 |
| OpenSSL | 3.5.7 (9 Jun 2026) |
| Operating System | Ubuntu (WSL on Windows) |
| Virtual environment | `venv/`, project-local |

All of the above match `requirements.txt`'s pinned versions exactly — no
version drift was found between what's installed and what's declared.
**No independent access to the "previous, faster PC" was available**, so
a direct side-by-side comparison could not be performed; see §13 for how
this could be closed out later. However, since the raw benchmark (§8)
shows the *same* machine, *same* network, and *same* account producing a
fast, correct response for one model and a total failure for another,
environment/hardware differences are not a plausible explanation for the
symptom on their own — see §9.

---

## 6. Model Configuration

Read directly from `baka_brain.py` (lines 44–56):

| Role | Constant | Model | Notes |
|---|---|---|---|
| Main brain | `MODEL_MAIN` | `meta/llama-3.3-70b-instruct` | **Currently unresponsive — see §8, §9** |
| Fast/cheap | `MODEL_FAST` | `meta/llama-3.1-8b-instruct` | Confirmed healthy (676ms response) |
| Deep reasoning | `MODEL_THINK` | `meta/llama-3.3-70b-instruct` | Same model as MAIN — shares its problem |
| Vision | `MODEL_VISION` | `meta/llama-3.2-90b-vision-instruct` | Not tested in this investigation |
| Image generation | `MODEL_IMAGE` | `black-forest-labs/flux.1-schnell` | Not tested in this investigation |
| Video generation | `MODEL_VIDEO` | `stabilityai/stable-video-diffusion` | Not tested in this investigation |

**Provider:** NVIDIA NIM, accessed via the `openai` Python SDK in
OpenAI-compatible mode (not OpenAI's own API).
**Endpoint:** `https://integrate.api.nvidia.com/v1` for text/vision
(chat completions); `https://ai.api.nvidia.com/v1/genai/{model}` for
image/video generation (a separate, non-chat REST path, not exercised by
this investigation).

**Feature flags** (also read directly from `baka_brain.py`):
`ENABLE_FAST_ROUTING=False`, `ENABLE_VISION=True`, `ENABLE_IMAGE_GEN=True`,
`ENABLE_VIDEO_GEN=True`.

**Which model is actually in use:** `MODEL_MAIN` (`meta/llama-3.3-70b-instruct`)
handles the large majority of AI-driven interactions — intent detection
for every free-text message, planning, and `/think` — since
`ENABLE_FAST_ROUTING` is off, meaning `MODEL_FAST` is not used as a
pre-filter and sees comparatively little traffic. This is precisely the
model found to be failing.

**Historical context** (from `git log`, not from this investigation's own
measurements): this is not the first time this project has hit this exact
class of problem. `MODEL_MAIN` has already been swapped twice before due
to NVIDIA-side model instability:
1. `z-ai/glm-5.1` — EOL'd by NVIDIA on 2026-07-02 (HTTP 410 Gone)
2. `z-ai/glm-5.2` — its replacement, went DEGRADED (HTTP 400) almost
   immediately
3. `meta/llama-3.3-70b-instruct` — adopted as "PROVEN STABLE" (per the
   code's own comment, citing "22M uses, most popular"), now itself
   found unresponsive by this investigation

---

## 7. HTTP Configuration

Read directly from `baka_brain.py` (lines 58–67, 81–174):

| Setting | Value | Source |
|---|---|---|
| Client-side timeout | 30.0 seconds | `OpenAI(..., timeout=30.0, ...)` |
| SDK's own retry | Disabled (`max_retries=0`) | Deliberate — see note below |
| App-level retry count | 3 attempts | `for attempt in range(3):` in `call_nvidia()` |
| Retry delay | 2 seconds between attempts (not after the last) | `if attempt < 2: time.sleep(2)` |
| Automatic model fallback | MAIN → FAST, conditional | Only fires if the error text matches specific patterns — see §9 |
| Streaming | Not used | `stream` parameter not set (defaults to non-streaming) |
| Connection reuse / keep-alive | Enabled by default | A single module-level `client` object is constructed once at import time and reused for every call, so `httpx`'s underlying connection pooling applies; not independently verified beyond this |

**Why the SDK's own retry is disabled:** an explicit code comment
(`baka_brain.py` line 61) states this was a deliberate fix for a prior
incident: "was blocking the event loop for 9 minutes on NVIDIA 504." The
30-second timeout plus app-controlled 3-attempt retry replaced the SDK's
own exponential-backoff retry specifically to cap worst-case wait time.
This fix is confirmed in `git log` (commit `385ac1e`/`98214d0`, v12.1:
"fix 9-min NIM timeout freeze"). That fix is working as intended — the
current worst case is bounded at roughly 94 seconds (3 × 30s + 2 × 2s),
not 9 minutes — but see §9 for why even that bounded worst case is being
hit unnecessarily.

**Automatic fallback condition**, quoted directly from the code
(`baka_brain.py` lines 123–129):
```python
model_dead = (
    ("410" in last_err)
    or ("DEGRADED" in last_err.upper())
    or ("504" in last_err)
    or ("Gateway Timeout" in last_err)
    or ("timeout" in last_err.lower() and "Read" in last_err)
)
```
This is the exact logic found responsible for the fallback not
triggering in the current situation — see §9.

---

## 8. Benchmark Results

### Network diagnostics (DNS + TCP connect, measured directly, outside any application code)

| Host | Resolved IP | DNS resolution | TCP connect |
|---|---|---|---|
| `integrate.api.nvidia.com` | 75.2.113.119 | 11.5ms | 4.2ms |
| `api.telegram.org` | 149.154.166.110 | 8.3ms | 156.9ms |

Both hosts resolve and connect quickly. Telegram's TCP connect is
noticeably higher than NVIDIA's (157ms vs. 4ms) but is still well within
normal range for a single connection and was not implicated by any
symptom (Telegram delivery was reported as working normally, and this is
consistent with that).

### Raw NVIDIA benchmark — `MODEL_MAIN` (`meta/llama-3.3-70b-instruct`), 5 runs

A temporary script (deleted after use) called NVIDIA's chat completions
endpoint directly, using the exact client configuration from
`baka_brain.py` (`timeout=30.0`, `max_retries=0`), sending the single
prompt `"Hello"` with `max_tokens=20`.

| Run | Connection | Total response time | Result | Error |
|---|---|---|---|---|
| 1 | established (see network diagnostics above) | 30,547 ms | **Failed** | `APITimeoutError: Request timed out.` |
| 2 | established | 30,085 ms | **Failed** | `APITimeoutError: Request timed out.` |
| 3 | established | 30,065 ms | **Failed** | `APITimeoutError: Request timed out.` |
| 4 | established | 30,080 ms | **Failed** | `APITimeoutError: Request timed out.` |
| 5 | established | 30,107 ms | **Failed** | `APITimeoutError: Request timed out.` |

- **Retry behaviour observed:** none — this script made single,
  independent requests per run, deliberately without the app's own retry
  wrapper, specifically to measure raw per-request latency to NVIDIA
  without the retry loop's own logic obscuring the result.
- **Errors:** 5 out of 5 runs failed identically, with the client's own
  timeout ceiling (30s) being the limiting factor in every case — i.e.
  the connection was accepted but no complete response was returned
  within the allotted time.
- **Average:** not computable — 0 of 5 requests succeeded.
- **Median:** not computable — 0 of 5 requests succeeded.
- **Worst:** 30,547 ms (Run 1).
- **Best (of the failures):** 30,065 ms (Run 3) — note that even the
  "best" outcome here is still a total failure; these numbers describe
  how long each failed attempt took to give up, not a range of successful
  latencies.

### Raw NVIDIA benchmark — `MODEL_FAST` (`meta/llama-3.1-8b-instruct`), 1 run

Run immediately afterward, on the same machine, same network, same API
key, same client configuration (with a 15s timeout instead of 30s), to
determine whether the failure was specific to `MODEL_MAIN` or affected
the account/endpoint broadly.

| Run | Total response time | Result | Reply (truncated) |
|---|---|---|---|
| 1 | 676 ms | **Success** | "Hello. How can I assist you to..." |

This single successful, fast result — on infrastructure otherwise
identical to the 5 failed `MODEL_MAIN` runs — is the key piece of
evidence isolating the problem to `MODEL_MAIN` specifically rather than
the network, the API key, or the account.

---

## 9. Root Cause Analysis

### What is NOT causing the issue (ruled out with direct evidence)

- **Local network/DNS/TLS.** DNS resolution and TCP connect to both
  NVIDIA and Telegram are fast (§8). Ruled out.
- **The local environment or installed package versions.** All versions
  match `requirements.txt` exactly (§5); more importantly, the *same*
  environment produced a fast, correct result for `MODEL_FAST` in the
  same test session (§8). If the environment were the cause, that call
  would have been slow or failed too. Ruled out.
- **The NVIDIA API key or account access.** The `MODEL_FAST` call
  succeeded using the identical key. Ruled out.
- **Account-level rate limiting (HTTP 429).** The failures observed were
  clean client-side timeouts (`APITimeoutError`), not rate-limit error
  responses. Ruled out as the primary cause (though not something this
  investigation can fully exclude for *other* times of day or usage
  patterns — see §13).
- **The 30-second timeout being set too low.** It is already a deliberate
  reduction from an unbounded/9-minute prior failure mode (§7), and 30
  seconds is a reasonable ceiling for a chat completion under normal
  conditions — the problem is not the timeout value, it's that the
  request never completes within any reasonable ceiling.
- **The retry count (3 attempts) being excessive.** Three attempts with a
  short delay is a normal, conservative retry policy. The issue is what
  those retries are directed at (see below), not how many there are.
- **Telegram delivery, for the "Hey" symptom specifically.** Consistent
  with the problem statement's own observation that "Telegram API is
  functioning normally" — this investigation's evidence supports that;
  the delay happens entirely before a reply is ever ready to send.
- **The scheduler**, consistent with the problem statement. Not
  implicated by any evidence gathered here.

### What IS causing the issue (direct evidence, not inference)

1. **`MODEL_MAIN` (`meta/llama-3.3-70b-instruct`) is currently
   unresponsive on NVIDIA's hosted infrastructure.** Fact, not
   assumption: 5 out of 5 direct, isolated requests to this exact model
   timed out at the 30-second ceiling with no response at all, while an
   otherwise-identical request to a different model succeeded in 676ms
   (§8).
2. **The bot's own retry loop (`call_nvidia()`, 3 attempts × up to 30s
   each, 2s between) multiplies this single-request failure into a much
   longer user-facing delay.** Worst case is bounded at roughly 94
   seconds; the reported "around one minute" is consistent with 1–2 of
   the 3 attempts timing out before one either succeeds (if NVIDIA
   recovers momentarily) or the loop gives up.
3. **The automatic MAIN→FAST fallback, built specifically to survive this
   exact scenario (and already proven necessary twice before, per `git
   log`), does not trigger for this specific failure.** Fact, from
   reading the fallback condition directly against the exact exception
   this investigation reproduced: the fallback checks for the substrings
   `"410"`, `"DEGRADED"`, `"504"`, `"Gateway Timeout"`, or (`"timeout"`
   **and** `"Read"`) in the error text. The actual exception raised by a
   client-side timeout is `APITimeoutError: "Request timed out."` — this
   string does not contain `"timeout"` as a contiguous substring (it
   contains "timed out", not "timeout"), and does not contain "Read" at
   all. **None of the fallback's conditions match**, so the bot silently
   keeps retrying the broken model instead of switching to the healthy
   one it already has configured and proven working.

Separately, and independently of the above:

4. **`/selftest`'s slowdown is a distinct, fully-explained side effect of
   a recent, working-as-intended change**, not a bug or a symptom of the
   same root cause. `selftest_cmd()` (`main.py`) sends 18 sequential
   messages to the same chat (1 intro + 16 section messages + 1 footer).
   `notification_service.py`'s `TelegramSender`, added in a recent sprint
   to prevent Telegram flood-control violations during reminder bursts,
   defaults to pacing same-chat messages at roughly one per second. 18
   messages at that pace adds on the order of 17–20 seconds versus the
   essentially-unpaced behavior that existed before that rate limiter was
   introduced. This is a real, measurable, and fully understood
   consequence of applying a general-purpose flood-protection default to
   a specific command that intentionally wants to burst many messages to
   one chat quickly — not a defect in the rate limiter itself, which is
   working exactly as designed for its original purpose (reminder
   delivery).

### Facts vs. assumptions, stated explicitly

**Facts** (directly measured or read from code during this
investigation): the 5/5 `MODEL_MAIN` timeout results; the single fast
`MODEL_FAST` result; the exact retry/timeout/fallback logic in
`baka_brain.py`; the exact message count and rate-limiter defaults behind
`/selftest`'s slowdown; the network diagnostic timings; the installed
environment versions.

**Assumptions / inferences** (reasonable, but not independently proven):
that the "previous PC" ran faster because it was used during a period
when whichever model was active then was healthy on NVIDIA's side, rather
than because of any hardware or environment difference — this is
consistent with all evidence gathered (a healthy model is fast on *this*
machine too) but was not verified against the previous machine directly,
since it was not available for comparison. Also assumed: that this is a
recurrence of the same *category* of problem the project has hit twice
before (per `git log`), rather than a coincidentally different kind of
NVIDIA-side issue — the pattern is suggestive but this investigation did
not have access to NVIDIA's own status/incident information to confirm
it.

---

## 10. Ranked Findings

| Rank | Finding | Evidence | Confidence |
|---|---|---|---|
| 1 | `MODEL_MAIN` (`meta/llama-3.3-70b-instruct`) is unresponsive on NVIDIA NIM | 5/5 direct, isolated timeouts at 30s ceiling; §8 | High |
| 2 | The MAIN→FAST fallback does not trigger for plain client-side timeouts, only for 410/DEGRADED/504/Gateway-Timeout/"timeout"+"Read" text matches | Exact fallback condition read from `baka_brain.py` lines 123–129, compared directly against the exact exception text reproduced in §8 | High |
| 3 | `/selftest`'s slowdown is caused by the Sprint 2A rate limiter pacing its 18 sequential same-chat messages at ~1/sec | `selftest_cmd()`'s message count read directly from `main.py`; `TelegramSender`'s default `per_chat_max_rate=1` read directly from `notification_service.py` | High |
| 4 | The 3-attempt, 30s-per-attempt retry loop multiplies a single hung request into up to ~94 seconds of user-facing delay | `call_nvidia()`'s attempt loop read directly from `baka_brain.py`; consistent with the reported "~1 minute" symptom | High |
| 5 | This is very likely a recurrence of a pattern this project has hit twice before (model instability requiring a `MODEL_MAIN` swap) | `git log` shows two prior swaps (GLM 5.1 → GLM 5.2 → Llama 3.3 70B) for the identical stated reason | Medium-high (pattern strongly suggestive; not confirmed against NVIDIA's own incident data) |
| 6 | Local network path (DNS/TCP/TLS) is not a contributing factor | Direct timing measurements to both NVIDIA and Telegram hosts; §8 | High |
| 7 | Local environment / package versions are not a contributing factor | Installed versions match `requirements.txt` exactly; the same environment produced a fast, correct `MODEL_FAST` result in the same session | High |
| 8 | NVIDIA account-level rate limiting (429s) is not what's happening | Failures were clean timeouts, not rate-limit responses | High |
| 9 | `MODEL_VISION`/`MODEL_IMAGE`/`MODEL_VIDEO` health is unknown | Not tested — outside the reported symptom's scope | Untested (no claim made) |
| 10 | The 2-second inter-attempt sleep is a minor contributor to total delay | 4 seconds total across 3 attempts, versus up to 90 seconds of timeout waiting | High (but low impact) |

---

## 11. Recommended Fixes

**None of the following were implemented. All are recommendations only.**

### Recommendation A — Widen the "model dead" fallback detection to recognize client-side timeouts

- **Description:** Update the fallback condition in `call_nvidia()` to
  also treat `APITimeoutError` (or its message text, matched more
  robustly than the current substring approach — e.g. matching on
  exception type rather than string content) as a "model dead" signal,
  so the existing MAIN→FAST fallback actually fires for this failure
  mode the way it already does for 410/DEGRADED/504 errors.
- **Expected performance gain:** for any message that hits a hung
  `MODEL_MAIN`, roughly **90 seconds down to 1–2 seconds** (the measured
  `MODEL_FAST` response time), since the bot would switch to the known-
  healthy model instead of exhausting all 3 retries against the broken
  one.
- **Risk:** Low. This extends an existing, already-proven pattern (the
  same fallback mechanism has been relied on twice before) to one more
  failure type; it does not change any other behavior.
- **Priority:** High — directly addresses the reported "Hey takes ~1
  minute" symptom and is a narrow, well-understood change.

### Recommendation B — Resolve the underlying NVIDIA-side model availability issue

- **Description:** Investigate `meta/llama-3.3-70b-instruct`'s current
  status on NVIDIA NIM directly (status page, support channel, or simply
  re-testing over time), and consider swapping `MODEL_MAIN` again if the
  issue persists — following the same pattern already used twice before
  in this project's history.
- **Expected performance gain:** full resolution — normal latency
  restored entirely (likely low-single-digit seconds per message, based
  on this model's own prior "PROVEN STABLE" characterization and the
  FAST model's measured performance).
- **Risk:** Low to moderate, depending on which model is chosen as a
  replacement — a new model swap carries the same class of "how stable is
  this NIM-hosted model really" uncertainty this project has already
  encountered twice.
- **Priority:** High — this is the actual root cause; Recommendation A
  mitigates its symptom but doesn't fix it.

### Recommendation C — Give `/selftest` its own, faster rate-limit treatment

- **Description:** Either configure a higher rate for `/selftest`'s
  messages specifically (the `BaseRateLimiter` interface `TelegramSender`
  is built on already supports per-call `rate_limit_args` for exactly
  this kind of override), or reduce the number of separate messages
  `/selftest` sends (e.g. batching multiple sections into fewer
  messages).
- **Expected performance gain:** recovers most or all of the ~17–20
  seconds added by pacing, for this one command specifically.
- **Risk:** Low. This is a narrow, command-specific adjustment that
  doesn't touch the rate limiter's general-purpose behavior (which is
  working as intended for its original reminder-burst use case).
- **Priority:** Medium — a real, confirmed usability regression, but
  lower urgency than the AI-response-time issue since it affects one
  diagnostic command rather than ordinary conversation.

### Recommendation D — Surface a "still thinking" message during long AI waits

- **Description:** After the first failed attempt (or after some shorter
  threshold, e.g. 5–10 seconds), send an interim message like "Still
  working on that, hang on..." rather than leaving the user with silence
  for up to 90 seconds.
- **Expected performance gain:** none directly (doesn't reduce actual
  latency), but meaningfully improves perceived responsiveness and
  reduces the chance a user assumes the bot is broken and gives up.
- **Risk:** Low. Purely additive UX change.
- **Priority:** Low — a nice-to-have that doesn't address the underlying
  cause, worth considering alongside Recommendation A rather than instead
  of it.

---

## 12. Things NOT Changed

Explicitly confirmed for the record:

- **No code modified.** No production file (`.py`) was edited as part of
  this investigation or this report.
- **No commits.** No `git commit` was run; no changes were staged.
- **No documentation updated.** No existing `.md` file was modified. This
  file (`AI_DIAGNOSTIC_REPORT.md`) is a new file, created fresh, per
  explicit instruction.
- **No configuration changed.** `.env`, `requirements.txt`,
  `pytest.ini`, and every other configuration file are untouched.
- The one temporary script written to perform the raw NVIDIA benchmark
  (§8) was deleted immediately after producing its output and was never
  part of the working tree at commit time.

---

## 13. Future Investigation

Things that remain unknown after this investigation, and how they could
be resolved later:

- **Whether `meta/llama-3.3-70b-instruct`'s unresponsiveness is a
  transient blip or an ongoing outage.** This investigation captured a
  single point-in-time snapshot (5 consecutive failures within a short
  window). Re-running the same raw benchmark at a later time, or several
  times across a day, would show whether this is intermittent or
  sustained. NVIDIA's own status page or support channel, if available,
  would be a more authoritative source than repeated client-side probing.
- **Whether `MODEL_VISION`, `MODEL_IMAGE`, and `MODEL_VIDEO` share the
  same problem.** Not tested in this investigation, since the reported
  symptoms were specific to chat messages and `/selftest`. A similar raw,
  direct benchmark against each could confirm or rule this out.
- **Direct comparison against the "previous, faster PC."** Not possible
  in this investigation since that machine was not available. If it's
  still accessible, running the same raw NVIDIA benchmark script (or an
  equivalent) there, at the same time as on this machine, would give a
  true side-by-side comparison and either confirm or rule out any
  remaining environment-specific explanation.
- **Whether account-level rate limiting plays any role at other times.**
  This investigation's failures were clean timeouts, not 429 responses,
  ruling out rate-limiting as the cause of *this* specific batch of
  failures — but the account's free-tier limits (per the project's own
  README: 1,000 calls/month, 40 requests/minute) were not specifically
  audited for current usage levels, and heavy testing (including the
  automated test suite work and prior sprints' live-bot usage) could be
  worth checking against NVIDIA's usage dashboard if the problem persists
  after Recommendation A/B are addressed.
- **Whether the fallback-detection gap (Finding #2) has caused silent
  degraded performance in other, less obvious situations** — the same
  string-matching approach is used for detecting a "dead" model
  elsewhere in `baka_brain.py`'s call paths (e.g. `_call_model()`'s own
  fallback logic, not directly exercised by this investigation) and could
  have the same blind spot; worth a follow-up read-through if
  Recommendation A is implemented.

---

## 14. Appendix

### Raw benchmark output — `MODEL_MAIN`

```
httpx version: 0.25.2
OpenSSL: OpenSSL 3.5.7 9 Jun 2026
Model under test: meta/llama-3.3-70b-instruct

Run 1: FAILED after 30547ms -- APITimeoutError: Request timed out.
Run 2: FAILED after 30085ms -- APITimeoutError: Request timed out.
Run 3: FAILED after 30065ms -- APITimeoutError: Request timed out.
Run 4: FAILED after 30080ms -- APITimeoutError: Request timed out.
Run 5: FAILED after 30107ms -- APITimeoutError: Request timed out.

All 5 attempts failed.
```

### Raw benchmark output — `MODEL_FAST`

```
meta/llama-3.1-8b-instruct OK 676 ms -> Hello. How can I assist you to
```

### Network diagnostic output

```
integrate.api.nvidia.com -> 75.2.113.119  DNS=11.5ms  TCP_connect=4.2ms
api.telegram.org -> 149.154.166.110  DNS=8.3ms  TCP_connect=156.9ms
```

### Relevant code locations

| Location | What's there |
|---|---|
| `baka_brain.py:44-56` | Model constants (`MODEL_MAIN`, `MODEL_FAST`, etc.) and feature flags |
| `baka_brain.py:58-67` | OpenAI client construction: `base_url`, `timeout=30.0`, `max_retries=0` |
| `baka_brain.py:81-174` | `call_nvidia()` — the 3-attempt retry loop, 2s inter-attempt sleep, and the MAIN→FAST fallback logic |
| `baka_brain.py:123-129` | The exact "model dead" detection condition found not to match plain client-side timeouts |
| `baka_brain.py:176` onward | `get_baka_response()` — the intent-detection entry point called for every free-text message |
| `main.py` (`handle_message`) | Routes a plain-text message to `get_baka_response()` via `run_blocking()` (`async_bridge.py`) when no slashless command or view-shortcut matches |
| `main.py:1722-1792` | `selftest_cmd()` — sends 18 sequential messages (1 intro + 16 sections + 1 footer) to the same chat |
| `notification_service.py` | `TelegramSender` — default `per_chat_max_rate=1, per_chat_time_period=1.0`, the rate limiter responsible for `/selftest`'s added pacing delay |

### Configuration values referenced

| Setting | Value |
|---|---|
| `MODEL_MAIN` | `meta/llama-3.3-70b-instruct` |
| `MODEL_FAST` | `meta/llama-3.1-8b-instruct` |
| Client timeout | 30.0 seconds |
| SDK retries | 0 (disabled) |
| App-level retry attempts | 3 |
| Inter-attempt sleep | 2 seconds |
| `TelegramSender` overall rate | 28 messages/second (default) |
| `TelegramSender` per-chat rate | 1 message/second (default) |
