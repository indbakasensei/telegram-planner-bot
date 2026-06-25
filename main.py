import os
import re
import logging
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from database import (
    init_db, add_task, get_tasks, get_tasks_by_date, get_tasks_by_week,
    mark_done, delete_task, update_task, get_task_by_id,
    search_tasks_by_title, task_exists,
    save_memory, get_memory, get_all_memories, search_memories, delete_memory,
    add_goal, get_goals,
    snooze_task, postpone_task, pause_task, resume_task,
    mark_reminded, get_paused_tasks,
    get_overdue_tasks, get_upcoming_deadlines, set_tags,
    get_tasks_by_tag, carry_forward_overdue,
    get_user_prefs, set_quiet_hours, set_reminder_interval,
    increment_reminder_count, mark_reminded, get_all_user_ids,
    stop_reminders, clear_snooze,
    add_subtask, get_subtasks, get_tasks_for_planning, count_tasks_per_day
)
from jarvis_brain import (
    get_jarvis_response, check_api_status,
    chat_with_ai, suggest_tasks, analyze_productivity,
    generate_study_plan, extract_memory_key,
    generate_daily_plan, generate_weekly_plan,
    generate_task_breakdown, suggest_reschedule_time
)
from conversation_state import (
    get_state, clear_state, update_context,
    add_history, get_history,
    set_pending_action, get_pending_action,
    set_gathering, get_gathering,
    set_editing, get_editing_id
)
from date_parser import parse_all, validate_datetime
from scheduler import get_due_tasks, get_tasks_needing_followup, auto_carry_forward, is_quiet_hours
import debug_system as dbg
from datetime import datetime, timedelta
import pytz

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
IST = pytz.timezone("Asia/Kolkata")


# ── Menus ─────────────────────────────────────────────
def main_menu():
    keyboard = [
        ['📌 Add Task', '📋 My Tasks'],
        ['📅 Today', '🗓 This Week', '📆 Overdue'],
        ['✅ Done', '🗑 Delete', '✏️ Edit'],
        ['🧠 Memory', '📊 Analyze'],
        ['⚙️ Settings', '❓ Help'],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def yes_no_menu():
    keyboard = [['✅ Yes, save it!', '❌ No, cancel']]
    return ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)

def format_tasks(tasks, label):
    if not tasks:
        return f"✅ No tasks for {label}!"
    msg = f"📋 *Tasks for {label}:*\n\n"
    _today = datetime.now(IST).strftime("%Y-%m-%d")
    for t in tasks:
        priority = t[5] if len(t) > 5 else "medium"
        recurrence = t[6] if len(t) > 6 else None
        is_overdue = t[2] and t[2] < _today
        emoji = "⏰" if is_overdue else "🔴" if priority == "high" else "🟢" if priority == "low" else "🟡"
        overdue_tag = " *(OVERDUE)*" if is_overdue else ""
        rec_icon = " 🔄" if recurrence else ""
        msg += f"{emoji} *[{t[0]}]* {t[1]}{rec_icon}{overdue_tag}\n"
        msg += f"      📅 {t[2] or 'No date'}  ⏰ {t[3] or 'No time'}  🏷 {t[4] if len(t) > 4 else 'General'}\n\n"
    return msg

def build_summary(data: dict) -> str:
    rec = f"\n🔄 Repeats: {data.get('recurrence', '')}" if data.get('recurrence') else ""
    return (
        f"📌 *{data.get('title')}*\n"
        f"📅 {data.get('date') or 'No date'}\n"
        f"⏰ {data.get('time') or 'No time'}\n"
        f"🏷 {data.get('category') or 'General'}"
        f"{rec}"
    )

def parse_time_from_text(text: str) -> str | None:
    """Quick regex time extraction"""
    t = text.lower()
    m = re.search(r'\b(\d{1,2}):(\d{2})\b', t)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if h <= 23 and mn <= 59:
            return f"{h:02d}:{mn:02d}"
    m = re.search(r'\b(\d{1,2})\s*(pm|am)\b', t)
    if m:
        h, p = int(m.group(1)), m.group(2)
        if h <= 12:
            if p == "pm" and h != 12: h += 12
            elif p == "am" and h == 12: h = 0
            return f"{h:02d}:00"
    m = re.search(r'\b(\d{1,2})\s*(?:baje|bajey)\b', t)
    if m and int(m.group(1)) <= 23:
        return f"{int(m.group(1)):02d}:00"
    return None


# ── Commands ──────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    clear_state(user_id)
    name = update.message.from_user.first_name or "there"
    await update.message.reply_text(
        f"👋 Hey {name}! I'm *JARVIS* — your AI personal assistant.\n\n"
        f"I help you manage tasks, reminders, and goals through natural conversation.\n\n"
        f"🗣 *Just type naturally:*\n"
        f"• _'Remind me to call mom tomorrow at 5pm'_\n"
        f"• _'Kal 8 baje gym yaad dila dena'_\n"
        f"• _'What do I have today?'_\n"
        f"• _'Remember my exam is on June 20'_\n\n"
        f"🔔 I'll keep reminding you until tasks are done!\n"
        f"🌙 Quiet hours: no pings while you sleep\n"
        f"📊 Track your productivity over time\n\n"
        f"Type /help to see all features, or just start talking!",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help1 = (
        "\U0001f916 *JARVIS — Complete Guide*\n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\U0001f4ac *TALK NATURALLY*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Just type in English, Hindi, or Hinglish!\n"
        "_'Remind me to study at 5pm'_\n"
        "_'Kal gym yaad dila dena'_\n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\U0001f4cc *TASK MANAGEMENT*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "/list \u2014 All pending tasks\n"
        "/today \u2014 Today's schedule\n"
        "/week \u2014 This week's plan\n"
        "/done <id> \u2014 Mark complete\n"
        "/edit <id> \u2014 Modify a task\n"
        "/delete <id> \u2014 Remove a task\n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\U0001f514 *REMINDERS*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Auto-reminders with buttons:\n"
        "  \u2705 Done  \u23f0 Snooze  \U0001f4c5 Tomorrow\n"
        "/pause <id> \u2014 Stop reminders\n"
        "/resume <id> \u2014 Restart reminders\n"
        "/paused \u2014 View paused tasks\n"
    )
    help2 = (
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\U0001f4c5 *TRACKING*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "/overdue \u2014 Overdue tasks\n"
        "/deadlines \u2014 Due in 3 days\n"
        "/carryforward \u2014 Move overdue to today\n"
        "/tag <id> <tags> \u2014 Add tags\n"
        "/tagged <tag> \u2014 Search by tag\n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\U0001f9e0 *AI FEATURES*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "/memory \u2014 Stored memories\n"
        "/analyze \u2014 Productivity report\n"
        "/suggest <goal> \u2014 Task ideas\n"
        "Just chat with me anytime!\n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\u2699\ufe0f *SETTINGS*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "/settings \u2014 View all settings\n"
        "/quiethours \u2014 Set sleep hours\n"
        "/interval <min> \u2014 Reminder freq\n"
        "/status \u2014 API health check\n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "\U0001f41e *DEBUG*\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "/debug \u2014 Toggle debug mode\n"
        "/report <issue> \u2014 Report a bug\n"
        "/bugs \u2014 View reported bugs\n"
        "/selftest \u2014 Test checklist"
    )
    await update.message.reply_text(help1, parse_mode="Markdown")
    await update.message.reply_text(help2, parse_mode="Markdown", reply_markup=main_menu())
async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(update.message.from_user.id)
    await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu())

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks(update.message.from_user.id)
    await update.message.reply_text(
        format_tasks(tasks, "All Pending"), parse_mode="Markdown", reply_markup=main_menu()
    )

async def today_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(IST).strftime("%Y-%m-%d")
    tasks = get_tasks_by_date(update.message.from_user.id, today)
    await update.message.reply_text(
        format_tasks(tasks, f"Today ({today})"), parse_mode="Markdown", reply_markup=main_menu()
    )

async def week_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(IST)
    tasks = get_tasks_by_week(update.message.from_user.id,
        now.strftime("%Y-%m-%d"), (now + timedelta(days=7)).strftime("%Y-%m-%d"))
    await update.message.reply_text(
        format_tasks(tasks, "This Week"), parse_mode="Markdown", reply_markup=main_menu()
    )

