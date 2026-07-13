"""
baka_brain.py — BAKA AI brain
Handles intent detection with memory, multiple tasks, and better Hindi/Hinglish support.
"""
import json
import os
import logging
import time
from openai import OpenAI, APITimeoutError
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Bulletproof .env loading — works regardless of working directory or import order
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(_env_path)
_api_key = os.getenv("NVIDIA_API_KEY")
if not _api_key:
    # Fallback: read .env manually if dotenv failed
    try:
        with open(_env_path) as _f:
            for _line in _f:
                if _line.startswith("NVIDIA_API_KEY="):
                    _api_key = _line.strip().split("=", 1)[1]
    except FileNotFoundError:
        pass

logger = logging.getLogger(__name__)

# v11.0: Multi-model AI infrastructure
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"

# ─────────────────────────────────────────────────────────────
# NVIDIA NIM MODELS — verified working as of July 2026
# ─────────────────────────────────────────────────────────────
# TEXT / VISION: use https://integrate.api.nvidia.com/v1/chat/completions
# IMAGE / VIDEO: use https://ai.api.nvidia.com/v1/genai/{model}
#
# History of MODEL_MAIN choices:
#   z-ai/glm-5.1  — EOL'd by NVIDIA on 2026-07-02 (HTTP 410 Gone)
#   z-ai/glm-5.2  — released same day, currently DEGRADED (HTTP 400)
#   meta/llama-3.3-70b-instruct  — 22M uses, most popular, PROVEN STABLE ← in use
# ─────────────────────────────────────────────────────────────

# Primary models
MODEL_MAIN   = "meta/llama-3.3-70b-instruct"         # Main brain — 22M uses, most stable
MODEL_FAST   = "meta/llama-3.1-8b-instruct"          # Fast/cheap intent + classification
MODEL_THINK  = "meta/llama-3.3-70b-instruct"         # Deep reasoning (same architecture family)
MODEL_VISION = "meta/llama-3.2-90b-vision-instruct"  # Image understanding (chat/completions endpoint)
MODEL_IMAGE  = "black-forest-labs/flux.1-schnell"    # Image generation (genai endpoint, NOT chat)
MODEL_VIDEO  = "stabilityai/stable-video-diffusion"  # Video generation (genai endpoint, NOT chat)

# Feature toggles — v11.2: image/video/vision ALWAYS ON per user request
ENABLE_FAST_ROUTING = False  # Use Llama 8B for simple intent classification
ENABLE_VISION       = True   # Photo understanding (Llama 3.2 Vision)
ENABLE_IMAGE_GEN    = True   # FLUX.1-schnell via NVIDIA NIM (always on)
ENABLE_VIDEO_GEN    = True   # Stable Video Diffusion via NVIDIA NIM (always on)

# v13.3.2: per-workload timeout profiles (hotfix following v13.3.1's
# fallback-detection fix). AI_DIAGNOSTIC_REPORT.md found a single flat 30s
# timeout applied to every chat-completion call regardless of workload,
# meaning ordinary "Hey"-style chat waited exactly as long as a deep
# reasoning call before failing over. These are passed as a PER-CALL
# `timeout=` override to individual .create() calls; the client's own
# timeout=30.0 below is unchanged and still applies to anything that
# doesn't pass an explicit override (kept as the safety ceiling).
# Image/video generation are untouched by this: they use their own,
# separate httpx.Client instances (120s / 300s respectively, see
# generate_image()/generate_video()), never the shared `client` object
# below, so they were never affected by the chat timeout to begin with.
TIMEOUT_FAST_CHAT       = 8.0   # ordinary chat / intent detection (get_baka_response) —
                                 # the dominant, most latency-sensitive, highest-frequency path
TIMEOUT_NORMAL_REASONING = 15.0  # plan/breakdown/suggestion generation — longer structured
                                 # output, called less often and more tolerant of extra time
TIMEOUT_LONG_REASONING  = 25.0  # /think — deliberately the most tolerant of the chat-completion
                                 # tiers; still under the original 30s ceiling
TIMEOUT_VISION          = 30.0  # unchanged from the original client default — no evidence
                                 # vision has the same problem, so left exactly as it was

client = OpenAI(
    base_url=NIM_BASE_URL,
    api_key=_api_key or "missing-key-check-env-file",
    # v12.1: bug fix — was blocking the event loop for 9 minutes on NVIDIA 504.
    # 30s timeout is generous for chat completions but stops the SDK from silently
    # retrying with exponential backoff. Our own retry loop (3 attempts, 2s sleep)
    # controls behavior instead. v13.3.2: this remains the default/ceiling for any
    # call that doesn't pass its own `timeout=` override — see TIMEOUT_* above.
    timeout=30.0,
    max_retries=0,
)

def clean_json(content: str) -> str:
    content = content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()
    start = content.find("{")
    end = content.rfind("}") + 1
    if start >= 0 and end > start:
        content = content[start:end]
    return content

def _is_model_dead(exc: Exception, err_str: str) -> bool:
    """True if this failure means MODEL_MAIN itself is unavailable (gone,
    degraded, or hung) and further retries against it are pointless —
    warrants an immediate fallback to MODEL_FAST rather than continuing
    to retry the same broken model.

    v13.3.1 hotfix: prefers matching the exception TYPE (robust) over
    string content (fragile) wherever the SDK gives us a real type to
    check. A plain client-side timeout raises openai.APITimeoutError with
    the message "Request timed out." — that string contains neither
    "timeout" as a contiguous substring (it's "timed out") nor "Read", so
    the original string-only check never matched it, and a hung
    MODEL_MAIN was retried 3 times against itself instead of falling back
    to the already-healthy MODEL_FAST. See AI_DIAGNOSTIC_REPORT.md.
    The 410/DEGRADED/504/Gateway-Timeout string checks are unchanged and
    kept as-is — they were not implicated by the investigation.
    """
    if isinstance(exc, APITimeoutError):
        return True
    err_upper = err_str.upper()
    return (
        ("410" in err_str)
        or ("DEGRADED" in err_upper)
        or ("504" in err_str)
        or ("GATEWAY TIMEOUT" in err_upper)
    )


