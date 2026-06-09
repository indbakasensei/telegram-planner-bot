import os
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime

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
            f"Suggest 5 specific, actionable tasks to achieve this goal. "
            f"Format each task as:\n"
            f"1. [Task title] — [Why it helps]\n"
            f"Keep it short and practical."
        )
    except Exception as e:
        return f"❌ AI error: {str(e)}"

def analyze_productivity(tasks: list) -> str:
    try:
        if not tasks:
            return "📭 You have no tasks yet! Add some tasks first with /add"
        task_list = ""
        for t in tasks:
            task_list += f"- {t[1]} | Date: {t[2] or 'No date'} | Category: {t[4]}\n"
        return ask_ai(
            f"You are a productivity analyst. Analyze these tasks and give insights:\n\n"
            f"{task_list}\n\n"
            f"Today's date: {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"Please provide:\n"
            f"1. 📊 Overall productivity pattern\n"
            f"2. ⚠️ Any overdue or urgent tasks\n"
            f"3. 💡 3 specific tips to improve productivity\n"
            f"4. 🎯 Focus recommendation for today\n"
            f"Keep it concise and actionable."
        )
    except Exception as e:
        return f"❌ AI error: {str(e)}"

def auto_schedule(user_input: str) -> dict:
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        response = ask_ai(
            f"Today's date is {today}.\n"
            f"Extract task details from this text: '{user_input}'\n\n"
            f"Reply ONLY in this exact format, nothing else:\n"
            f"TITLE: <task title>\n"
            f"DATE: <YYYY-MM-DD or 'none'>\n"
            f"TIME: <HH:MM or 'none'>\n"
            f"CATEGORY: <Study/Health/Work/Personal/Other>"
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
                result['due_time'] = None if val.lower() == 'none' else val
            elif "CATEGORY:" in line:
                result['category'] = line.split("CATEGORY:")[1].strip()
        return result
    except Exception as e:
        return {'error': str(e)}
