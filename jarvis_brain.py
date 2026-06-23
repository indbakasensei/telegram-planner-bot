"""
jarvis_brain.py — JARVIS AI brain
Handles intent detection with memory, multiple tasks, and better Hindi/Hinglish support.
"""
import json
import os
import logging
import time
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
logger = logging.getLogger(__name__)

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY")
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

def call_nvidia(messages: list, temperature=0.1, max_tokens=1024) -> str:
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model="meta/llama-3.1-8b-instruct",
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"API attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2)
            else:
                raise e

def get_jarvis_response(user_input: str, existing_tasks: list,
                        history: list = None, memories: list = None) -> dict:
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)
    next_week = today + timedelta(days=7)

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

    system = f"""You are JARVIS, an intelligent Telegram AI assistant.

DATE CONTEXT:
Today={today.strftime('%A %d %B %Y')} ({today.strftime('%Y-%m-%d')})
Tomorrow={tomorrow.strftime('%A')} ({tomorrow.strftime('%Y-%m-%d')})
DayAfterTomorrow={day_after.strftime('%Y-%m-%d')}
NextWeek={next_week.strftime('%Y-%m-%d')}

{task_ctx}
{memory_ctx}
Recent chat: {hist_ctx}

LANGUAGE SUPPORT — You understand:
- English: "remind me to call mom tomorrow at 5pm"
- Hindi: "Kal subah 8 baje gym yaad dila dena"
- Hinglish: "Bhai next Friday assignment submit karna hai"
- "Aaj"=today, "Kal"=tomorrow, "Parso"=day after tomorrow
- "Subah"=morning(AM), "Raat"=night(PM), "Shaam"=evening(PM), "Dopahar"=afternoon(PM)
- "Baje"=o'clock, "Har roz"=every day, "Har hafte"=every week

INTENT TYPES:
TASK — New task/reminder to create
EDIT — Modify existing task (by name or id)
DELETE — Remove task
VIEW — Show tasks (today/tomorrow/week/all)
MEMORY_SAVE — User wants to store a fact ("remember that...", "mera exam...")
MEMORY_GET — User wants to retrieve stored info ("when are my exams?")
GOAL — Long-term goal (not a specific dated task)
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
7. For invalid time (25 PM) or past date: flag in errors

TITLE EXTRACTION:
"Remind me to call mom" → "Call mom"
"Kal gym yaad dila dena" → "Gym"  
"Physics assignment submit karna hai" → "Physics assignment"
"Study physics today at 8pm" → "Study Physics"

Respond ONLY with valid JSON:
{{
  "intent": "TASK|EDIT|DELETE|VIEW|MEMORY_SAVE|MEMORY_GET|GOAL|PLAN|ADVICE|CHAT|MULTIPLE",
  "view_period": "today|tomorrow|week|year|all|null",
  "task_id": null,
  "entities": {{
    "title": "extracted task name or null",
    "date": "YYYY-MM-DD or null",
    "time": "HH:MM or null",
    "category": "Study|Health|Work|Personal|Other|null",
    "priority": "high|medium|low|null",
    "recurrence": "daily|weekly|monthly|null",
    "recurrence_day": "weekday name or day number or null"
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
        logger.error(f"JARVIS error: {e}")
        return {"intent": "CHAT", "entities": {}, "confidence": 0.0,
                "missing": [], "errors": [],
                "response": f"Something went wrong. Please try again.",
                "needs_confirm": False, "tasks": [], "confirm_summary": None}


def check_api_status() -> dict:
    start = time.time()
    try:
        response = client.chat.completions.create(
            model="meta/llama-3.1-8b-instruct",
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


def chat_with_ai(message: str) -> str:
    try:
        return call_nvidia([{
            "role": "user",
            "content": f"You are JARVIS, a helpful AI assistant. Be concise and friendly.\nUser: {message}"
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