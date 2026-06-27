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
    add_subtask, get_subtasks, get_tasks_for_planning, count_tasks_per_day,
    add_habit, is_habit, log_habit_completion, get_habit_log,
    get_habits, get_missed_days, reset_streak,
    log_completion, log_snooze, log_interaction as db_log_interaction,
    reset_all_tasks, reset_all_memories, reset_all_habits,
    reset_learning_data, reset_everything, get_data_stats,
    get_tasks_for_followup, mark_followup_sent, increment_snooze_count,
    get_snooze_count, get_stale_tasks, get_unresolved_today,
    get_all_active_user_ids,
    get_wellness_prefs, set_wellness, mark_wellness_sent,
    get_wellness_enabled_users, count_tasks_at_time, get_high_priority_soon
)
from preferences import analyze_user, suggest_time_for_task, suggest_interval_for_task
from baka_brain import (
    get_baka_response, check_api_status,
    chat_with_ai, suggest_tasks, analyze_productivity,
    generate_study_plan, extract_memory_key,
    generate_daily_plan, generate_weekly_plan,
    generate_task_breakdown, suggest_reschedule_time,
    generate_structured_plan
)
from fmt import HTML, esc, b, i, code, task_line, confirm_box, header, DIVIDER
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
# v6.1: Admin lock — the first user to run /claimadmin becomes the sole admin.
# Stored in a tiny file so it survives restarts. Only the admin can use admin tools.
ADMIN_FILE = "admin_id.txt"

def get_admin_id():
    try:
        with open(ADMIN_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None

def set_admin_id(uid):
    with open(ADMIN_FILE, "w") as f:
        f.write(str(uid))

def is_admin(uid):
    admin = get_admin_id()
    return admin is not None and uid == admin

# In-memory flag: is the admin currently in debug/admin mode?
_admin_mode = {}
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
        return f"✅ No tasks for {esc(label)}!"
    msg = f"📋 {b('Tasks for ' + str(label))}\n\n"
    _today = datetime.now(IST).strftime("%Y-%m-%d")
    for t in tasks:
        priority = t[5] if len(t) > 5 else "medium"
        recurrence = t[6] if len(t) > 6 else None
        is_overdue = t[2] and t[2] < _today
        emoji = "⏰" if is_overdue else "🔴" if priority == "high" else "🟢" if priority == "low" else "🟡"
        overdue_tag = " " + i("(overdue)") if is_overdue else ""
        rec_icon = ""
        if recurrence == "daily":
            rec_icon = " 🔁"
        elif recurrence == "weekly":
            rec_icon = " 📆"
        elif recurrence == "monthly":
            rec_icon = " 🗓"
        category = t[4] if len(t) > 4 else "General"
        msg += f"{emoji} {code('[' + str(t[0]) + ']')} {esc(t[1])}{rec_icon}{overdue_tag}\n"
        msg += f"   <i>📅 {esc(t[2] or 'No date')} · ⏰ {esc(t[3] or 'No time')} · 🏷 {esc(category)}</i>\n\n"
    return msg

def build_summary(data: dict) -> str:
    return confirm_box(
        title=data.get('title') or 'Untitled',
        date=data.get('date'),
        time=data.get('time'),
        category=data.get('category') or 'General',
        priority=data.get('priority'),
        recurrence=data.get('recurrence'),
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
        f"👋 Hey {name}! I'm *BAKA* — your *Behavioral Adaptive Knowledge Assistant*.\n\n"
        f"I learn how you work and help you stay on top of tasks, reminders, habits, and goals — "
        f"all through natural conversation.\n\n"
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
        "🤖 *BAKA — Behavioral Adaptive Knowledge Assistant*\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "💬 *TWO WAYS TO TALK*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "*1. Natural language:*\n"
        "_'Remind me to study at 5pm'_\n"
        "_'Kal gym yaad dila dena'_\n"
        "_'plan my day'_\n\n"
        "*2. Commands work WITH or WITHOUT slash:*\n"
        "`/list` ≡ `list`\n"
        "`/done 5` ≡ `done 5`\n"
        "`/breakdown 3` ≡ `breakdown 3`\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "📌 *TASKS*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "`list` — All pending tasks\n"
        "`today` — Today's schedule\n"
        "`week` — This week's plan\n"
        "`done <id>` — Mark complete\n"
        "`edit <id>` — Modify a task\n"
        "`delete <id>` — Remove a task\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🔔 *REMINDERS*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "Tap-able buttons on every reminder:\n"
        "  ✅ Done  ⏰ Snooze  📅 Tomorrow\n"
        "`snooze <id> <min>` — Custom snooze\n"
        "`pause <id>` — Stop reminders\n"
        "`resume <id>` — Restart\n"
        "`paused` — View paused tasks\n"
        "`stopreminder <id>` — Disable for one task\n"
    )
    help2 = (
        "━━━━━━━━━━━━━━━━━━━\n"
        "📅 *TRACKING*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "`overdue` — Overdue tasks\n"
        "`deadlines` — Due in 3 days\n"
        "`carryforward` — Move overdue to today\n"
        "`tag <id> <tags>` — Add tags\n"
        "`tagged <tag>` — Search by tag\n"
        "`checktasks` — Diagnose reminders\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🧠 *PLANNING & AI*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "`plan today` / `plan week` — Time-blocked plan (asks to apply!)\n"
        "`breakdown <id>` — Split big task into subtasks\n"
        "`reschedule <id>` — AI picks new time\n"
        "`overload` — Find overloaded days\n"
        "`analyze` — Productivity report\n"
        "`suggest <goal>` — Task suggestions\n"
        "`memory` — Stored memories\n"
        "`forget <key>` — Delete a memory\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "⚙️ *SETTINGS*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "`settings` — View preferences\n"
        "`quiethours <start> <end>` — Sleep window\n"
        "`interval <min>` — Reminder frequency\n"
        "`status` — API health\n\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "🐞 *DEBUG*\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        "`debug` — Toggle debug mode\n"
        "`report <issue>` — Report a bug\n"
        "`bugs` — View open bugs\n"
        "`trace` — Last AI interaction\n"
        "`selftest` — Test checklist\n\n"
        "💡 _Slash is optional everywhere!_"
    )
    await update.message.reply_text(help1, parse_mode="Markdown")
    await update.message.reply_text(help2, parse_mode="Markdown", reply_markup=main_menu())

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_state(update.message.from_user.id)
    await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu())

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = get_tasks(update.message.from_user.id)
    await update.message.reply_text(
        format_tasks(tasks, "All Pending"), parse_mode=HTML, reply_markup=main_menu()
    )

async def today_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(IST).strftime("%Y-%m-%d")
    tasks = get_tasks_by_date(update.message.from_user.id, today)
    await update.message.reply_text(
        format_tasks(tasks, f"Today ({today})"), parse_mode=HTML, reply_markup=main_menu()
    )

