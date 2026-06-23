import os
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=os.getenv("NVIDIA_API_KEY")
)

def ask_ai(prompt: str) -> str:
    response = client.chat.completions.create(
        model="meta/llama-3.1-8b-instruct",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
        temperature=0.7
    )
    return response.choices[0].message.content

def check_api_status() -> dict:
    """Check if NVIDIA API is working and return status"""
    try:
        response = client.chat.completions.create(
            model="meta/llama-3.1-8b-instruct",
            messages=[{"role": "user", "content": "Reply with only the word: OK"}],
            max_tokens=5
        )
        reply = response.choices[0].message.content.strip()
        usage = response.usage
        return {
            'status': 'online',
            'response': reply,
            'prompt_tokens': usage.prompt_tokens if usage else 'N/A',
            'completion_tokens': usage.completion_tokens if usage else 'N/A',
            'total_tokens': usage.total_tokens if usage else 'N/A'
        }
    except Exception as e:
        error_str = str(e)
        if '429' in error_str or 'rate' in error_str.lower():
            return {'status': 'rate_limited', 'error': error_str}
        elif '401' in error_str or 'auth' in error_str.lower():
            return {'status': 'invalid_key', 'error': error_str}
        else:
            return {'status': 'error', 'error': error_str}

def chat_with_ai(user_message: str) -> str:
    try:
        return ask_ai(
            f"You are a helpful personal assistant inside a Telegram planner bot. "
            f"Answer clearly and concisely.\n\nUser: {user_message}"
        )
    except Exception as e:
        return f"❌ AI error: {str(e)}"

def suggest_tasks(goal: str) -> str:
    try:
        return ask_ai(
            f"You are a productivity coach. The user has this goal: '{goal}'.\n"
            f"Suggest 5 specific, actionable tasks to achieve this goal.\n"
            f"Format:\n1. [Task title] — [Why it helps]\nKeep it short and practical."
        )
    except Exception as e:
        return f"❌ AI error: {str(e)}"

def analyze_productivity(tasks: list) -> str:
    try:
        if not tasks:
            return "📭 No tasks yet! Add some with /add"
        task_list = ""
        for t in tasks:
            task_list += f"- {t[1]} | Date: {t[2] or 'No date'} | Category: {t[4]}\n"
        return ask_ai(
            f"You are a productivity analyst. Analyze these tasks:\n\n{task_list}\n\n"
            f"Today: {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"Provide:\n1. 📊 Productivity pattern\n2. ⚠️ Overdue/urgent tasks\n"
            f"3. 💡 3 improvement tips\n4. 🎯 Today's focus\nBe concise."
        )
    except Exception as e:
        return f"❌ AI error: {str(e)}"

def auto_schedule(user_input: str) -> dict:
    try:
        today = datetime.now()
        tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        response = ask_ai(
            f"Today is {today.strftime('%Y-%m-%d')}. Tomorrow is {tomorrow}.\n"
            f"Extract task details from: '{user_input}'\n\n"
            f"Reply ONLY in this exact format:\n"
            f"TITLE: <task title>\nDATE: <YYYY-MM-DD or none>\n"
            f"TIME: <HH:MM or none>\nCATEGORY: <Study/Health/Work/Personal/Other>"
        )
        lines = response.strip().split("\n")
        result = {}
        for line in lines:
            if "TITLE:" in line:
                result['title'] = line.split("TITLE:")[1].strip()
            elif "DATE:" in line:
                val = line.split("DATE:")[1].strip()
                result['due_date'] = None if val.lower() == 'none' else val
            elif "TIME:" in line:
                val = line.split("TIME:")[1].strip()
                result['due_time'] = None if val.lower() in ['none', 'yes', 'no'] else val
            elif "CATEGORY:" in line:
                result['category'] = line.split("CATEGORY:")[1].strip()
        return result
    except Exception as e:
        return {'error': str(e)}

def detect_intent(user_input: str, existing_tasks: list) -> dict:
    try:
        today = datetime.now()
        tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        day_after = (today + timedelta(days=2)).strftime("%Y-%m-%d")
        next_week = (today + timedelta(days=7)).strftime("%Y-%m-%d")

        task_list = ""
        for t in existing_tasks:
            task_list += f"ID:{t[0]} | Title:{t[1]} | Date:{t[2] or 'none'} | Time:{t[3] or 'none'}\n"

        response = ask_ai(
            f"Today is {today.strftime('%Y-%m-%d')} ({today.strftime('%A')}).\n"
            f"Tomorrow is {tomorrow}.\n"
            f"Day after tomorrow is {day_after}.\n"
            f"Next week starts {next_week}.\n\n"
            f"User message: '{user_input}'\n\n"
            f"Existing tasks:\n{task_list or 'No tasks yet'}\n\n"
            f"Classify the message. Reply ONLY in this exact format:\n"
            f"INTENT: <SCHEDULE or EDIT or DELETE or VIEW or CHAT>\n"
            f"TASK_ID: <id number or none>\n"
            f"TITLE: <task title or none>\n"
            f"DATE: <YYYY-MM-DD or none>\n"
            f"TIME: <HH:MM or none>\n"
            f"CATEGORY: <Study or Health or Work or Personal or Other or none>\n"
            f"MISSING_TIME: <YES or NO>\n"
            f"VIEW_PERIOD: <today or tomorrow or week or year or none>\n\n"
            f"STRICT Rules:\n"
            f"1. SCHEDULE: user clearly wants to CREATE a new task/reminder/todo\n"
            f"   Examples: 'remind me to...', 'I need to finish...', 'add task...'\n"
            f"2. EDIT: user wants to CHANGE an existing task by name or ID\n"
            f"3. DELETE: user wants to REMOVE/DELETE a task\n"
            f"4. VIEW: user wants to SEE/SHOW/LIST tasks\n"
            f"   Examples: 'show me tasks for tomorrow', 'what do I have today',\n"
            f"   'list my schedule', 'what is due tomorrow'\n"
            f"5. CHAT: questions, general conversation, anything else\n"
            f"   Examples: 'can you help me?', 'hey bot', 'what should I study?'\n\n"
            f"NEVER classify a question like 'can you show me...' as SCHEDULE.\n"
            f"NEVER classify 'can you help me with something?' as SCHEDULE or EDIT.\n"
            f"DATE: always use actual YYYY-MM-DD. 'tomorrow' = {tomorrow}, "
            f"'day after tomorrow' = {day_after}, 'next week' = {next_week}.\n"
            f"TIME: HH:MM only. Never YES/NO.\n"
            f"MISSING_TIME: YES only when INTENT is SCHEDULE and no time given."
        )

        lines = response.strip().split("\n")
        result = {}
        for line in lines:
            for key in ["INTENT", "TASK_ID", "TITLE", "DATE", "TIME",
                       "CATEGORY", "MISSING_TIME", "VIEW_PERIOD"]:
                if line.strip().startswith(f"{key}:"):
                    val = line.split(f"{key}:")[1].strip()
                    result[key.lower()] = None if val.lower() == 'none' else val

        # Safety checks
        if result.get('time') in ['YES', 'NO', 'yes', 'no']:
            result['time'] = None
            result['missing_time'] = 'YES'

        if result.get('task_id') and result.get('intent', '').upper() == 'SCHEDULE':
            result['intent'] = 'EDIT'

        return result
    except Exception as e:
        return {'intent': 'CHAT', 'error': str(e)}
