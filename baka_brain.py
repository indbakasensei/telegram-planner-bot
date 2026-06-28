"""
baka_brain.py — BAKA AI brain
Handles intent detection with memory, multiple tasks, and better Hindi/Hinglish support.
"""
import json
import os
import logging
import time
from openai import OpenAI
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

# v10.0: Model config — single constant makes v11.0 multi-model swap easy
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
MODEL_MAIN = "z-ai/glm-5.1"  # GLM 5.1 — main brain
# v11.0 planned: MODEL_FAST, MODEL_IMAGE, MODEL_VISION, MODEL_VIDEO

client = OpenAI(
    base_url=NIM_BASE_URL,
    api_key=_api_key or "missing-key-check-env-file"
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

def call_nvidia(messages: list, temperature=0.1, max_tokens=1024, top_p=1) -> str:
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL_MAIN,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"API attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2)
            else:
                raise e

def get_baka_response(user_input: str, existing_tasks: list,
                        history: list = None, memories: list = None,
                        user_context: dict = None) -> dict:
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
        ], temperature=0.1)

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
    start = time.time()
    try:
        response = client.chat.completions.create(
            model=MODEL_MAIN,
            messages=[{"role": "user", "content": "Reply with only: ONLINE"}],
            max_tokens=10, temperature=0
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
        # Use slightly higher temperature for more natural reasoning
        return call_nvidia(messages, temperature=0.6, max_tokens=600, top_p=0.95)
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
        }], temperature=0.7, max_tokens=512)
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
        }], temperature=0.5, max_tokens=512)
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
                          temperature=0.4, max_tokens=800)
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
                           temperature=0.6, max_tokens=600)
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
                           temperature=0.6, max_tokens=700)
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
                          temperature=0.4, max_tokens=400)
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
        }], temperature=0.6, max_tokens=800)
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