async def week_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(IST)
    tasks = get_tasks_by_week(update.message.from_user.id,
        now.strftime("%Y-%m-%d"), (now + timedelta(days=7)).strftime("%Y-%m-%d"))
    await update.message.reply_text(
        format_tasks(tasks, "This Week"), parse_mode=HTML, reply_markup=main_menu()
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
        # v5.0: if it's a habit, log completion and show streak
        was_habit = is_habit(task_id)
        if was_habit:
            ok, streak_or_msg = log_habit_completion(task_id, user_id)
            if ok:
                streak_text = f"\n🔥 Streak: *{streak_or_msg}* day{'s' if streak_or_msg != 1 else ''}!"
            else:
                streak_text = "\n_(already logged today)_"
            await update.message.reply_text(
                f"✅ *Habit completed!*\n📌 {task[1]}{streak_text}",
                parse_mode="Markdown", reply_markup=main_menu()
            )
        else:
            mark_done(task_id, user_id)
            # v6.0: log completion for preference learning
            try:
                _now = datetime.now(IST)
                _scheduled = task[3] or "00:00"
                _delay = 0
                if task[3]:
                    try:
                        sh, sm = map(int, task[3].split(":"))
                        _scheduled_dt = _now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                        _delay = max(0, int((_now - _scheduled_dt).total_seconds() / 60))
                    except (ValueError, AttributeError):
                        pass
                log_completion(user_id, task_id, task[1], task[4] or "General",
                               _scheduled, _now.strftime("%Y-%m-%d %H:%M:%S"), _delay)
                db_log_interaction(user_id, "task_done")
            except Exception:
                pass
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

        rec_msg = f"\n🔁 Repeats: {esc(rec)}" if rec else ""
        await update.message.reply_text(
            f"✅ {b('Saved!')}\n\n"
            f"📌 {b(title)}\n"
            f"<i>📅 {esc(date or 'No date')} · ⏰ {esc(data.get('time') or 'No time')} · 🏷 {esc(data.get('category', 'General'))}</i>"
            f"{rec_msg}\n\n"
            f"Use {code('/done ' + str(task_id))} when complete!",
            parse_mode=HTML, reply_markup=main_menu()
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

    elif action == "create_habit":
        title = data.get("title")
        time_val = data.get("time")
        rec = data.get("recurrence", "daily")
        rec_weekday = data.get("recurrence_weekday")
        if not title:
            await update.message.reply_text("❌ No habit title — try again.",
                                            reply_markup=main_menu())
            return
        hid = add_habit(user_id, title, time=time_val,
                        recurrence=rec, recurrence_weekday=rec_weekday,
                        category=data.get("category", "Health"),
                        priority=data.get("priority", "medium"))
        await update.message.reply_text(
            f"🌱 *Habit saved!*\n\n"
            f"📌 *{title}* [{hid}]\n"
            f"🔄 {rec}\n"
            f"⏰ {time_val or 'flexible'}\n\n"
            f"_Mark done daily to build your streak!_\n"
            f"Use /habits to view all habits.",
            parse_mode="Markdown", reply_markup=main_menu()
        )

    elif action == "apply_plan":
        items = data.get("items", [])
        applied_count = 0
        skipped_count = 0
        for item in items:
            tid = item.get("task_id")
            when = item.get("time")
            if tid and when:
                # Validate HH:MM format
                import re as _re
                if _re.match(r"^\d{1,2}:\d{2}$", str(when)):
                    h, mn = when.split(":")
                    new_time = f"{int(h):02d}:{int(mn):02d}"
                    update_task(tid, user_id, due_time=new_time)
                    applied_count += 1
                else:
                    skipped_count += 1
        msg = f"✅ *Plan applied!*\n\nUpdated {applied_count} task(s)"
        if skipped_count:
            msg += f" (skipped {skipped_count} with invalid times)"
        msg += ".\n\n_You'll get reminders at the new times._"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())

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
    # v6.0: log interaction timestamp for active-hours analysis
    try:
        db_log_interaction(user_id, "message")
    except Exception:
        pass

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
        # v6.1: admin destructive-reset confirmations
        if action_type == "admin_reset_tasks":
            clear_state(user_id)
            if user_input.strip() == "YES RESET" and is_admin(user_id):
                n = reset_all_tasks(user_id)
                await update.message.reply_text(
                    f"\u2705 Reset complete. Deleted {n} tasks. Task IDs now start from 1 again.",
                    reply_markup=main_menu()
                )
            else:
                await update.message.reply_text("Cancelled — nothing deleted.",
                                                reply_markup=main_menu())
            return
        if action_type == "admin_reset_all":
            clear_state(user_id)
            if user_input.strip() == "YES NUKE EVERYTHING" and is_admin(user_id):
                counts = reset_everything(user_id)
                summary = ", ".join(f"{k}:{v}" for k, v in counts.items() if v)
                await update.message.reply_text(
                    f"\u2705 *Nuclear reset done.*\nDeleted: {summary or 'nothing'}.\n"
                    f"All IDs reset.",
                    parse_mode="Markdown", reply_markup=main_menu()
                )
            else:
                await update.message.reply_text("Cancelled — nothing deleted.",
                                                reply_markup=main_menu())
            return
        am_pm = re.match(r"^(\d{1,2})\s*(AM|PM)$", user_input.upper())
        if am_pm:
            h2, period2 = int(am_pm.group(1)), am_pm.group(2)
            if period2 == "PM" and h2 != 12: h2 += 12
            elif period2 == "AM" and h2 == 12: h2 = 0
            data["time"] = str(h2).zfill(2) + ":00"
            update_context(user_id, {"pending_data": data})
            await update.message.reply_text(
                "Got it! " + esc(user_input) + "\n\n" + build_summary(data) + "\n\nShall I save this?",
                parse_mode=HTML, reply_markup=yes_no_menu()
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
                f"⏰ Updated to {esc(parsed_time)}!\n\n{build_summary(data)}\n\nShall I save this?",
                parse_mode=HTML, reply_markup=yes_no_menu()
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
                f"Say {b('yes')} to save, {b('no')} to cancel, or tell me what to change (e.g. 'set time to 5pm')",
                parse_mode=HTML, reply_markup=yes_no_menu()
            )
        return

    # ── Editing ──
    if state == "editing":
        task_id = get_editing_id(user_id)
        if task_id:
            parsed = parse_all(user_input)
            result = get_baka_response(
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
        result = get_baka_response(
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
                parse_mode=HTML, reply_markup=yes_no_menu()
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

    # ── v4.1 EXHAUSTIVE natural-language command map ─────
    # All slash commands ALSO work without the slash.
    # Phrases checked in order — most specific first to avoid mismatches.

    # Phase 1: phrases needing arguments (must be a STARTS-WITH match)
    _starts_with_handlers = [
        # (prefix_list, handler, needs_args)
        (["plan today", "plan my day", "today's plan", "schedule my day",
          "make a plan", "what should i do today"], plan_cmd, ["today"]),
        (["plan week", "plan my week", "weekly plan", "week ahead",
          "plan this week"], plan_cmd, ["week"]),
        (["breakdown ", "break down ", "split task ", "subtasks for "], breakdown_cmd, None),
        (["reschedule ", "move task ", "shift task "], reschedule_cmd, None),
        (["snooze "], snooze_cmd, None),
        (["pause "], pause_cmd, None),
        (["resume "], resume_cmd, None),
        (["tag "], tag_cmd, None),
        (["tagged ", "tasks with tag "], tagged_cmd, None),
        (["stopreminder ", "stop reminder ", "stop reminders for "], stopreminder_cmd, None),
        (["delreminder ", "delete reminder "], delreminder_cmd, None),
        (["done ", "complete task ", "finish task ", "mark done "], done_task, None),
        (["delete ", "remove ", "del "], delete_task_cmd, None),
        (["edit "], edit_task_cmd, None),
        (["report ", "bug "], report_cmd, None),
        (["resolve "], resolve_cmd, None),
        (["forget ", "delete memory ", "remove memory ",
          "delete remembered ", "remove remembered "], forget_cmd, None),
        (["quiethours ", "quiet hours ", "set quiet "], quiethours_cmd, None),
        (["interval ", "reminder interval ", "set interval "], interval_cmd, None),
        (["suggest "], suggest_cmd, None),
        (["streak "], streak_cmd, None),
        (["habitlog ", "habit log "], habitlog_cmd, None),
        (["addhabit ", "add habit ", "new habit "], addhabit_cmd, None),
        (["skiphabit ", "skip habit ", "reset streak "], skiphabit_cmd, None),
    ]
    for prefixes, handler, default_args in _starts_with_handlers:
        for prefix in prefixes:
            if _low_full.startswith(prefix):
                args_str = user_input[len(prefix):].strip()
                context.args = (args_str.split() if args_str else (default_args or []))
                await handler(update, context)
                return

    # Phase 2: phrases that are full-message matches (no args)
    _exact_handlers = {
        # Task viewing
        ("list", "my tasks", "show tasks", "all tasks", "show all"): list_tasks,
        ("today", "today's tasks", "show today", "what's today",
         "what do i have today", "schedule today"): today_tasks,
        ("week", "this week", "weekly", "show week", "what's this week"): week_tasks,
        # Status
        ("status", "api status", "check status", "is api working",
         "is the bot online", "health check"): status_cmd,
        ("settings", "my settings", "view settings", "show settings"): settings_cmd,
        # Debug
        ("debug", "toggle debug", "turn on debug", "enable debug",
         "debug mode on", "turn off debug", "disable debug", "debug mode off"): debug_cmd,
        ("bugs", "show bugs", "list bugs", "view bugs", "what bugs", "open bugs"): bugs_cmd,
        ("trace", "trace this", "what did you understand",
         "what was my last message"): trace_cmd,
        ("selftest", "self test", "run tests", "run self test", "test"): selftest_cmd,
        # Lists
        ("overdue", "show overdue", "my overdue", "what is overdue",
         "what's overdue"): overdue_cmd,
        ("deadlines", "show deadlines", "my deadlines", "what deadlines",
         "upcoming deadlines"): deadlines_cmd,
        ("memory", "show memory", "show memories", "my memories",
         "what do you remember"): memory_cmd,
        ("paused", "show paused", "paused tasks"): paused_cmd,
        # Planning
        ("overload", "am i overloaded", "show overload",
         "load check", "busy days"): overload_cmd,
        ("habits", "show habits", "my habits", "list habits"): habits_cmd,
        ("insights", "what have you learned", "my patterns",
         "learned behavior", "what do you know about me"): insights_cmd,
        ("review", "review tasks", "stale tasks", "what needs review",
         "old tasks"): review_cmd,
        ("carryforward", "carry forward", "move overdue to today"): carryforward_cmd,
        # Analysis
        ("analyze", "analyse", "analyze me", "productivity",
         "how productive", "analyse productivity"): analyze_cmd,
        # Help
        ("help", "show help", "what can you do", "help me",
         "guide me", "commands"): help_command,
        ("cancel", "stop", "nevermind", "never mind", "abort"): cancel_cmd,
        # Diagnostics
        ("checktasks", "check tasks", "diagnose tasks", "task diagnostics"): checktasks_cmd,
    }
    for phrases, handler in _exact_handlers.items():
        if _low_full in phrases or any(_low_full == p for p in phrases):
            context.args = []
            await handler(update, context)
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
            format_tasks(tasks, label), parse_mode=HTML, reply_markup=main_menu()
        )
        return

    # ── Idle — BAKA ──
    now = datetime.now(IST)
    parsed = parse_all(user_input, now)
    memories = get_all_memories(user_id)
    existing_tasks = get_tasks(user_id)

    result = get_baka_response(user_input, existing_tasks, get_history(user_id), memories)
    intent = result.get("intent", "CHAT").upper()
    entities = result.get("entities", {})
    missing = result.get("missing", [])
    needs_confirm = result.get("needs_confirm", False)
    response_text = result.get("response", "")
    confirm_summary = result.get("confirm_summary")

    # Merge local parser results — ONLY for task-like intents.
    # Bug 13: don't let a stray "today" in casual chat turn CHAT into a task.
    if intent in ["TASK", "HABIT", "EDIT", "MULTIPLE"]:
        low = user_input.lower()
        # Relative time: "in N min/hour" — parser's resolved time MUST win
        _has_relative_time = bool(re.search(
            r"\b(in|after)\s+\d+\s+(min|minute|mins|minutes|hour|hours|hr|hrs)\b", low))
        # Vague time words: parser knows the exact mapping, AI often guesses wrong
        _has_vague_time = bool(re.search(
            r"\b(morning|subah|evening|shaam|tonight|night|raat|afternoon|dopahar|"
            r"noon|lunch|midnight|end of day|later|soon)\b", low))

        ai_time = entities.get("time", "")
        # Reject malformed AI times like "25:00", "1 min", "13 AM"→"13:00" mislabeled
        ai_time_valid = bool(ai_time and re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", str(ai_time)))

        if (_has_relative_time or _has_vague_time) and parsed.get("time"):
            # Parser wins for relative + vague phrasings
            entities["time"] = parsed["time"]
        elif ai_time and not ai_time_valid:
            # AI returned something malformed → discard, fall back to parser
            entities["time"] = parsed.get("time")

        if parsed.get("date") and not entities.get("date"):
            entities["date"] = parsed["date"]
        if parsed.get("time") and not entities.get("time"):
            entities["time"] = parsed["time"]
        if parsed.get("recurrence") and not entities.get("recurrence"):
            entities["recurrence"] = parsed["recurrence"]["type"]
        if parsed.get("priority") and not entities.get("priority"):
            entities["priority"] = parsed["priority"]

        # Bug: invalid time / past date detection from the parser
        if parsed.get("is_invalid_time"):
            entities["time"] = None
            await update.message.reply_text(
                "⚠️ That time doesn't look valid. Try a format like `3 PM`, `15:00`, or `evening`.",
                parse_mode="Markdown", reply_markup=main_menu()
            )
            clear_state(user_id)
            return
        if parsed.get("is_past"):
            await update.message.reply_text(
                "⚠️ That date is in the past. Did you mean a future date?",
                reply_markup=main_menu()
            )
            clear_state(user_id)
            return

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
                parse_mode=HTML, reply_markup=main_menu()
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
            format_tasks(tasks, label), parse_mode=HTML, reply_markup=main_menu()
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
            # v8.0: smart suggestion — warn if the time slot is crowded
            extra = ""
            try:
                slot_count = count_tasks_at_time(user_id, summary_data["date"], summary_data["time"])
                if slot_count >= 2:
                    extra = f"\n\n💡 <i>Heads up: you already have {slot_count} task(s) at that exact time.</i>"
            except Exception:
                pass
            await update.message.reply_text(
                f"Got it! Here's what I'll save:\n\n{summary}{extra}\n\nShall I save this?",
                parse_mode=HTML, reply_markup=yes_no_menu()
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
        # v5.0: real habit creation with streak tracking
        title = entities.get("title") or user_input
        recurrence = entities.get("recurrence") or "daily"
        time_val = entities.get("time") or parsed.get("time")
        # Extract recurrence weekday for weekly habits
        rec_obj = parsed.get("recurrence") or {}
        rec_weekday = rec_obj.get("weekday")
        set_pending_action(user_id, "create_habit", {
            "action": "create_habit",
            "title": title,
            "time": time_val,
            "recurrence": recurrence,
            "recurrence_weekday": rec_weekday,
            "category": entities.get("category", "Health"),
            "priority": entities.get("priority", "medium"),
        })
        rec_label = recurrence
        if recurrence == "weekly" and rec_weekday is not None:
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            rec_label = f"every {day_names[rec_weekday]}"
        await update.message.reply_text(
            f"🌱 *Setting up a habit!*\n\n"
            f"📌 *{title}*\n"
            f"🔄 Repeats: {rec_label}\n"
            f"⏰ Time: {time_val or 'flexible'}\n\n"
            f"_I'll track your streak as you mark it done each day._\n\n"
            f"Save this habit?",
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
            # v5.0: habit-aware completion
            if is_habit(task_id):
                ok, streak_or_msg = log_habit_completion(task_id, user_id)
                streak_text = (f"\n🔥 Streak: *{streak_or_msg}* day"
                               f"{'s' if isinstance(streak_or_msg,int) and streak_or_msg != 1 else ''}!"
                               if ok else "\n_(already logged today)_")
                await query.edit_message_text(
                    f"✅ *Habit completed!*\n📌 {task[1]}{streak_text}",
                    parse_mode="Markdown"
                )
            else:
                mark_done(task_id, user_id)
                # v6.0: log for preference learning
                try:
                    _now = datetime.now(IST)
                    _scheduled = task[3] or "00:00"
                    _delay = 0
                    if task[3]:
                        try:
                            sh, sm = map(int, task[3].split(":"))
                            _sd = _now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                            _delay = max(0, int((_now - _sd).total_seconds() / 60))
                        except (ValueError, AttributeError):
                            pass
                    log_completion(user_id, task_id, task[1], task[4] or "General",
                                   _scheduled, _now.strftime("%Y-%m-%d %H:%M:%S"), _delay)
                    db_log_interaction(user_id, "task_done")
                except Exception:
                    pass
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
        increment_snooze_count(task_id)
        # v6.0: log snooze for preference learning
        try:
            _t = get_task_by_id(task_id, user_id)
            if _t:
                log_snooze(user_id, task_id, _t[1], _t[4] or "General", minutes)
                db_log_interaction(user_id, "task_snooze")
        except Exception:
            pass
        label = f"{minutes} minutes" if minutes < 60 else "1 hour"
        # v7.0: repeated-snooze detection
        scount = get_snooze_count(task_id)
        if scount >= 3:
            _t = get_task_by_id(task_id, user_id)
            suggested = None
            try:
                suggested = suggest_time_for_task(user_id, _t[4] or "General") if _t else None
            except Exception:
                pass
            tip = f"\n\n💡 You've snoozed this {scount} times. "
            if suggested:
                tip += f"You usually get things done around *{suggested}* — want me to move it there? Reply: reschedule {task_id}"
            else:
                tip += "Maybe it needs a better time or to be broken down. Try /breakdown " + str(task_id)
            await query.edit_message_text(
                f"⏰ Snoozed for {label}.{tip}",
                parse_mode="Markdown"
            )
        else:
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

    elif action == "finish_yes":
        # v7.0: user confirms they finished
        task = get_task_by_id(task_id, user_id)
        if task:
            if is_habit(task_id):
                ok, streak = log_habit_completion(task_id, user_id)
                txt = (f"\U0001f525 Streak: {streak}!" if ok else "_(already logged)_")
                await query.edit_message_text(
                    f"\u2705 *Awesome!* Logged:\n\U0001f4cc {task[1]}\n{txt}",
                    parse_mode="Markdown")
            else:
                mark_done(task_id, user_id)
                try:
                    _now = datetime.now(IST)
                    log_completion(user_id, task_id, task[1], task[4] or "General",
                                   task[3] or "00:00", _now.strftime("%Y-%m-%d %H:%M:%S"), 0)
                except Exception:
                    pass
                await query.edit_message_text(
                    f"\u2705 *Great job!* Marked done:\n\U0001f4cc {task[1]}",
                    parse_mode="Markdown")
        else:
            await query.edit_message_text("Task not found.")

    elif action == "finish_no":
        # v7.0: not finished — offer help
        task = get_task_by_id(task_id, user_id)
        if task:
            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("📅 Reschedule", callback_data=f"postpone:{task_id}"),
                    InlineKeyboardButton("🔨 Break it down", callback_data=f"dobreak:{task_id}"),
                ],
                [InlineKeyboardButton("🔕 Stop asking", callback_data=f"stoprem:{task_id}")],
            ])
            await query.edit_message_text(
                f"No worries! For *{task[1]}*, want to:\n\n"
                f"📅 Reschedule it to tomorrow\n"
                f"🔨 Break it into smaller steps\n"
                f"🔕 Or stop the follow-ups?",
                parse_mode="Markdown", reply_markup=buttons)
        else:
            await query.edit_message_text("Task not found.")

    elif action == "dobreak":
        # v7.0: trigger breakdown from the follow-up flow
        task = get_task_by_id(task_id, user_id)
        if task:
            await query.edit_message_text(f"🔨 Breaking down *{task[1]}*...",
                                          parse_mode="Markdown")
            subtasks = generate_task_breakdown(task[1], task[2])
            if subtasks:
                set_pending_action(user_id, "create_subtasks", {
                    "action": "create_subtasks",
                    "parent_id": task_id,
                    "parent_title": task[1],
                    "parent_date": task[2],
                    "subtasks": subtasks,
                })
                msg = f"💡 Suggested steps for *{task[1]}*:\n\n"
                for i, st in enumerate(subtasks, 1):
                    msg += f"{i}. {st.get('title','?')}\n"
                msg += "\nSave these as subtasks?"
                await context.bot.send_message(chat_id=user_id, text=msg,
                    parse_mode="Markdown", reply_markup=yes_no_menu())
            else:
                await context.bot.send_message(chat_id=user_id,
                    text="Couldn't break it down. Try /breakdown <id> manually.")

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
        # v6.0: log snooze for preference learning
        try:
            log_snooze(user_id, tid, task[1], task[4] or "General", minutes)
            db_log_interaction(user_id, "task_snooze")
        except Exception:
            pass
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
    """v4.1: Generate a time-blocked plan AND offer to apply it to actual tasks."""
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
        plan_data = generate_structured_plan(tasks, prefs, "this week")
        await _present_plan(update, user_id, plan_data, period_label="Week Ahead")
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
    plan_data = generate_structured_plan(tasks, prefs, "today")
    await _present_plan(update, user_id, plan_data, period_label=f"Today ({today_str})")


async def _present_plan(update, user_id, plan_data, period_label):
    """Show the plan and ask whether to apply it to actual task schedule."""
    schedule = plan_data.get("schedule", [])
    summary = plan_data.get("summary", "")
    if not schedule:
        await update.message.reply_text(
            "Couldn't generate a structured plan. Try /list to see your tasks.",
            reply_markup=main_menu()
        )
        return

    msg = f"📋 *Plan for {period_label}*\n\n{summary}\n\n"
    valid_items = []
    for item in schedule:
        tid = item.get("task_id")
        when = item.get("time", "?")
        dur = item.get("duration_min", "?")
        note = item.get("note", "")
        task = get_task_by_id(int(tid), user_id) if tid else None
        if task:
            msg += f"⏰ *{when}* — [{tid}] {task[1]} ({dur}m)\n"
            if note:
                msg += f"   _{note}_\n"
            valid_items.append({"task_id": int(tid), "time": when})
    if not valid_items:
        await update.message.reply_text(msg + "\n_No valid items to apply._",
                                        parse_mode="Markdown", reply_markup=main_menu())
        return

    msg += f"\n_Apply this plan to schedule these {len(valid_items)} tasks?_"
    set_pending_action(user_id, "apply_plan", {
        "action": "apply_plan",
        "items": valid_items,
    })
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=yes_no_menu())


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


# ── v5.0: Habit Engine Commands ───────────────────────
async def habits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all habits with streak summary."""
    user_id = update.message.from_user.id
    habits = get_habits(user_id)
    if not habits:
        await update.message.reply_text(
            "🌱 *No habits yet!*\n\n"
            "Start one with:\n"
            "_'I want to run every day at 6 AM'_\n"
            "_'addhabit Drink water hourly'_\n"
            "_'gym every monday at 7 AM'_",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return
    msg = f"🌱 *Your Habits ({len(habits)})*\n\n"
    for h in habits:
        hid, title, dtime, rec, weekday, streak, longest, last_done, start = h
        streak = streak or 0
        fire = "🔥" * min(streak, 5) if streak > 0 else "○"
        rec_label = "daily" if rec == "daily" else f"weekly (day {weekday})" if rec == "weekly" else rec or "—"
        msg += f"*[{hid}]* {title}\n"
        msg += f"   {fire} Streak: *{streak}* | Best: {longest or 0}\n"
        msg += f"   ⏰ {dtime or 'flexible'} • {rec_label}\n"
        if last_done:
            msg += f"   Last done: {last_done}\n"
        msg += "\n"
    msg += "_Mark done daily to build streaks!_\nUse /streak <id> for details."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())


async def streak_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed streak info for a habit."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            "Usage: /streak <habit_id>\nUse /habits to see your habits.",
            reply_markup=main_menu()
        )
        return
    try:
        hid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /streak <habit_id>")
        return
    task = get_task_by_id(hid, user_id)
    if not task or not is_habit(hid):
        await update.message.reply_text("❌ That's not a habit. Use /habits to see them.")
        return

    log = get_habit_log(hid, user_id, days=14)
    missed = get_missed_days(hid, user_id, days=14)
    habits = [h for h in get_habits(user_id) if h[0] == hid]
    if not habits:
        await update.message.reply_text("Habit not found or paused.")
        return
    h = habits[0]
    _, title, dtime, rec, weekday, streak, longest, last_done, start = h
    streak = streak or 0
    longest = longest or 0

    msg = f"🌱 *{title}*\n\n"
    msg += f"🔥 Current streak: *{streak} day{'s' if streak != 1 else ''}*\n"
    msg += f"🏆 Longest streak: *{longest} day{'s' if longest != 1 else ''}*\n"
    msg += f"📅 Started: {start or '?'}\n"
    if last_done:
        msg += f"✅ Last done: {last_done}\n"
    msg += f"\n*Last 14 days:*\n"

    # Visual 14-day grid
    from datetime import date as _d
    today = datetime.now(IST).date()
    logged_dates = {row[0] for row in log if row[1]}
    bar = ""
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        bar += "🟩" if day.strftime("%Y-%m-%d") in logged_dates else "⬜"
    msg += bar + "\n"

    if missed:
        msg += f"\n⚠️ Missed {len(missed)} day(s) in this window."
        if len(missed) >= 3:
            msg += "\n💡 _Tip: try changing the time or making it easier._"

    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())


async def habitlog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Detailed log for a habit."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("Usage: /habitlog <habit_id>")
        return
    try:
        hid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /habitlog <habit_id>")
        return
    task = get_task_by_id(hid, user_id)
    if not task or not is_habit(hid):
        await update.message.reply_text("That's not a habit.")
        return

    log = get_habit_log(hid, user_id, days=30)
    if not log:
        await update.message.reply_text(f"No log entries yet for *{task[1]}*.",
                                        parse_mode="Markdown")
        return
    msg = f"📊 *Log for {task[1]}* (last 30 days)\n\n"
    for d, completed in log[:30]:
        emoji = "✅" if completed else "❌"
        msg += f"{emoji} {d}\n"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())


async def addhabit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick habit creation from a single command."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            "🌱 *Add a habit*\n\n"
            "Usage: /addhabit <habit name> [at HH:MM] [daily|weekly]\n"
            "Example: /addhabit Drink water at 09:00 daily\n\n"
            "Or just say it naturally:\n"
            "_'I want to run every day at 6 AM'_",
            parse_mode="Markdown"
        )
        return
    text = " ".join(context.args)
    # Use parser to extract time + recurrence from the natural description
    from date_parser import parse_all as _parse
    p = _parse(text, datetime.now(IST))
    time_val = p.get("time")
    rec = p.get("recurrence")
    rec_type = rec["type"] if rec else "daily"
    rec_weekday = rec.get("weekday") if rec else None
    # Strip out time/recurrence words from title
    title = text
    import re as _re
    title = _re.sub(r"\b(at\s+\d{1,2}:\d{2})\b|\b(daily|every day|every week|weekly|monthly)\b",
                    "", title, flags=_re.IGNORECASE).strip()
    title = _re.sub(r"\s+", " ", title)
    if not title:
        await update.message.reply_text("Tell me what the habit is.")
        return
    hid = add_habit(user_id, title, time=time_val,
                    recurrence=rec_type, recurrence_weekday=rec_weekday)
    await update.message.reply_text(
        f"🌱 *Habit created!*\n\n"
        f"📌 *{title}*\n"
        f"🔄 {rec_type}{' (day ' + str(rec_weekday) + ')' if rec_weekday is not None else ''}\n"
        f"⏰ {time_val or 'flexible'}\n\n"
        f"Mark it done every time you do it — I'll track your streak!\n"
        f"Use /habits to see all habits.",
        parse_mode="Markdown", reply_markup=main_menu()
    )


async def skiphabit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset streak — user is skipping intentionally."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("Usage: /skiphabit <habit_id>")
        return
    try:
        hid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /skiphabit <habit_id>")
        return
    task = get_task_by_id(hid, user_id)
    if not task or not is_habit(hid):
        await update.message.reply_text("That's not a habit.")
        return
    reset_streak(hid)
    await update.message.reply_text(
        f"🔄 Streak reset for *{task[1]}*. No worries — start fresh tomorrow!",
        parse_mode="Markdown", reply_markup=main_menu()
    )


# ── v6.0: Preference Learning Commands ────────────────
async def insights_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show what BAKA has learned about your behavior."""
    user_id = update.message.from_user.id
    data = analyze_user(user_id, days=30)

    if data["total_tasks"] < 3:
        await update.message.reply_text(
            "\U0001f4ca *Not enough data yet*\n\n"
            "I need at least 3 tasks across a few days to learn your patterns. "
            "Keep using me — I'll start spotting trends soon!",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return

    msg = "\U0001f9e0 *What I've learned about you*\n"
    msg += f"_(based on last 30 days, {data['total_tasks']} tasks)_\n\n"

    for line in data["insights"]:
        msg += f"\u2022 {line}\n"
    msg += "\n"

    if data["active_hours_top3"]:
        msg += "\U0001f550 *Active hours:*\n"
        for h, n in data["active_hours_top3"]:
            msg += f"   {h:02d}:00 ({n} interactions)\n"
        msg += "\n"

    if data["snooze_patterns"]:
        msg += "\u23f0 *Snooze patterns:*\n"
        for cat, count, avg_min in data["snooze_patterns"][:3]:
            msg += f"   {cat}: {count}x (avg {int(avg_min)}m)\n"
        msg += "\n"

    if data["category_focus"]:
        msg += "\U0001f4cc *Top categories:*\n"
        sorted_cats = sorted(data["category_focus"].items(), key=lambda x: -x[1])
        for cat, n in sorted_cats[:5]:
            msg += f"   {cat}: {n} tasks\n"
        msg += "\n"

    msg += f"_Use these insights to tweak `/settings` for better defaults._"
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())


# ── v6.1: ADMIN MODE (owner-only) ─────────────────────
async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the user their own Telegram ID — needed to claim admin."""
    uid = update.message.from_user.id
    name = update.message.from_user.first_name or "there"
    admin = get_admin_id()
    status = "\u2705 You are the admin." if is_admin(uid) else (
        "\U0001f513 No admin set yet — use /claimadmin to become admin."
        if admin is None else "\U0001f512 Admin already set (not you)."
    )
    await update.message.reply_text(
        f"\U0001f464 *Your Info*\n\n"
        f"Name: {name}\n"
        f"Telegram ID: `{uid}`\n\n"
        f"{status}",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def claimadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """First user to run this becomes the permanent admin."""
    uid = update.message.from_user.id
    admin = get_admin_id()
    if admin is not None:
        if uid == admin:
            await update.message.reply_text("\u2705 You're already the admin.",
                                            reply_markup=main_menu())
        else:
            await update.message.reply_text("\U0001f512 An admin is already set. Access denied.",
                                            reply_markup=main_menu())
        return
    set_admin_id(uid)
    await update.message.reply_text(
        f"\U0001f451 *You are now the admin!*\n\n"
        f"Your ID `{uid}` is locked in.\n"
        f"Use /admin to open the control panel.\n"
        f"Admin commands are invisible to everyone else.",
        parse_mode="Markdown", reply_markup=main_menu()
    )

def admin_only(func):
    """Decorator: block non-admins from admin commands."""
    async def wrapper(update, context):
        uid = update.message.from_user.id
        if not is_admin(uid):
            # Silent denial — pretend the command doesn't exist
            await update.message.reply_text("\u2753 Unknown command. Type /help.",
                                            reply_markup=main_menu())
            return
        return await func(update, context)
    return wrapper

@admin_only
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The admin control panel."""
    uid = update.message.from_user.id
    in_mode = _admin_mode.get(uid, False)
    stats = get_data_stats(uid)
    msg = (
        "\U0001f6e0 *ADMIN CONTROL PANEL*\n"
        f"Debug mode: {'\U0001f7e2 ON' if in_mode else '\u26aa OFF'}\n\n"
        "\U0001f4ca *Your Data:*\n"
        f"  Active tasks: {stats['active_tasks']}\n"
        f"  Completed: {stats['done_tasks']}\n"
        f"  Habits: {stats['habits']}\n"
        f"  Memories: {stats['memories']}\n"
        f"  Goals: {stats['goals']}\n"
        f"  Highest task ID: {stats['max_task_id']}\n"
        f"  Learning logs: {stats['completions_logged']} done, {stats['snoozes_logged']} snoozed\n\n"
        "\U0001f527 *Commands:*\n"
        "/adminmode \u2014 toggle debug/admin mode\n"
        "/resettasks \u2014 delete all tasks + reset IDs to 0\n"
        "/resetmemory \u2014 wipe all memories\n"
        "/resethabits \u2014 wipe all habits + streaks\n"
        "/resetlearning \u2014 wipe preference-learning data\n"
        "/resetall \u2014 \u26a0\ufe0f nuke EVERYTHING + reset IDs\n"
        "/sql <query> \u2014 run a read-only SQL query (debug)\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())

@admin_only
async def adminmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle a verbose debug mode for the admin."""
    uid = update.message.from_user.id
    _admin_mode[uid] = not _admin_mode.get(uid, False)
    on = _admin_mode[uid]
    # Also flip the existing /debug interaction tracer
    import debug_system as _dbg
    if on != _dbg.is_debug_on(uid):
        _dbg.toggle_debug(uid)
    await update.message.reply_text(
        f"\U0001f527 Admin debug mode is now *{'ON' if on else 'OFF'}*.\n"
        + ("You'll see intent, entities, parsed date/time, and SQL traces."
           if on else "Verbose output off."),
        parse_mode="Markdown", reply_markup=main_menu()
    )

@admin_only
async def resettasks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    # Require confirmation
    set_pending_action(uid, "admin_reset_tasks", {"action": "admin_reset_tasks"})
    await update.message.reply_text(
        "\u26a0\ufe0f *Reset ALL tasks?*\n\n"
        "This deletes every task and resets task IDs back to start from 1.\n"
        "Memories, habits, and learning data are kept.\n\n"
        "Type *YES RESET* to confirm, or anything else to cancel.",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )

@admin_only
async def resetmemory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    n = reset_all_memories(uid)
    await update.message.reply_text(f"\U0001f5d1 Wiped {n} memories.",
                                    reply_markup=main_menu())

@admin_only
async def resethabits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    n = reset_all_habits(uid)
    await update.message.reply_text(f"\U0001f5d1 Wiped {n} habits and their logs.",
                                    reply_markup=main_menu())

@admin_only
async def resetlearning_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    n = reset_learning_data(uid)
    await update.message.reply_text(f"\U0001f5d1 Wiped {n} learning-log entries.",
                                    reply_markup=main_menu())

@admin_only
async def resetall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    set_pending_action(uid, "admin_reset_all", {"action": "admin_reset_all"})
    await update.message.reply_text(
        "\u26a0\u26a0 *NUCLEAR RESET* \u26a0\u26a0\n\n"
        "This deletes EVERYTHING: tasks, memories, habits, goals, learning data.\n"
        "Task IDs reset to start from 1.\n\n"
        "Type *YES NUKE EVERYTHING* to confirm.",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove()
    )

@admin_only
async def sql_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Read-only SQL for debugging. SELECT only."""
    uid = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            "Usage: /sql <SELECT query>\nExample: /sql SELECT id,title,due_time FROM tasks WHERE done=0",
            reply_markup=main_menu()
        )
        return
    query = " ".join(context.args)
    if not query.strip().lower().startswith("select"):
        await update.message.reply_text("\u274c Only SELECT queries allowed (read-only).",
                                        reply_markup=main_menu())
        return
    try:
        import sqlite3
        conn = sqlite3.connect("planner.db")
        c = conn.cursor()
        c.execute(query)
        rows = c.fetchall()
        conn.close()
        if not rows:
            await update.message.reply_text("(no rows)", reply_markup=main_menu())
            return
        out = "\n".join(str(r) for r in rows[:30])
        if len(rows) > 30:
            out += f"\n... and {len(rows)-30} more rows"
        await update.message.reply_text(f"```\n{out}\n```", parse_mode="Markdown",
                                        reply_markup=main_menu())
    except Exception as e:
        await update.message.reply_text(f"\u274c SQL error: {str(e)[:200]}",
                                        reply_markup=main_menu())


# ── v7.0: Review stale tasks ──────────────────────────
async def review_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show stale tasks (3+ days overdue) for bulk decisions."""
    user_id = update.message.from_user.id
    stale = get_stale_tasks(user_id, days_threshold=3)
    if not stale:
        await update.message.reply_text(
            "✨ *Nothing stale!*\n\nNo tasks are sitting 3+ days overdue. Nice and clean.",
            parse_mode="Markdown", reply_markup=main_menu()
        )
        return
    msg = f"🧹 *Review: {len(stale)} stale task(s)*\n"
    msg += "_(3+ days past due — decide what to do)_\n\n"
    for t in stale[:10]:
        tid, title, ddate, dtime, cat, prio, scount, fcount = t
        emoji = "🔴" if prio == "high" else "🟢" if prio == "low" else "🟡"
        # days overdue
        try:
            days_over = (datetime.now(IST).date() -
                         datetime.strptime(ddate, "%Y-%m-%d").date()).days
        except Exception:
            days_over = "?"
        msg += f"{emoji} *[{tid}]* {title}\n"
        msg += f"   📅 {ddate} ({days_over}d overdue)"
        if scount:
            msg += f" • snoozed {scount}x"
        msg += "\n\n"
    msg += ("*What you can do:*\n"
            "• `carryforward` — move all to today\n"
            "• `delete <id>` — drop ones you won't do\n"
            "• `reschedule <id>` — pick a new time\n"
            "• `done <id>` — if actually finished")
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())


# ── v8.0: Proactive / Wellness Commands ───────────────
WELLNESS_MESSAGES = {
    "water": ["💧 Time to drink some water! Stay hydrated.",
              "💧 Hydration check — grab a glass of water.",
              "💧 Quick water break? Your body will thank you."],
    "break": ["🧘 You've been at it a while. Take a 5-minute break.",
              "🧘 Stand up, stretch, walk around for a moment.",
              "🧘 Brain needs rest — step away for 5 minutes."],
    "eyes":  ["👀 Look away from the screen — focus on something 20 feet away for 20 seconds.",
              "👀 Eye break! Blink a few times and rest your eyes.",
              "👀 20-20-20 rule: look 20ft away for 20 seconds."],
    "posture": ["🪑 Posture check — sit up straight, roll your shoulders back.",
                "🪑 Straighten your back and relax your shoulders."],
}

async def wellness_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Control wellness reminders (water, break, eyes, posture)."""
    user_id = update.message.from_user.id
    prefs = get_wellness_prefs(user_id)
    if not context.args:
        status = "🟢 ON" if prefs["on"] else "⚪ OFF"
        await update.message.reply_text(
            f"🌿 {b('Wellness Reminders')}\n\n"
            f"Status: {status}\n"
            f"Interval: every {prefs['interval']} min\n"
            f"Types: {esc(prefs['types'])}\n\n"
            f"{b('Commands:')}\n"
            f"{code('wellness on')} / {code('wellness off')}\n"
            f"{code('wellness interval 60')} — change frequency\n"
            f"{code('wellness water')} / {code('break')} / {code('eyes')} / {code('all')}\n\n"
            f"<i>Only sent during your awake hours — never during quiet hours.</i>",
            parse_mode=HTML, reply_markup=main_menu()
        )
        return
    arg = context.args[0].lower()
    if arg in ("on", "enable", "start"):
        set_wellness(user_id, on=True)
        await update.message.reply_text(
            f"🟢 Wellness reminders {b('ON')}. I'll nudge you to take care of yourself "
            f"every {prefs['interval']} min during your active hours.",
            parse_mode=HTML, reply_markup=main_menu())
    elif arg in ("off", "disable", "stop"):
        set_wellness(user_id, on=False)
        await update.message.reply_text(
            f"⚪ Wellness reminders {b('OFF')}.",
            parse_mode=HTML, reply_markup=main_menu())
    elif arg == "interval" and len(context.args) > 1:
        try:
            mins = int(context.args[1])
            if mins < 15:
                await update.message.reply_text("Minimum interval is 15 minutes.",
                                                reply_markup=main_menu())
                return
            set_wellness(user_id, interval=mins)
            await update.message.reply_text(
                f"🌿 Wellness interval set to every {b(str(mins) + ' min')}.",
                parse_mode=HTML, reply_markup=main_menu())
        except ValueError:
            await update.message.reply_text("Usage: wellness interval <minutes>",
                                            reply_markup=main_menu())
    elif arg in ("water", "break", "eyes", "posture", "all"):
        set_wellness(user_id, types=arg, on=True)
        await update.message.reply_text(
            f"🌿 Wellness type set to {b(arg)} and reminders turned ON.",
            parse_mode=HTML, reply_markup=main_menu())
    else:
        await update.message.reply_text(
            "Usage: wellness on|off|interval <min>|water|break|eyes|all",
            reply_markup=main_menu())


async def proactive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Control panel for all proactive features."""
    user_id = update.message.from_user.id
    w = get_wellness_prefs(user_id)
    prefs = get_user_prefs(user_id)
    msg = (
        f"🤖 {b('Proactive Features')}\n\n"
        f"These are things BAKA does on its own to help you:\n\n"
        f"🔔 {b('Reminders')} — always on\n"
        f"   <i>Reminds until done, escalates near deadlines</i>\n\n"
        f"👀 {b('Follow-ups')} — always on\n"
        f"   <i>Asks 'did you finish?' after tasks pass</i>\n\n"
        f"🌙 {b('End-of-day summary')} — 21:00 daily\n"
        f"   <i>Lists what's still pending today</i>\n\n"
        f"🌿 {b('Wellness nudges')} — {'🟢 ON' if w['on'] else '⚪ OFF'}\n"
        f"   <i>Water/break/eye reminders. Toggle: {code('wellness on')}</i>\n\n"
        f"⏰ {b('Quiet hours')} — {esc(prefs['quiet_start'])}–{esc(prefs['quiet_end'])}\n"
        f"   <i>No proactive messages during this window</i>\n\n"
        f"💡 High-priority tasks due soon get a heads-up automatically."
    )
    await update.message.reply_text(msg, parse_mode=HTML, reply_markup=main_menu())

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
    app.add_handler(CommandHandler("habits", habits_cmd))
    app.add_handler(CommandHandler("streak", streak_cmd))
    app.add_handler(CommandHandler("habitlog", habitlog_cmd))
    app.add_handler(CommandHandler("addhabit", addhabit_cmd))
    app.add_handler(CommandHandler("skiphabit", skiphabit_cmd))
    app.add_handler(CommandHandler("insights", insights_cmd))
    app.add_handler(CommandHandler("review", review_cmd))
    app.add_handler(CommandHandler("wellness", wellness_cmd))
    app.add_handler(CommandHandler("proactive", proactive_cmd))
    # v6.1 admin commands
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("claimadmin", claimadmin_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("adminmode", adminmode_cmd))
    app.add_handler(CommandHandler("resettasks", resettasks_cmd))
    app.add_handler(CommandHandler("resetmemory", resetmemory_cmd))
    app.add_handler(CommandHandler("resethabits", resethabits_cmd))
    app.add_handler(CommandHandler("resetlearning", resetlearning_cmd))
    app.add_handler(CommandHandler("resetall", resetall_cmd))
    app.add_handler(CommandHandler("sql", sql_cmd))
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
                    text=f"🔔 {b('Reminder!')}\n\n📌 {b(title)}\n"
                         f"<i>📅 {esc(due_date or 'No date')} · ⏰ {esc(due_time or 'No time')}</i>",
                    parse_mode=HTML,
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

    # ── v7.0: "Did you finish?" follow-up check ──────────
    async def check_did_you_finish(context):
        """Ask users if they completed tasks whose time has passed."""
        try:
            tasks = get_tasks_for_followup()
            for t in tasks:
                tid, uid, title, ddate, dtime, fcount, fsent, category = t
                # Respect quiet hours
                if is_quiet_hours(uid):
                    continue
                buttons = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Yes, done!", callback_data=f"finish_yes:{tid}"),
                        InlineKeyboardButton("❌ Not yet", callback_data=f"finish_no:{tid}"),
                    ],
                    [
                        InlineKeyboardButton("⏰ Snooze 1h", callback_data=f"snooze:{tid}:60"),
                        InlineKeyboardButton("📅 Tomorrow", callback_data=f"postpone:{tid}"),
                    ],
                ])
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=f"👀 *Follow-up*\n\nDid you finish:\n📌 *{title}*?\n"
                             f"_(was due {ddate} at {dtime})_",
                        parse_mode="Markdown",
                        reply_markup=buttons
                    )
                    mark_followup_sent(tid)
                except Exception as e:
                    logger.error(f"Follow-up send failed: {e}")
        except Exception as e:
            logger.error(f"check_did_you_finish failed: {e}")

    app.job_queue.run_repeating(check_did_you_finish, interval=900, first=120)

    # ── v7.0: End-of-day unresolved summary ──────────────
    async def end_of_day_summary(context):
        """At 21:00, list tasks still unresolved today."""
        try:
            for uid in get_all_active_user_ids():
                if is_quiet_hours(uid):
                    continue
                pending = get_unresolved_today(uid)
                if not pending:
                    continue
                msg = f"🌙 *End of day check-in*\n\n"
                if len(pending) == 1:
                    msg += f"You have 1 task still pending today:\n\n"
                else:
                    msg += f"You have {len(pending)} tasks still pending today:\n\n"
                for tid, title, dtime, cat, prio in pending[:8]:
                    emoji = "🔴" if prio == "high" else "🟢" if prio == "low" else "🟡"
                    msg += f"{emoji} [{tid}] {title}" + (f" ⏰ {dtime}" if dtime else "") + "\n"
                msg += "\n_Mark them done, or they'll carry to tomorrow._"
                try:
                    await context.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"end_of_day_summary failed: {e}")

    app.job_queue.run_daily(end_of_day_summary,
        time=datetime.strptime("21:00", "%H:%M").time(),
        name="end_of_day_summary")

    # ── v8.0: Wellness reminders (opt-in) ────────────────
    import random as _random
    async def wellness_reminder(context):
        """Send opt-in wellness nudges, respecting quiet hours + interval."""
        try:
            for uid in get_wellness_enabled_users():
                if is_quiet_hours(uid):
                    continue
                w = get_wellness_prefs(uid)
                # Respect the interval since last wellness message
                if w["last"]:
                    try:
                        last = IST.localize(datetime.strptime(w["last"], "%Y-%m-%d %H:%M"))
                        mins_since = (datetime.now(IST) - last).total_seconds() / 60
                        if mins_since < w["interval"]:
                            continue
                    except (ValueError, AttributeError):
                        pass
                # Choose a message type
                types = w["types"]
                if types == "all":
                    pool = []
                    for msgs in WELLNESS_MESSAGES.values():
                        pool.extend(msgs)
                else:
                    pool = WELLNESS_MESSAGES.get(types, WELLNESS_MESSAGES["water"])
                text = _random.choice(pool)
                try:
                    await context.bot.send_message(chat_id=uid, text=text)
                    mark_wellness_sent(uid)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"wellness_reminder failed: {e}")

    # Check every 15 min; the per-user interval gate does the real spacing
    app.job_queue.run_repeating(wellness_reminder, interval=900, first=300)

    # ── v8.0: Proactive high-priority deadline nudge ─────
    async def priority_nudge(context):
        """Heads-up for high-priority tasks due within 3 hours (once each)."""
        try:
            for uid in get_all_active_user_ids():
                if is_quiet_hours(uid):
                    continue
                soon = get_high_priority_soon(uid, hours=3)
                for tid, title, dtime, fcount in soon:
                    # only nudge once — reuse followup_sent as the 'nudged' marker
                    if fcount and fcount > 0:
                        continue
                    buttons = InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Done", callback_data=f"done:{tid}"),
                        InlineKeyboardButton("🔨 Break down", callback_data=f"dobreak:{tid}"),
                    ]])
                    try:
                        await context.bot.send_message(
                            chat_id=uid,
                            text=f"🔴 {b('Heads up')} — high-priority task coming up:\n\n"
                                 f"📌 {b(title)}\n<i>⏰ Due at {esc(dtime)}</i>\n\n"
                                 f"Want to start now, or break it into steps?",
                            parse_mode=HTML, reply_markup=buttons)
                        mark_followup_sent(tid)
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"priority_nudge failed: {e}")

    app.job_queue.run_repeating(priority_nudge, interval=1800, first=600)

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
    logger.info("🤖 BAKA is online!")
    print("🤖 BAKA is running! Check bot.log for logs.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()