def call_nvidia(messages: list, temperature=0.1, max_tokens=1024, top_p=1,
                request_type="INTENT_DETECTION", user_id=None,
                timeout: float = TIMEOUT_FAST_CHAT) -> str:
    """Legacy call function — defaults to MODEL_MAIN. v11.1: now logs to analytics.

    v13.3.1: retries MODEL_MAIN per the configured policy (3 attempts,
    2s between), stopping early the moment a failure is identified as
    "model dead" (no point retrying a model that just timed out or
    returned 410/DEGRADED/504 against itself). Falls back to MODEL_FAST
    exactly once, immediately after that retry policy concludes —
    whether it concluded by exhausting all 3 attempts or by stopping
    early. Previously, fallback was attempted from inside every failed
    attempt, meaning FAST could be tried multiple times, and a failed
    fallback attempt would still fall through into retrying the
    already-known-dead MAIN model again.

    v13.3.2: `timeout` defaults to TIMEOUT_FAST_CHAT since this function's
    dominant caller is get_baka_response() — intent detection on every
    plain chat message, the most latency-sensitive path in the bot.
    Callers generating longer structured output (plans, breakdowns,
    analysis) pass a longer explicit override; see call sites.
    """
    import time as _time
    start = _time.time()
    last_err = None
    last_exc = None
    fallback_worthy = False
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL_MAIN,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                timeout=timeout,
            )
            ms = round((_time.time() - start) * 1000)
            text = response.choices[0].message.content.strip()
            # v11.1: log to analytics
            try:
                from analytics import log_ai_request
                usage = getattr(response, "usage", None)
                log_ai_request(
                    model_name=MODEL_MAIN,
                    latency_ms=ms,
                    status="success",
                    user_id=user_id,
                    request_type=request_type,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
                    response_text=text,
                    fallback_used=(attempt > 0),
                )
            except Exception:
                pass
            return text
        except Exception as e:
            last_err = str(e)
            last_exc = e
            logger.error(f"API attempt {attempt+1} failed: {e}")
            fallback_worthy = _is_model_dead(e, last_err)
            if fallback_worthy:
                break  # MAIN is confirmed dead/hung -- stop retrying it
            if attempt < 2:
                time.sleep(2)

    # Retry policy above has concluded (exhausted, or stopped early on a
    # fallback-worthy failure). Attempt MODEL_FAST exactly once,
    # immediately, if warranted -- never for an error that isn't
    # recognized as "model dead" (e.g. a bad-request/auth error would
    # likely fail on FAST too, so falling back would be pointless).
    if fallback_worthy and MODEL_MAIN != MODEL_FAST:
        logger.warning(f"MAIN model {MODEL_MAIN} is unavailable ({last_err[:80]}). "
                       f"Falling back to {MODEL_FAST}.")
        try:
            fb = client.chat.completions.create(
                model=MODEL_FAST,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                timeout=timeout,
            )
            text = fb.choices[0].message.content.strip()
            try:
                from analytics import log_ai_request
                usage = getattr(fb, "usage", None)
                log_ai_request(
                    model_name=MODEL_FAST, latency_ms=round((_time.time()-start)*1000),
                    status="success", user_id=user_id, request_type=request_type,
                    prompt_tokens=getattr(usage,"prompt_tokens",0) if usage else 0,
                    completion_tokens=getattr(usage,"completion_tokens",0) if usage else 0,
                    response_text=text, fallback_used=True,
                    error_message=f"MAIN unavailable: fell back to {MODEL_FAST}",
                )
            except Exception:
                pass
            return text
        except Exception as fb_err:
            logger.error(f"FAST fallback also failed: {fb_err}")

    # No successful result from MAIN or (if attempted) FAST. Log and
    # raise the ORIGINAL MAIN failure — not suppressed, not replaced by
    # the fallback's own error, matching the pre-existing contract that
    # callers see the real underlying failure.
    try:
        from analytics import log_ai_request
        log_ai_request(
            model_name=MODEL_MAIN,
            latency_ms=round((_time.time() - start) * 1000),
            status="error",
            user_id=user_id,
            request_type=request_type,
            error_message=last_err[:300] if last_err else "unknown",
        )
    except Exception:
        pass
    raise last_exc

