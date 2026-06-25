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
    save_memory, get_memory, get_all_memories, search_memories,
    add_goal, get_goals,
    snooze_task, postpone_task, pause_task, resume_task,
    mark_reminded, get_paused_tasks,
    get_overdue_tasks, get_upcoming_deadlines, set_tags,
    get_tasks_by_tag, carry_forward_overdue
)
from jarvis_brain import (
    get_jarvis_response, check_api_status,
    chat_with_ai, suggest_tasks, analyze_productivity,
    generate_study_plan, extract_memory_key
)
from conversation_state import (
    get_state, clear_state, update_context,
    add_history, get_history,
    set_pending_action, get_pending_action,
    set_gathering, get_gathering,
    set_editing, get_editing_id
)
from date_parser import parse_all, validate_datetime
from scheduler import get_due_tasks
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
        ['📌 Add Task', '📋 List Tasks'],
        ['📅 Today', '🗓 This Week'],
        ['✅ Done', '🗑 Delete'],
        ['✏️ Edit', '📊 Analyze'],
        ['🧠 Memory', '🔍 Status'],
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
        f"👋 Hey {name}! I'm *JARVIS*, your personal AI assistant.\n\n"
        f"Talk to me naturally — English, Hindi, or Hinglish!\n\n"
        f"_Examples:_\n"
        f"• _'Kal 8 baje gym yaad dila dena'_\n"
        f"• _'Physics assignment next Friday tak complete karni hai'_\n"
        f"• _'What do I have today?'_\n"
        f"• _'Remember that my exam is on June 20'_\n\n"
        f"Use the menu or just type!",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *JARVIS — Help*\n\n"
        "*Just type naturally!*\n"
        "Hindi, Hinglish, English — all work!\n\n"
        "*Commands:*\n"
        "/list — All tasks\n"
        "/today — Today's tasks\n"
        "/week — This week\n"
        "/done <id> — Mark complete\n"
        "/delete <id> — Delete\n"
        "/edit <id> — Edit task\n"
        "/memory — View stored memories\n"
        "/analyze — Productivity analysis\n"
        "/suggest <goal> — Task suggestions\n"
        "/status — API health\n"
        "/cancel — Cancel current action",
        parse_mode="Markdown", reply_markup=main_menu()
    )

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
        '📋 List Tasks': lambda: list_tasks(update, context),
        '📅 Today': lambda: today_tasks(update, context),
        '🗓 This Week': lambda: week_tasks(update, context),
        '✅ Done': lambda: done_task(update, context),
        '🗑 Delete': lambda: delete_task_cmd(update, context),
        '✏️ Edit': lambda: edit_task_cmd(update, context),
        '📊 Analyze': lambda: analyze_cmd(update, context),
        '🧠 Memory': lambda: memory_cmd(update, context),
        '🔍 Status': lambda: status_cmd(update, context),
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
            await update.message.reply_text("What should I call this task?", reply_markup=ReplyKeyboardRemove())
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
        if parsed["date"] and not entities.get("date"):
            entities["date"] = parsed["date"]
        if parsed["time"] and not entities.get("time"):
            entities["time"] = parsed["time"]
        if parsed["recurrence"] and not entities.get("recurrence"):
            entities["recurrence"] = parsed["recurrence"]["type"]

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
        if task_id:
            task = get_task_by_id(int(task_id), user_id)
            if task:
                set_pending_action(user_id, "delete_task", {"action": "delete", "task_id": int(task_id)})
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
        if task_id:
            update_task(int(task_id), user_id,
                due_date=entities.get("date"),
                due_time=entities.get("time"),
                category=entities.get("category"),
                priority=entities.get("priority")
            )
            task = get_task_by_id(int(task_id), user_id)
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
        tasks = get_tasks(user_id)
        await update.message.reply_text("📋 Let me create a plan for you...")
        plan = generate_study_plan(user_input, "end of week", tasks)
        await update.message.reply_text(f"📋 *Your Plan:*\n\n{plan}", parse_mode="Markdown", reply_markup=main_menu())

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