async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        tasks = get_tasks(user_id)
        if not tasks:
            await update.message.reply_text("🎉 No pending tasks!", reply_markup=main_menu())
            return
        msg = "✅ *Mark which task done?* `/done <id>`\n\n"
        for t in tasks:
            msg += f"*[{t[0]}]* {t[1]}\n"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
        return
    try:
        task_id = int(context.args[0])
        task = get_task_by_id(task_id, user_id)
        if not task:
            await update.message.reply_text(f"❌ Task [{task_id}] not found.")
            return
        mark_done(task_id, user_id)
        await update.message.reply_text(
            f"✅ *Done!* Great job:\n📌 {task[1]}",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    except ValueError:
        await update.message.reply_text("Usage: /done <id>")

async def delete_task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        tasks = get_tasks(user_id)
        if not tasks:
            await update.message.reply_text("🎉 No pending tasks!", reply_markup=main_menu())
            return
        msg = "🗑 *Delete which task?* `/delete <id>`\n\n"
        for t in tasks:
            msg += f"*[{t[0]}]* {t[1]} — 📅 {t[2] or 'No date'}\n"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
        return
    try:
        task_id = int(context.args[0])
        task = get_task_by_id(task_id, user_id)
        if not task:
            await update.message.reply_text(f"❌ Task [{task_id}] not found.")
            return
        delete_task(task_id, user_id)
        await update.message.reply_text(f"🗑 Deleted: *{task[1]}*", parse_mode="Markdown", reply_markup=main_menu())
    except ValueError:
        await update.message.reply_text("Usage: /delete <id>")

async def edit_task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        tasks = get_tasks(user_id)
        if not tasks:
            await update.message.reply_text("🎉 No pending tasks!", reply_markup=main_menu())
            return
        msg = "✏️ *Edit which task?* `/edit <id>`\n\n"
        for t in tasks:
            msg += f"*[{t[0]}]* {t[1]} — 📅 {t[2] or 'No date'} ⏰ {t[3] or 'No time'}\n"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
        return
    try:
        task_id = int(context.args[0])
        task = get_task_by_id(task_id, user_id)
        if not task:
            await update.message.reply_text(f"❌ Task [{task_id}] not found.")
            return
        set_editing(user_id, task_id)
        await update.message.reply_text(
            f"✏️ Editing *[{task_id}]*: {task[1]}\n\n"
            f"📅 {task[2] or 'No date'}  ⏰ {task[3] or 'No time'}  🏷 {task[4]}\n\n"
            f"Tell me what to change:\n"
            f"_'Set time to 6pm'_ | _'Move to tomorrow'_ | _'Change to Study'_",
            parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
        )
    except ValueError:
        await update.message.reply_text("Usage: /edit <id>")

async def memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    memories = get_all_memories(user_id)
    if not memories:
        await update.message.reply_text(
            "🧠 No memories stored yet!\n\n"
            "Tell me things to remember:\n"
            "_'Remember my exam is on June 20'_\n"
            "_'My favorite study time is 7 PM'_",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return
    msg = "🧠 *Your Memories:*\n\n"
    for key, val in memories:
        msg += f"• *{key}*: {val}\n"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks(update.message.from_user.id)
    await update.message.reply_text("📊 Analyzing...")
    result = analyze_productivity(tasks)
    await update.message.reply_text(f"📊 *Analysis:*\n\n{result}", parse_mode="Markdown", reply_markup=main_menu())

async def suggest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /suggest <goal>")
        return
    goal = " ".join(context.args)
    await update.message.reply_text("🧠 Generating suggestions...")
    result = suggest_tasks(goal)
    await update.message.reply_text(f"🎯 *Tasks for: {goal}*\n\n{result}", parse_mode="Markdown", reply_markup=main_menu())

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thinking = await update.message.reply_text("🔍 Running diagnostics...")
    result = check_api_status()
    if result["status"] == "online":
        rt = result.get("response_time_ms", 0)
        speed = "⚡ Fast" if rt < 1000 else "🐢 Slow" if rt > 3000 else "✅ Normal"
        text = (
            f"✅ *NVIDIA API — Online*\n\n"
            f"🤖 Model: `{result.get('model', 'llama-3.1-8b')}`\n"
            f"⏱ Response: {rt}ms ({speed})\n"
            f"🔁 Finish: {result.get('finish_reason', 'N/A')}\n\n"
            f"📊 *Tokens Used:*\n"
            f"   Prompt: {result['prompt_tokens']}\n"
            f"   Completion: {result['completion_tokens']}\n"
            f"   Total: {result['total_tokens']}\n\n"
            f"💳 *Free Tier Limits:*\n"
            f"   1,000 calls/month | 40 req/min\n\n"
            f"🔗 build.nvidia.com"
        )
    elif result["status"] == "rate_limited":
        text = "⚠️ *Rate Limited*\n\nWait 1-2 min. (40 req/min limit)"
    elif result["status"] == "invalid_key":
        text = "❌ *Invalid Key* — Update at build.nvidia.com"
    else:
        text = f"❌ *Error* — `{str(result.get('error','Unknown'))[:150]}`"
    await thinking.delete()
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu())


# ── Task executor ─────────────────────────────────────
async def execute_task_action(user_id: int, data: dict, update: Update):
    action = data.get("action", "create")

    if action == "create":
        title = data.get("title")
        date = data.get("date")
        if not title:
            await update.message.reply_text("❌ No task title. Please try again.", reply_markup=main_menu())
            return

        # Validate
        errors = validate_datetime(date, data.get("time"))
        if errors:
            await update.message.reply_text(
                f"{'  '.join(errors)}\n\nPlease correct and try again.",
                reply_markup=main_menu()
            )
            return

        if task_exists(user_id, title, date):
            matches2 = search_tasks_by_title(user_id, title or "")
            eid = matches2[0][0] if matches2 else "?"
            await update.message.reply_text(
                f"Task *{title}* is already saved as [{eid}]. "
                f"Use /done {eid} when complete!",
                parse_mode="Markdown", reply_markup=main_menu()
            )
            return

        # Recurrence
        rec = data.get("recurrence")
        rec_type = None
        rec_weekday = None
        rec_day = None
        if rec == "daily":
            rec_type = "daily"
        elif rec == "weekly":
            rec_type = "weekly"
        elif rec == "monthly":
            rec_type = "monthly"
            rec_day = data.get("recurrence_day", 1)

        task_id = add_task(
            user_id, title, date, data.get("time"),
            data.get("category", "General"), data.get("priority", "medium"),
            rec_type, rec_weekday, rec_day
        )

        rec_msg = f"\n🔄 Repeats: {rec}" if rec else ""
        await update.message.reply_text(
            f"✅ *Saved!*\n\n"
            f"📌 *{title}*\n"
            f"📅 {date or 'No date'}  ⏰ {data.get('time') or 'No time'}  🏷 {data.get('category', 'General')}"
            f"{rec_msg}\n\n"
            f"Use /done {task_id} when complete!",
            parse_mode="Markdown", reply_markup=main_menu()
        )

    elif action == "create_multiple":
        tasks = data.get("tasks", [])
        saved = []
        for task_data in tasks:
            title = task_data.get("title")
            date = task_data.get("date")
            if title and not task_exists(user_id, title, date):
                tid = add_task(user_id, title, date, task_data.get("time"),
                               task_data.get("category", "General"), "medium")
                saved.append(f"📌 *{title}* [{tid}]")
        if saved:
            await update.message.reply_text(
                f"✅ *{len(saved)} tasks saved!*\n\n" + "\n".join(saved),
                parse_mode="Markdown", reply_markup=main_menu()
            )
        else:
            await update.message.reply_text("⚠️ All tasks already exist.", reply_markup=main_menu())

    elif action == "create_subtasks":
        parent_id = data.get("parent_id")
        parent_date = data.get("parent_date")
        subtasks = data.get("subtasks", [])
        saved = []
        for st in subtasks:
            title = st.get("title")
            if not title:
                continue
            prio = st.get("priority", "medium")
            sub_id = add_subtask(user_id, parent_id, title,
                                 due_date=parent_date,
                                 category="General", priority=prio)
            saved.append(f"  [{sub_id}] {title}")
        if saved:
            await update.message.reply_text(
                f"✅ *{len(saved)} subtasks created!*\n\n" + "\n".join(saved) +
                f"\n\nThey're linked to task #{parent_id}.",
                parse_mode="Markdown", reply_markup=main_menu()
            )

    elif action == "delete":
        task_id = data.get("task_id")
        task = get_task_by_id(task_id, user_id)
        if task:
            delete_task(task_id, user_id)
            await update.message.reply_text(f"🗑 *Deleted:* {task[1]}", parse_mode="Markdown", reply_markup=main_menu())


# ── Main message handler ──────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_input = update.message.text.strip()
    state = get_state(user_id)

    logger.info(f"User {user_id} [{state}]: {user_input}")
    add_history(user_id, "user", user_input)

    # ── Menu buttons ──
    menu_map = {
        '📌 Add Task': lambda: ask_for_task(update, user_id),
        '📋 My Tasks': lambda: list_tasks(update, context),
        '📋 List Tasks': lambda: list_tasks(update, context),
        '📅 Today': lambda: today_tasks(update, context),
        '🗓 This Week': lambda: week_tasks(update, context),
        '📆 Overdue': lambda: overdue_cmd(update, context),
        '✅ Done': lambda: done_task(update, context),
        '🗑 Delete': lambda: delete_task_cmd(update, context),
        '✏️ Edit': lambda: edit_task_cmd(update, context),
        '📊 Analyze': lambda: analyze_cmd(update, context),
        '🧠 Memory': lambda: memory_cmd(update, context),
        '🔍 Status': lambda: status_cmd(update, context),
        '⚙️ Settings': lambda: settings_cmd(update, context),
        '❓ Help': lambda: help_command(update, context),
    }
    if user_input in menu_map:
        context.args = []
        await menu_map[user_input]()
        return

    # ── Confirming ──
    if state == "confirming":
        action_type, data = get_pending_action(user_id)
        am_pm = re.match(r"^(\d{1,2})\s*(AM|PM)$", user_input.upper())
        if am_pm:
            h2, period2 = int(am_pm.group(1)), am_pm.group(2)
            if period2 == "PM" and h2 != 12: h2 += 12
            elif period2 == "AM" and h2 == 12: h2 = 0
            data["time"] = str(h2).zfill(2) + ":00"
            update_context(user_id, {"pending_data": data})
            await update.message.reply_text(
                "Got it! " + user_input + "\n\n" + build_summary(data) + "\n\nShall I save this?",
                parse_mode="Markdown", reply_markup=yes_no_menu()
            )
            return
        if user_input.lower() == "skip time":
            clear_state(user_id)
            await execute_task_action(user_id, data, update)
            return
        positive = any(w in user_input.lower() for w in
                      ["yes", "yeah", "yep", "haan", "ha", "ok", "okay", "sure",
                       "✅", "save", "confirm", "bilkul", "do it", "kar do", "theek"])
        negative = any(w in user_input.lower() for w in
                      ["no", "nahi", "nope", "cancel", "❌", "mat", "don't", "dont", "band"])
        wants_time = any(w in user_input.lower() for w in
                        ["time", "waqt", "baje", "timing", "time?", "kitne"])
        parsed_time = parse_time_from_text(user_input)

        if positive:
            clear_state(user_id)
            await execute_task_action(user_id, data, update)
        elif negative:
            clear_state(user_id)
            await update.message.reply_text("❌ Cancelled!", reply_markup=main_menu())
        elif parsed_time:
            data["time"] = parsed_time
            update_context(user_id, {"pending_data": data})
            await update.message.reply_text(
                f"⏰ Updated to {parsed_time}!\n\n{build_summary(data)}\n\nShall I save this?",
                parse_mode="Markdown", reply_markup=yes_no_menu()
            )
        elif wants_time:
            await update.message.reply_text(
                f"⏰ What time for *{data.get('title')}*?\n_(e.g. 17:00, 5pm, 8 baje, or 'skip')_",
                parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
            )
        elif user_input.lower() == "skip":
            clear_state(user_id)
            await execute_task_action(user_id, data, update)
        else:
            await update.message.reply_text(
                f"Here's what I'll save:\n\n{build_summary(data)}\n\n"
                f"Say *yes* to save, *no* to cancel, or tell me what to change (e.g. 'set time to 5pm')",
                parse_mode="Markdown", reply_markup=yes_no_menu()
            )
        return

    # ── Editing ──
    if state == "editing":
        task_id = get_editing_id(user_id)
        if task_id:
            parsed = parse_all(user_input)
            result = get_jarvis_response(
                f"Modify task [{task_id}]. User: '{user_input}'",
                [], get_history(user_id)
            )
            entities = result.get("entities", {})
            if parsed["date"] and not entities.get("date"):
                entities["date"] = parsed["date"]
            if parsed["time"] and not entities.get("time"):
                entities["time"] = parsed["time"]
            direct_time = parse_time_from_text(user_input)
            if direct_time and not entities.get("time"):
                entities["time"] = direct_time

            update_task(task_id, user_id,
                title=entities.get("title"),
                due_date=entities.get("date"),
                due_time=entities.get("time"),
                category=entities.get("category"),
                priority=entities.get("priority")
            )
            task = get_task_by_id(task_id, user_id)
            clear_state(user_id)
            await update.message.reply_text(
                f"✅ *Updated!*\n\n📌 *{task[1]}*\n"
                f"📅 {task[2] or 'No date'}  ⏰ {task[3] or 'No time'}  🏷 {task[4]}",
                parse_mode="Markdown", reply_markup=main_menu()
            )
        else:
            clear_state(user_id)
        return

    # ── Gathering ──
    if state == "gathering":
        partial, missing = get_gathering(user_id)
        parsed = parse_all(user_input)
        result = get_jarvis_response(
            f"Context: {partial}. Need: {missing}. User: '{user_input}'",
            get_tasks(user_id), get_history(user_id)
        )
        entities = result.get("entities", {})

        # Merge parsed dates/times
        if parsed["date"] and not entities.get("date"):
            entities["date"] = parsed["date"]
        if parsed["time"] and not entities.get("time"):
            entities["time"] = parsed["time"]

        for k, v in entities.items():
            if v and not partial.get(k):
                partial[k] = v

        # Validate errors
        if parsed["errors"]:
            err_msg = "\n".join(parsed["errors"])
            await update.message.reply_text(
                f"{err_msg}\n\nPlease try again with a valid date/time.",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        if not partial.get("title"):
            set_gathering(user_id, partial, ["title"])
            # v3.0: smarter combined question
            if partial.get("date") and partial.get("time"):
                _ask = f"Got it! What task should I schedule for {partial['date']} at {partial['time']}?"
            elif partial.get("date"):
                _ask = f"What task should I set for {partial['date']}?"
            elif partial.get("time"):
                _ask = f"What should I remind you about at {partial['time']}?"
            else:
                _ask = "What task would you like to add? Tell me what and when!"
            await update.message.reply_text(_ask, reply_markup=ReplyKeyboardRemove())
        else:
            set_pending_action(user_id, "create_task", {
                "action": "create",
                "title": partial.get("title"),
                "date": partial.get("date"),
                "time": partial.get("time"),
                "category": partial.get("category", "General"),
                "priority": partial.get("priority", "medium"),
                "recurrence": partial.get("recurrence"),
            })
            await update.message.reply_text(
                f"Got it! Here's what I'll save:\n\n{build_summary(partial)}\n\nShall I save this?",
                parse_mode="Markdown", reply_markup=yes_no_menu()
            )
        return

    # ── Bug 10: answer "what time/date is it" directly with correct IST ──
    low = user_input.lower()
    if any(p in low for p in ["what time is it", "what's the time", "current time",
                               "time kya", "kitne baje", "abhi kitne",
                               "what is the time", "what date", "today's date",
                               "what day is it", "aaj kya"]):
        n = datetime.now(IST)
        await update.message.reply_text(
            f"🕐 It's *{n.strftime('%I:%M %p')}* on *{n.strftime('%A, %d %B %Y')}* (IST).",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return


    # ── v3.1 Bug 17: natural-language commands without slash ─────────
    _low_full = user_input.lower().strip()
    # v3.2: Routes to /forget — DELETE intent might confuse memories with tasks
    _low_strip = user_input.lower().strip()
    if (_low_strip.startswith("forget ")
        or _low_strip.startswith("delete memory ")
        or _low_strip.startswith("remove memory ")
        or _low_strip.startswith("delete remembered ")
        or _low_strip.startswith("remove remembered ")):
        # Extract the key (everything after the trigger phrase)
        for trigger in ["forget ", "delete memory ", "remove memory ",
                        "delete remembered ", "remove remembered "]:
            if _low_strip.startswith(trigger):
                key_to_forget = user_input[len(trigger):].strip()
                context.args = key_to_forget.split() if key_to_forget else []
                await forget_cmd(update, context)
                return

    _command_phrases = {
        ("plan my day", "plan today", "what should i do today", "today's plan",
         "schedule my day", "make a plan"): plan_cmd,
        ("plan my week", "plan this week", "weekly plan", "week ahead"): plan_cmd,
        ("am i overloaded", "show overload", "load check", "busy days"): overload_cmd,
        ("show bugs", "list bugs", "view bugs", "what bugs"): bugs_cmd,
        ("show settings", "my settings", "view settings"): settings_cmd,
        ("show overdue", "my overdue", "what is overdue"): overdue_cmd,
        ("show deadlines", "my deadlines", "what deadlines"): deadlines_cmd,
        ("show memory", "show memories", "my memories", "what do you remember"): memory_cmd,
        ("show paused", "paused tasks"): paused_cmd,
        ("api status", "check status", "is api working", "is the bot online"): status_cmd,
        ("self test", "run tests", "run self test"): selftest_cmd,
        ("show help", "what can you do", "help me", "guide me"): help_command,
        ("turn on debug", "enable debug", "debug mode on"): debug_cmd,
        ("turn off debug", "disable debug", "debug mode off"): debug_cmd,
        ("trace this", "what did you understand", "what was my last message"): trace_cmd,
        ("carry forward", "move overdue to today"): carryforward_cmd,
    }
    for phrases, _handler in _command_phrases.items():
        if any(p in _low_full for p in phrases):
            # set context.args based on the phrase matched
            context.args = []
            if _handler == plan_cmd:
                if "week" in _low_full or "weekly" in _low_full:
                    context.args = ["week"]
                else:
                    context.args = ["today"]
            await _handler(update, context)
            return

    # ── Quick-match VIEW requests so LLM can't misclassify them as TASK ──
    _low = user_input.lower()
    _view_words = ["show", "list", "dikhao", "batao", "what do i have", "overdue", "deadline",
                   "what's pending", "my tasks", "mera task", "mere task",
                   "show plan", "show schedule", "kya hai aaj", "aaj kya hai",
                   "what is scheduled", "what are my tasks"]
    _period_words = {
        "today": ["today", "aaj", "aj"],
        "tomorrow": ["tomorrow", "kal"],
        "week": ["week", "hafte", "this week"],
        "month": ["month", "mahine", "this month"],
        "year": ["year", "saal", "this year"],
    }
    if any(vw in _low for vw in _view_words):
        _period = "all"
        for p, words in _period_words.items():
            if any(w in _low for w in words):
                _period = p
                break
        if _period == "today":
            tasks = get_tasks_by_date(user_id, datetime.now(IST).strftime("%Y-%m-%d"))
            label = f"Today ({datetime.now(IST).strftime('%Y-%m-%d')})"
        elif _period == "tomorrow":
            tmrw = (datetime.now(IST) + timedelta(days=1)).strftime("%Y-%m-%d")
            tasks = get_tasks_by_date(user_id, tmrw)
            label = f"Tomorrow ({tmrw})"
        elif _period == "week":
            n = datetime.now(IST)
            tasks = get_tasks_by_week(user_id, n.strftime("%Y-%m-%d"),
                                      (n + timedelta(days=7)).strftime("%Y-%m-%d"))
            label = "This Week"
        elif _period == "month":
            n = datetime.now(IST)
            tasks = get_tasks_by_week(user_id, n.strftime("%Y-%m-%d"),
                                      (n + timedelta(days=30)).strftime("%Y-%m-%d"))
            label = "This Month"
        elif _period == "year":
            n = datetime.now(IST)
            tasks = get_tasks_by_week(user_id, n.strftime("%Y-%m-%d"),
                                      f"{n.year}-12-31")
            label = "This Year"
        else:
            tasks = get_tasks(user_id)
            label = "All Pending"
        await update.message.reply_text(
            format_tasks(tasks, label), parse_mode="Markdown", reply_markup=main_menu()
        )
        return

    # ── Idle — JARVIS ──
    now = datetime.now(IST)
    parsed = parse_all(user_input, now)
    memories = get_all_memories(user_id)
    existing_tasks = get_tasks(user_id)

    result = get_jarvis_response(user_input, existing_tasks, get_history(user_id), memories)
    intent = result.get("intent", "CHAT").upper()
    entities = result.get("entities", {})
    missing = result.get("missing", [])
    needs_confirm = result.get("needs_confirm", False)
    response_text = result.get("response", "")
    confirm_summary = result.get("confirm_summary")

    # Merge local parser results — ONLY for task-like intents.
    # Bug 13: don't let a stray "today" in casual chat turn CHAT into a task.
    if intent in ["TASK", "EDIT", "MULTIPLE"]:
        # Bug 14 + 19b: if user said "in N min/hour" or "after N min/hour"
        # parser's resolved time MUST win — AI often interprets "1" as 01:00.
        _has_relative_time = bool(re.search(
            r"\b(in|after)\s+\d+\s+(min|minute|mins|minutes|hour|hours|hr|hrs)\b",
            user_input.lower()
        ))
        ai_time = entities.get("time", "")
        if _has_relative_time and parsed.get("time"):
            entities["time"] = parsed["time"]
        elif ai_time and not re.match(r"^\d{2}:\d{2}$", ai_time):
            entities["time"] = None
        if parsed["date"] and not entities.get("date"):
            entities["date"] = parsed["date"]
        if parsed["time"] and not entities.get("time"):
            entities["time"] = parsed["time"]
        if parsed["recurrence"] and not entities.get("recurrence"):
            entities["recurrence"] = parsed["recurrence"]["type"]
        # v3.0: use urgency-detected priority if AI didn't set one
        if parsed.get("priority") and not entities.get("priority"):
            entities["priority"] = parsed["priority"]

    logger.info(f"Intent:{intent} | Entities:{entities} | Missing:{missing}")
    add_history(user_id, "assistant", response_text)
    dbg.log_interaction(user_id, user_input, intent, entities, response_text)
    if dbg.is_debug_on(user_id):
        import json as _json
        await update.message.reply_text(
            f"\U0001f41e *Debug*\n"
            f"Intent: `{intent}`\n"
            f"Entities: `{_json.dumps(entities, ensure_ascii=False)}`\n"
            f"Date parsed: `{parsed.get('date')}` Time: `{parsed.get('time')}` "
            f"Ambiguous: `{parsed.get('time_ambiguous')}`",
            parse_mode="Markdown"
        )

    # ── Handle parse errors first ──
    if parsed["errors"] and intent in ["TASK", "EDIT", "MULTIPLE"]:
        # past date or invalid time — only warn when actually making a task
        await update.message.reply_text(
            "  ".join(parsed["errors"]) + "\n\nPlease give me a valid future date/time.",
            reply_markup=main_menu()
        )
        return

    if intent == "VIEW":
        period = result.get("view_period", "today")
        if period == "month":
            tasks = get_tasks_by_week(user_id,
                now.strftime("%Y-%m-%d"),
                (now + timedelta(days=30)).strftime("%Y-%m-%d"))
            await update.message.reply_text(
                format_tasks(tasks, "This Month"),
                parse_mode="Markdown", reply_markup=main_menu()
            )
            return
        if period == "tomorrow":
            target = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            tasks = get_tasks_by_date(user_id, target)
            label = f"Tomorrow ({target})"
        elif period == "week":
            tasks = get_tasks_by_week(user_id, now.strftime("%Y-%m-%d"),
                                      (now + timedelta(days=7)).strftime("%Y-%m-%d"))
            label = "This Week"
        elif period == "year":
            tasks = get_tasks_by_week(user_id, now.strftime("%Y-%m-%d"), f"{now.year}-12-31")
            label = "This Year"
        elif period == "all":
            tasks = get_tasks(user_id)
            label = "All Pending"
        else:
            target = now.strftime("%Y-%m-%d")
            tasks = get_tasks_by_date(user_id, target)
            label = f"Today ({target})"
        await update.message.reply_text(
            format_tasks(tasks, label), parse_mode="Markdown", reply_markup=main_menu()
        )

    elif intent == "MULTIPLE":
        tasks_list = result.get("tasks", [])
        if not tasks_list:
            set_gathering(user_id, entities, ["title"])
            await update.message.reply_text(response_text or "What task would you like to add?",
                reply_markup=ReplyKeyboardRemove())
            return
        # Merge parsed date into all tasks; parse per-task time from title text
        from date_parser import parse_time as _pt
        for t in tasks_list:
            if not t.get("date") and parsed["date"]:
                t["date"] = parsed["date"]
            if not t.get("time"):
                # try to pull a time out of this task's own title
                tt, _, _ = _pt(t.get("title", ""), now)
                if tt:
                    t["time"] = tt

        summary = "*Multiple tasks detected:*\n\n"
        for i, t in enumerate(tasks_list, 1):
            summary += f"{i}. 📌 *{t.get('title')}* — 📅 {t.get('date') or 'No date'} ⏰ {t.get('time') or 'No time'}\n"
        summary += "\nShall I save all of these?"
        set_pending_action(user_id, "create_multiple", {
            "action": "create_multiple", "tasks": tasks_list
        })
        await update.message.reply_text(summary, parse_mode="Markdown", reply_markup=yes_no_menu())

    elif intent == "TASK":
        # Bug 7: recurring tasks don't need a specific date
        if entities.get("recurrence") and "date" in (missing or []):
            missing = [m for m in missing if m != "date"]

        # Bug 12: a title that is just the reminder phrasing is NOT a real title
        _title = (entities.get("title") or "").strip().lower()
        _bad_titles = ["remind me", "remind", "yaad dila dena", "yaad dila",
                       "reminder", "set reminder", "task", "schedule task",
                       "remind me in", "remind me to"]
        title_is_real = bool(_title) and _title not in _bad_titles and len(_title) > 2
        if not title_is_real:
            entities["title"] = None
            if "title" not in (missing or []):
                missing = (missing or []) + ["title"]

        if parsed.get("time_ambiguous") and entities.get("title"):
            raw_h = parsed["time"].split(":")[0] if parsed.get("time") else "?"
            set_pending_action(user_id, "create_task", {
                "action": "create",
                "title": entities.get("title"),
                "date": entities.get("date") or parsed.get("date"),
                "time": None,
                "category": entities.get("category", "General"),
                "priority": entities.get("priority", "medium"),
            })
            await update.message.reply_text(
                "Did you mean " + raw_h + " AM (morning) or " + raw_h + " PM (evening)?",
                reply_markup=ReplyKeyboardMarkup(
                    [[raw_h + " AM", raw_h + " PM", "Skip time"]],
                    one_time_keyboard=True, resize_keyboard=True
                )
            )
            return
        if not entities.get("title") or missing:
            set_gathering(user_id, entities, missing or ["title"])
            await update.message.reply_text(
                response_text or "What task would you like to add?",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            summary_data = {
                "title": entities.get("title"),
                "date": entities.get("date"),
                "time": entities.get("time"),
                "category": entities.get("category", "General"),
                "recurrence": entities.get("recurrence"),
            }
            set_pending_action(user_id, "create_task", {
                "action": "create", **summary_data,
                "priority": entities.get("priority", "medium"),
            })
            summary = confirm_summary or build_summary(summary_data)
            await update.message.reply_text(
                f"Got it! Here's what I'll save:\n\n{summary}\n\nShall I save this?",
                parse_mode="Markdown", reply_markup=yes_no_menu()
            )

    elif intent == "DELETE":
        task_id = result.get("task_id")
        title = entities.get("title")
        # Bug 19: safe int conversion — LLM may return non-numeric task_id for memory keys etc.
        try:
            tid_int = int(task_id) if task_id is not None else None
        except (ValueError, TypeError):
            tid_int = None
        if tid_int is not None:
            task = get_task_by_id(tid_int, user_id)
            if task:
                set_pending_action(user_id, "delete_task", {"action": "delete", "task_id": tid_int})
                await update.message.reply_text(
                    f"🗑 Delete *{task[1]}*?\nConfirm?",
                    parse_mode="Markdown", reply_markup=yes_no_menu()
                )
            else:
                await update.message.reply_text("❌ Task not found. Use /list.", reply_markup=main_menu())
        elif title:
            matches = search_tasks_by_title(user_id, title)
            if len(matches) == 1:
                set_pending_action(user_id, "delete_task", {"action": "delete", "task_id": matches[0][0]})
                await update.message.reply_text(
                    f"🗑 Delete *{matches[0][1]}*?\nConfirm?",
                    parse_mode="Markdown", reply_markup=yes_no_menu()
                )
            elif len(matches) > 1:
                msg = "🗑 *Multiple matches:*\n\n"
                for t in matches:
                    msg += f"*[{t[0]}]* {t[1]}\n"
                msg += "\nUse /delete <id>"
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
            else:
                await update.message.reply_text("❌ Task not found. Use /list.", reply_markup=main_menu())
        else:
            await update.message.reply_text(response_text, reply_markup=main_menu())

    elif intent == "EDIT":
        task_id = result.get("task_id")
        title = entities.get("title")
        if not task_id and title:
            matches = search_tasks_by_title(user_id, title)
            if matches:
                task_id = str(matches[0][0])
        # Bug 19: safe int conversion for EDIT
        try:
            edit_tid = int(task_id) if task_id is not None else None
        except (ValueError, TypeError):
            edit_tid = None
        if edit_tid is not None:
            update_task(edit_tid, user_id,
                due_date=entities.get("date"),
                due_time=entities.get("time"),
                category=entities.get("category"),
                priority=entities.get("priority")
            )
            task = get_task_by_id(edit_tid, user_id)
            await update.message.reply_text(
                f"✅ *Updated!*\n\n📌 *{task[1]}*\n"
                f"📅 {task[2] or 'No date'}  ⏰ {task[3] or 'No time'}  🏷 {task[4]}",
                parse_mode="Markdown", reply_markup=main_menu()
            )
        else:
            await update.message.reply_text(
                "❌ Couldn't find that task. Use /list then /edit <id>", reply_markup=main_menu())

    elif intent == "MEMORY_SAVE":
        key, value = extract_memory_key(user_input)
        if key and value:
            save_memory(user_id, key, value)
            await update.message.reply_text(
                f"🧠 *Remembered!*\n\n*{key}*: {value}",
                parse_mode="Markdown", reply_markup=main_menu()
            )
        else:
            await update.message.reply_text(
                "What would you like me to remember? Try:\n_'Remember that my exam is June 20'_",
                parse_mode="Markdown", reply_markup=main_menu()
            )

    elif intent == "MEMORY_GET":
        query = result.get("memory_key") or entities.get("title") or user_input
        results = search_memories(user_id, query)
        if results:
            msg = "🧠 *Found in memory:*\n\n"
            for k, v in results:
                msg += f"• *{k}*: {v}\n"
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
        else:
            all_mem = get_all_memories(user_id)
            if all_mem:
                msg = "🧠 *All your memories:*\n\n"
                for k, v in all_mem:
                    msg += f"• *{k}*: {v}\n"
                await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
            else:
                await update.message.reply_text(
                    "🧠 No memories stored yet. Tell me things to remember!",
                    reply_markup=main_menu()
                )

    elif intent == "PLAN":
        # v4.0: route to /plan command with smart period detection
        period = "week" if any(w in user_input.lower() for w in ["week", "hafte", "weekly"]) else "today"
        context.args = [period]
        await plan_cmd(update, context)

    elif intent == "GOAL":
        title = entities.get("title") or user_input
        deadline = entities.get("date")
        add_goal(user_id, title, deadline)
        await update.message.reply_text(
            f"🎯 *Goal set!*\n\n*{title}*\n"
            f"📅 Deadline: {deadline or 'No deadline'}\n\n"
            f"Want me to break this into tasks? Just ask!",
            parse_mode="Markdown", reply_markup=main_menu()
        )

    elif intent == "HABIT":
        # v3.0: offer to set up recurring task for habit requests
        title = entities.get("title") or user_input
        recurrence = entities.get("recurrence") or "daily"
        time_val = entities.get("time") or parsed.get("time")
        set_pending_action(user_id, "create_task", {
            "action": "create",
            "title": title,
            "date": None,
            "time": time_val,
            "category": entities.get("category", "Health"),
            "priority": entities.get("priority", "medium"),
            "recurrence": recurrence,
        })
        await update.message.reply_text(
            f"💪 *Setting up a habit!*\n\n"
            f"🔁 *{title}*\n"
            f"🔄 Repeats: {recurrence}\n"
            f"⏰ Time: {time_val or 'No time set'}\n\n"
            f"Shall I save this?",
            parse_mode="Markdown", reply_markup=yes_no_menu()
        )

    else:
        await update.message.reply_text(f"🤖 {response_text}", reply_markup=main_menu())


async def ask_for_task(update, user_id):
    clear_state(user_id)
    set_gathering(user_id, {}, ["title"])
    await update.message.reply_text(
        "📌 What task would you like to add?\nJust describe it naturally!",
        reply_markup=ReplyKeyboardRemove()
    )



# ── DEBUG SYSTEM COMMANDS (v1.0) ──────────────────────
async def debug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    on = dbg.toggle_debug(user_id)
    await update.message.reply_text(
        f"🐞 Debug mode is now *{'ON' if on else 'OFF'}*.\n"
        + ("I'll show you the detected intent and entities after each message."
           if on else "Back to normal responses."),
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            "🐞 *Report a bug*\nUsage: /report <what went wrong>\n"
            "Example: /report it saved 3 baje as 3 AM instead of asking",
            parse_mode="Markdown"
        )
        return
    desc = " ".join(context.args)
    bug_id = dbg.report_bug(user_id, desc)
    await update.message.reply_text(
        f"✅ Bug #{bug_id} saved with full context!\n"
        f"I captured your last message and what I understood from it.\n"
        f"Use /bugs to see all reports.",
        reply_markup=main_menu()
    )

async def bugs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    bugs = dbg.get_open_bugs(user_id)
    if not bugs:
        await update.message.reply_text("🎉 No open bugs!", reply_markup=main_menu())
        return
    msg = "🐞 *Open Bugs:*\n\n"
    for b in bugs:
        icon = "💥" if b[1] == "auto_exception" else "📝"
        msg += f"{icon} *#{b[0]}* — {b[2][:60]}\n"
        if b[3]:
            msg += f"     _on: {b[3][:50]}_\n"
        msg += "\n"
    msg += "Use /resolve <id> to close one."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())

async def resolve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /resolve <bug_id>")
        return
    try:
        bug_id = int(context.args[0])
        if dbg.resolve_bug(bug_id):
            await update.message.reply_text(f"✅ Bug #{bug_id} marked resolved!", reply_markup=main_menu())
        else:
            await update.message.reply_text(f"❌ Bug #{bug_id} not found.")
    except ValueError:
        await update.message.reply_text("Usage: /resolve <number>")

async def trace_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    trace = dbg.get_last_trace(user_id)
    if not trace:
        await update.message.reply_text("No interaction traced yet. Send a message first.")
        return
    import json as _json
    await update.message.reply_text(
        f"🔍 *Last Interaction Trace:*\n\n"
        f"📥 You said: `{trace['user_input']}`\n"
        f"🎯 Intent: `{trace['intent']}`\n"
        f"📦 Entities:\n`{_json.dumps(trace['entities'], indent=2, ensure_ascii=False)}`\n"
        f"📤 Reply: {trace['response'][:200]}\n"
        f"🕐 Time: {trace['time']}",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def selftest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧪 *Self-Test Checklist*\n\n"
        "Send each of these messages one by one and check the result.\n"
        "If any behaves wrong, reply with /report <what went wrong>.\n",
        parse_mode="Markdown"
    )
    msg = "*Test messages to try:*\n\n"
    for i, (test_msg, expected) in enumerate(dbg.SELFTEST_MESSAGES, 1):
        msg += f"{i}. `{test_msg}`\n     ✓ _{expected}_\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())



# ── v1.1: Inline button callback handler ──────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    parts = data.split(":")
    action = parts[0]
    task_id = int(parts[1]) if len(parts) > 1 else None

    if action == "done":
        task = get_task_by_id(task_id, user_id)
        if task:
            mark_done(task_id, user_id)
            await query.edit_message_text(
                f"✅ *Done!* Completed:\n📌 {task[1]}",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("❌ Task not found.")

    elif action == "snooze":
        minutes = int(parts[2]) if len(parts) > 2 else 10
        from datetime import datetime as _dt, timedelta as _td
        snooze_until = (_dt.now(IST) + _td(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
        snooze_task(task_id, user_id, snooze_until)
        label = f"{minutes} minutes" if minutes < 60 else "1 hour"
        await query.edit_message_text(
            f"⏰ Snoozed for {label}. I'll remind you again at {snooze_until.split()[1]}.",
        )

    elif action == "postpone":
        from datetime import datetime as _dt, timedelta as _td
        tomorrow = (_dt.now(IST) + _td(days=1)).strftime("%Y-%m-%d")
        postpone_task(task_id, user_id, tomorrow)
        task = get_task_by_id(task_id, user_id)
        await query.edit_message_text(
            f"📅 Moved to tomorrow ({tomorrow}).\n📌 {task[1] if task else ''}",
        )

    elif action == "pause":
        pause_task(task_id, user_id)
        await query.edit_message_text("⏸ Task paused. Reminders stopped until you resume it.")

    elif action == "resume":
        resume_task(task_id, user_id)
        await query.edit_message_text("▶️ Task resumed. Reminders are back on.")

    elif action == "stoprem":
        task = get_task_by_id(task_id, user_id)
        if task:
            stop_reminders(task_id, user_id)
            await query.edit_message_text(
                f"🔕 Reminders stopped for *{task[1]}*\n"
                f"Task still in your list but won't ping you again.\n"
                f"Use /resume {task_id} to turn back on.",
                parse_mode="Markdown"
            )

    elif action == "deltask":
        task = get_task_by_id(task_id, user_id)
        if task:
            delete_task(task_id, user_id)
            await query.edit_message_text(
                f"🗑 Deleted: *{task[1]}*",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("❌ Task not found.")


# ── v1.1: Pause / Resume commands ─────────────────────
async def pause_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("Usage: /pause <task_id>")
        return
    try:
        tid = int(context.args[0])
        task = get_task_by_id(tid, user_id)
        if not task:
            await update.message.reply_text(f"❌ Task [{tid}] not found.")
            return
        pause_task(tid, user_id)
        await update.message.reply_text(
            f"⏸ Paused: *{task[1]}*\nReminders stopped. Use /resume {tid} to turn back on.",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    except ValueError:
        await update.message.reply_text("Usage: /pause <number>")

async def resume_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("Usage: /resume <task_id>")
        return
    try:
        tid = int(context.args[0])
        task = get_task_by_id(tid, user_id)
        if not task:
            await update.message.reply_text(f"❌ Task [{tid}] not found.")
            return
        resume_task(tid, user_id)
        await update.message.reply_text(
            f"▶️ Resumed: *{task[1]}*\nReminders are back on.",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    except ValueError:
        await update.message.reply_text("Usage: /resume <number>")

async def paused_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    tasks = get_paused_tasks(user_id)
    if not tasks:
        await update.message.reply_text("No paused tasks.", reply_markup=main_menu())
        return
    msg = "⏸ *Paused Tasks:*\n\n"
    for t in tasks:
        msg += f"*[{t[0]}]* {t[1]} — 📅 {t[2] or 'No date'}\n"
    msg += "\nUse /resume <id> to reactivate."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())



# ── v1.2: Overdue / Deadline / Tag commands ───────────
async def overdue_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    n = datetime.now(IST)
    tasks = get_overdue_tasks(user_id, n.strftime("%Y-%m-%d"), n.strftime("%H:%M"))
    if not tasks:
        await update.message.reply_text("✅ No overdue tasks!", reply_markup=main_menu())
        return
    msg = "⚠️ *Overdue Tasks:*\n\n"
    for t in tasks:
        msg += f"🔴 *[{t[0]}]* {t[1]}\n"
        msg += f"      📅 {t[2]} ⏰ {t[3] or 'No time'}\n\n"
    msg += "Use /done <id> to complete or /carryforward to move all to today."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())

async def carryforward_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    today = datetime.now(IST).strftime("%Y-%m-%d")
    count = carry_forward_overdue(user_id, today)
    if count > 0:
        await update.message.reply_text(
            f"📅 Moved {count} overdue task(s) to today ({today}).",
            reply_markup=main_menu()
        )
    else:
        await update.message.reply_text("✅ No overdue tasks to carry forward!", reply_markup=main_menu())

async def deadlines_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    today = datetime.now(IST).strftime("%Y-%m-%d")
    tasks = get_upcoming_deadlines(user_id, today, days_ahead=3)
    if not tasks:
        await update.message.reply_text("✅ No upcoming deadlines in the next 3 days!", reply_markup=main_menu())
        return
    msg = "🔥 *Upcoming Deadlines (next 3 days):*\n\n"
    for t in tasks:
        days_left = (datetime.strptime(t[2], "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days
        urgency = "🔴 TODAY" if days_left == 0 else f"🟡 {days_left}d left" if days_left == 1 else f"🟢 {days_left}d left"
        msg += f"{urgency} *[{t[0]}]* {t[1]}\n"
        msg += f"      📅 {t[2]} ⏰ {t[3] or 'No time'}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())

async def tag_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "🏷 *Tags*\n\n"
            "Add tags: /tag <task_id> <tag1> <tag2> ...\n"
            "Example: /tag 5 exam urgent\n\n"
            "View by tag: /tagged <tag>\n"
            "Example: /tagged exam",
            parse_mode="Markdown"
        )
        return
    try:
        tid = int(context.args[0])
        tags = " ".join(context.args[1:]).lower()
        task = get_task_by_id(tid, user_id)
        if not task:
            await update.message.reply_text(f"❌ Task [{tid}] not found.")
            return
        set_tags(tid, user_id, tags)
        await update.message.reply_text(
            f"🏷 Tags set for *{task[1]}*: `{tags}`",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    except ValueError:
        await update.message.reply_text("Usage: /tag <task_id> <tags>")

async def tagged_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("Usage: /tagged <tag>\nExample: /tagged exam")
        return
    tag = context.args[0].lower()
    tasks = get_tasks_by_tag(user_id, tag)
    if not tasks:
        await update.message.reply_text(f"No tasks tagged with \"{tag}\".", reply_markup=main_menu())
        return
    msg = f"🏷 *Tasks tagged \"{tag}\":*\n\n"
    for t in tasks:
        msg += f"*[{t[0]}]* {t[1]} — 📅 {t[2] or 'No date'} 🏷 `{t[6] or ''}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())


# ── v2.0: Passive PA Commands ─────────────────────────
async def quiethours_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        prefs = get_user_prefs(user_id)
        await update.message.reply_text(
            f"🌙 *Quiet Hours*\n\n"
            f"Currently: *{prefs['quiet_start']} — {prefs['quiet_end']}* IST\n"
            f"No reminders during this time.\n\n"
            f"Change: /quiethours <start> <end>\n"
            f"Example: /quiethours 22:00 06:00\n"
            f"Disable: /quiethours off",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return
    if context.args[0].lower() == "off":
        set_quiet_hours(user_id, "00:00", "00:00")
        await update.message.reply_text("🔔 Quiet hours disabled. Reminders will come anytime.",
            reply_markup=main_menu())
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /quiethours <start> <end>\nExample: /quiethours 23:00 07:00")
        return
    start, end = context.args[0], context.args[1]
    set_quiet_hours(user_id, start, end)
    await update.message.reply_text(
        f"🌙 Quiet hours set: *{start} — {end}* IST\nNo reminders during this window.",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    prefs = get_user_prefs(user_id)
    is_quiet = is_quiet_hours(user_id)
    await update.message.reply_text(
        f"⚙️ *Your Settings*\n\n"
        f"🌙 Quiet hours: *{prefs['quiet_start']} — {prefs['quiet_end']}*"
        f" {'(active now 🔕)' if is_quiet else '(inactive 🔔)'}\n"
        f"🔁 Reminder interval: *{prefs['interval']} min*\n"
        f"📊 Max reminders per task: *{prefs['max_reminders']}*\n\n"
        f"*Change settings:*\n"
        f"/quiethours <start> <end>\n"
        f"/interval <minutes> — change reminder repeat interval",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def interval_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        prefs = get_user_prefs(user_id)
        await update.message.reply_text(
            f"🔁 Current reminder interval: *{prefs['interval']} min*\n"
            f"Change: /interval <minutes>\nExample: /interval 15",
            parse_mode="Markdown"
        )
        return
    try:
        mins = int(context.args[0])
        if mins < 5:
            await update.message.reply_text("Minimum interval is 5 minutes.")
            return
        set_reminder_interval(user_id, mins)
        await update.message.reply_text(
            f"🔁 Reminder interval set to *{mins} minutes*.",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    except ValueError:
        await update.message.reply_text("Usage: /interval <number>")


# ── v2.1: Stop reminder / delete reminder commands ────
async def stopreminder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        tasks = get_tasks(user_id)
        pending = [t for t in tasks if t[3]]  # tasks with a due_time
        if not pending:
            await update.message.reply_text(
                "No tasks with active reminders.",
                reply_markup=main_menu()
            )
            return
        msg = "🔕 *Stop reminders for which task?*\n"
        msg += "Reply: /stopreminder <id>\n\n"
        for t in pending:
            msg += f"*[{t[0]}]* {t[1]} — ⏰ {t[3]}\n"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
        return
    try:
        tid = int(context.args[0])
        task = get_task_by_id(tid, user_id)
        if not task:
            await update.message.reply_text(f"❌ Task [{tid}] not found.")
            return
        stop_reminders(tid, user_id)
        await update.message.reply_text(
            f"🔕 Reminders stopped for *{task[1]}*\n"
            f"Task still exists. Use /resume {tid} to turn back on.",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    except ValueError:
        await update.message.reply_text("Usage: /stopreminder <task_id>")

async def delreminder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias — delete a task entirely via /delreminder <id>"""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            "🗑 *Delete a task entirely:*\n"
            "Usage: /delreminder <id>\n\n"
            "Or use /stopreminder <id> to keep the task but stop the pings.",
            parse_mode="Markdown"
        )
        return
    try:
        tid = int(context.args[0])
        task = get_task_by_id(tid, user_id)
        if not task:
            await update.message.reply_text(f"❌ Task [{tid}] not found.")
            return
        delete_task(tid, user_id)
        await update.message.reply_text(
            f"🗑 Deleted: *{task[1]}*",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    except ValueError:
        await update.message.reply_text("Usage: /delreminder <task_id>")


# ── v3.1: Forget memory command ───────────────────────
async def forget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        mems = get_all_memories(user_id)
        if not mems:
            await update.message.reply_text("Nothing to forget — your memory is empty.",
                reply_markup=main_menu())
            return
        msg = "\U0001f9e0 *Which memory should I forget?*\nReply: /forget <key>\n\n"
        for k, v in mems:
            msg += f"\u2022 *{k}*: {v[:50]}\n"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
        return
    key = " ".join(context.args).lower().strip()
    value = get_memory(user_id, key)
    if value is None:
        # Try fuzzy match — find any key containing this word
        mems = get_all_memories(user_id)
        matches = [(k, v) for k, v in mems if key in k.lower() or key in v.lower()]
        if not matches:
            await update.message.reply_text(f"\u274c No memory found matching '{key}'.",
                reply_markup=main_menu())
            return
        if len(matches) > 1:
            msg = f"\U0001f9e0 Multiple matches for '{key}':\n\n"
            for k, v in matches:
                msg += f"\u2022 *{k}*\n"
            msg += "\nBe more specific: /forget <exact key>"
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
            return
        key = matches[0][0]
    try:
        delete_memory(user_id, key)
        # Verify deletion
        verify = get_memory(user_id, key)
        if verify is not None:
            await update.message.reply_text(
                f"⚠️ Tried to forget *{key}* but it's still there.\n"
                f"This might be a database issue — try /report to log it.",
                parse_mode="Markdown", reply_markup=main_menu()
            )
            return
        await update.message.reply_text(
            f"\U0001f5d1 Forgot: *{key}*",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Couldn't forget *{key}*: {str(e)[:100]}",
            parse_mode="Markdown", reply_markup=main_menu()
        )


# ── v3.1: Custom snooze command ───────────────────────
async def snooze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if len(context.args) < 2:
        await update.message.reply_text(
            "\u23f0 *Custom snooze*\n\n"
            "Usage: /snooze <task_id> <minutes>\n"
            "Example: /snooze 5 45 \u2014 snooze task #5 for 45 minutes\n\n"
            "Or tap the snooze buttons on any reminder for 10m / 1h.",
            parse_mode="Markdown"
        )
        return
    try:
        tid = int(context.args[0])
        minutes = int(context.args[1])
        if minutes < 1 or minutes > 1440:
            await update.message.reply_text("Snooze duration must be 1-1440 minutes (24 hours max).")
            return
        task = get_task_by_id(tid, user_id)
        if not task:
            await update.message.reply_text(f"\u274c Task [{tid}] not found.")
            return
        from datetime import timedelta as _td
        snooze_until = (datetime.now(IST) + _td(minutes=minutes)).strftime("%Y-%m-%d %H:%M")
        snooze_task(tid, user_id, snooze_until)
        h = minutes // 60
        m = minutes % 60
        label = f"{h}h {m}m" if h else f"{m}m"
        await update.message.reply_text(
            f"\u23f0 Snoozed *{task[1]}* for {label}.\nI'll remind you at {snooze_until.split()[1]}.",
            parse_mode="Markdown", reply_markup=main_menu()
        )
    except ValueError:
        await update.message.reply_text("Usage: /snooze <task_id> <minutes>")


# ── v3.3: Reminder diagnostic command ─────────────────
async def checktasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Diagnose why reminders may not be firing."""
    user_id = update.message.from_user.id
    import sqlite3
    conn = sqlite3.connect("planner.db")
    c = conn.cursor()
    c.execute("""SELECT id, title, due_date, due_time, done, paused,
                 snooze_until, last_reminded, reminder_count
                 FROM tasks WHERE user_id=? AND done=0
                 ORDER BY due_date, due_time""", (user_id,))
    tasks = c.fetchall()
    conn.close()
    if not tasks:
        await update.message.reply_text("No active tasks.", reply_markup=main_menu())
        return
    now = datetime.now(IST)
    current_dt = now.strftime("%Y-%m-%d %H:%M")
    msg = f"\U0001f50d *Task Diagnostics* (now: {current_dt})\n\n"
    for t in tasks:
        tid, title, dd, dt_, done, paused, snz, last_r, rcnt = t
        msg += f"*[{tid}]* {title}\n"
        msg += f"  \U0001f4c5 {dd or 'no date'} \u23f0 {dt_ or 'no time'}\n"
        if paused:
            msg += f"  \u23f8 PAUSED — no reminders\n"
        if snz:
            status = "\u23f0 active" if snz > current_dt else "\u26a0\ufe0f EXPIRED (should fire!)"
            msg += f"  \U0001f4a4 Snooze until: {snz} [{status}]\n"
        if last_r:
            msg += f"  \U0001f4ec Last reminded: {last_r}\n"
        msg += f"  \U0001f504 Reminders sent: {rcnt or 0}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())


# ── v4.0: Smart Planning Commands ─────────────────────
async def plan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a time-blocked daily or weekly plan."""
    user_id = update.message.from_user.id
    period = (context.args[0].lower() if context.args else "today")
    now = datetime.now(IST)

    if period in ("week", "weekly"):
        start = now.strftime("%Y-%m-%d")
        end = (now + timedelta(days=7)).strftime("%Y-%m-%d")
        tasks = get_tasks_for_planning(user_id, start, end)
        if not tasks:
            await update.message.reply_text(
                "📅 Your week is clear! Add some tasks first.",
                reply_markup=main_menu()
            )
            return
        await update.message.reply_text("📅 Generating your weekly plan...")
        prefs = get_user_prefs(user_id)
        plan = generate_weekly_plan(tasks, prefs)
        await update.message.reply_text(
            f"🗓 *Your Week Ahead*\n\n{plan}",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return

    # Default: today
    today_str = now.strftime("%Y-%m-%d")
    tasks = get_tasks_for_planning(user_id, today_str, today_str)
    if not tasks:
        await update.message.reply_text(
            "📅 Nothing scheduled today! Add some tasks or enjoy your day.",
            reply_markup=main_menu()
        )
        return
    await update.message.reply_text("📋 Generating your daily plan...")
    prefs = get_user_prefs(user_id)
    plan = generate_daily_plan(tasks, prefs)
    await update.message.reply_text(
        f"📋 *Today's Plan ({today_str})*\n\n{plan}",
        parse_mode="Markdown", reply_markup=main_menu()
    )


async def breakdown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Break a task into 3-5 actionable subtasks."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            "💡 *Task Breakdown*\n\n"
            "Usage: /breakdown <task_id>\n"
            "Example: /breakdown 5\n\n"
            "I'll suggest 3-5 actionable subtasks for that big task.",
            parse_mode="Markdown"
        )
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /breakdown <task_id>")
        return
    task = get_task_by_id(tid, user_id)
    if not task:
        await update.message.reply_text(f"❌ Task [{tid}] not found.")
        return

    await update.message.reply_text(f"🧠 Breaking down *{task[1]}*...", parse_mode="Markdown")
    subtasks = generate_task_breakdown(task[1], task[2])

    if not subtasks:
        await update.message.reply_text(
            "Couldn't generate subtasks. Try a more descriptive task title.",
            reply_markup=main_menu()
        )
        return

    # Store as pending action so user can confirm
    set_pending_action(user_id, "create_subtasks", {
        "action": "create_subtasks",
        "parent_id": tid,
        "parent_title": task[1],
        "parent_date": task[2],
        "subtasks": subtasks,
    })

    msg = f"💡 *Suggested breakdown for:*\n📌 *{task[1]}*\n\n"
    for i, st in enumerate(subtasks, 1):
        h = st.get("estimated_hours", "?")
        p = st.get("priority", "medium")
        emoji = "🔴" if p == "high" else "🟢" if p == "low" else "🟡"
        msg += f"{i}. {emoji} {st.get('title', '?')} (~{h}h)\n"
    msg += "\nSave all as subtasks?"

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=yes_no_menu())


async def reschedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI-suggested reschedule for a task."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            "📅 *Smart Reschedule*\n\n"
            "Usage: /reschedule <task_id>\n"
            "I'll suggest a better time avoiding conflicts.",
            parse_mode="Markdown"
        )
        return
    try:
        tid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /reschedule <task_id>")
        return
    task = get_task_by_id(tid, user_id)
    if not task:
        await update.message.reply_text(f"❌ Task [{tid}] not found.")
        return

    # Find conflicts (same date, similar time)
    same_day = get_tasks_by_date(user_id, task[2]) if task[2] else []
    conflicts = [t for t in same_day if t[0] != tid]

    await update.message.reply_text(f"🤔 Finding a better time for *{task[1]}*...",
                                    parse_mode="Markdown")
    new_time = suggest_reschedule_time(task[1], conflicts)
    if not new_time:
        await update.message.reply_text(
            "Couldn't suggest a time. Use /edit to set manually.",
            reply_markup=main_menu()
        )
        return

    update_task(tid, user_id, due_time=new_time)
    updated = get_task_by_id(tid, user_id)
    await update.message.reply_text(
        f"✅ *Rescheduled!*\n\n"
        f"📌 *{updated[1]}*\n"
        f"📅 {updated[2]} ⏰ {new_time}\n\n"
        f"_AI suggested this time to avoid conflicts with your other tasks._",
        parse_mode="Markdown", reply_markup=main_menu()
    )


async def overload_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detect days that have too many tasks."""
    user_id = update.message.from_user.id
    now = datetime.now(IST)
    start = now.strftime("%Y-%m-%d")
    end = (now + timedelta(days=14)).strftime("%Y-%m-%d")
    counts = count_tasks_per_day(user_id, start, end)
    if not counts:
        await update.message.reply_text("✅ No tasks scheduled in the next 2 weeks.",
                                        reply_markup=main_menu())
        return
    overloaded = [(d, c) for d, c in counts.items() if c > 4]
    balanced = [(d, c) for d, c in counts.items() if 1 <= c <= 4]
    light = [(d, c) for d, c in counts.items() if c < 1]

    msg = "📊 *Task Load (Next 2 Weeks)*\n\n"
    if overloaded:
        msg += "⚠️ *Overloaded days:*\n"
        for d, c in sorted(overloaded):
            msg += f"   🔴 {d}: {c} tasks — consider redistributing\n"
        msg += "\n"
    if balanced:
        msg += "✅ *Balanced days:*\n"
        for d, c in sorted(balanced)[:5]:
            msg += f"   🟢 {d}: {c} task(s)\n"
        if len(balanced) > 5:
            msg += f"   ... and {len(balanced)-5} more days\n"
    if not overloaded and not balanced:
        msg += "Your schedule looks light. Time to plan something!"
    if overloaded:
        msg += "\n💡 Use /reschedule <id> to move tasks around."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())

async def error_handler(update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}", exc_info=context.error)
    try:
        if update and update.message:
            uid = update.message.from_user.id
            user_text = update.message.text or ""
            bug_id = dbg.log_exception(uid, user_text, context.error)
            await update.message.reply_text(
                f"\u26a0\ufe0f Something went wrong (auto-logged as bug #{bug_id}).\n"
                f"Use /bugs to see it or /report to add notes.",
                reply_markup=main_menu()
            )
            return
    except Exception:
        pass
    try:
        if update and update.message:
            await update.message.reply_text(
                "⚠️ Something went wrong. Please try again.\nUse /status to check API.",
                reply_markup=main_menu()
            )
    except Exception:
        pass


def main():
    init_db()
    dbg.init_bugs_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(CommandHandler("today", today_tasks))
    app.add_handler(CommandHandler("week", week_tasks))
    app.add_handler(CommandHandler("done", done_task))
    app.add_handler(CommandHandler("delete", delete_task_cmd))
    app.add_handler(CommandHandler("edit", edit_task_cmd))
    app.add_handler(CommandHandler("memory", memory_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("suggest", suggest_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("debug", debug_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("bugs", bugs_cmd))
    app.add_handler(CommandHandler("resolve", resolve_cmd))
    app.add_handler(CommandHandler("trace", trace_cmd))
    app.add_handler(CommandHandler("selftest", selftest_cmd))
    app.add_handler(CommandHandler("pause", pause_cmd))
    app.add_handler(CommandHandler("resume", resume_cmd))
    app.add_handler(CommandHandler("paused", paused_cmd))
    app.add_handler(CommandHandler("overdue", overdue_cmd))
    app.add_handler(CommandHandler("carryforward", carryforward_cmd))
    app.add_handler(CommandHandler("deadlines", deadlines_cmd))
    app.add_handler(CommandHandler("tag", tag_cmd))
    app.add_handler(CommandHandler("tagged", tagged_cmd))
    app.add_handler(CommandHandler("quiethours", quiethours_cmd))
    app.add_handler(CommandHandler("settings", settings_cmd))
    app.add_handler(CommandHandler("interval", interval_cmd))
    app.add_handler(CommandHandler("stopreminder", stopreminder_cmd))
    app.add_handler(CommandHandler("delreminder", delreminder_cmd))
    app.add_handler(CommandHandler("forget", forget_cmd))
    app.add_handler(CommandHandler("snooze", snooze_cmd))
    app.add_handler(CommandHandler("checktasks", checktasks_cmd))
    app.add_handler(CommandHandler("plan", plan_cmd))
    app.add_handler(CommandHandler("breakdown", breakdown_cmd))
    app.add_handler(CommandHandler("reschedule", reschedule_cmd))
    app.add_handler(CommandHandler("overload", overload_cmd))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)

    async def check_reminders(context):
        due = get_due_tasks()
        for task in due:
            task_id, uid, title, due_date, due_time = task
            try:
                buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Done", callback_data=f"done:{task_id}"),
                        InlineKeyboardButton("⏰ Snooze 10m", callback_data=f"snooze:{task_id}:10"),
                    ],
                    [
                        InlineKeyboardButton("🕐 Snooze 1h", callback_data=f"snooze:{task_id}:60"),
                        InlineKeyboardButton("📅 Tomorrow", callback_data=f"postpone:{task_id}"),
                    ],
                    [
                        InlineKeyboardButton("🔕 Stop Reminders", callback_data=f"stoprem:{task_id}"),
                        InlineKeyboardButton("🗑 Delete Task", callback_data=f"deltask:{task_id}"),
                    ],
                ])
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"🔔 *Reminder!*\n\n📌 *{title}*\n"
                         f"📅 {due_date or 'No date'} ⏰ {due_time or 'No time'}",
                    parse_mode="Markdown",
                    reply_markup=buttons
                )
                from datetime import datetime as _dt
                mark_reminded(task_id, _dt.now(IST).strftime("%Y-%m-%d %H:%M"))
            except Exception as e:
                logger.error(f"Reminder failed: {e}")

    app.job_queue.run_repeating(check_reminders, interval=60, first=10)

    async def check_followups(context):
        """v2.0: Re-remind overdue tasks at escalating intervals."""
        try:
            followups = get_tasks_needing_followup()
            # Batch by user
            by_user = {}
            for task in followups:
                tid, uid, title, ddate, dtime, rcount, last_rem = task
                by_user.setdefault(uid, []).append(task)

            for uid, tasks in by_user.items():
                if len(tasks) == 1:
                    # Single task — individual reminder
                    t = tasks[0]
                    tid, _, title, ddate, dtime, rcount, _ = t
                    urgency = "🔴" if rcount >= 3 else "🟡" if rcount >= 1 else "🔵"
                    buttons = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("✅ Done", callback_data=f"done:{tid}"),
                            InlineKeyboardButton("⏰ Snooze 10m", callback_data=f"snooze:{tid}:10"),
                        ],
                        [
                            InlineKeyboardButton("🕐 Snooze 1h", callback_data=f"snooze:{tid}:60"),
                            InlineKeyboardButton("📅 Tomorrow", callback_data=f"postpone:{tid}"),
                        ],
                        [
                            InlineKeyboardButton("🔕 Stop Reminders", callback_data=f"stoprem:{tid}"),
                            InlineKeyboardButton("🗑 Delete Task", callback_data=f"deltask:{tid}"),
                        ],
                    ])
                    await context.bot.send_message(
                        chat_id=uid,
                        text=f"{urgency} *Follow-up #{rcount+1}*\n\n"
                             f"📌 *{title}*\n"
                             f"📅 {ddate or 'No date'} ⏰ {dtime or 'No time'}\n\n"
                             f"_This task is still pending. Tap Done or Snooze._",
                        parse_mode="Markdown",
                        reply_markup=buttons
                    )
                    increment_reminder_count(tid)
                    mark_reminded(tid, datetime.now(IST).strftime("%Y-%m-%d %H:%M"))
                else:
                    # Multiple overdue — batch into one message
                    msg = f"📋 *You have {len(tasks)} pending tasks:*\n\n"
                    for t in tasks[:5]:
                        tid, _, title, ddate, dtime, rcount, _ = t
                        urgency = "🔴" if rcount >= 3 else "🟡"
                        msg += f"{urgency} *[{tid}]* {title} — 📅 {ddate or '?'} ⏰ {dtime or '?'}\n"
                        increment_reminder_count(tid)
                        mark_reminded(tid, datetime.now(IST).strftime("%Y-%m-%d %H:%M"))
                    if len(tasks) > 5:
                        msg += f"... and {len(tasks)-5} more.\n"
                    msg += "\n_Use /done <id> to complete or /list to see all._"
                    try:
                        await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Follow-up check failed: {e}")

    app.job_queue.run_repeating(check_followups, interval=300, first=60)

    async def daily_carry_forward(context):
        """v2.0: Auto carry-forward overdue tasks once daily."""
        try:
            count = auto_carry_forward()
            if count > 0:
                logger.info(f"Auto carry-forward: moved {count} overdue tasks to today")
        except Exception as e:
            logger.error(f"Carry-forward failed: {e}")

    app.job_queue.run_daily(daily_carry_forward,
        time=datetime.strptime("00:05", "%H:%M").time(),
        name="daily_carry_forward")

    async def check_deadlines(context):
        """v1.2: Warn users about tasks due within 24 hours — runs every hour."""
        try:
            import sqlite3
            conn = sqlite3.connect("planner.db")
            c = conn.cursor()
            c.execute("SELECT DISTINCT user_id FROM tasks WHERE done=0")
            users = [r[0] for r in c.fetchall()]
            conn.close()

            n = datetime.now(IST)
            today = n.strftime("%Y-%m-%d")
            for uid in users:
                # Overdue check
                overdue = get_overdue_tasks(uid, today, n.strftime("%H:%M"))
                if overdue:
                    msg = f"\u26a0\ufe0f *You have {len(overdue)} overdue task(s):*\n\n"
                    for t in overdue[:3]:
                        msg += f"\U0001f534 *[{t[0]}]* {t[1]} (was due {t[2]})\n"
                    if len(overdue) > 3:
                        msg += f"...and {len(overdue)-3} more.\n"
                    msg += "\nUse /overdue to see all or /carryforward to move to today."
                    try:
                        await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                    except Exception:
                        pass

                # Deadline warning (tasks due today that haven't been reminded yet)
                deadlines = get_upcoming_deadlines(uid, today, days_ahead=1)
                upcoming = [t for t in deadlines if t[2] == today]
                if upcoming:
                    msg = f"\U0001f525 *Deadline today:*\n\n"
                    for t in upcoming[:3]:
                        msg += f"\U0001f534 *[{t[0]}]* {t[1]} \u23f0 {t[3] or 'No time'}\n"
                    try:
                        await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Deadline check failed: {e}")

    app.job_queue.run_repeating(check_deadlines, interval=3600, first=120)
    logger.info("🤖 JARVIS is online!")
    print("🤖 JARVIS is running! Check bot.log for logs.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()