def get_baka_response(user_input: str, existing_tasks: list,
                        history: list = None, memories: list = None,
                        user_context: dict = None, user_id: int = None) -> dict:
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)
    next_week = today + timedelta(days=7)

    # v11.0: rich context — let the AI reason WITH the user's actual data
    profile_ctx = ""
    if user_context:
        parts = []
        if user_context.get("recent_completions"):
            parts.append("Recent completions: " + ", ".join(
                f"{t[0]} ({t[1]})" for t in user_context["recent_completions"][:3]))
        if user_context.get("open_tasks_by_category"):
            cats = user_context["open_tasks_by_category"]
            parts.append("Open tasks by category: " + ", ".join(
                f"{k}: {v}" for k, v in cats.items() if k))
        if user_context.get("overdue_count"):
            parts.append(f"Overdue tasks: {user_context['overdue_count']}")
        if user_context.get("active_habits"):
            parts.append("Active habits: " + ", ".join(
                f"{h[0]} (streak {h[1]})" for h in user_context["active_habits"][:3]))
        if parts:
            profile_ctx = "USER PROFILE (use this to give personalized responses):\n" + "\n".join(parts) + "\n\n"

    task_ctx = ""
    if existing_tasks:
        task_ctx = "User's current tasks:\n"
        for t in existing_tasks[:8]:
            task_ctx += f"  [{t[0]}] {t[1]} | {t[2] or 'no date'} | {t[3] or 'no time'}\n"

    memory_ctx = ""
    if memories:
        memory_ctx = "User's stored memories:\n"
        for key, val in memories[:5]:
            memory_ctx += f"  {key}: {val}\n"

    hist_ctx = ""
    if history:
        for h in history[-4:]:
            hist_ctx += f"{h['role'].upper()}: {h['content']}\n"

    system = f"""You are BAKA, an intelligent Telegram AI assistant.

DATE CONTEXT:
Today={today.strftime('%A %d %B %Y')} ({today.strftime('%Y-%m-%d')})
Tomorrow={tomorrow.strftime('%A')} ({tomorrow.strftime('%Y-%m-%d')})
DayAfterTomorrow={day_after.strftime('%Y-%m-%d')}
NextWeek={next_week.strftime('%Y-%m-%d')}

{task_ctx}
{memory_ctx}
{profile_ctx}Recent chat: {hist_ctx}

LANGUAGE SUPPORT — You understand:
- English: "remind me to call mom tomorrow at 5pm"
- Hindi: "Kal subah 8 baje gym yaad dila dena"
- Hinglish: "Bhai next Friday assignment submit karna hai"
- "Aaj"=today, "Kal"=tomorrow, "Parso"=day after tomorrow
- "Subah"=morning(AM), "Raat"=night(PM), "Shaam"=evening(PM), "Dopahar"=afternoon(PM)
- "Baje"=o'clock, "Har roz"=every day, "Har hafte"=every week

INTENT TYPES:
TASK — New task/reminder to create (one-time, has or will get a specific date)
HABIT — Recurring activity the user wants to build ("every day", "har roz", "every Monday", "daily", "weekly", "har Sunday", "on the 1st of every month"). ANY phrase with "every", "har", "daily", "weekly", "monthly" is a HABIT, NOT a goal.
EDIT — Modify existing task (by name or id)
DELETE — Remove task
VIEW — Show tasks (today/tomorrow/week/all)
MEMORY_SAVE — User wants to store a personal FACT about themselves ("remember that my exam is...", "mera naam..."). NOT for tasks with dates.
MEMORY_GET — User wants to retrieve stored info ("when are my exams?")
GOAL — A long-term aspiration with NO recurrence and NO specific date ("I want to learn guitar", "get fit"). If it has "every/har/daily" it is a HABIT, not a GOAL.
PLAN — Planning request ("plan my week", "help me prepare")
ADVICE — Seeking tips/motivation
CHAT — General conversation
MULTIPLE — Multiple tasks in one message (detected separately)

CRITICAL RULES:
1. NEVER use raw user message as task title
2. Extract ACTUAL task intelligently
3. "Schedule task" → ask WHAT task (title=null)
4. Always confirm before saving (needs_confirm=true)
5. For MEMORY_SAVE: extract key and value
6. For multiple tasks: set intent=MULTIPLE and list tasks array
7. For invalid time (25 PM, 13 AM, 25:99) or past date (yesterday): set "time"/"date" to null and add a message to "errors"
8. RECURRENCE = HABIT: "every day"/"har roz"/"daily" → HABIT daily. "every Monday"/"har Monday" → HABIT weekly. "1st of every month" → HABIT monthly. NEVER classify these as GOAL.
9. A message with a specific future date AND an action verb (submit, finish, call, meeting) is a TASK, never MEMORY_SAVE. "Remind me on 25 December" = TASK. "Submit on 2026-12-25" = TASK.
10. "evening"/"shaam" = 18:00, "morning"/"subah" = 08:00, "tonight" = 21:00, "afternoon"/"dopahar" = 14:00, "noon" = 12:00, "lunch" = 13:00. Use these EXACT times, do not guess other values.

TITLE EXTRACTION:
"Remind me to call mom" → "Call mom"
"Kal gym yaad dila dena" → "Gym"  
"Physics assignment submit karna hai" → "Physics assignment"
"Study physics today at 8pm" → "Study Physics"

Respond ONLY with valid JSON:
{{
  "intent": "TASK|HABIT|EDIT|DELETE|VIEW|MEMORY_SAVE|MEMORY_GET|GOAL|PLAN|ADVICE|CHAT|MULTIPLE",
  "view_period": "today|tomorrow|week|year|all|null",
  "task_id": null,
  "entities": {{
    "title": "extracted task name or null",
    "date": "YYYY-MM-DD or null",
    "time": "HH:MM or null",
    "category": "Study|Health|Work|Personal|Other|null",
    "priority": "high|medium|low|null",
    "recurrence": "daily|weekly|monthly|null",
    "recurrence_day": "weekday name or day number or null",
    "is_deadline": "true if the task has deadline phrasing (due, submit by, deadline, before, tak), false otherwise"
  }},
  "memory_key": "key to store/retrieve or null",
  "memory_value": "value to store or null",
  "tasks": [],
  "confidence": 0.9,
  "missing": [],
  "errors": [],
  "response": "natural conversational reply",
  "confirm_summary": "formatted summary or null",
  "needs_confirm": false
}}

For MULTIPLE intent, populate tasks array:
"tasks": [
  {{"title": "Buy groceries", "date": "2026-06-16", "time": null, "category": "Personal"}},
  {{"title": "Call mom", "date": "2026-06-16", "time": null, "category": "Personal"}}
]"""

    try:
        content = call_nvidia([
            {"role": "system", "content": system},
            {"role": "user", "content": user_input}
        ], temperature=0.1, request_type="INTENT_DETECTION", user_id=user_id)

        cleaned = clean_json(content)
        result = json.loads(cleaned)

        # Safety: reject raw message as title
        title = result.get("entities", {}).get("title", "")
        if title and (len(title) > 80 or title.lower().strip() == user_input.lower().strip()):
            result["entities"]["title"] = None
            result.setdefault("missing", []).insert(0, "title")
            result["needs_confirm"] = False
            result["response"] = "What would you like to call this task?"

        return result

    except json.JSONDecodeError:
        logger.error(f"JSON parse failed. Output: {content[:200]}")
        lower = user_input.lower()
        if any(w in lower for w in ["show", "list", "what", "today", "tomorrow", "week", "dikhao"]):
            return {"intent": "VIEW", "view_period": "today", "entities": {},
                    "missing": [], "errors": [], "response": "Here are your tasks:",
                    "needs_confirm": False, "tasks": []}
        elif any(w in lower for w in ["remember", "yaad rakh", "store", "save this"]):
            return {"intent": "MEMORY_SAVE", "entities": {}, "missing": [],
                    "errors": [], "response": "What would you like me to remember?",
                    "needs_confirm": False, "tasks": []}
        else:
            return {"intent": "CHAT", "entities": {}, "confidence": 0.5,
                    "missing": [], "errors": [],
                    "response": "Could you rephrase that? I want to make sure I understand correctly.",
                    "needs_confirm": False, "tasks": []}
    except Exception as e:
        logger.error(f"BAKA error: {e}")
        return {"intent": "CHAT", "entities": {}, "confidence": 0.0,
                "missing": [], "errors": [],
                "response": f"Something went wrong. Please try again.",
                "needs_confirm": False, "tasks": [], "confirm_summary": None}


def check_api_status() -> dict:
    # v13.3.2: a status/liveness probe (/status) should give a quick,
    # decisive answer rather than waiting the full chat-completion budget.
    start = time.time()
    try:
        response = client.chat.completions.create(
            model=MODEL_MAIN,
            messages=[{"role": "user", "content": "Reply with only: ONLINE"}],
            max_tokens=10, temperature=0,
            timeout=TIMEOUT_FAST_CHAT,
        )
        elapsed = round((time.time() - start) * 1000)
        usage = response.usage
        return {
            "status": "online",
            "model": response.model,
            "response_time_ms": elapsed,
            "reply": response.choices[0].message.content.strip(),
            "prompt_tokens": usage.prompt_tokens if usage else "N/A",
            "completion_tokens": usage.completion_tokens if usage else "N/A",
            "total_tokens": usage.total_tokens if usage else "N/A",
            "finish_reason": response.choices[0].finish_reason
        }
    except Exception as e:
        elapsed = round((time.time() - start) * 1000)
        err = str(e)
        if "429" in err:
            status = "rate_limited"
        elif "401" in err or "403" in err:
            status = "invalid_key"
        elif "503" in err or "502" in err:
            status = "server_down"
        elif "timeout" in err.lower():
            status = "timeout"
        else:
            status = "error"
        return {"status": status, "error": err, "response_time_ms": elapsed}



def benchmark_ai(quick=True) -> dict:
    """
    Run a multi-test benchmark on the current AI model.
    Tests: latency, intent accuracy, JSON compliance, language understanding, reasoning.
    quick=True runs 3 tests; quick=False runs all 6.
    Returns detailed results dict.
    """
    import time as _time
    results = {
        "model": MODEL_MAIN,
        "tests": [],
        "passed": 0,
        "total": 0,
        "avg_latency_ms": 0,
    }
    latencies = []

    def _run_test(name, prompt, check_fn, max_tokens=100):
        """Run a single test, return (passed, latency_ms, raw_output)."""
        start = _time.time()
        try:
            raw = call_nvidia([{"role": "user", "content": prompt}],
                              temperature=0, max_tokens=max_tokens)
            ms = round((_time.time() - start) * 1000)
            passed = check_fn(raw)
            return {"name": name, "passed": passed, "latency_ms": ms,
                    "output": raw[:150], "error": None}
        except Exception as e:
            ms = round((_time.time() - start) * 1000)
            return {"name": name, "passed": False, "latency_ms": ms,
                    "output": None, "error": str(e)[:100]}

    # Test 1: Basic connectivity + latency
    results["tests"].append(_run_test(
        "Connectivity",
        "Reply with exactly one word: ONLINE",
        lambda r: "online" in r.lower()
    ))

    # Test 2: JSON compliance (critical for BAKA's intent system)
    results["tests"].append(_run_test(
        "JSON compliance",
        'Reply ONLY with valid JSON: {"status": "ok", "number": 42}',
        lambda r: '"status"' in r and '"ok"' in r,
        max_tokens=50
    ))

    # Test 3: Intent classification accuracy
    results["tests"].append(_run_test(
        "Intent detection",
        'Classify this message intent as exactly one of TASK/CHAT/VIEW/MEMORY_SAVE. '
        'Message: "Remind me to call mom tomorrow at 5pm". Reply with ONLY the intent word.',
        lambda r: "TASK" in r.upper()
    ))

    if not quick:
        # Test 4: Hindi/Hinglish understanding
        results["tests"].append(_run_test(
            "Hindi understanding",
            'What does "Kal subah 8 baje gym yaad dila dena" mean in English? '
            'Reply in one sentence.',
            lambda r: any(w in r.lower() for w in ["remind", "gym", "morning", "tomorrow"]),
            max_tokens=100
        ))

        # Test 5: Reasoning / task extraction
        results["tests"].append(_run_test(
            "Task extraction",
            'Extract the task title from: "Bhai next Friday assignment submit karna hai". '
            'Reply with ONLY the title, nothing else.',
            lambda r: "assignment" in r.lower(),
            max_tokens=50
        ))

        # Test 6: Multi-step instruction following
        results["tests"].append(_run_test(
            "Instruction following",
            'I will give you a task. Extract: 1) title 2) date 3) time. '
            'Task: "Meeting with boss tomorrow at 3pm". '
            'Reply as JSON: {"title":"...","date":"tomorrow","time":"15:00"}',
            lambda r: '"title"' in r and ("15:00" in r or "3" in r),
            max_tokens=100
        ))

    # Compute summary
    results["total"] = len(results["tests"])
    results["passed"] = sum(1 for t in results["tests"] if t["passed"])
    latencies = [t["latency_ms"] for t in results["tests"] if t["latency_ms"]]
    results["avg_latency_ms"] = round(sum(latencies) / len(latencies)) if latencies else 0
    results["score"] = f"{results['passed']}/{results['total']}"

    # Performance grade
    pct = (results["passed"] / results["total"] * 100) if results["total"] else 0
    avg = results["avg_latency_ms"]
    if pct >= 100 and avg < 2000:
        results["grade"] = "A+"
    elif pct >= 80 and avg < 3000:
        results["grade"] = "A"
    elif pct >= 60:
        results["grade"] = "B"
    elif pct >= 40:
        results["grade"] = "C"
    else:
        results["grade"] = "F"

    return results






# ── v11.0: Per-Model Call Functions ───────────────────
def _call_model(model_id: str, messages: list, temperature=0.1, max_tokens=1024,
                top_p=1, model_label="?", request_type="UNKNOWN", user_id=None,
                timeout: float = TIMEOUT_NORMAL_REASONING) -> tuple:
    """
    Internal multi-model dispatcher. Returns (response_text, latency_ms, error).
    On failure, returns (None, latency_ms, error_str).

    v11.1: Automatically logs every call to the ai_usage analytics table.
    Logging never raises — analytics failures are invisible to callers.

    v13.3.2: `timeout` defaults to TIMEOUT_NORMAL_REASONING, matching this
    dispatcher's general-purpose callers (call_main, call_fast). Callers
    with a different latency profile (call_think, call_vision) pass their
    own explicit override.
    """
    import time as _time
    start = _time.time()
    last_err = None
    response_obj = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                timeout=timeout,
            )
            ms = round((_time.time() - start) * 1000)
            text = response.choices[0].message.content.strip()
            logger.info(f"[{model_label}] {ms}ms ok ({len(text)} chars)")
            # v11.1: capture token usage + log to analytics
            try:
                from analytics import log_ai_request
                usage = getattr(response, "usage", None)
                log_ai_request(
                    model_name=model_id,
                    latency_ms=ms,
                    status="success",
                    user_id=user_id,
                    request_type=request_type,
                    prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
                    completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
                    response_text=text,
                    fallback_used=(attempt > 0),
                )
            except Exception as _e:
                logger.error(f"analytics log failed (non-fatal): {_e}")
            return text, ms, None
        except Exception as e:
            last_err = str(e)
            logger.error(f"[{model_label}] attempt {attempt+1} failed: {last_err[:100]}")
            if attempt < 2:
                time.sleep(1)
    ms = round((_time.time() - start) * 1000)
    # v11.1: log the failed call too
    try:
        from analytics import log_ai_request
        log_ai_request(
            model_name=model_id,
            latency_ms=ms,
            status="error",
            user_id=user_id,
            request_type=request_type,
            error_message=last_err[:300] if last_err else "unknown",
        )
    except Exception:
        pass
    return None, ms, last_err


def call_main(messages: list, temperature=0.1, max_tokens=1024, top_p=1,
              request_type="CHAT", user_id=None) -> str:
    """Main brain — for intent detection, planning, important reasoning."""
    text, _, _ = _call_model(MODEL_MAIN, messages, temperature, max_tokens, top_p,
                              "MAIN", request_type=request_type, user_id=user_id)
    return text or ""


def call_fast(messages: list, temperature=0.1, max_tokens=256,
              request_type="CLASSIFICATION", user_id=None) -> str:
    """
    Fast/cheap model (Llama 3.1 8B) for quick classification.
    Falls back to MAIN if FAST fails or returns nothing.
    """
    text, _, err = _call_model(MODEL_FAST, messages, temperature, max_tokens, 1,
                                "FAST", request_type=request_type, user_id=user_id,
                                timeout=TIMEOUT_FAST_CHAT)
    if text:
        return text
    logger.warning(f"FAST failed ({err[:80] if err else 'empty'}), falling back to MAIN")
    return call_main(messages, temperature, max_tokens, request_type=request_type, user_id=user_id)


def call_think(messages: list, temperature=0.6, max_tokens=800,
               request_type="THINK", user_id=None) -> str:
    """
    Deep reasoning — for /think, advice, multi-step problem solving.
    Higher temperature for more natural reasoning.

    v13.3.2: uses TIMEOUT_LONG_REASONING — /think is explicitly a "take
    your time" feature; users invoking it are more tolerant of a longer
    wait than an ordinary chat message, and a short timeout here risks
    truncating a genuinely long but healthy response.
    """
    text, _, _ = _call_model(MODEL_THINK, messages, temperature, max_tokens, 0.95,
                              "THINK", request_type=request_type, user_id=user_id,
                              timeout=TIMEOUT_LONG_REASONING)
    return text or "I had trouble thinking through that."


def call_vision(image_data_or_url: str, prompt: str, max_tokens=600,
                request_type="VISION", user_id=None) -> str:
    """
    Image understanding via Llama 3.2 Vision.

    v13.3.2: explicitly passes TIMEOUT_VISION (30.0 — identical to the
    original client-level default) rather than inheriting _call_model()'s
    new, shorter TIMEOUT_NORMAL_REASONING default. No evidence vision has
    the same hang problem as MODEL_MAIN, so its effective timeout is
    deliberately left exactly as it was before this hotfix.
    """
    if not ENABLE_VISION:
        return "Image understanding is currently disabled."
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_or_url}}
        ]
    }]
    text, _, err = _call_model(MODEL_VISION, messages, 0.2, max_tokens, 1,
                                "VISION", request_type=request_type, user_id=user_id,
                                timeout=TIMEOUT_VISION)
    if not text:
        return f"Couldn't process the image: {(err or '?')[:100]}"
    return text


def generate_image(prompt: str, size: str = "1024x1024", user_id: int = None) -> dict:
    """
    Generate an image with FLUX.1-schnell via NVIDIA NIM — the ONLY image source.

    Official spec (docs.api.nvidia.com/nim/reference/black-forest-labs-flux_1-schnell-infer):
      POST https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell
      Body: {"prompt": str, "width": 1024, "height": 1024, "cfg_scale": 0,
             "mode": "base", "samples": 1, "seed": 0, "steps": 4}
      200 → {"artifacts": [{"base64": "...", "finishReason": "SUCCESS"}]}

    Notes from the spec:
      - prompt is a PLAIN STRING (not a text_prompts array)
      - only width=height=1024 is supported on the hosted API
      - cfg_scale allowed range is exactly 0
      - steps 1-4 (schnell is distilled for 4)
      - seed 0 = random

    Returns {"data_url": "data:image/jpeg;base64,...", "error": None} on success.
    """
    if not ENABLE_IMAGE_GEN:
        return {"data_url": None, "error": "Image generation is disabled."}
    import time as _time
    import httpx as _httpx

    start = _time.time()
    nim_url = "https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell"
    body = {
        "prompt": prompt[:10000],   # spec: length <= 10000
        "width": 1024,              # spec: only 1024 supported
        "height": 1024,             # spec: only 1024 supported
        "cfg_scale": 0,             # spec: allowed range is 0 to 0
        "mode": "base",
        "samples": 1,               # spec: only 1 supported
        "seed": 0,                  # 0 = random
        "steps": 4,                 # schnell optimized for 4 steps
    }
    headers = {
        "Authorization": f"Bearer {_api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    data_url = None
    err_msg = None
    try:
        with _httpx.Client(timeout=120.0) as http:
            resp = http.post(nim_url, headers=headers, json=body)
            if resp.status_code == 200:
                data = resp.json()
                artifacts = data.get("artifacts") or []
                if artifacts and isinstance(artifacts, list):
                    b64 = artifacts[0].get("base64")
                    finish = artifacts[0].get("finishReason", "")
                    if b64:
                        data_url = f"data:image/jpeg;base64,{b64}"
                        logger.info(f"NIM FLUX ok ({len(b64)} chars, finish={finish})")
                # Defensive: some NIM builds return top-level keys instead
                if not data_url:
                    for key in ("image", "b64_json", "data"):
                        val = data.get(key)
                        if isinstance(val, str) and len(val) > 100:
                            data_url = f"data:image/jpeg;base64,{val}"
                            break
                if not data_url:
                    err_msg = f"NIM returned 200 but no image data: {str(data)[:150]}"
            elif resp.status_code == 422:
                err_msg = f"Invalid request (422): {resp.text[:200]}"
            elif resp.status_code == 404:
                err_msg = ("FLUX.1-schnell endpoint not found (404). Your API key may not "
                           "have Visual GenAI access — check build.nvidia.com/black-forest-labs/flux_1-schnell "
                           "and regenerate your key from that page.")
            elif resp.status_code in (401, 403):
                err_msg = "NVIDIA_API_KEY rejected (401/403). Regenerate at build.nvidia.com."
            elif resp.status_code == 429:
                err_msg = "Rate limit (429). Free tier: 40 req/min, 1000/month. Wait a minute."
            else:
                err_msg = f"NIM {resp.status_code}: {resp.text[:200]}"
    except _httpx.TimeoutException:
        err_msg = "NIM timed out after 120s. The model may be under heavy load — try again."
    except Exception as e:
        err_msg = str(e)[:200]

    ms = round((_time.time() - start) * 1000)
    if err_msg:
        logger.error(f"image gen failed: {err_msg}")

    try:
        from analytics import log_image_request
        log_image_request(
            model_name=MODEL_IMAGE,
            latency_ms=ms,
            status="success" if data_url else "error",
            user_id=user_id,
            prompt_text=prompt,
            image_count=1 if data_url else 0,
            error_message=err_msg,
        )
    except Exception:
        pass

    return {"data_url": data_url, "error": err_msg}


def generate_video(image_data_url: str = None, prompt: str = None,
                   user_id: int = None) -> dict:
    """
    Generate a short video with Stable Video Diffusion via NVIDIA NIM —
    the ONLY hosted video model on NIM (Cosmos has no hosted endpoint).

    Official spec (docs.api.nvidia.com/nim/reference/stabilityai-stable-video-diffusion-infer):
      POST https://ai.api.nvidia.com/v1/genai/stabilityai/stable-video-diffusion
      Body: {"image": "data:image/jpeg;base64,...", "seed": 0,
             "cfg_scale": 1.8, "motion_bucket_id": 127}
      The input image is scaled to 1024x576. Must be < 200KB inline.

    SVD is image-to-video. For a text prompt, we first generate the frame
    with FLUX (NIM), then animate it with SVD (NIM) — a 100% NVIDIA pipeline.

    Returns {"video_b64": "<base64 mp4>", "frame_data_url": ..., "error": None}.
    """
    if not ENABLE_VIDEO_GEN:
        return {"video_b64": None, "frame_data_url": None, "error": "Video generation is disabled."}
    import time as _time
    import base64 as _base64
    import httpx as _httpx

    start = _time.time()
    frame_url = image_data_url

    # Step 1: no image given → generate the first frame with FLUX (NIM)
    if not frame_url:
        if not prompt:
            return {"video_b64": None, "frame_data_url": None,
                    "error": "Need a prompt or an image to make a video."}
        img_result = generate_image(prompt, user_id=user_id)
        if not img_result.get("data_url"):
            return {"video_b64": None, "frame_data_url": None,
                    "error": f"Frame generation failed: {img_result.get('error')}"}
        frame_url = img_result["data_url"]

    # Step 1.5: SVD requires the inline image < 200KB — downscale if needed
    try:
        header, b64_data = frame_url.split(",", 1)
        raw = _base64.b64decode(b64_data)
        if len(raw) > 190_000:  # keep margin under the 200KB limit
            try:
                from PIL import Image
                import io as _io
                img = Image.open(_io.BytesIO(raw)).convert("RGB")
                img.thumbnail((1024, 576))
                quality = 85
                while quality >= 40:
                    buf = _io.BytesIO()
                    img.save(buf, format="JPEG", quality=quality)
                    if buf.tell() <= 190_000:
                        break
                    quality -= 10
                raw = buf.getvalue()
                frame_url = "data:image/jpeg;base64," + _base64.b64encode(raw).decode()
                logger.info(f"SVD frame downscaled to {len(raw)} bytes (q={quality})")
            except ImportError:
                return {"video_b64": None, "frame_data_url": frame_url,
                        "error": "Frame exceeds 200KB and Pillow isn't installed. "
                                 "Run: pip install Pillow"}
    except Exception as e:
        return {"video_b64": None, "frame_data_url": frame_url,
                "error": f"Frame preparation failed: {str(e)[:150]}"}

    # Step 2: animate with SVD (NIM)
    nim_url = "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-video-diffusion"
    body = {
        "image": frame_url,
        "seed": 0,
        "cfg_scale": 1.8,          # spec default; <=9
        "motion_bucket_id": 127,   # spec: only 127 supported
    }
    headers = {
        "Authorization": f"Bearer {_api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    video_b64 = None
    err_msg = None
    try:
        with _httpx.Client(timeout=300.0) as http:  # video takes a while
            resp = http.post(nim_url, headers=headers, json=body)
            if resp.status_code == 200:
                data = resp.json()
                # Response may use "video", "artifacts", or "b64_json"
                video_b64 = data.get("video")
                if not video_b64:
                    artifacts = data.get("artifacts") or []
                    if artifacts and isinstance(artifacts, list):
                        video_b64 = artifacts[0].get("base64")
                if not video_b64:
                    for key in ("b64_json", "data", "mp4"):
                        val = data.get(key)
                        if isinstance(val, str) and len(val) > 1000:
                            video_b64 = val
                            break
                if not video_b64:
                    err_msg = f"SVD returned 200 but no video data: {str(data)[:150]}"
            elif resp.status_code == 404:
                err_msg = ("SVD endpoint not found (404). Your API key may not have "
                           "Visual GenAI access — check build.nvidia.com/stabilityai/stable-video-diffusion")
            elif resp.status_code in (401, 403):
                err_msg = "NVIDIA_API_KEY rejected. Regenerate at build.nvidia.com."
            elif resp.status_code == 429:
                err_msg = "Rate limit hit. Wait a minute and retry."
            elif resp.status_code == 422:
                err_msg = f"Invalid request (422): {resp.text[:200]}"
            else:
                err_msg = f"NIM {resp.status_code}: {resp.text[:200]}"
    except _httpx.TimeoutException:
        err_msg = "Video generation timed out (5 min). SVD may be under heavy load."
    except Exception as e:
        err_msg = str(e)[:200]

    ms = round((_time.time() - start) * 1000)
    if err_msg:
        logger.error(f"video gen failed: {err_msg}")

    try:
        from analytics import log_ai_request
        log_ai_request(
            model_name=MODEL_VIDEO,
            latency_ms=ms,
            status="success" if video_b64 else "error",
            user_id=user_id,
            request_type="VIDEO_GENERATION",
            response_text=None,
            error_message=err_msg,
        )
    except Exception:
        pass

    return {"video_b64": video_b64, "frame_data_url": frame_url, "error": err_msg}


def fast_intent_classify(user_input: str) -> dict:
    """
    Use FAST model for a quick intent guess. Returns {intent, confidence}.
    Used as a pre-filter — if confidence is high enough we skip the full MAIN call.
    """
    if not ENABLE_FAST_ROUTING:
        return {"intent": None, "confidence": 0}
    prompt = (
        "Classify this message into exactly one intent. Respond with ONLY the intent word.\n"
        "Intents: TASK, HABIT, VIEW, MEMORY_SAVE, MEMORY_GET, EDIT, DELETE, GOAL, CHAT, THINK.\n"
        f"Message: \"{user_input[:200]}\"\n"
        "Intent:"
    )
    try:
        raw = call_fast([{"role": "user", "content": prompt}], temperature=0, max_tokens=10)
        intent = (raw or "").strip().upper().split()[0] if raw else "CHAT"
        # Trust FAST only for clear-cut intents
        if intent in ("TASK","HABIT","VIEW","MEMORY_SAVE","MEMORY_GET","EDIT","DELETE","GOAL","CHAT","THINK"):
            return {"intent": intent, "confidence": 0.75}
    except Exception as e:
        logger.error(f"fast_intent_classify failed: {e}")
    return {"intent": None, "confidence": 0}


def benchmark_all_models() -> dict:
    """
    Benchmark MAIN + FAST + VISION availability. Returns per-model status.
    Used by enhanced /status command.
    """
    import time as _time
    results = {}
    # MAIN — a liveness probe wants a quick, decisive answer, not a long wait
    text, ms, err = _call_model(MODEL_MAIN,
        [{"role":"user","content":"Say ONLINE in one word"}], 0, 20, 1, "MAIN_check",
        timeout=TIMEOUT_FAST_CHAT)
    results["main"] = {"model": MODEL_MAIN, "online": text is not None,
                       "ms": ms, "error": err}
    # FAST
    text, ms, err = _call_model(MODEL_FAST,
        [{"role":"user","content":"Say ONLINE in one word"}], 0, 20, 1, "FAST_check",
        timeout=TIMEOUT_FAST_CHAT)
    results["fast"] = {"model": MODEL_FAST, "online": text is not None,
                       "ms": ms, "error": err}
    # VISION (skip if no test image — just check model is accepted)
    if ENABLE_VISION:
        results["vision"] = {"model": MODEL_VISION, "online": "ready (needs image to test)",
                             "ms": 0, "error": None}
    else:
        results["vision"] = {"model": MODEL_VISION, "online": "disabled", "ms": 0, "error": None}
    results["image"] = {"model": MODEL_IMAGE,
                        "online": "ready (always on)" if ENABLE_IMAGE_GEN else "disabled",
                        "ms": 0, "error": None}
    results["video"] = {"model": MODEL_VIDEO,
                        "online": "ready (always on)" if ENABLE_VIDEO_GEN else "disabled",
                        "ms": 0, "error": None}
    return results


def think_freely(user_question: str, user_context: dict = None,
                  recent_tasks: list = None, memories: list = None) -> str:
    """
    v11.0: Free-form AI reasoning — no JSON, no constraints.
    The AI sees the user's profile, open tasks, and memories, then
    answers the question conversationally with real insight.
    This is where BAKA stops being a command bot and becomes an assistant.
    """
    today = datetime.now()

    ctx_lines = [
        f"You are BAKA, the user's personal AI assistant. Today is {today.strftime('%A, %d %B %Y at %H:%M')}.",
        "Your job is to give thoughtful, personalized advice based on what you know about the user.",
        "Don't be generic — reference their actual tasks, habits, and patterns when relevant.",
        "Be warm but direct. Keep responses under 200 words unless the question demands more.",
        "",
    ]

    if user_context:
        if user_context.get("recent_completions"):
            ctx_lines.append("Recent things they completed:")
            for t in user_context["recent_completions"][:5]:
                ctx_lines.append(f"  - {t[0]} ({t[1] or 'General'})")
        if user_context.get("open_tasks_by_category"):
            cats = user_context["open_tasks_by_category"]
            ctx_lines.append(f"Currently open tasks: {sum(cats.values())} total — "
                             + ", ".join(f"{k}: {v}" for k, v in cats.items() if k))
        if user_context.get("overdue_count"):
            ctx_lines.append(f"They have {user_context['overdue_count']} overdue task(s).")
        if user_context.get("active_habits"):
            ctx_lines.append("Active habits:")
            for h in user_context["active_habits"][:3]:
                ctx_lines.append(f"  - {h[0]} (streak {h[1]})")

    if recent_tasks:
        ctx_lines.append("\nRecent open tasks:")
        for t in recent_tasks[:5]:
            ctx_lines.append(f"  [{t[0]}] {t[1]} due {t[2] or '?'} {t[3] or ''}")

    if memories:
        ctx_lines.append("\nUser's stored memories (facts they told BAKA):")
        for key, val in memories[:10]:
            ctx_lines.append(f"  {key}: {val}")

    system_prompt = "\n".join(ctx_lines)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_question},
    ]
    try:
        # v11.0: route through THINK model for deep reasoning
        return call_think(messages, temperature=0.6, max_tokens=600)
    except Exception as e:
        logger.error(f"think_freely failed: {e}")
        return f"I had trouble thinking about that. Try again, or rephrase."

def chat_with_ai(message: str) -> str:
    try:
        return call_nvidia([{
            "role": "user",
            "content": f"You are BAKA, a helpful AI assistant. Be concise and friendly.\nUser: {message}"
        }], temperature=0.7, max_tokens=512)
    except Exception as e:
        return f"❌ Error: {str(e)}"


def suggest_tasks(goal: str) -> str:
    try:
        return call_nvidia([{"role": "user", "content":
            f"You are a productivity coach. User's goal: '{goal}'\n"
            f"Suggest 5 specific actionable tasks.\n"
            f"Format: 1. [Task name] — [Why it helps]\nBe concise."
        }], temperature=0.7, max_tokens=512, timeout=TIMEOUT_NORMAL_REASONING)
    except Exception as e:
        return f"❌ Error: {str(e)}"


def analyze_productivity(tasks: list) -> str:
    try:
        if not tasks:
            return "📭 No tasks yet! Add some tasks first."
        task_list = "\n".join([
            f"- {t[1]} | {t[2] or 'No date'} | {t[4] if len(t) > 4 else 'General'} | {'Done' if len(t) > 5 else 'Pending'}"
            for t in tasks
        ])
        return call_nvidia([{"role": "user", "content":
            f"Analyze these tasks for productivity insights:\n{task_list}\n"
            f"Today: {datetime.now().strftime('%Y-%m-%d')}\n"
            f"Provide:\n1) Pattern\n2) Urgent/overdue items\n3) 3 improvement tips\n4) Today's focus\nBe concise."
        }], temperature=0.5, max_tokens=512, timeout=TIMEOUT_NORMAL_REASONING)
    except Exception as e:
        return f"❌ Error: {str(e)}"


def generate_structured_plan(tasks_today: list, user_prefs: dict = None,
                             period_label: str = "today") -> dict:
    """
    Generate a structured time-blocked plan that can be APPLIED back to the DB.
    Returns: {
        "summary": "human-readable plan summary",
        "schedule": [
            {"task_id": <id>, "time": "HH:MM", "duration_min": 60, "note": "why this time"}
        ]
    }
    """
    if not tasks_today:
        return {"summary": "No tasks to plan.", "schedule": []}
    if user_prefs is None:
        user_prefs = {}

    task_lines = []
    for t in tasks_today:
        tid, title, ddate, dtime, cat, prio = t[:6]
        prio_emoji = "🔴" if prio == "high" else "🟢" if prio == "low" else "🟡"
        task_lines.append(
            f"  id={tid} | {title} | {cat} | {prio} | "
            f"currently_at={dtime or 'flexible'} on {ddate}"
        )
    quiet_start = user_prefs.get("quiet_start", "23:00")
    quiet_end = user_prefs.get("quiet_end", "07:00")

    try:
        prompt = (
            f"You are a productivity coach. Generate a time-blocked plan for {period_label}.\n\n"
            f"Tasks (with their IDs):\n" + "\n".join(task_lines) + "\n\n"
            f"Rules:\n"
            f"- User awake from {quiet_end} to {quiet_start}\n"
            f"- High priority tasks earlier when fresh\n"
            f"- Group similar categories together\n"
            f"- Realistic time blocks (30-90 min each)\n"
            f"- Suggest specific HH:MM start times\n\n"
            f"Reply ONLY with JSON in this exact format:\n"
            f'{{\n'
            f'  "summary": "Brief motivational summary of the day",\n'
            f'  "schedule": [\n'
            f'    {{"task_id": 5, "time": "09:00", "duration_min": 60, "note": "high-energy morning slot"}},\n'
            f'    {{"task_id": 7, "time": "10:30", "duration_min": 45, "note": "follow-up after first task"}}\n'
            f'  ]\n'
            f'}}\n\n'
            f"Every task in the input must appear in the schedule. No extra text."
        )
        raw = call_nvidia([{"role": "user", "content": prompt}],
                          temperature=0.4, max_tokens=800, timeout=TIMEOUT_NORMAL_REASONING)
        cleaned = clean_json(raw)
        data = json.loads(cleaned)
        return data
    except Exception as e:
        logger.error(f"Structured plan failed: {e}")
        return {"summary": "Couldn't generate structured plan.", "schedule": []}


def generate_daily_plan(tasks_today: list, user_prefs: dict = None) -> str:
    """Generate a time-blocked plan for today's tasks."""
    if not tasks_today:
        return "Nothing scheduled for today! Add some tasks or enjoy your day."
    if user_prefs is None:
        user_prefs = {}
    task_lines = []
    for t in tasks_today:
        tid, title, ddate, dtime, cat, prio = t[:6]
        prio_emoji = "🔴" if prio == "high" else "🟢" if prio == "low" else "🟡"
        task_lines.append(f"  {prio_emoji} [{tid}] {title} ({cat}, {prio}) — "
                          f"{'⏰ '+dtime if dtime else 'no fixed time'}")
    quiet_start = user_prefs.get("quiet_start", "23:00")
    quiet_end = user_prefs.get("quiet_end", "07:00")
    try:
        prompt = (
            f"You are a productivity coach. Create a TIME-BLOCKED plan for today.\n"
            f"Tasks:\n" + "\n".join(task_lines) + "\n\n"
            f"Constraints:\n"
            f"- User is awake from {quiet_end} to {quiet_start}\n"
            f"- High-priority tasks should be earlier when energy is fresh\n"
            f"- Group similar categories together\n"
            f"- Suggest realistic time blocks (30-90 min each)\n"
            f"- Include short breaks between tasks\n\n"
            f"Format as a clean schedule with time slots. Be concise. End with one motivational line."
        )
        return call_nvidia([{"role": "user", "content": prompt}],
                           temperature=0.6, max_tokens=600, timeout=TIMEOUT_NORMAL_REASONING)
    except Exception as e:
        return f"❌ Error generating plan: {e}"


def generate_weekly_plan(tasks_week: list, user_prefs: dict = None) -> str:
    """Generate a 7-day plan from all upcoming tasks."""
    if not tasks_week:
        return "Your week is clear! Time to set some goals."
    by_day = {}
    for t in tasks_week:
        tid, title, ddate, dtime, cat, prio = t[:6]
        by_day.setdefault(ddate, []).append((tid, title, dtime, cat, prio))
    summary = []
    for date in sorted(by_day.keys()):
        summary.append(f"\n{date}:")
        for tid, title, dtime, cat, prio in by_day[date]:
            prio_emoji = "🔴" if prio == "high" else "🟢" if prio == "low" else "🟡"
            summary.append(f"  {prio_emoji} [{tid}] {title} ({cat}) — {dtime or 'flexible'}")
    try:
        prompt = (
            "You are a productivity coach. Review this week's tasks and suggest:\n"
            "1. Days that look overloaded (>4 tasks)\n"
            "2. Tasks that could be moved to balance the week\n"
            "3. Daily theme/focus for each day\n"
            "4. A motivational summary\n\n"
            "Tasks by day:" + "\n".join(summary) + "\n\n"
            "Be concise. Use ✅ for balanced days, ⚠️ for overloaded ones."
        )
        return call_nvidia([{"role": "user", "content": prompt}],
                           temperature=0.6, max_tokens=700, timeout=TIMEOUT_NORMAL_REASONING)
    except Exception as e:
        return f"❌ Error: {e}"


def generate_task_breakdown(task_title: str, deadline: str = None,
                            existing_subtasks: list = None) -> list:
    """Break a large task into 3-5 subtasks. Returns a list of dicts."""
    try:
        prompt = (
            f"Break this task into 3-5 actionable subtasks:\n"
            f"Task: {task_title}\n"
            f"Deadline: {deadline or 'flexible'}\n\n"
            f"Reply ONLY with JSON in this exact format:\n"
            f'{{"subtasks": [\n'
            f'  {{"title": "First step", "estimated_hours": 1, "priority": "high"}},\n'
            f'  {{"title": "Second step", "estimated_hours": 2, "priority": "medium"}}\n'
            f']}}\n\n'
            f"Subtasks should be specific and actionable. No extra text."
        )
        raw = call_nvidia([{"role": "user", "content": prompt}],
                          temperature=0.4, max_tokens=400, timeout=TIMEOUT_NORMAL_REASONING)
        cleaned = clean_json(raw)
        data = json.loads(cleaned)
        return data.get("subtasks", [])
    except Exception as e:
        logger.error(f"Breakdown failed: {e}")
        return []


def suggest_reschedule_time(task_title: str, conflict_tasks: list) -> str:
    """Given a task and other tasks at conflicting times, suggest a new time."""
    try:
        others = "\n".join([f"- {t[1]} at {t[3] or 'flexible'}" for t in conflict_tasks[:5]])
        prompt = (
            f"User wants to reschedule: '{task_title}'\n"
            f"Other tasks on that day:\n{others}\n\n"
            f"Suggest a good time (HH:MM format) avoiding conflicts. "
            f"Reply with ONLY the time, e.g. '14:30'. Nothing else."
        )
        result = call_nvidia([{"role": "user", "content": prompt}],
                             temperature=0.3, max_tokens=20)
        # Extract HH:MM
        import re
        m = re.search(r"\b(\d{1,2}:\d{2})\b", result)
        if m:
            return m.group(1)
        return None
    except Exception:
        return None


def generate_study_plan(goal: str, deadline: str, existing_tasks: list) -> str:
    try:
        task_list = "\n".join([f"- {t[1]} | {t[2] or 'no date'}" for t in existing_tasks[:5]])
        today = datetime.now().strftime("%Y-%m-%d")
        return call_nvidia([{"role": "user", "content":
            f"Create a study plan for: '{goal}'\n"
            f"Deadline: {deadline}\nToday: {today}\n"
            f"Existing tasks: {task_list or 'None'}\n\n"
            f"Generate a day-by-day study schedule breaking the goal into sessions.\n"
            f"Format: Day 1 (Date): [What to study] [Duration]\nBe specific and realistic."
        }], temperature=0.6, max_tokens=800, timeout=TIMEOUT_NORMAL_REASONING)
    except Exception as e:
        return f"❌ Error: {str(e)}"


def extract_memory_key(user_input: str) -> tuple:
    """Extract key-value pair from memory save request"""
    try:
        content = call_nvidia([{"role": "user", "content":
            f"Extract the memory key and value from: '{user_input}'\n"
            f"Reply ONLY as: KEY: <short key>\nVALUE: <what to remember>"
        }], temperature=0, max_tokens=100)
        key, value = None, None
        for line in content.strip().split("\n"):
            if line.startswith("KEY:"):
                key = line.split("KEY:")[1].strip().lower()
            elif line.startswith("VALUE:"):
                value = line.split("VALUE:")[1].strip()
        return key, value
    except Exception:
        return None, None