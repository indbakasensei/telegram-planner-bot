import os
import re
import sys
import time
import logging
import logging.handlers
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler, Defaults
)
import pytz
from database import (
    init_db, add_task, get_tasks, get_tasks_by_date, get_tasks_by_week,
    mark_done, delete_task, update_task, get_task_by_id,
    search_tasks_by_title, task_exists,
    save_memory, get_memory, get_all_memories, search_memories,
    search_memories_smart, delete_memory,
    add_goal, get_goals, get_goals_full, update_goal_progress, get_done_today_count,
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
    search_all, save_template, get_template, get_all_templates,
    delete_template, get_weekly_report_data, export_user_data,
    mark_as_deadline, get_pending_deadlines, mark_buffer_sent, parse_buffer_sent,
    log_missed_capability, get_missed_capabilities, mark_missed_reviewed,
    get_user_context_for_ai,
    add_observation, get_pending_observations, respond_to_observation, get_observation,
    add_materials, get_materials, mark_material_acquired, delete_material,
    find_material_by_name, add_worklog, get_worklog, get_last_worklog_days,
    compute_project_progress, get_project_overview, get_active_projects,
    get_all_pending_materials,
    get_wellness_enabled_users, count_tasks_at_time, get_high_priority_soon,
    verify_schema_integrity
)
from preferences import analyze_user, suggest_time_for_task, suggest_interval_for_task
from baka_brain import (
    get_baka_response, check_api_status,
    chat_with_ai, suggest_tasks, analyze_productivity,
    generate_study_plan, extract_memory_key,
    generate_daily_plan, generate_weekly_plan, benchmark_ai, think_freely,
    call_main, call_fast, call_think, call_vision,
    generate_image, generate_video, benchmark_all_models,
    MODEL_MAIN, MODEL_FAST, MODEL_THINK, MODEL_VISION, MODEL_IMAGE,
    AI_PROVIDER,
    ENABLE_VISION, ENABLE_IMAGE_GEN,
    generate_task_breakdown, suggest_reschedule_time,
    generate_structured_plan
)
from fmt import (HTML, esc, b, i, code, task_line, confirm_box, header,
                 DIVIDER)
from telegram.error import BadRequest
import ui as UI
from conversation_state import (
    get_state, get_context, clear_state, update_context,
    add_history, get_history,
    set_pending_action, get_pending_action,
    set_gathering, get_gathering,
    set_editing, get_editing_id, claims_messages
)
from date_parser import parse_all, validate_datetime
from scheduler import get_due_tasks, get_tasks_needing_followup, auto_carry_forward, is_quiet_hours
import debug_system as dbg
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from async_bridge import run_blocking
from notification_service import TelegramSender, safe_edit_message_text, safe_answer_callback_query
import instance_lock
from core.intent import IntentEngine, ConversationContext, Intent
from core.routing import RoutingLayer
from core.offline import OfflineEngine, RequestContext, build_enabled_registry
from core.actions.create_task import format_summary as _offline_format_summary
from core.actions.delete_task import format_preview as _offline_format_delete_preview
from core.storage import Storage
from core import feature_flags
# v15.0-beta.1: Workspace OS production wiring. Import is side-effect-free
# and offline; nothing here runs unless feature_flags.WORKSPACE is ON, so
# the flag-OFF path stays byte-identical to v14.26.
from core.workspace import app as workspace_app
# v15.1: Workspace groups -- usable project/game/goal ↔ private Telegram
# forum-group projection. These commands are always available (not gated by
# the WORKSPACE orchestrator flag); they only act when the owner invokes them.
import asyncio
from core.workspace import groups_app as ws_groups
from core.workspace.adapters.projection import TelegramProjection

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# v14.21: dedicated developer debug log. Production logging is
# UNCHANGED -- bot.log and the console stay INFO-filtered (their
# handlers are pinned to INFO below); debugbot.log additionally
# captures DEBUG records (the Intent/Routing/Offline decision blocks,
# [Offline]/[Offline Commit] traces, etc.) in a rotating, gitignored,
# safe-to-delete file. Created lazily on first DEBUG record; the
# log sanitizer attaches to it like every other root handler (it is
# registered before install_log_sanitizer() runs below). Delete it
# any time -- dev_reset.sh does. See DEBUGGING.md "Debug logging
# workflow".
for _h in logging.getLogger().handlers:
    _h.setLevel(logging.INFO)
_debug_handler = logging.handlers.RotatingFileHandler(
    "debugbot.log", maxBytes=2_000_000, backupCount=3, delay=True,
    encoding="utf-8")
_debug_handler.setLevel(logging.DEBUG)
_debug_handler.setFormatter(
    logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(_debug_handler)
logging.getLogger().setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)

# v14.12: production log hygiene. httpx emits one INFO line per Telegram
# API request -- the exact lines that used to leak the bot token into
# bot.log (log_sanitizer.py's BOT_TOKEN_URL_RE fix masks them now, but
# they are also pure per-poll noise at INFO). apscheduler chatters about
# every job tick. Both keep WARNING+ so real problems still surface;
# drop these lines to DEBUG-diagnose the transport itself.
for _noisy in ("httpx", "httpcore", "apscheduler"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# v14.0 Stage 1: Intent Engine, Shadow Mode only (see core/intent/__init__.py).
# Stateless, so one process-wide instance is safe to share across requests.
intent_engine = IntentEngine()

# v14.1B: Routing Layer, decision-logging only (see core/routing/__init__.py).
# ALWAYS resolves to Legacy -- see router.py's module docstring. Stateless.
routing_layer = RoutingLayer()

# v14.1C/v14.2: Storage Facade + Offline Engine (see core/storage/__init__.py,
# core/offline/__init__.py). Stateless. Gated entirely by core/feature_flags.py
# (all OFF today) -- see the integration point in handle_message() below.
# v14.9: the registry is built per-domain from the feature flags
# (build_enabled_registry, ADR-013) -- a domain whose flag is OFF has no
# specs registered at all, so its messages resolve to unsupported_intent/
# unsupported_action and fall through to Legacy exactly as before.
storage = Storage()
offline_engine = OfflineEngine(storage, registry=build_enabled_registry())

# v12.1: Install log sanitizer BEFORE anything else logs.
# Redacts bot tokens, API keys, and user IDs (admin → "admin", others → "user_***XXX").
try:
    from log_sanitizer import install_log_sanitizer
    install_log_sanitizer()  # reads admin_id.txt automatically
except Exception as _e:
    # Non-fatal — logs will be more verbose but the bot still runs
    logger.warning(f"log sanitizer not installed: {_e}")

# Bulletproof .env loading (matches baka_brain.py pattern)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(_env_path)
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

_HTML_TAG_RE = re.compile(r"<[^>]+>")


async def _reply_rich(message, text, **kwargs):
    """v14.12: send rich HTML with a graceful degradation path -- if
    Telegram ever rejects an entity (e.g. an older Bot API server and
    <blockquote expandable>), resend the same content stripped of tags
    rather than letting /help or /selftest crash."""
    try:
        await message.reply_text(text, parse_mode=HTML, **kwargs)
    except BadRequest:
        await message.reply_text(_HTML_TAG_RE.sub("", text), **kwargs)


def is_admin(uid):
    admin = get_admin_id()
    return admin is not None and uid == admin

# In-memory flag: is the admin currently in debug/admin mode?
_admin_mode = {}
# v14.25: in-memory manual test-run sessions (Developer Center -> Run Tests).
# user_id -> {"index": int, "results": [ {test_id, status, bug_id} ], "awaiting_note": bool}
_test_runs = {}
IST = ZoneInfo("Asia/Kolkata")

# v13.2: single source of truth for the startup log line (see main()).
# Deliberately not threaded into user-facing text like /help -- that's
# Telegram UX, out of scope for the infrastructure sprint that added
# this; see CHANGELOG.md.
BAKA_VERSION = "15.1.0-alpha.7"


# ── Menus ─────────────────────────────────────────────
def main_menu():
    keyboard = [
        ['🏠 Dashboard', '📌 Add Task'],
        ['📅 Today', '📋 My Tasks', '📆 Overdue'],
        ['🎯 Goals', '🌱 Habits', '📊 Stats'],
        ['✅ Done', '🗑 Delete', '✏️ Edit'],
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
        f"👑 _First time? Send /claimadmin to become the owner._\n\n"
        f"Type /help to see all features, or just start talking!",
        parse_mode="Markdown", reply_markup=main_menu()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """v14.12 design; v14.18 (Phase 5R): presentation extracted to
    ui.help_cards() -- the handler only decides admin visibility and
    sends. Known-broken analytics commands stay unadvertised."""
    user_id = update.message.from_user.id
    msg1, msg2 = UI.help_cards(BAKA_VERSION, is_admin(user_id))
    await _reply_rich(update.message, msg1)
    await _reply_rich(update.message, msg2, reply_markup=main_menu())


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
    result = await run_blocking(analyze_productivity, tasks)
    await update.message.reply_text(f"📊 *Analysis:*\n\n{result}", parse_mode="Markdown", reply_markup=main_menu())

async def suggest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /suggest <goal>")
        return
    goal = " ".join(context.args)
    await update.message.reply_text("🧠 Generating suggestions...")
    result = await run_blocking(suggest_tasks, goal)
    await update.message.reply_text(f"🎯 *Tasks for: {goal}*\n\n{result}", parse_mode="Markdown", reply_markup=main_menu())

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """v9.1: Enhanced AI diagnostic with benchmarking."""
    user_id = update.message.from_user.id
    # Check if user wants full benchmark
    full = bool(context.args and context.args[0].lower() in ("full", "benchmark", "deep"))

    thinking = await update.message.reply_text(
        f"🔍 Running {'full benchmark (6 tests)' if full else 'quick diagnostic (3 tests)'}..."
    )

    # Basic connectivity check
    result = await run_blocking(check_api_status)

    if result["status"] != "online":
        # v14.18 (Phase 5R): presentation extracted to ui.ai_status_error_card().
        await thinking.delete()
        await update.message.reply_text(UI.ai_status_error_card(result),
                                        parse_mode=HTML, reply_markup=main_menu())
        return

    # Run benchmark
    bench = await run_blocking(benchmark_ai, quick=not full)

    # v14.18 (Phase 5R): presentation extracted to ui.ai_status_card().
    text, kb = UI.ai_status_card(result, bench, full)
    await thinking.delete()
    await update.message.reply_text(text, parse_mode=HTML, reply_markup=kb)


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

        # v10.1: mark as deadline if user phrased it that way
        is_deadline = bool(data.get("is_deadline"))
        if is_deadline:
            try:
                mark_as_deadline(task_id, user_id, True)
            except Exception:
                pass

        rec_msg = f"\n🔁 Repeats: {esc(rec)}" if rec else ""
        if is_deadline:
            # Compute time-to-deadline for a friendly preview
            try:
                deadline_dt = datetime.strptime(
                    f"{date} {data.get('time')}", "%Y-%m-%d %H:%M").replace(tzinfo=IST)
                hours_left = (deadline_dt - datetime.now(IST)).total_seconds() / 3600
                if hours_left > 24:
                    countdown = f"{int(hours_left/24)} days"
                else:
                    countdown = f"{int(hours_left)} hours"
            except Exception:
                countdown = "soon"
            deadline_msg = (f"\n\n⏳ {b('Deadline mode ON')} — I'll ping you {b('before')} "
                           f"the deadline (7d/3d/1d/6h/1h ahead) so you can plan, "
                           f"not just panic at the last minute.\n"
                           f"<i>Time until deadline: {esc(countdown)}</i>")
        else:
            deadline_msg = ""

        await update.message.reply_text(
            f"✅ {b('Saved!')}\n\n"
            f"📌 {b(title)}\n"
            f"<i>📅 {esc(date or 'No date')} · ⏰ {esc(data.get('time') or 'No time')} · 🏷 {esc(data.get('category', 'General'))}</i>"
            f"{rec_msg}{deadline_msg}\n\n"
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

    # v14.25: Developer Center Run Tests -- if this admin just marked a test
    # FAILED, the next message is the note. Log a bug and advance. Checked
    # first so it can't be swallowed by intent routing.
    _run = _test_runs.get(user_id)
    if _run and _run.get("awaiting_note") and is_admin(user_id):
        tests = _quick_suite_tests()
        test = tests[_run["index"]]
        bug_id = dbg.report_bug(user_id, f"[REGRESSION {test.test_id}] {user_input}")
        _run["results"].append({"test_id": test.test_id, "status": "FAIL",
                                "bug_id": dbg.format_bug_id(bug_id)})
        _run["index"] += 1
        _run["awaiting_note"] = False
        text, kb = _test_run_view(user_id, _run, tests)
        await update.message.reply_text(text, parse_mode=HTML, reply_markup=kb)
        return

    logger.info(f"User {user_id} [{state}]: {user_input}")
    add_history(user_id, "user", user_input)
    # v6.0: log interaction timestamp for active-hours analysis
    try:
        db_log_interaction(user_id, "message")
    except Exception:
        pass

    # v15.0-beta.1: Workspace OS pipeline, feature-flag gated. When
    # WORKSPACE is OFF this branch is skipped entirely -> byte-identical to
    # v14.26. When ON, a recognized workspace utterance is handled by the AI
    # Orchestrator (message -> Interpreter -> Orchestrator -> Entity Engine
    # -> Timeline -> Sync) and we return; anything it doesn't recognize
    # falls through to the Legacy pipeline below (no duplicate commands).
    if feature_flags.WORKSPACE:
        try:
            handled, reply = workspace_app.process_message(user_id, user_input)
        except Exception:
            logger.exception("Workspace pipeline failed; falling back to Legacy")
            handled, reply = False, ""
        if handled:
            await update.message.reply_text(reply, parse_mode=HTML)
            return

    # v14.0 Stage 1: Intent Engine, Shadow Mode (docs/adr/ADR-002-intent-engine.md).
    # v14.1B: Routing Layer, decision-logging only (DRG-001_Intent_Aware_Routing.md,
    # docs/adr/ADR-006-intent-aware-routing.md) -- ALWAYS resolves to Legacy;
    # only the recommendation is logged. Neither step affects routing below.
    intent = None
    try:
        intent = intent_engine.classify(
            text=user_input,
            context=ConversationContext(
                state=state,
                partial_data=get_context(user_id).get("partial_data", {}),
                now=datetime.now(IST),
            ),
        )
        logger.debug(intent)
        routing_decision = routing_layer.route(intent)
        logger.debug(routing_decision)
    except Exception:
        logger.exception("Intent Engine / Routing Layer failed (decision-logging only, non-fatal)")

    # v14.2: Offline Engine, feature-flag gated (core/offline/engine.py,
    # ADR-007). OFF today (OFFLINE_TASKS defaults False, unset in .env) --
    # this whole block is a no-op and behaviour below is byte-for-byte
    # identical to v14.1C. When ON, only the four read-only task actions
    # this Stage implements are handled here; everything else (including
    # other QUERY_TASK phrasings like "/habits") falls through to Legacy
    # exactly as if this block didn't exist -- see engine.py's module
    # docstring for why intent alone isn't enough to gate this precisely.
    # v14.4: task update's second message (the change itself) is gated on
    # conversation state, not Intent Engine classification -- a bare
    # "set time to 6pm" reply carries no reliable EDIT_TASK signal on its
    # own (core/intent/rules.py has no notion of conversation state).
    # Checked before the intent-gated block below, mirroring how Legacy's
    # own handle_message() prioritizes state over intent-based routing.
    # See docs/adr/ADR-009-offline-task-update.md.
    if feature_flags.OFFLINE_TASKS and state == "editing":
        editing_task_id = get_editing_id(user_id)
        if editing_task_id:
            try:
                edit_result = offline_engine.continue_editing(
                    user_input, editing_task_id, user_id, datetime.now(IST)
                )
                if edit_result.success:
                    clear_state(user_id)
                    await update.message.reply_text(
                        edit_result.message, parse_mode=HTML, reply_markup=main_menu()
                    )
                    return
                if "unrecognized_change" not in edit_result.warnings:
                    # A recognized failure (task not found, validation
                    # failed) -- show it directly rather than falling
                    # through to Legacy's AI-mediated handler, which
                    # would likely fail identically on the same input.
                    await update.message.reply_text(
                        edit_result.message or "❌ Something went wrong.",
                        reply_markup=main_menu()
                    )
                    return
                # unrecognized_change: fall through to Legacy's own
                # `if state == "editing":` handler below, unchanged --
                # state is NOT cleared, nothing was written.
            except Exception:
                logger.exception("Offline Engine update failed -- falling through to Legacy")

    # v14.9: the gate is now flag-OR across domains -- which domain's
    # actions actually exist inside offline_engine is decided by
    # build_enabled_registry() at startup (ADR-013), so e.g. with only
    # OFFLINE_HABITS on, task messages resolve no spec and fall through
    # to Legacy untouched.
    # v14.12: ADR-011 Option A applied -- conversation state outranks
    # intent-gated dispatch. In confirming/gathering/editing the message
    # belongs to the state machine (handled below, exactly like Legacy);
    # a mid-confirmation "done 5" re-prompts instead of completing.
    # (The state-gated editing block above is unaffected: it IS state
    # machinery, ADR-009.)
    if ((feature_flags.OFFLINE_TASKS or feature_flags.OFFLINE_HABITS)
            and intent is not None and not claims_messages(state)):
        try:
            offline_result = offline_engine.execute(RequestContext(
                user_id=user_id, text=user_input,
                intent=intent.intent, entities=intent.entities,
                now=datetime.now(IST),
            ))
            if offline_result.success and offline_result.metadata.get("start_editing"):
                # v14.4: task update entry point ("edit task <id>" /
                # "rename task <id>") -- reuses conversation_state.py's
                # existing set_editing()/get_editing_id(), the same
                # mechanism Legacy's own edit_task_cmd() uses. See ADR-009.
                set_editing(user_id, offline_result.metadata["task_id"])
                await update.message.reply_text(
                    offline_result.message, parse_mode=HTML, reply_markup=ReplyKeyboardRemove()
                )
                return
            if offline_result.success and offline_result.metadata.get("needs_confirmation"):
                # v14.3: task creation always confirms before writing, same
                # as Legacy's execute_task_action() -- reuses conversation_state.py's
                # existing confirming-state machinery exactly as Legacy does,
                # with a distinct action_type so the confirming-state handler
                # below can commit via the Storage Facade instead of Legacy's
                # own database.add_task() call. See ADR-008.
                # v14.5: task delete ALSO confirms -- deliberately, unlike
                # Legacy's real delete_task_cmd() (verified: no confirmation
                # at all). See ADR-010.
                pending_action_type = ("offline_delete_task" if intent.intent is Intent.DELETE_TASK
                                       else "offline_add_task")
                set_pending_action(user_id, pending_action_type,
                                    offline_result.metadata["pending_data"])
                await update.message.reply_text(
                    offline_result.message, parse_mode=HTML, reply_markup=yes_no_menu()
                )
                return
            if offline_result.success:
                await update.message.reply_text(
                    offline_result.message, parse_mode=HTML, reply_markup=main_menu()
                )
                return
        except Exception:
            logger.exception("Offline Engine execution failed -- falling through to Legacy")
    # Existing routing continues unchanged below (Legacy).

    # ── Menu buttons ──
    menu_map = {
        '🏠 Dashboard': lambda: dashboard_cmd(update, context),
        '📌 Add Task': lambda: ask_for_task(update, user_id),
        '📋 My Tasks': lambda: list_tasks(update, context),
        '📋 List Tasks': lambda: list_tasks(update, context),
        '📅 Today': lambda: today_tasks(update, context),
        '🗓 This Week': lambda: week_tasks(update, context),
        '📆 Overdue': lambda: overdue_cmd(update, context),
        '🎯 Goals': lambda: goals_dash_cmd(update, context),
        '🌱 Habits': lambda: habits_cmd(update, context),
        '📊 Stats': lambda: _stats_entry(update, context),
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
        # v14.3: Offline task creation's own confirm step (ADR-008). Same
        # positive/negative word lists as the generic branch below, kept
        # local to this branch since it commits via the Storage Facade
        # (offline_engine.execute_pending), not Legacy's execute_task_action().
        if action_type == "offline_add_task":
            positive_o = any(w in user_input.lower() for w in
                          ["yes", "yeah", "yep", "haan", "ha", "ok", "okay", "sure",
                           "✅", "save", "confirm", "bilkul", "do it", "kar do", "theek"])
            negative_o = any(w in user_input.lower() for w in
                          ["no", "nahi", "nope", "cancel", "❌", "mat", "don't", "dont", "band"])
            if positive_o:
                clear_state(user_id)
                commit_result = offline_engine.execute_pending("offline_add_task", data, user_id)
                await update.message.reply_text(
                    commit_result.message, parse_mode=HTML, reply_markup=main_menu()
                )
            elif negative_o:
                clear_state(user_id)
                await update.message.reply_text("❌ Cancelled!", reply_markup=main_menu())
            else:
                await update.message.reply_text(
                    _offline_format_summary(data) + "\n\nSay yes to save, no to cancel.",
                    parse_mode=HTML, reply_markup=yes_no_menu()
                )
            return
        # v14.5: Offline task delete's own confirm step (ADR-010) --
        # deliberately added beyond Legacy's real (verified) no-confirm
        # delete_task_cmd() behavior. Same word lists, same layering as
        # offline_add_task above.
        if action_type == "offline_delete_task":
            positive_d = any(w in user_input.lower() for w in
                          ["yes", "yeah", "yep", "haan", "ha", "ok", "okay", "sure",
                           "✅", "save", "confirm", "bilkul", "do it", "kar do", "theek"])
            negative_d = any(w in user_input.lower() for w in
                          ["no", "nahi", "nope", "cancel", "❌", "mat", "don't", "dont", "band"])
            if positive_d:
                clear_state(user_id)
                commit_result = offline_engine.execute_pending("offline_delete_task", data, user_id)
                await update.message.reply_text(
                    commit_result.message, parse_mode=HTML, reply_markup=main_menu()
                )
            elif negative_d:
                clear_state(user_id)
                await update.message.reply_text("❌ Cancelled!", reply_markup=main_menu())
            else:
                task_for_preview = storage.tasks.get_by_id(data.get("task_id"), user_id)
                if task_for_preview is None:
                    clear_state(user_id)
                    await update.message.reply_text(
                        "❌ That task no longer exists.", reply_markup=main_menu()
                    )
                else:
                    await update.message.reply_text(
                        _offline_format_delete_preview(task_for_preview)
                        + "\n\nSay yes to delete, no to cancel.",
                        parse_mode=HTML, reply_markup=yes_no_menu()
                    )
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
            result = await run_blocking(get_baka_response,
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
        result = await run_blocking(get_baka_response,
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
        (["search ", "find ", "look for "], search_cmd, None),
        (["think ", "ask ", "what should i ", "should i ",
          "help me decide", "what do you think", "your opinion"], think_cmd, None),
        (["image ", "generate image", "create image", "draw "], image_cmd, None),
        (["need ", "materials ", "add materials", "components ",
          "add components", "i need "], need_cmd, None),
        (["got ", "have ", "acquired ", "purchased ",
          "bought "], got_cmd, None),
        (["worklog ", "log ", "note ", "progress on ",
          "update on "], worklog_cmd, None),
        (["started ", "starting ", "begin work on ",
          "starting work on "], started_cmd, None),
        (["finished ", "completed ", "done with ",
          "finished the ", "khatam "], finished_cmd, None),
        (["project ", "how is my ", "status of ",
          "how is the "], project_cmd, None),
        (["video ", "generate video", "create video", "make a video"], video_cmd, None),
        (["savetemplate ", "save template "], savetemplate_cmd, None),
        (["template ", "use template "], template_cmd, None),
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
        ("dashboard", "home", "show dashboard", "open dashboard",
         "main menu", "overview"): dashboard_cmd,
        ("goals", "my goals", "show goals", "goal dashboard"): goals_dash_cmd,
        ("stats", "statistics", "productivity dashboard",
         "my stats", "show stats"): _stats_entry,
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
        ("templates", "my templates", "show templates", "list templates"): template_cmd,
        ("projects", "my projects", "show projects",
         "list projects", "active projects"): project_cmd,
        ("shopping", "shopping list", "my shopping list",
         "what do i need to buy", "buy list"): shopping_cmd,
        ("export", "export data", "backup", "export my data"): export_cmd,
        ("deadline mode", "what is deadline mode",
         "deadline help", "deadlines"): deadline_cmd,
        ("suggestions", "my suggestions", "ai suggestions",
         "what do you suggest", "show suggestions"): suggestions_cmd,
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

    # v11.0: fetch rich user context so the AI reasons WITH user data
    try:
        _user_context = get_user_context_for_ai(user_id)
    except Exception:
        _user_context = None

    result = await run_blocking(get_baka_response, user_input, existing_tasks, get_history(user_id),
                                memories, user_context=_user_context, user_id=user_id)
    intent = result.get("intent", "CHAT").upper()
    entities = result.get("entities", {})
    missing = result.get("missing", [])
    needs_confirm = result.get("needs_confirm", False)
    response_text = result.get("response", "")
    confirm_summary = result.get("confirm_summary")
    confidence = result.get("confidence", 1.0)

    # v11.0 prep: Auto-log missed capabilities for later feature mining.
    # Triggers: low confidence, OR AI said CHAT but message has action verbs.
    try:
        _msg_lower = user_input.lower()
        _action_verbs = ("remind", "schedule", "add ", "create", "make ",
                         "show ", "list ", "find ", "search ", "track ",
                         "help me", "what should", "should i", "can you",
                         "do i have", "when is", "how many")
        _looks_like_action = any(v in _msg_lower for v in _action_verbs)
        _low_confidence = confidence is not None and confidence < 0.6
        _chat_but_action = (intent == "CHAT" and _looks_like_action
                            and len(user_input) > 5)
        if _low_confidence or _chat_but_action:
            miss_type = "low_confidence" if _low_confidence else "chat_no_action"
            log_missed_capability(
                user_id, user_input,
                ai_intent=intent,
                ai_response=response_text[:200] if response_text else None,
                miss_type=miss_type,
                confidence=confidence,
                notes=f"verbs_in_input={_looks_like_action}"
            )
            logger.info(f"[missed_capability] logged {miss_type} for: {user_input[:50]}")
    except Exception as e:
        logger.error(f"miss-logging failed: {e}")

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
        # v10.1: deadline detection — parser OR AI says so
        if parsed.get("is_deadline") or entities.get("is_deadline"):
            entities["is_deadline"] = True

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
                "is_deadline": bool(entities.get("is_deadline")),
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
            # v10.0: suggest time from learned patterns if no time was set
            if not summary_data.get("time"):
                try:
                    suggested = suggest_time_for_task(user_id, summary_data.get("category", "General"))
                    if suggested:
                        extra += f"\n\n💡 <i>You usually do {esc(summary_data.get('category', 'these'))} tasks around {esc(suggested)}. Want me to set that?</i>"
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
        key, value = await run_blocking(extract_memory_key, user_input)
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
        # DBG-0006: keyword-aware search — a full question ("When is my exam?")
        # falls back to its keyword ("exam") instead of matching nothing and
        # dumping every memory.
        results = search_memories_smart(user_id, query)
        if results:
            msg = "🧠 *Found in memory:*\n\n"
            for k, v in results:
                msg += f"• *{k}*: {v}\n"
            await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu())
        elif get_all_memories(user_id):
            await update.message.reply_text(
                "🧠 I couldn't find a memory about that. "
                "Send /memory to see everything you've saved.",
                reply_markup=main_menu())
        else:
            await update.message.reply_text(
                "🧠 No memories stored yet. Tell me things to remember!",
                reply_markup=main_menu())

    elif intent == "PLAN":
        # v4.0: route to /plan command with smart period detection
        period = "week" if any(w in user_input.lower() for w in ["week", "hafte", "weekly"]) else "today"
        context.args = [period]
        await plan_cmd(update, context)

    elif intent == "GOAL":
        title = entities.get("title") or user_input
        deadline = entities.get("date")
        if not deadline:
            # DBG-0004: derive a deadline from the phrasing (e.g. "this year"
            # → 31 Dec) when the AI didn't extract one.
            from date_parser import parse_date as _parse_date
            deadline, _ = _parse_date(user_input)
        gid = add_goal(user_id, title, deadline)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎯 View Goals", callback_data="dash:goals"),
            InlineKeyboardButton("🏠 Dashboard", callback_data="dash:home"),
        ]])
        await update.message.reply_text(
            f"🎯 {b('Goal set!')}\n\n📌 {b(title)}\n"
            f"<i>📅 Deadline: {esc(deadline or 'No deadline')}</i>\n\n"
            f"Track progress in your Goals dashboard. I can also break this into tasks — just ask!",
            parse_mode=HTML, reply_markup=kb
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
    # v14.22: /debug now opens the admin-only Developer Center (Debug
    # Menu), which hosts the Self-Test framework. Non-admins are
    # silently denied using the same is_admin() gate and message the
    # @admin_only decorator uses (that decorator is defined later in
    # this file, so the check is inlined rather than applied). The
    # debug-mode toggle moved into the menu (🐞 button -> dev:toggle).
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❓ Unknown command. Type /help.",
                                        reply_markup=main_menu())
        return
    text, kb = UI.dev_menu_card(dbg.is_debug_on(user_id))
    await update.message.reply_text(text, parse_mode=HTML, reply_markup=kb)

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
    # v14.21: DBG-prefixed display id (independent bug numbering).
    await update.message.reply_text(
        f"✅ Bug {dbg.format_bug_id(bug_id)} saved with full context!\n"
        f"I captured your last message and what I understood from it.\n"
        f"Use /bugs to see all reports.",
        reply_markup=main_menu()
    )

async def bugs_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # v14.18 (Phase 5R): presentation extracted to ui.bugs_card().
    user_id = update.message.from_user.id
    bugs = dbg.get_open_bugs(user_id)
    await update.message.reply_text(UI.bugs_card(bugs),
                                    parse_mode=HTML, reply_markup=main_menu())

async def resolve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /resolve <bug_id>")
        return
    # v14.21: accepts '18', '#18', or 'DBG-0018' (parse_bug_id).
    bug_id = dbg.parse_bug_id(context.args[0])
    if bug_id is None:
        await update.message.reply_text("Usage: /resolve <number>")
        return
    if dbg.resolve_bug(bug_id):
        await update.message.reply_text(
            f"✅ Bug {dbg.format_bug_id(bug_id)} marked resolved!",
            reply_markup=main_menu())
    else:
        await update.message.reply_text(f"❌ Bug {dbg.format_bug_id(bug_id)} not found.")

async def trace_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # v14.18 (Phase 5R): presentation extracted to ui.trace_card().
    user_id = update.message.from_user.id
    trace = dbg.get_last_trace(user_id)
    await update.message.reply_text(
        UI.trace_card(trace), parse_mode=HTML, reply_markup=main_menu()
    )

async def selftest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """v14.12: live diagnostics report (replaces the v11.1 manual test
    checklist, which lives on in debug_system.SELFTEST_MESSAGES and
    TESTING.md's manual smoke section). Every check runs against the
    real running process -- no AI calls (that's /status's job)."""
    import resource
    import database as _db

    t_start = time.perf_counter()
    user_id = update.message.from_user.id
    checks = []          # (ok, label, detail)

    def check(label, fn):
        t0 = time.perf_counter()
        try:
            detail = fn()
            checks.append((True, label, f"{detail} · {(time.perf_counter()-t0)*1000:.0f}ms"))
        except Exception as exc:
            checks.append((False, label, f"{type(exc).__name__}: {exc}"))

    # ── live probes ──
    check("Database read", lambda: f"{len(get_tasks(user_id))} open tasks")
    check("Database integrity", lambda: (
        "schema ok" if _db.verify_schema_integrity()["ok"] else "MISSING OBJECTS"))
    check("Scheduler", lambda: f"{len(get_due_tasks())} due now")
    check("Intent Engine", lambda: intent_engine.classify(
        text="add task selftest probe",
        context=ConversationContext(state="idle", partial_data={},
                                     now=datetime.now(IST))).intent.name)
    check("Routing Layer", lambda: routing_layer.route(intent_engine.classify(
        text="list", context=ConversationContext(
            state="idle", partial_data={}, now=datetime.now(IST)))
        ).recommended_destination.name)
    check("Offline Engine", lambda: (
        f"{len(build_enabled_registry().intents())} intents registered"))
    check("Storage Facade", lambda: f"{len(storage.habits.get_all(user_id))} habits")
    check("Conversation state", lambda: get_state(user_id))

    # v14.18 (Phase 5R): report rendering extracted to
    # ui.selftest_report(); the live probes above stay here (they touch
    # the running process -- DB, engines, state).
    try:
        db_size = f"{os.path.getsize(_db.DB_NAME) / 1024:.0f} KB"
    except OSError:
        db_size = "unknown"
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    flag_values = [
        ("OFFLINE_TASKS", feature_flags.OFFLINE_TASKS),
        ("OFFLINE_HABITS", feature_flags.OFFLINE_HABITS),
        ("OFFLINE_GOALS", feature_flags.OFFLINE_GOALS),
        ("OFFLINE_PROJECTS", feature_flags.OFFLINE_PROJECTS),
    ]
    elapsed_ms = (time.perf_counter() - t_start) * 1000
    report = UI.selftest_report(
        BAKA_VERSION, sys.version.split()[0], AI_PROVIDER,
        MODEL_MAIN, MODEL_FAST, MODEL_THINK,
        _db.DB_NAME.split("/")[-1], db_size, rss_mb,
        flag_values, checks, elapsed_ms,
    )
    await _reply_rich(update.message, report, reply_markup=main_menu())



# ── v1.1: Inline button callback handler ──────────────
def _quick_suite_tests():
    """The regression Quick Suite, sorted (stable order for the manual
    runner's index-based walk). v14.25."""
    from core import regression as reg
    from core.regression.models import Suite
    reg.discover()
    return reg.by_suite(Suite.QUICK)


def _test_run_view(user_id, run, tests):
    """(text, keyboard) for the run's current test, or the summary when
    finished (which also ends the session). v14.25."""
    if run["index"] >= len(tests):
        _test_runs.pop(user_id, None)
        return UI.dev_run_summary_card(run["results"])
    test = tests[run["index"]]
    return UI.dev_run_test_card(test, run["index"], len(tests))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer_callback_query(query)
    user_id = query.from_user.id
    data = query.data

    parts = data.split(":")
    action = parts[0]
    # v9.0: safe task_id parse — dashboard callbacks (dash:home) have non-numeric
    # payloads; never crash on int() conversion.
    task_id = None
    if len(parts) > 1:
        try:
            task_id = int(parts[1])
        except (ValueError, TypeError):
            task_id = None

    # v9.0: callback logger (debug infra, spec #15)
    try:
        logger.info(f"[callback] user={user_id} data={data}")
    except Exception:
        pass

    # v9.0: dashboard navigation router — handled in dashboard module
    if action == "dash":
        await route_dashboard_callback(update, context, parts)
        return

    if action == "done":
        task = get_task_by_id(task_id, user_id)
        if task:
            # v5.0: habit-aware completion
            if is_habit(task_id):
                ok, streak_or_msg = log_habit_completion(task_id, user_id)
                streak_text = (f"\n🔥 Streak: *{streak_or_msg}* day"
                               f"{'s' if isinstance(streak_or_msg,int) and streak_or_msg != 1 else ''}!"
                               if ok else "\n_(already logged today)_")
                await safe_edit_message_text(query,
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
                await safe_edit_message_text(query,
                    f"✅ *Done!* Completed:\n📌 {task[1]}",
                    parse_mode="Markdown"
                )
        else:
            await safe_edit_message_text(query, "❌ Task not found.")

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
            await safe_edit_message_text(query,
                f"⏰ Snoozed for {label}.{tip}",
                parse_mode="Markdown"
            )
        else:
            await safe_edit_message_text(query,
                f"⏰ Snoozed for {label}. I'll remind you again at {snooze_until.split()[1]}.",
            )

    elif action == "postpone":
        from datetime import datetime as _dt, timedelta as _td
        tomorrow = (_dt.now(IST) + _td(days=1)).strftime("%Y-%m-%d")
        postpone_task(task_id, user_id, tomorrow)
        task = get_task_by_id(task_id, user_id)
        await safe_edit_message_text(query,
            f"📅 Moved to tomorrow ({tomorrow}).\n📌 {task[1] if task else ''}",
        )

    elif action == "pause":
        pause_task(task_id, user_id)
        await safe_edit_message_text(query, "⏸ Task paused. Reminders stopped until you resume it.")

    elif action == "resume":
        resume_task(task_id, user_id)
        await safe_edit_message_text(query, "▶️ Task resumed. Reminders are back on.")

    elif action == "unflagdeadline":
        # v10.1: stop buffer reminders for a deadline task
        if task_id:
            try:
                mark_as_deadline(task_id, user_id, False)
                await safe_edit_message_text(query,
                    "🔕 Buffer reminders muted for this task. "
                    "You'll still get the reminder at the deadline itself."
                )
            except Exception:
                await safe_edit_message_text(query, "Couldn't update task.")

    elif action == "vision_save_tasks":
        # v11.0: extract bullet-point tasks from vision result and create them
        atype, vdata = get_pending_action(user_id)
        if atype != "vision_result" or not vdata:
            await safe_edit_message_text(query, "Image analysis expired — please send the photo again.")
            return
        text = vdata.get("text", "")
        # Find bullet-point or numbered tasks in the AI's response
        import re as _re
        candidates = []
        for line in text.split("\n"):
            line = line.strip()
            # Match common task formats: "- task", "* task", "1. task", "• task"
            m = _re.match(r'^[-*•]\s+(.+)$', line) or _re.match(r'^\d+[.)]\s+(.+)$', line)
            if m:
                candidate = m.group(1).strip()
                if 3 < len(candidate) < 200:
                    candidates.append(candidate)
        if not candidates:
            await safe_edit_message_text(query,
                "Couldn't find clear task items in the image analysis. "
                "Try sending the photo again with a caption like 'extract todos'.")
            return
        # Create tasks for today
        today_str = datetime.now(IST).strftime("%Y-%m-%d")
        created = []
        for title in candidates[:10]:  # cap at 10 to avoid spam
            if not task_exists(user_id, title, today_str):
                tid = add_task(user_id, title, today_str, None, "General", "medium")
                created.append((tid, title))
        clear_state(user_id)
        if created:
            lines = [f"✅ {b(f'Created {len(created)} task(s) from your image:')}", ""]
            for tid, title in created:
                lines.append(f"  {code('['+str(tid)+']')} {esc(title)}")
            await safe_edit_message_text(query, "\n".join(lines), parse_mode=HTML)
        else:
            await safe_edit_message_text(query, "All those tasks already exist!")

    elif action == "proj":
        # v12.0 project callbacks: proj:started:{gid}, proj:finished:{gid},
        # proj:got:{mid}, proj:view:{gid}, proj:shopping
        subcmd = parts[1] if len(parts) > 1 else ""
        arg = parts[2] if len(parts) > 2 else None
        if subcmd == "started" and arg:
            try:
                add_worklog(user_id, int(arg), "Work started", kind="started")
                await safe_edit_message_text(query, f"🚀 Marked as started (goal #{arg}).")
            except Exception as e:
                await safe_edit_message_text(query, f"Error: {str(e)[:100]}")
        elif subcmd == "finished" and arg:
            try:
                add_worklog(user_id, int(arg), "Project finished", kind="finished")
                await safe_edit_message_text(query, "🎉 Project marked as finished!")
            except Exception as e:
                await safe_edit_message_text(query, f"Error: {str(e)[:100]}")
        elif subcmd == "got" and arg:
            try:
                mark_material_acquired(user_id, int(arg), True)
                await safe_edit_message_text(query, "✅ Marked as acquired.")
            except Exception as e:
                await safe_edit_message_text(query, f"Error: {str(e)[:100]}")
        elif subcmd == "view" and arg:
            proj = get_project_overview(user_id, int(arg))
            if proj:
                await safe_edit_message_text(query,
                    f"📊 {b(esc(proj['title']))} — {proj['progress']}%\n"
                    f"Materials: {proj['materials_acquired']}/{proj['materials_total']}\n"
                    f"Send {code(f'project {arg}')} for the full card.",
                    parse_mode=HTML)
        elif subcmd == "shopping":
            items = get_all_pending_materials(user_id)
            if items:
                names = ", ".join(m[0] for m in items[:20])
                await safe_edit_message_text(query,
                    f"🛒 Still need: {esc(names)}",
                    parse_mode=HTML)
            else:
                await safe_edit_message_text(query, "🛒 Shopping list is empty! 🎉")

    elif action == "vision_ask_again":
        await safe_edit_message_text(query,
            "👀 Send the same image again with a more specific caption "
            "(e.g. 'what brand is this product?' or 'translate this text').")

    elif action == "finish_yes":
        # v7.0: user confirms they finished
        task = get_task_by_id(task_id, user_id)
        if task:
            if is_habit(task_id):
                ok, streak = log_habit_completion(task_id, user_id)
                txt = (f"\U0001f525 Streak: {streak}!" if ok else "_(already logged)_")
                await safe_edit_message_text(query,
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
                await safe_edit_message_text(query,
                    f"\u2705 *Great job!* Marked done:\n\U0001f4cc {task[1]}",
                    parse_mode="Markdown")
        else:
            await safe_edit_message_text(query, "Task not found.")

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
            await safe_edit_message_text(query,
                f"No worries! For *{task[1]}*, want to:\n\n"
                f"📅 Reschedule it to tomorrow\n"
                f"🔨 Break it into smaller steps\n"
                f"🔕 Or stop the follow-ups?",
                parse_mode="Markdown", reply_markup=buttons)
        else:
            await safe_edit_message_text(query, "Task not found.")

    elif action == "dobreak":
        # v7.0: trigger breakdown from the follow-up flow
        task = get_task_by_id(task_id, user_id)
        if task:
            await safe_edit_message_text(query, f"🔨 Breaking down *{task[1]}*...",
                                          parse_mode="Markdown")
            subtasks = await run_blocking(generate_task_breakdown, task[1], task[2])
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
            await safe_edit_message_text(query,
                f"🔕 Reminders stopped for *{task[1]}*\n"
                f"Task still in your list but won't ping you again.\n"
                f"Use /resume {task_id} to turn back on.",
                parse_mode="Markdown"
            )

    elif action == "deltask":
        task = get_task_by_id(task_id, user_id)
        if task:
            delete_task(task_id, user_id)
            await safe_edit_message_text(query,
                f"🗑 Deleted: *{task[1]}*",
                parse_mode="Markdown"
            )
        else:
            await safe_edit_message_text(query, "❌ Task not found.")

    elif action == "dev":
        # v14.22: Developer Center / Self-Test framework. Admin-only;
        # silent no-op for non-admins (they never see the buttons, and
        # a spoofed callback does nothing). Namespace: dev:* (UI_SPEC §10).
        if not is_admin(user_id):
            return
        page = parts[1] if len(parts) > 1 else "menu"
        if page == "menu":
            text, kb = UI.dev_menu_card(dbg.is_debug_on(user_id))
            await safe_edit_message_text(query, text, parse_mode=HTML, reply_markup=kb)
        elif page == "toggle":
            on = dbg.toggle_debug(user_id)
            text, kb = UI.dev_menu_card(on)
            await safe_edit_message_text(query, text, parse_mode=HTML, reply_markup=kb)
        elif page == "st":
            from core import selftest
            if len(parts) > 2 and parts[2] == "run":
                # Show a running placeholder, then execute the whole
                # suite OFF the event loop (some tests do blocking I/O),
                # then render the results.
                await safe_edit_message_text(query, UI.selftest_running_text(),
                                             parse_mode=HTML)
                report = await run_blocking(selftest.run)
                text, kb = UI.selftest_results_card(report)
                await safe_edit_message_text(query, text, parse_mode=HTML, reply_markup=kb)
            else:
                selftest.discover()
                text, kb = UI.selftest_screen_card(
                    selftest.categories(), len(selftest.registered_tests()))
                await safe_edit_message_text(query, text, parse_mode=HTML, reply_markup=kb)
        elif page == "run":
            # v14.25: manual regression runner (Developer Center -> Run Tests).
            # Walks the Quick Suite one test at a time; the FAIL-note capture
            # happens in handle_message (a text reply logs a bug, then advances).
            sub = parts[2] if len(parts) > 2 else "start"
            tests = _quick_suite_tests()
            run = _test_runs.get(user_id)
            if sub == "start" or run is None:
                run = {"index": 0, "results": [], "awaiting_note": False}
                _test_runs[user_id] = run
            elif sub in ("pass", "skip") and run["index"] < len(tests):
                run["results"].append({
                    "test_id": tests[run["index"]].test_id,
                    "status": "PASS" if sub == "pass" else "SKIP",
                    "bug_id": None,
                })
                run["index"] += 1
            elif sub == "fail" and run["index"] < len(tests):
                run["awaiting_note"] = True
                await safe_edit_message_text(
                    query, UI.dev_run_fail_prompt(tests[run["index"]]),
                    parse_mode=HTML)
                return
            text, kb = _test_run_view(user_id, run, tests)
            await safe_edit_message_text(query, text, parse_mode=HTML, reply_markup=kb)


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
    # v14.18 (Phase 5R): presentation extracted to ui.settings_card().
    user_id = update.message.from_user.id
    prefs = get_user_prefs(user_id)
    is_quiet = is_quiet_hours(user_id)
    await update.message.reply_text(
        UI.settings_card(prefs, is_quiet),
        parse_mode=HTML, reply_markup=main_menu()
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
        plan_data = await run_blocking(generate_structured_plan, tasks, prefs, "this week")
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
    plan_data = await run_blocking(generate_structured_plan, tasks, prefs, "today")
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
    subtasks = await run_blocking(generate_task_breakdown, task[1], task[2])

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
    new_time = await run_blocking(suggest_reschedule_time, task[1], conflicts)
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
    """List all habits with streak summary. v14.20 (RC1): HTML via
    ui.habits_overview_card() -- closes the documented Markdown
    title-corruption bug on this surface."""
    user_id = update.message.from_user.id
    habits = get_habits(user_id)
    await update.message.reply_text(UI.habits_overview_card(habits),
                                    parse_mode=HTML, reply_markup=main_menu())


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
    # v14.20 (RC1): HTML via ui.habit_streak_card().
    await update.message.reply_text(
        UI.habit_streak_card(habits[0], log, missed, datetime.now(IST).date()),
        parse_mode=HTML, reply_markup=main_menu())


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
    # v14.20 (RC1): HTML via ui.habit_log_card() (handles the empty-log
    # variant; keyboard presence preserved per variant).
    if not log:
        await update.message.reply_text(UI.habit_log_card(task[1], log),
                                        parse_mode=HTML)
        return
    await update.message.reply_text(UI.habit_log_card(task[1], log),
                                    parse_mode=HTML, reply_markup=main_menu())


async def addhabit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick habit creation from a single command."""
    user_id = update.message.from_user.id
    if not context.args:
        # v14.20 (RC1): HTML via ui.habit_usage_card().
        await update.message.reply_text(UI.habit_usage_card(), parse_mode=HTML)
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
    # v14.20 (RC1): HTML via ui.habit_created_card().
    await update.message.reply_text(
        UI.habit_created_card(title, rec_type, rec_weekday, time_val),
        parse_mode=HTML, reply_markup=main_menu()
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
    # v14.20 (RC1): HTML via ui.habit_streak_reset_card().
    await update.message.reply_text(
        UI.habit_streak_reset_card(task[1]),
        parse_mode=HTML, reply_markup=main_menu()
    )


# ── v6.0: Preference Learning Commands ────────────────
async def insights_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show what BAKA has learned about your behavior."""
    # v14.18 (Phase 5R): presentation extracted to ui.insights_card()
    # (including the not-enough-data variant -- pure display selection).
    user_id = update.message.from_user.id
    data = analyze_user(user_id, days=30)
    await update.message.reply_text(UI.insights_card(data),
                                    parse_mode=HTML, reply_markup=main_menu())


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
    # v14.18 (Phase 5R): presentation extracted to ui.admin_panel_card().
    uid = update.message.from_user.id
    in_mode = _admin_mode.get(uid, False)
    stats = get_data_stats(uid)
    await update.message.reply_text(UI.admin_panel_card(stats, in_mode),
                                    parse_mode=HTML, reply_markup=main_menu())

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
    # v14.18 (Phase 5R): presentation extracted to ui.proactive_card().
    user_id = update.message.from_user.id
    w = get_wellness_prefs(user_id)
    prefs = get_user_prefs(user_id)
    await update.message.reply_text(UI.proactive_card(w, prefs),
                                    parse_mode=HTML, reply_markup=main_menu())


# ── v9.0: DASHBOARD SYSTEM ────────────────────────────
def _gather_dashboard_data(user_id):
    """Batch-read everything the home dashboard needs (spec #14: one place)."""
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    all_pending = get_tasks(user_id)
    today_tasks_list = get_tasks_by_date(user_id, today)
    overdue = get_overdue_tasks(user_id, today, current_time)
    goals = get_goals_full(user_id)
    habits = get_habits(user_id)
    best_streak = max([h[6] or 0 for h in habits], default=0)
    try:
        done_today = get_done_today_count(user_id)
    except Exception:
        done_today = 0
    # completion rate from learning data (best-effort)
    try:
        prof = analyze_user(user_id, days=30)
        completion_rate = prof.get("completion_rate", 0)
    except Exception:
        completion_rate = 0
    return {
        "date_str": now.strftime("%A, %d %B %Y"),
        "pending": len(all_pending),
        "today_count": len(today_tasks_list),
        "overdue": len(overdue),
        "done_today": done_today,
        "goals": goals,
        "habits": habits,
        "streak_best": best_streak,
        "completion_rate": completion_rate,
    }

def _build_today_groups(user_id):
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")
    todays = get_tasks_by_date(user_id, today)
    overdue = get_overdue_tasks(user_id, today, current_time)
    # done today
    conn = __import__("sqlite3").connect("planner.db")
    c = conn.cursor()
    c.execute("""SELECT id,title,due_date,due_time,category,priority,done
                 FROM tasks WHERE user_id=? AND done=1
                 AND substr(COALESCE(last_completed,created_at),1,10)=?""",
              (user_id, today))
    done = c.fetchall()
    conn.close()
    high = [t for t in todays if (len(t) > 5 and t[5] == "high")]
    upcoming = [t for t in todays if not (len(t) > 5 and t[5] == "high")]
    return {"overdue": overdue, "high": high, "upcoming": upcoming, "done": done}

def _build_stats(user_id):
    try:
        prof = analyze_user(user_id, days=30)
    except Exception:
        prof = {}
    all_tasks = get_tasks(user_id)
    now = datetime.now(IST)
    overdue = get_overdue_tasks(user_id, now.strftime("%Y-%m-%d"), now.strftime("%H:%M"))
    total = prof.get("total_tasks", len(all_tasks))
    overdue_rate = (len(overdue) / total) if total else 0
    cats = prof.get("category_focus", {})
    top_cats = sorted(cats.items(), key=lambda x: -x[1]) if cats else []
    active = prof.get("active_hours_top3", [])
    return {
        "completion_rate": prof.get("completion_rate", 0),
        "overdue_rate": overdue_rate,
        "total_tasks": total,
        "done_tasks": prof.get("total_completions", 0),
        "tone": prof.get("tone", "balanced"),
        "active_hour": active[0][0] if active else None,
        "top_categories": top_cats,
        "insights": prof.get("insights", []),
    }



async def _stats_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the productivity stats card as a fresh message (menu entry)."""
    user_id = update.message.from_user.id
    text, kb = UI.stat_card(_build_stats(user_id))
    await update.message.reply_text(text, parse_mode=HTML, reply_markup=kb)

async def goals_dash_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open the goals dashboard directly."""
    user_id = update.message.from_user.id
    goals = get_goals_full(user_id)
    text, kb = UI.goal_card(goals)
    await update.message.reply_text(text, parse_mode=HTML, reply_markup=kb)

async def dashboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open the central dashboard (spec #1)."""
    user_id = update.message.from_user.id
    try:
        db_log_interaction(user_id, "dashboard_open")
    except Exception:
        pass
    data = _gather_dashboard_data(user_id)
    text, kb = UI.dashboard_card(data)
    logger.info(f"[dashboard] render home user={user_id}")
    await update.message.reply_text(text, parse_mode=HTML, reply_markup=kb)

async def route_dashboard_callback(update, context, parts):
    """
    Centralized dashboard callback router (spec #13).
    parts: ['dash', '<page>', '<optional id>']
    Edits the message in place (spec #11).
    """
    query = update.callback_query
    user_id = query.from_user.id
    page = parts[1] if len(parts) > 1 else "home"
    arg = parts[2] if len(parts) > 2 else None
    logger.info(f"[dashboard] callback page={page} arg={arg} user={user_id}")

    async def _edit(text, kb):
        # safe_edit_message_text already handles "not modified" (no-op)
        # and message-gone (falls back to a fresh send) -- see
        # notification_service.py.
        await safe_edit_message_text(query, text, parse_mode=HTML, reply_markup=kb)

    if page == "home":
        text, kb = UI.dashboard_card(_gather_dashboard_data(user_id))
        await _edit(text, kb)

    elif page == "today":
        groups = _build_today_groups(user_id)
        text, kb = UI.today_card(groups, datetime.now(IST).strftime("%A, %d %B"))
        await _edit(text, kb)

    elif page == "tasks":
        tasks = get_tasks(user_id)
        text, kb = UI.task_list_card(tasks, "Pending Tasks")
        await _edit(text, kb)

    elif page == "task" and arg:
        try:
            tid = int(arg)
            task = get_task_by_id(tid, user_id)
            if task:
                text, kb = UI.task_card(task)
                await _edit(text, kb)
            else:
                await _edit("Task not found.", None)
        except (ValueError, TypeError):
            await _edit("Invalid task.", None)

    elif page == "goals":
        goals = get_goals_full(user_id)
        text, kb = UI.goal_card(goals)
        await _edit(text, kb)

    elif page == "goalplus" and arg:
        try:
            res = update_goal_progress(int(arg), user_id, 10)
            if res and res[2]:
                await safe_answer_callback_query(query, "🎉 Goal complete!", show_alert=True)
        except (ValueError, TypeError):
            pass
        text, kb = UI.goal_card(get_goals_full(user_id))
        await _edit(text, kb)

    elif page == "goalminus" and arg:
        try:
            update_goal_progress(int(arg), user_id, -10)
        except (ValueError, TypeError):
            pass
        text, kb = UI.goal_card(get_goals_full(user_id))
        await _edit(text, kb)

    elif page == "habits":
        habits = get_habits(user_id)
        text, kb = UI.habit_card(habits)
        await _edit(text, kb)

    elif page == "stats":
        text, kb = UI.stat_card(_build_stats(user_id))
        await _edit(text, kb)

    elif page == "edit" and arg:
        # Hand off to existing edit flow
        try:
            tid = int(arg)
            set_editing(user_id, tid)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✏️ Editing task {code('['+str(tid)+']')}. "
                     f"Tell me what to change (e.g. 'set time to 6pm', 'rename to X').",
                parse_mode=HTML)
        except (ValueError, TypeError):
            pass

    else:
        text, kb = UI.dashboard_card(_gather_dashboard_data(user_id))
        await _edit(text, kb)


# ── v10.0: Search, Templates, Export ──────────────────
async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search tasks, memories, habits, goals by keyword."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            f"🔍 {b('Search')}\n\nUsage: {code('search <keyword>')}\n"
            f"Searches task titles, categories, tags, memories, habits, and goals.",
            parse_mode=HTML, reply_markup=main_menu()
        )
        return
    keyword = " ".join(context.args)
    results = search_all(user_id, keyword)
    total = sum(len(v) for v in results.values())
    if total == 0:
        await update.message.reply_text(
            f"🔍 No results for {b(keyword)}.",
            parse_mode=HTML, reply_markup=main_menu()
        )
        return
    lines = [f"🔍 {b('Results for: ' + keyword)} ({total} found)", ""]
    if results["tasks"]:
        lines.append(f"📋 {b('Tasks')} ({len(results['tasks'])})")
        for t in results["tasks"][:5]:
            done = "✅" if t[6] else "⏳"
            lines.append(f"   {done} {code('['+str(t[0])+']')} {esc(t[1])}")
        lines.append("")
    if results["habits"]:
        lines.append(f"🌱 {b('Habits')} ({len(results['habits'])})")
        for h in results["habits"]:
            lines.append(f"   🔁 {esc(h[1])} (streak {h[4] or 0})")
        lines.append("")
    if results["memories"]:
        lines.append(f"🧠 {b('Memories')} ({len(results['memories'])})")
        for k, v in results["memories"]:
            lines.append(f"   {esc(k)}: {esc(v[:60])}")
        lines.append("")
    if results["goals"]:
        lines.append(f"🎯 {b('Goals')} ({len(results['goals'])})")
        for g in results["goals"]:
            lines.append(f"   {esc(g[1])}")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())


async def savetemplate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save a task as a reusable template."""
    user_id = update.message.from_user.id
    if len(context.args) < 2:
        await update.message.reply_text(
            f"📝 {b('Save Template')}\n\nUsage: {code('savetemplate <name> <task_id>')}\n"
            f"Example: {code('savetemplate gym 5')}\n\n"
            f"Saves task #5 as a template called 'gym' that you can reuse anytime.",
            parse_mode=HTML, reply_markup=main_menu()
        )
        return
    name = context.args[0]
    try:
        tid = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Usage: savetemplate <name> <task_id>", reply_markup=main_menu())
        return
    task = get_task_by_id(tid, user_id)
    if not task:
        await update.message.reply_text(f"❌ Task [{tid}] not found.", reply_markup=main_menu())
        return
    save_template(user_id, name, task[1],
                  category=task[4] if len(task) > 4 else "General",
                  priority=task[5] if len(task) > 5 else "medium",
                  recurrence_type=task[7] if len(task) > 7 else None,
                  default_time=task[3])
    await update.message.reply_text(
        f"📝 {b('Template saved!')}\n\n"
        f"Name: {code(name)}\n"
        f"Based on: {esc(task[1])}\n\n"
        f"Use {code('template ' + name)} to create a task from it anytime.",
        parse_mode=HTML, reply_markup=main_menu()
    )


async def template_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a task from a saved template."""
    user_id = update.message.from_user.id
    if not context.args:
        templates = get_all_templates(user_id)
        if not templates:
            await update.message.reply_text(
                f"📝 {b('No templates yet')}\n\n"
                f"Save one with: {code('savetemplate <name> <task_id>')}",
                parse_mode=HTML, reply_markup=main_menu()
            )
            return
        lines = [f"📝 {b('Your Templates')}", ""]
        for t in templates:
            name, title, cat, prio, rec, dtime = t
            lines.append(f"  {code(name)} → {esc(title)} ({esc(cat)}, {esc(prio)})")
        lines.append(f"\nUse: {code('template <name>')} to create a task from any template.")
        await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())
        return
    name = context.args[0]
    tmpl = get_template(user_id, name)
    if not tmpl:
        await update.message.reply_text(
            f"❌ Template '{esc(name)}' not found. Use {code('template')} to list them.",
            parse_mode=HTML, reply_markup=main_menu()
        )
        return
    tname, title, category, priority, recurrence, default_time = tmpl
    # Create the task with template defaults
    set_pending_action(user_id, "create_task", {
        "action": "create",
        "title": title,
        "date": datetime.now(IST).strftime("%Y-%m-%d"),
        "time": default_time,
        "category": category,
        "priority": priority,
        "recurrence": recurrence,
    })
    await update.message.reply_text(
        f"📝 {b('From template: ' + tname)}\n\n"
        + build_summary({"title": title, "date": datetime.now(IST).strftime("%Y-%m-%d"),
                         "time": default_time, "category": category,
                         "priority": priority, "recurrence": recurrence})
        + "\n\nSave this task?",
        parse_mode=HTML, reply_markup=yes_no_menu()
    )


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export all your data as a plain-text summary."""
    user_id = update.message.from_user.id
    data = export_user_data(user_id)
    # Split into chunks if too long for one message (Telegram limit 4096)
    chunks = [data[i:i+4000] for i in range(0, len(data), 4000)]
    for chunk in chunks:
        await update.message.reply_text(f"{code(chunk)}", parse_mode=HTML)
    await update.message.reply_text(
        f"✅ Export complete. Copy the text above for your records.",
        reply_markup=main_menu()
    )


# ── v10.1: Deadline Toggle Command ────────────────────
async def deadline_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle pre-deadline buffer reminders for a specific task."""
    user_id = update.message.from_user.id
    args = context.args
    if not args:
        await update.message.reply_text(
            f"⏳ {b('Deadline Mode')}\n\n"
            f"Mark a task as a deadline so BAKA reminds you {b('before')} it's due "
            f"(7d/3d/1d/6h/1h ahead), not just at the deadline itself.\n\n"
            f"Usage:\n"
            f"   {code('deadline <id>')} — toggle deadline mode for a task\n"
            f"   {code('deadline <id> on')} — force ON\n"
            f"   {code('deadline <id> off')} — force OFF\n\n"
            f"You can also just say things like:\n"
            f"   <i>\"Assignment due Friday 5pm\"</i>\n"
            f"   <i>\"Submit report by tomorrow 10am\"</i>\n"
            f"and BAKA auto-detects them as deadlines.",
            parse_mode=HTML, reply_markup=main_menu())
        return
    try:
        tid = int(args[0])
    except ValueError:
        await update.message.reply_text("Usage: deadline <task_id> [on|off]", reply_markup=main_menu())
        return
    task = get_task_by_id(tid, user_id)
    if not task:
        await update.message.reply_text(f"❌ Task [{tid}] not found.", reply_markup=main_menu())
        return
    # Determine target state
    if len(args) > 1:
        action = args[1].lower()
        new_state = action in ("on", "yes", "true", "enable")
    else:
        # Toggle
        import sqlite3
        conn = sqlite3.connect("planner.db"); c = conn.cursor()
        c.execute("SELECT COALESCE(is_deadline,0) FROM tasks WHERE id=?", (tid,))
        row = c.fetchone()
        new_state = not bool(row[0]) if row else True
        conn.close()
    mark_as_deadline(tid, user_id, new_state)
    state_label = "ON" if new_state else "OFF"
    state_emoji = "⏳" if new_state else "⚪"
    await update.message.reply_text(
        f"{state_emoji} Deadline mode {b(state_label)} for {b(task[1])}.\n"
        + ("\nI'll ping you ahead of time so you can plan!" if new_state
           else "\nNo more advance warnings for this task."),
        parse_mode=HTML, reply_markup=main_menu())


# ── v11.0 prep: View missed capabilities ──────────────
@admin_only
async def misses_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show what the AI is failing to handle — for picking next features to add."""
    user_id = update.message.from_user.id
    misses = get_missed_capabilities(user_id, limit=30, only_unreviewed=True)
    if not misses:
        await update.message.reply_text(
            f"🧠 {b('AI Miss Log')}\n\nNothing logged yet. As you use BAKA, "
            f"any input the AI handles poorly will appear here. Review it later "
            f"to pick what features to build next.",
            parse_mode=HTML, reply_markup=main_menu())
        return
    # Group by miss_type
    by_type = {}
    for m in misses:
        mid, inp, intent, resp, mtype, conf, notes, created = m
        by_type.setdefault(mtype, []).append((mid, inp, intent, conf))
    lines = [f"🧠 {b('AI Miss Log')} ({len(misses)} unreviewed)", ""]
    for mtype, items in by_type.items():
        lines.append(f"\n{b(mtype)} ({len(items)})")
        for mid, inp, intent, conf in items[:8]:
            conf_str = f"conf={conf:.2f}" if conf else "?"
            lines.append(f"  {code('#'+str(mid))} {esc(inp[:80])}")
            lines.append(f"     <i>→ {esc(intent or '?')} ({conf_str})</i>")
        if len(items) > 8:
            lines.append(f"     <i>...and {len(items)-8} more</i>")
    lines.append(f"\n💡 <i>Use {code('reviewed <id>')} to mark a miss as reviewed.</i>")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())


@admin_only
async def reviewed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark a missed-capability log entry as reviewed (admin-only)."""
    if not context.args:
        await update.message.reply_text(f"Usage: {code('reviewed <id>')}",
                                        parse_mode=HTML, reply_markup=main_menu())
        return
    try:
        mid = int(context.args[0])
        mark_missed_reviewed(mid)
        await update.message.reply_text(f"✅ Miss #{mid} marked reviewed.",
                                        reply_markup=main_menu())
    except (ValueError, Exception) as e:
        await update.message.reply_text(f"❌ {esc(str(e))}",
                                        parse_mode=HTML, reply_markup=main_menu())


# ── v11.0 prep: Free-Form AI Reasoning ────────────────
async def think_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ask BAKA to think about anything — no JSON, no constraints.
    Sees your full profile and gives personalized, contextual advice.
    """
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            f"🧠 {b('Think Mode')}\n\n"
            f"Ask me anything and I'll think about it using your actual data:\n"
            f"  • Your recent completions and active habits\n"
            f"  • Your open tasks across categories\n"
            f"  • Your stored memories\n\n"
            f"Examples:\n"
            f"  {code('think what should I focus on today?')}\n"
            f"  {code('think am I taking on too much?')}\n"
            f"  {code('think how can I improve my mornings?')}\n"
            f"  {code('think do you see any pattern in my snoozes?')}",
            parse_mode=HTML, reply_markup=main_menu())
        return
    question = " ".join(context.args)
    thinking = await update.message.reply_text("🧠 <i>Thinking...</i>", parse_mode=HTML)
    try:
        user_ctx = get_user_context_for_ai(user_id)
        open_tasks = get_tasks(user_id)[:10]
        mems = get_all_memories(user_id)
        answer = await run_blocking(think_freely, question, user_context=user_ctx,
                              recent_tasks=open_tasks, memories=mems)
        await thinking.delete()
        await update.message.reply_text(
            f"🧠 {b('BAKA thinks:')}\n\n{esc(answer)}",
            parse_mode=HTML, reply_markup=main_menu())
    except Exception as e:
        logger.error(f"think_cmd failed: {e}")
        await thinking.delete()
        await update.message.reply_text(
            f"I had trouble thinking about that — {esc(str(e)[:100])}",
            parse_mode=HTML, reply_markup=main_menu())


# ── v11.0: Photo/Image Handler ────────────────────────
# ══ v15.1 Workspace groups (project/game/goal ↔ private Telegram forum) ══
# One workspace = one private group; each entity = a topic; photos + notes
# land in the active entity's topic (or General). All Telegram bindings live
# in the adapter layer -- the Workspace OS stays Telegram-agnostic.
_WS_GROUPS = ws_groups.WorkspaceGroups()

# v15.1.0-alpha.3 Cognitive Engine (Phase 1): /ask reasons over the Workspace
# via grounded tools (LLM planner routes; answers come only from real data).
_COGNITIVE = None


def _cognitive():
    global _COGNITIVE
    if _COGNITIVE is None:
        from core.ai.cognition import CognitiveEngine
        from core.ai.llm_planner import LLMPlanner
        _COGNITIVE = CognitiveEngine(planner=LLMPlanner())
    return _COGNITIVE


async def ask_cmd(update, context):
    user_id = update.message.from_user.id
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text(
            "Usage: <code>/ws &lt;question about your workspaces&gt;</code>\n"
            "e.g. <code>/ws which component is blocked in Drone?</code>", parse_mode=HTML)
        return
    res = await asyncio.to_thread(_cognitive().handle, user_id, query)
    await update.message.reply_text(esc(res.answer), parse_mode=HTML)


def _ws_projection(context):
    """A live Telegram projection bound to the running loop (its client calls
    are bridged from the worker thread we run the app service on)."""
    client = workspace_app.make_projection_client(
        context.bot, asyncio.get_running_loop())
    return TelegramProjection(client)


async def _newws_cmd(update, context, kind):
    user_id = update.message.from_user.id
    title = " ".join(context.args).strip() if context.args else ""
    if not title:
        await update.message.reply_text(f"Usage: <code>/new{kind} &lt;title&gt;</code>",
                                        parse_mode=HTML)
        return
    ws = await asyncio.to_thread(_WS_GROUPS.create, user_id, kind, title)
    await update.message.reply_text(
        f"{ws.icon} Created {kind} {b(esc(ws.title))} (#{ws.id}) and made it active.\n\n"
        f"Next: make a private Telegram group with {b('Topics enabled')}, add me as "
        f"admin, then send {code('/linkhere')} in that group. After that, add entities "
        f"with {code('/add <name>')} and send a photo + note to log progress.",
        parse_mode=HTML)


async def newproject_cmd(update, context):
    await _newws_cmd(update, context, "project")


async def newgame_cmd(update, context):
    await _newws_cmd(update, context, "game")


async def newgoal_cmd(update, context):
    await _newws_cmd(update, context, "goal")


async def workspaces_cmd(update, context):
    user_id = update.message.from_user.id
    wss = await asyncio.to_thread(_WS_GROUPS.list_workspaces, user_id)
    if not wss:
        await update.message.reply_text(
            "No workspaces yet. Try /newproject, /newgame, or /newgoal.")
        return
    lines = [f"{w.icon} {b(esc(w.title))} — #{w.id} ({esc(w.template)})" for w in wss]
    await update.message.reply_text(
        "🗂 " + b("Your workspaces") + "\n" + "\n".join(lines) +
        "\n\nOpen one with " + code("/use <name>") + ".", parse_mode=HTML)


async def useworkspace_cmd(update, context):
    user_id = update.message.from_user.id
    ref = " ".join(context.args).strip()
    if not ref:
        await update.message.reply_text("Usage: <code>/use &lt;workspace name or #id&gt;</code>",
                                        parse_mode=HTML)
        return
    ws = await asyncio.to_thread(_WS_GROUPS.open_workspace, user_id, ref)
    if not ws:
        await update.message.reply_text(f"No workspace matches {b(esc(ref))}.", parse_mode=HTML)
        return
    await update.message.reply_text(f"{ws.icon} Active workspace: {b(esc(ws.title))}.",
                                    parse_mode=HTML)


async def linkhere_cmd(update, context):
    user_id = update.message.from_user.id
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "Send /linkhere inside the private group you want to link "
            "(create it, enable Topics, and add me as an admin first).")
        return
    proj = _ws_projection(context)
    try:
        ws = await asyncio.to_thread(_WS_GROUPS.link_group, user_id, chat.id, proj)
    except Exception as e:
        await update.message.reply_text(f"Couldn't link: {esc(str(e))}")
        return
    if not ws:
        await update.message.reply_text(
            "Open a workspace first (in our private chat): /newproject, /newgame, "
            "/newgoal, or /use <name>.")
        return
    await update.message.reply_text(
        f"🔗 Linked this group to {b(esc(ws.title))}. Add entities with "
        f"{code('/add <name>')}; send a photo + note to log progress.", parse_mode=HTML)


async def addentity_cmd(update, context):
    user_id = update.message.from_user.id
    name = " ".join(context.args).strip()
    if not name:
        await update.message.reply_text("Usage: <code>/add &lt;entity name&gt;</code>  "
                                        "(e.g. <code>/add Hu Tao</code>)", parse_mode=HTML)
        return
    proj = _ws_projection(context)
    try:
        m, topic = await asyncio.to_thread(_WS_GROUPS.add_entity, user_id, name, proj)
    except Exception as e:
        await update.message.reply_text(
            f"Couldn't create the topic: {esc(str(e))}\n"
            "Make sure the linked group has Topics enabled and I'm an admin.")
        return
    if not m:
        await update.message.reply_text(
            "Open a workspace first: /newproject, /newgame, /newgoal, or /use <name>.")
        return
    extra = " · topic created" if topic else " · (link a group with /linkhere for a topic)"
    await update.message.reply_text(
        f"➕ Added {b(esc(m.title))}{extra} and made it active. Send a photo + note "
        f"to log progress there.", parse_mode=HTML)


async def openentity_cmd(update, context):
    user_id = update.message.from_user.id
    ref = " ".join(context.args).strip()
    if not ref:
        await update.message.reply_text("Usage: <code>/open &lt;entity name&gt;</code>",
                                        parse_mode=HTML)
        return
    m = await asyncio.to_thread(_WS_GROUPS.open_entity, user_id, ref)
    if not m:
        await update.message.reply_text(
            f"No entity matches {b(esc(ref))} in the active workspace.", parse_mode=HTML)
        return
    await update.message.reply_text(
        f"🎯 Active entity: {b(esc(m.title))}. Photos + notes now go to its topic.",
        parse_mode=HTML)


async def current_cmd(update, context):
    user_id = update.message.from_user.id
    ctx = await asyncio.to_thread(_WS_GROUPS.current, user_id)
    if not ctx.workspace_id:
        await update.message.reply_text(
            "No active workspace. Try /newproject, /newgame, or /newgoal.")
        return
    entity = f"{b(esc(ctx.entity_title))}" if ctx.entity_title else "— (General)"
    await update.message.reply_text(
        "🗂 Workspace: " + b(esc(ctx.workspace_title)) + "\n"
        "🔗 Group linked: " + ("yes" if ctx.linked else "no (use /linkhere in the group)") + "\n"
        "🎯 Active entity: " + entity, parse_mode=HTML)


async def note_cmd(update, context):
    user_id = update.message.from_user.id
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Usage: <code>/note &lt;progress note&gt;</code>",
                                        parse_mode=HTML)
        return
    await _ws_do_log(update, context, user_id, text, None)


async def _ws_do_log(update, context, user_id, text, photo_file_id):
    proj = _ws_projection(context)
    try:
        res = await asyncio.to_thread(
            _WS_GROUPS.log_progress, user_id, text, proj, photo_file_id)
    except Exception as e:
        await update.message.reply_text(
            f"Saved locally, but posting to the group failed: {esc(str(e))}\n"
            "Make sure the group has Topics enabled and I'm an admin.")
        return
    if not res.ok:
        await update.message.reply_text(
            "Open a workspace first: /newproject, /newgame, /newgoal, or /use <name>.")
        return
    where = f"→ {esc(res.entity_title)}" if res.entity_title else "→ General"
    posted = ("posted to your group" if res.posted
              else "saved (link a group with /linkhere to mirror it)")
    await update.message.reply_text(f"📝 Progress {where}: {posted}.", parse_mode=HTML)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    When user sends a photo, use Llama 3.2 Vision to understand it.
    Common use cases: handwritten todo lists, screenshots of schedules,
    photos of whiteboards/notes, receipts to track.

    v15.1: if the user has an ACTIVE workspace, a photo is instead treated as
    a progress log -> stored + posted to the active entity's Telegram topic.
    """
    user_id = update.message.from_user.id

    # Workspace groups: an active workspace turns photos into progress logs.
    if _WS_GROUPS.has_active(user_id):
        photo = update.message.photo[-1]
        caption = (update.message.caption or "").strip()
        await _ws_do_log(update, context, user_id, caption, photo.file_id)
        return

    if not ENABLE_VISION:
        await update.message.reply_text(
            "📷 Image understanding is currently disabled. "
            "Enable it in baka_brain.py: ENABLE_VISION = True",
            reply_markup=main_menu())
        return

    thinking = await update.message.reply_text(
        "👀 <i>Looking at your image...</i>", parse_mode=HTML)
    try:
        # Get the highest-res photo Telegram sent
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        # Download as bytes, then base64 encode for the vision API
        import base64
        img_bytes = await file.download_as_bytearray()
        b64 = base64.b64encode(bytes(img_bytes)).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"

        # Use caption as the prompt, or default to "describe + extract tasks"
        caption = (update.message.caption or "").strip()
        if not caption:
            prompt = (
                "Look at this image and: "
                "1) Briefly describe what you see (1 sentence). "
                "2) If you see any tasks, todos, schedules, or actionable items, "
                "list them as bullet points so the user can add them. "
                "If no actionable items, just describe."
            )
        else:
            prompt = caption

        result = await run_blocking(call_vision, data_url, prompt, max_tokens=500)
        await thinking.delete()

        # Offer to act on the extracted info
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Save as tasks", callback_data="vision_save_tasks"),
            InlineKeyboardButton("💬 Ask again", callback_data="vision_ask_again"),
        ]])
        # Cache the result so the "save as tasks" button can use it
        set_pending_action(user_id, "vision_result", {
            "action": "vision_result",
            "text": result[:2000],
            "image_url": data_url[:100] + "...",  # truncate for state
        })

        await update.message.reply_text(
            f"📷 {b('Image Analysis')}\n\n{esc(result)}",
            parse_mode=HTML, reply_markup=kb)
    except Exception as e:
        logger.error(f"vision processing failed: {e}")
        await thinking.delete()
        await update.message.reply_text(
            f"Sorry, I couldn't process that image: {esc(str(e)[:150])}",
            parse_mode=HTML, reply_markup=main_menu())


# ── v11.0: Image Generation Command ───────────────────
async def image_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate an image with FLUX.1-schnell via NVIDIA NIM (must be enabled in baka_brain.py)."""
    user_id = update.message.from_user.id
    if not ENABLE_IMAGE_GEN:
        await update.message.reply_text(
            f"🎨 {b('Image Generation')}\n\n"
            f"Currently disabled (saves credits). To enable:\n"
            f"  Edit {code('baka_brain.py')}\n"
            f"  Set {code('ENABLE_IMAGE_GEN = True')}\n"
            f"  Restart the bot.\n\n"
            f"Then use: {code('image <prompt>')}",
            parse_mode=HTML, reply_markup=main_menu())
        return
    if not context.args:
        await update.message.reply_text(
            f"🎨 {b('Image Generation')}\n\n"
            f"Usage: {code('image <prompt>')}\n\n"
            f"Examples:\n"
            f"  {code('image a serene mountain lake at sunset')}\n"
            f"  {code('image futuristic study room with glowing screens')}\n"
            f"  {code('image anime style productivity dashboard')}\n\n"
            f"<i>Model: FLUX.1-schnell via NVIDIA NIM</i>",
            parse_mode=HTML, reply_markup=main_menu())
        return
    prompt = " ".join(context.args)
    thinking = await update.message.reply_text(
        f"🎨 <i>Generating image...</i>\n"
        f"<i>Prompt: {esc(prompt[:100])}</i>",
        parse_mode=HTML)
    try:
        result = await run_blocking(generate_image, prompt, user_id=user_id)
        await thinking.delete()

        # NIM returns base64 data URL — decode and send as bytes to Telegram
        data_url = result.get("data_url")
        if data_url:
            import base64, io
            b64_data = data_url.split(",", 1)[1] if "," in data_url else data_url
            img_bytes = base64.b64decode(b64_data)
            img_file = io.BytesIO(img_bytes)
            img_file.name = "generated.jpg"
            await update.message.reply_photo(
                photo=img_file,
                caption=f"🎨 {b(prompt[:200])}\n<i>FLUX.1-schnell · NVIDIA NIM</i>",
                parse_mode=HTML)
        else:
            await update.message.reply_text(
                f"❌ {b('Image generation failed')}\n\n"
                f"{esc(result.get('error', 'unknown error'))}",
                parse_mode=HTML, reply_markup=main_menu())
    except Exception as e:
        logger.error(f"image_cmd failed: {e}")
        await thinking.delete()
        await update.message.reply_text(
            f"❌ Error: {esc(str(e)[:150])}",
            parse_mode=HTML, reply_markup=main_menu())



# ── v11.2: Video Generation (Stable Video Diffusion via NIM) ──
async def video_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Generate a short video: FLUX creates the frame, SVD animates it.
    100% NVIDIA NIM pipeline — no third-party services.
    """
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            f"🎬 {b('Video Generation')}\n\n"
            f"Usage: {code('video <prompt>')}\n\n"
            f"Examples:\n"
            f"  {code('video waves crashing on a beach at sunset')}\n"
            f"  {code('video steam rising from a coffee cup')}\n\n"
            f"<i>Pipeline: FLUX.1-schnell frame → Stable Video Diffusion\n"
            f"Both via NVIDIA NIM. Takes 1-3 minutes.</i>",
            parse_mode=HTML, reply_markup=main_menu())
        return
    prompt = " ".join(context.args)
    thinking = await update.message.reply_text(
        f"🎬 <i>Generating video (1-3 min)...</i>\n"
        f"<i>Step 1/2: Creating frame with FLUX...</i>",
        parse_mode=HTML)
    try:
        result = await run_blocking(generate_video, prompt=prompt, user_id=user_id)
        await thinking.delete()
        video_b64 = result.get("video_b64")
        if video_b64:
            import base64, io
            vid_bytes = base64.b64decode(video_b64)
            vid_file = io.BytesIO(vid_bytes)
            vid_file.name = "generated.mp4"
            await update.message.reply_video(
                video=vid_file,
                caption=f"🎬 {b(prompt[:200])}\n<i>FLUX + Stable Video Diffusion · NVIDIA NIM</i>",
                parse_mode=HTML)
        else:
            await update.message.reply_text(
                f"❌ {b('Video generation failed')}\n\n"
                f"{esc(result.get('error', 'unknown error'))}",
                parse_mode=HTML, reply_markup=main_menu())
    except Exception as e:
        logger.error(f"video_cmd failed: {e}")
        try:
            await thinking.delete()
        except Exception:
            pass
        await update.message.reply_text(
            f"❌ Error: {esc(str(e)[:150])}",
            parse_mode=HTML, reply_markup=main_menu())


# ── v11.0: Multi-model Status ─────────────────────────
async def models_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """v11.1: Multi-Model AI status with real usage data."""
    user_id = update.message.from_user.id
    thinking = await update.message.reply_text("🔍 Checking all models...")

    # Real usage data from analytics
    try:
        import analytics
        stats = {s["model"]: s for s in analytics.get_model_stats(user_id)}
    except Exception:
        stats = {}

    # Quick liveness probe
    health = await run_blocking(benchmark_all_models)

    # v14.18 (Phase 5R): presentation extracted to ui.models_card().
    await thinking.delete()
    await update.message.reply_text(UI.models_card(health, stats),
                                    parse_mode=HTML, reply_markup=main_menu())


# ── v11.1: Usage Analytics Dashboard ──────────────────
async def usage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Display AI usage analytics — today + lifetime + top patterns."""
    user_id = update.message.from_user.id
    try:
        import analytics
        today = analytics.get_today_overview(user_id)
        lifetime = analytics.get_lifetime_overview(user_id)
        top_models = analytics.get_most_used(user_id, "model_name", limit=3)
        top_providers = analytics.get_most_used(user_id, "provider", limit=3)
        top_types = analytics.get_most_used(user_id, "request_type", limit=5)
        recent = analytics.get_recent_activity(user_id, limit=5)
    except Exception as e:
        await update.message.reply_text(f"Analytics not ready yet: {esc(str(e))}",
                                        parse_mode=HTML, reply_markup=main_menu())
        return

    if lifetime["lifetime_requests"] == 0:
        await update.message.reply_text(
            f"📊 {b('AI Usage')}\n\nNo AI calls logged yet. As you use BAKA, "
            f"every AI request will be tracked here.",
            parse_mode=HTML, reply_markup=main_menu())
        return

    lines = [f"📊 {b('AI Usage Analytics')}", ""]
    lines.append(f"{b('Today')}")
    lines.append(f"  Requests: {b(today['requests_today'])}")
    lines.append(f"  Tokens: {b(today['tokens_today'])}")
    if today["cost_today"] > 0:
        lines.append(f"  Est. cost: ${today['cost_today']:.4f}")
    lines.append(f"  Avg latency: {today['avg_latency_ms']}ms")
    lines.append(f"  Success rate: {today['success_rate']}%")
    lines.append("")

    lines.append(f"{b('Lifetime')}")
    lines.append(f"  Total requests: {b(lifetime['lifetime_requests'])}")
    lines.append(f"  Total tokens: {b(lifetime['lifetime_tokens'])}")
    if lifetime["lifetime_cost"] > 0:
        lines.append(f"  Est. total cost: ${lifetime['lifetime_cost']:.4f}")
    lines.append(f"  Success rate: {lifetime['lifetime_success_rate']}%")
    lines.append("")

    if top_models:
        lines.append(f"{b('Most-used models')}")
        for m, n in top_models:
            lines.append(f"  • {esc(m)}: {n}")
        lines.append("")

    if top_providers:
        lines.append(f"{b('Providers')}")
        for p, n in top_providers:
            lines.append(f"  • {esc(p)}: {n}")
        lines.append("")

    if top_types:
        lines.append(f"{b('Request types')}")
        for t, n in top_types:
            lines.append(f"  • {esc(t)}: {n}")
        lines.append("")

    if recent:
        lines.append(f"{b('Recent activity')}")
        for ts, model, rtype, lat, tok, status in recent[:5]:
            icon = "✅" if status == "success" else "❌"
            time_part = ts.split(" ")[1][:5] if ts and " " in ts else "?"
            lines.append(f"  {icon} {esc(time_part)} {esc((model or '?')[:25])} "
                         f"({esc(rtype or '?')}, {lat}ms)")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤖 Models", callback_data="dash:models_view"),
        InlineKeyboardButton("⚡ Performance", callback_data="dash:perf_view"),
        InlineKeyboardButton("❌ Errors", callback_data="dash:errors_view"),
    ]])
    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=kb)


async def performance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Latency percentiles, fastest/slowest, trends."""
    user_id = update.message.from_user.id
    try:
        import analytics
        perc = analytics.latency_percentiles(user_id, days=7)
        trends = analytics.get_trends(user_id)
        fastest, slowest = analytics.get_fastest_slowest(user_id)
        most_reliable = analytics.get_most_reliable(user_id)
    except Exception as e:
        await update.message.reply_text(f"Analytics error: {esc(str(e))}",
                                        parse_mode=HTML, reply_markup=main_menu())
        return

    lines = [f"⚡ {b('AI Performance')}", ""]

    if perc["n"] == 0:
        lines.append(i("No data yet — make some AI calls first."))
    else:
        lines.append(f"{b('Latency (last 7 days, n=' + str(perc['n']) + ')')}")
        lines.append(f"  Median (p50): {b(str(perc['p50']) + 'ms')}")
        lines.append(f"  p95: {b(str(perc['p95']) + 'ms')}")
        lines.append(f"  p99: {b(str(perc['p99']) + 'ms')}")
        lines.append("")

    if fastest:
        lines.append(f"⚡ {b('Fastest')}: {esc(fastest['model'])} ({fastest['avg_latency_ms']}ms avg)")
    if slowest:
        lines.append(f"🐢 {b('Slowest')}: {esc(slowest['model'])} ({slowest['avg_latency_ms']}ms avg)")
    if most_reliable:
        lines.append(f"🛡 {b('Most reliable')}: {esc(most_reliable['model'])} ({most_reliable['success_rate']}%)")
    lines.append("")

    lines.append(f"{b('Trend')}")
    lines.append(f"  Today: {b(trends['daily'])}")
    lines.append(f"  Yesterday: {trends['yesterday']}")
    lines.append(f"  This week: {trends['weekly']}")
    lines.append(f"  This month: {trends['monthly']}")
    lines.append(f"  Direction: {b(trends['daily_trend'])}")

    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())


async def errors_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recent errors + breakdown."""
    user_id = update.message.from_user.id
    try:
        import analytics
        bd = analytics.get_error_breakdown(user_id)
        recent = analytics.get_recent_errors(user_id, limit=8)
    except Exception as e:
        await update.message.reply_text(f"Analytics error: {esc(str(e))}",
                                        parse_mode=HTML, reply_markup=main_menu())
        return

    lines = [f"❌ {b('AI Errors')}", ""]
    if bd["total_errors"] == 0:
        lines.append(f"✅ No errors logged. Everything's clean!")
        await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())
        return

    lines.append(f"Total errors: {b(bd['total_errors'])}")
    if bd["fallback_activations"]:
        lines.append(f"Fallbacks activated: {b(bd['fallback_activations'])}")
    lines.append("")

    if bd["top_errors"]:
        lines.append(f"{b('Most common errors')}")
        for err, n in bd["top_errors"]:
            lines.append(f"  • ({n}x) {esc((err or '?')[:100])}")
        lines.append("")

    if bd["models_with_errors"]:
        lines.append(f"{b('Models causing errors')}")
        for m, n in bd["models_with_errors"]:
            lines.append(f"  • {esc(m or '?')}: {n}")
        lines.append("")

    if recent:
        lines.append(f"{b('Recent error timeline')}")
        for ts, model, rtype, err in recent[:5]:
            time_part = ts.split(" ")[1][:5] if ts and " " in ts else "?"
            lines.append(f"  ❌ {esc(time_part)} {esc((model or '?')[:25])} "
                         f"<i>{esc((err or '?')[:80])}</i>")

    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())


# ── v11.1: AI Status snippet for the main dashboard ───
def get_ai_status_summary(user_id: int) -> str:
    """Returns an HTML snippet for embedding in the main dashboard card."""
    try:
        import analytics
        today = analytics.get_today_overview(user_id)
        models = analytics.get_model_stats(user_id)
        primary = models[0] if models else None
        if today["requests_today"] == 0 and not primary:
            return ""
        lines = [f"\n{DIVIDER}\n🧠 {b('AI STATUS')}"]
        if primary:
            lines.append(f"  Provider: {esc(primary['provider'])}")
            lines.append(f"  Primary: {code(primary['model'])}")
        lines.append(f"  Requests today: {b(today['requests_today'])}")
        if today["avg_latency_ms"]:
            lines.append(f"  Avg response: {today['avg_latency_ms']}ms")
        lines.append(f"  Success rate: {today['success_rate']}%")
        return "\n".join(lines)
    except Exception:
        return ""


# ── v11.0: AI Observations / Suggestions ──────────────
async def suggestions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show AI-generated suggestions waiting for your review."""
    user_id = update.message.from_user.id
    obs = get_pending_observations(user_id, limit=10)
    if not obs:
        await update.message.reply_text(
            f"💡 {b('AI Suggestions')}\n\n"
            f"<i>No pending suggestions. BAKA generates these once a day at 22:00 "
            f"by analyzing your patterns. They'll appear here for your review.</i>",
            parse_mode=HTML, reply_markup=main_menu())
        return
    lines = [f"💡 {b('AI Suggestions')} ({len(obs)} pending)", ""]
    for o in obs:
        oid, observation, suggestion, atype, apayload, created = o
        lines.append(f"{b('#'+str(oid))} {esc(observation)}")
        if suggestion:
            lines.append(f"   💭 <i>{esc(suggestion)}</i>")
        lines.append(f"   {code('approve ' + str(oid))}  |  {code('dismiss ' + str(oid))}")
        lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())


async def approve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve an AI suggestion — applies it if it has an action_type."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(f"Usage: {code('approve <id>')}",
                                        parse_mode=HTML, reply_markup=main_menu())
        return
    try:
        oid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID.", reply_markup=main_menu())
        return
    obs = get_observation(oid, user_id)
    if not obs:
        await update.message.reply_text(f"❌ Suggestion #{oid} not found.",
                                        reply_markup=main_menu())
        return
    _, observation, suggestion, atype, apayload, status = obs
    if status != "pending":
        await update.message.reply_text(f"Suggestion already {esc(status)}.",
                                        parse_mode=HTML, reply_markup=main_menu())
        return
    respond_to_observation(oid, "approved")
    msg = f"✅ Approved: <i>{esc(observation)}</i>"
    # Auto-apply if action_type is set
    if atype == "create_habit" and apayload:
        try:
            import json as _json
            data = _json.loads(apayload)
            hid = add_habit(user_id, data["title"],
                            time=data.get("time"),
                            recurrence_type=data.get("recurrence", "daily"))
            msg += f"\n\n🌱 Created habit: {b(data['title'])} [{hid}]"
        except Exception as e:
            msg += f"\n\n<i>(Couldn't auto-apply: {esc(str(e)[:80])})</i>"
    await update.message.reply_text(msg, parse_mode=HTML, reply_markup=main_menu())


async def dismiss_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dismiss an AI suggestion."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(f"Usage: {code('dismiss <id>')}",
                                        parse_mode=HTML, reply_markup=main_menu())
        return
    try:
        oid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID.", reply_markup=main_menu())
        return
    respond_to_observation(oid, "dismissed")
    await update.message.reply_text(f"❌ Dismissed suggestion #{oid}.",
                                    reply_markup=main_menu())


# ══════════════════════════════════════════════════════════════
# v12.0 — Project Management commands
# ══════════════════════════════════════════════════════════════
def _progress_bar(pct: int, width: int = 10) -> str:
    filled = int(pct * width / 100)
    return "█" * filled + "░" * (width - filled)


async def need_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """need <goal_id> <items>  — add materials to a project."""
    user_id = update.message.from_user.id
    if len(context.args) < 2:
        await update.message.reply_text(
            f"📦 {b('Add Materials')}\n\n"
            f"Usage: {code('need <goal_id> <items>')}\n\n"
            f"Example:\n"
            f"  {code('need 3 motor, propeller, battery, frame, controller')}\n\n"
            f"Comma-separated. Use {code('goals')} to see your goal IDs.",
            parse_mode=HTML, reply_markup=main_menu())
        return
    try:
        gid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("First argument must be a goal ID.", reply_markup=main_menu())
        return
    items_str = " ".join(context.args[1:])
    added = add_materials(user_id, gid, items_str)
    if not added:
        await update.message.reply_text(
            f"No new materials added (all were already there, or none provided).",
            reply_markup=main_menu())
        return
    lines = [f"📦 {b(f'Added {len(added)} material(s):')}", ""]
    for mid, name in added:
        lines.append(f"  {code(f'#{mid}')} {esc(name)}")
    lines.append(f"\nMark as acquired: {code('got <name>')}")
    lines.append(f"View project: {code(f'project {gid}')}")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())


async def got_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """got <name>  — fuzzy-mark a pending material as acquired."""
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(
            f"✅ {b('Mark material acquired')}\n\n"
            f"Usage: {code('got <name>')}\n"
            f"Example: {code('got motor')}\n\n"
            f"Fuzzy-matches across all your active projects.",
            parse_mode=HTML, reply_markup=main_menu())
        return
    keyword = " ".join(context.args)
    matches = find_material_by_name(user_id, keyword)
    if not matches:
        await update.message.reply_text(
            f"❌ No pending material matches '{esc(keyword)}'. "
            f"Try {code('projects')} to see what's needed.",
            parse_mode=HTML, reply_markup=main_menu())
        return
    if len(matches) == 1:
        mid, name, gid, gtitle = matches[0]
        mark_material_acquired(user_id, mid, True)
        proj = get_project_overview(user_id, gid)
        bar = _progress_bar(proj["progress"]) if proj else ""
        msg = (f"✅ Got {b(esc(name))} for {esc(gtitle)}\n\n"
               f"Progress: {bar} {proj['progress']}%\n"
               f"Materials: {proj['materials_acquired']}/{proj['materials_total']}")
        if proj["materials_acquired"] == proj["materials_total"] and proj["materials_total"]:
            msg += f"\n\n🎉 {b('All materials acquired!')} Time to build."
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Project", callback_data=f"proj:view:{gid}"),
        ]])
        await update.message.reply_text(msg, parse_mode=HTML, reply_markup=kb)
    else:
        # Multiple matches — ask which one
        lines = [f"🤔 Multiple materials match '{esc(keyword)}'. Which one?", ""]
        buttons = []
        for mid, name, gid, gtitle in matches[:5]:
            lines.append(f"  {code(f'#{mid}')} {esc(name)} <i>({esc(gtitle)})</i>")
            buttons.append([InlineKeyboardButton(
                f"✅ {name[:25]} ({gtitle[:20]})",
                callback_data=f"proj:got:{mid}")])
        await update.message.reply_text("\n".join(lines), parse_mode=HTML,
                                        reply_markup=InlineKeyboardMarkup(buttons))


async def worklog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """worklog <goal_id> <entry>  — log project progress."""
    user_id = update.message.from_user.id
    if len(context.args) < 2:
        await update.message.reply_text(
            f"📝 {b('Log Project Progress')}\n\n"
            f"Usage: {code('worklog <goal_id> <entry>')}\n"
            f"Example: {code('worklog 3 finished the frame today')}\n\n"
            f"Or use shortcuts:\n"
            f"  {code('started <goal_id>')}\n"
            f"  {code('finished <goal_id>')}",
            parse_mode=HTML, reply_markup=main_menu())
        return
    try:
        gid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("First arg must be goal ID.", reply_markup=main_menu())
        return
    entry = " ".join(context.args[1:])
    # Auto-detect kind
    low = entry.lower()
    if any(w in low for w in ("finished", "done", "completed", "khatam")):
        kind = "finished"
    elif any(w in low for w in ("blocked", "stuck", "issue", "problem")):
        kind = "blocker"
    elif any(w in low for w in ("started", "began", "shuru")):
        kind = "started"
    else:
        kind = "progress"
    add_worklog(user_id, gid, entry, kind=kind)
    proj = get_project_overview(user_id, gid)
    icon = {"started": "🚀", "progress": "🔨", "finished": "✅",
            "blocker": "🚧", "note": "📝"}.get(kind, "📝")
    if proj:
        bar = _progress_bar(proj["progress"])
        await update.message.reply_text(
            f"{icon} Logged for {b(esc(proj['title']))}: {esc(entry)}\n\n"
            f"Progress: {bar} {proj['progress']}%",
            parse_mode=HTML, reply_markup=main_menu())
    else:
        await update.message.reply_text(f"{icon} Logged: {esc(entry)}",
                                        parse_mode=HTML, reply_markup=main_menu())


async def started_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(f"Usage: {code('started <goal_id>')}",
                                        parse_mode=HTML, reply_markup=main_menu())
        return
    try:
        gid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: started <goal_id>", reply_markup=main_menu())
        return
    add_worklog(user_id, gid, "Work started", kind="started")
    proj = get_project_overview(user_id, gid)
    if proj:
        await update.message.reply_text(
            f"🚀 Work started on {b(esc(proj['title']))}. Deadline: {esc(proj['deadline'] or 'none')}",
            parse_mode=HTML, reply_markup=main_menu())
    else:
        await update.message.reply_text("🚀 Started.", reply_markup=main_menu())


async def finished_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text(f"Usage: {code('finished <goal_id>')}",
                                        parse_mode=HTML, reply_markup=main_menu())
        return
    try:
        gid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: finished <goal_id>", reply_markup=main_menu())
        return
    add_worklog(user_id, gid, "Project finished", kind="finished")
    await update.message.reply_text(
        f"🎉 {b('Congrats!')} Project marked as finished.",
        parse_mode=HTML, reply_markup=main_menu())


async def project_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """project <goal_id> — full dashboard card."""
    user_id = update.message.from_user.id
    if not context.args:
        # No arg → show list of active projects
        projects = get_active_projects(user_id)
        if not projects:
            await update.message.reply_text(
                f"📊 {b('No active projects yet')}\n\n"
                f"A project is any goal you've attached materials or worklog entries to.\n\n"
                f"Start one:\n"
                f"  1. {code('goal build drone by 2026-08-15')}\n"
                f"  2. {code('need <goal_id> motor, battery, frame')}\n"
                f"  3. {code('started <goal_id>')}",
                parse_mode=HTML, reply_markup=main_menu())
            return
        lines = [f"📊 {b('Your Active Projects')}", ""]
        for gid, title, deadline in projects:
            proj = get_project_overview(user_id, gid)
            if not proj:
                continue
            bar = _progress_bar(proj["progress"])
            lines.append(f"{code(f'#{gid}')} {b(esc(title))}")
            lines.append(f"  {bar} {proj['progress']}% · "
                         f"{proj['materials_acquired']}/{proj['materials_total']} materials · "
                         f"{esc(proj['work_state'])}")
            if deadline:
                lines.append(f"  📅 due {esc(deadline)}")
            lines.append("")
        lines.append(f"View one: {code('project <id>')}")
        await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())
        return

    try:
        gid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: project <goal_id>", reply_markup=main_menu())
        return
    proj = get_project_overview(user_id, gid)
    if not proj:
        await update.message.reply_text(f"❌ Goal #{gid} not found.", reply_markup=main_menu())
        return
    bar = _progress_bar(proj["progress"], width=15)
    lines = [
        f"📊 {b(esc(proj['title']))} — #{gid}",
        "",
        f"{bar} {b(str(proj['progress']) + '%')}",
        f"📅 Deadline: {esc(proj['deadline'] or 'none')}",
        f"🔨 Work: {b(esc(proj['work_state']))}",
        "",
        f"📦 {b('Materials')} ({proj['materials_acquired']}/{proj['materials_total']})",
    ]
    if not proj["materials"]:
        lines.append(f"  <i>None added yet. Try {code(f'need {gid} <items>')}</i>")
    else:
        for m in proj["materials"]:
            mid, name, qty, acq, cost, notes, created, acq_at = m
            icon = "✅" if acq else "🔲"
            qty_str = f" ×{qty}" if qty > 1 else ""
            lines.append(f"  {icon} {esc(name)}{qty_str}")

    if proj["worklog"]:
        lines.append(f"\n📝 {b('Recent worklog')} (last {min(5, len(proj['worklog']))})")
        for w in proj["worklog"][:5]:
            wid, entry, kind, created = w
            icon = {"started": "🚀", "progress": "🔨", "finished": "✅",
                    "blocker": "🚧", "note": "📝"}.get(kind, "📝")
            date_short = (created or "")[5:10]  # MM-DD
            lines.append(f"  {icon} <i>{esc(date_short)}</i> {esc(entry[:80])}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Work started", callback_data=f"proj:started:{gid}"),
         InlineKeyboardButton("✅ Finished", callback_data=f"proj:finished:{gid}")],
        [InlineKeyboardButton("🛒 Shopping list", callback_data="proj:shopping")],
    ])
    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=kb)


async def shopping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-shopping list — everything still needed across all projects."""
    user_id = update.message.from_user.id
    items = get_all_pending_materials(user_id)
    if not items:
        await update.message.reply_text(
            f"🛒 {b('Shopping list is empty!')} 🎉\n\n"
            f"All acquired. Nothing pending across your active projects.",
            parse_mode=HTML, reply_markup=main_menu())
        return
    # Group by project
    by_proj = {}
    for name, qty, gtitle, gid in items:
        by_proj.setdefault((gid, gtitle), []).append((name, qty))
    lines = [f"🛒 {b('Shopping List')} — {len(items)} item(s) across {len(by_proj)} project(s)", ""]
    for (gid, gtitle), rows in by_proj.items():
        lines.append(f"{b(esc(gtitle))} <i>(#{gid})</i>")
        for name, qty in rows:
            qty_str = f" ×{qty}" if qty > 1 else ""
            lines.append(f"  🔲 {esc(name)}{qty_str}")
        lines.append("")
    lines.append(f"<i>Mark as acquired with {code('got <name>')}</i>")
    await update.message.reply_text("\n".join(lines), parse_mode=HTML, reply_markup=main_menu())


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


def main() -> None:
    """v11.1: Main entry point with startup validation for Python 3.14."""
    # v13.1: must be the very first thing main() does -- a blocked
    # duplicate instance should exit before touching the database, the
    # Telegram API, or anything else. Raises InstanceAlreadyRunningError,
    # handled distinctly in the `if __name__ == "__main__":` block below.
    instance_lock.acquire()

    # ── Startup validation ─────────────────────────────
    if sys.version_info < (3, 12):
        raise RuntimeError(
            f"BAKA requires Python 3.12+. You are running {sys.version}. "
            "Please upgrade: https://www.python.org/downloads/"
        )

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing. Create a .env file with:\n"
            "  BOT_TOKEN=your_telegram_bot_token\n"
            "  NVIDIA_API_KEY=your_nvidia_api_key"
        )

    # v13.2: this line had been stuck at "v11.1" since that version,
    # silently drifting out of sync on every release since (a known,
    # documented issue -- see DEBUGGING.md's Known Issues, now resolved by
    # deriving the string instead of hardcoding it).
    logger.info(f"🚀 Starting BAKA v{BAKA_VERSION} on Python {sys.version.split()[0]}")
    logger.info(f"📡 AI provider: {AI_PROVIDER} → {MODEL_MAIN}")
    logger.info("🗄️ Initializing database...")

    init_db()
    dbg.init_bugs_db()

    # v13.2: startup integrity verification (Sprint 3 task 5) -- confirms
    # required tables/indexes exist and reports schema version, foreign-key
    # enforcement, and journal mode. Logged clearly either way; a problem
    # here is surfaced loudly but does not block startup (init_db() already
    # ran and is additive/idempotent, so the bot is very likely still
    # functional even if this reports something unexpected).
    integrity = verify_schema_integrity()
    if integrity["ok"]:
        logger.info(
            f"✅ Schema integrity OK — schema_version={integrity['schema_version']}, "
            f"journal_mode={integrity['journal_mode']}, foreign_keys={integrity['foreign_keys']}."
        )
    else:
        logger.warning(
            f"⚠️ Schema integrity check found issues: "
            f"missing_tables={integrity['missing_tables']}, "
            f"missing_indexes={integrity['missing_indexes']}, "
            f"error={integrity.get('error')}."
        )

    # v12.2: JobQueue schedules run_daily() jobs against Defaults.tzinfo
    # (falls back to UTC otherwise). Must be a pytz timezone, not
    # zoneinfo.ZoneInfo — JobQueue internally calls .localize() on it,
    # which zoneinfo objects don't support. This does not change any
    # existing run_daily()/run_repeating() call — naive `time` objects
    # passed to run_daily() now resolve against IST instead of UTC.
    defaults = Defaults(tzinfo=pytz.timezone("Asia/Kolkata"))
    # v13.0: every outbound Bot API call (send_message, edit_message_text,
    # send_photo, answer_callback_query, ...) automatically routes through
    # TelegramSender's process_request() once registered here -- pacing,
    # retry, and flood protection apply bot-wide with no call-site changes.
    app = (Application.builder()
           .token(BOT_TOKEN)
           .defaults(defaults)
           .rate_limiter(TelegramSender())
           .build())

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
    app.add_handler(CommandHandler("dashboard", dashboard_cmd))
    app.add_handler(CommandHandler("home", dashboard_cmd))
    app.add_handler(CommandHandler("search", search_cmd))
    app.add_handler(CommandHandler("savetemplate", savetemplate_cmd))
    app.add_handler(CommandHandler("template", template_cmd))
    app.add_handler(CommandHandler("templates", template_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("deadline", deadline_cmd))
    app.add_handler(CommandHandler("misses", misses_cmd))
    app.add_handler(CommandHandler("think", think_cmd))
    app.add_handler(CommandHandler("ask", think_cmd))
    app.add_handler(CommandHandler("reviewed", reviewed_cmd))
    app.add_handler(CommandHandler("goals", goals_dash_cmd))
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
    app.add_handler(CommandHandler("image", image_cmd))
    app.add_handler(CommandHandler("generate", image_cmd))
    app.add_handler(CommandHandler("video", video_cmd))
    app.add_handler(CommandHandler("models", models_cmd))
    app.add_handler(CommandHandler("usage", usage_cmd))
    app.add_handler(CommandHandler("performance", performance_cmd))
    app.add_handler(CommandHandler("errors", errors_cmd))
    app.add_handler(CommandHandler("suggestions", suggestions_cmd))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("dismiss", dismiss_cmd))
    # v12.0 project management
    app.add_handler(CommandHandler("need", need_cmd))
    app.add_handler(CommandHandler("materials", need_cmd))
    app.add_handler(CommandHandler("got", got_cmd))
    app.add_handler(CommandHandler("have", got_cmd))
    app.add_handler(CommandHandler("worklog", worklog_cmd))
    app.add_handler(CommandHandler("log", worklog_cmd))
    app.add_handler(CommandHandler("started", started_cmd))
    app.add_handler(CommandHandler("finished", finished_cmd))
    app.add_handler(CommandHandler("project", project_cmd))
    app.add_handler(CommandHandler("projects", project_cmd))
    app.add_handler(CommandHandler("shopping", shopping_cmd))
    # v15.1 Workspace groups (project/game/goal ↔ private Telegram forum group)
    app.add_handler(CommandHandler("newproject", newproject_cmd))
    app.add_handler(CommandHandler("newgame", newgame_cmd))
    app.add_handler(CommandHandler("newgoal", newgoal_cmd))
    app.add_handler(CommandHandler("workspaces", workspaces_cmd))
    app.add_handler(CommandHandler("use", useworkspace_cmd))
    app.add_handler(CommandHandler("linkhere", linkhere_cmd))
    app.add_handler(CommandHandler("add", addentity_cmd))
    app.add_handler(CommandHandler("open", openentity_cmd))
    app.add_handler(CommandHandler("current", current_cmd))
    app.add_handler(CommandHandler("note", note_cmd))
    # v15.1.0-alpha.3 Cognitive Engine: ask questions about your workspaces
    app.add_handler(CommandHandler("ws", ask_cmd))
    app.add_handler(CommandHandler("query", ask_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
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
        """v9.0 Evening Review at 21:00: done today, missed, tomorrow preview."""
        try:
            now = datetime.now(IST)
            today = now.strftime("%Y-%m-%d")
            tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            for uid in get_all_active_user_ids():
                if is_quiet_hours(uid):
                    continue
                pending = get_unresolved_today(uid)
                try:
                    done_today = get_done_today_count(uid)
                except Exception:
                    done_today = 0
                tomorrow_tasks = get_tasks_by_date(uid, tomorrow)
                if not pending and not done_today and not tomorrow_tasks:
                    continue

                lines = [f"🌙 {b('Evening Review')}", f"<i>{esc(now.strftime('%A, %d %B'))}</i>", ""]
                # Accomplishments
                if done_today:
                    lines.append(f"✅ {b(str(done_today) + ' completed')} today — nice work!")
                # Missed / pending
                if pending:
                    lines.append(f"⏳ {b(str(len(pending)) + ' still pending')}:")
                    for tid, title, dtime, cat, prio in pending[:6]:
                        emoji = "🔴" if prio == "high" else "🟢" if prio == "low" else "🟡"
                        tm = f" ⏰ {esc(dtime)}" if dtime else ""
                        lines.append(f"   {emoji} {esc(title)}{tm}")
                    lines.append(f"   <i>These carry to tomorrow automatically.</i>")
                lines.append("")
                # Tomorrow preview
                if tomorrow_tasks:
                    lines.append(f"🔮 {b('Tomorrow:')} {len(tomorrow_tasks)} task(s) lined up")
                    for t in tomorrow_tasks[:4]:
                        tm = f" ⏰ {esc(t[3])}" if len(t) > 3 and t[3] else ""
                        lines.append(f"   • {esc(t[1])}{tm}")

                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📅 Tomorrow", callback_data="dash:today"),
                    InlineKeyboardButton("📊 Stats", callback_data="dash:stats"),
                ]])
                try:
                    await context.bot.send_message(chat_id=uid, text="\n".join(lines).rstrip(),
                                                   parse_mode=HTML, reply_markup=kb)
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
                        last = datetime.strptime(w["last"], "%Y-%m-%d %H:%M").replace(tzinfo=IST)
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

    # ── v9.0: Morning Briefing (08:00 daily) ─────────────
    async def morning_briefing(context):
        """Daily 08:00 briefing: today's priorities, deadlines, overdue, goals."""
        try:
            now = datetime.now(IST)
            today = now.strftime("%Y-%m-%d")
            current_time = now.strftime("%H:%M")
            for uid in get_all_active_user_ids():
                if is_quiet_hours(uid):
                    continue
                todays = get_tasks_by_date(uid, today)
                overdue = get_overdue_tasks(uid, today, current_time)
                deadlines = get_upcoming_deadlines(uid, today, days_ahead=2)
                goals = get_goals_full(uid)
                if not todays and not overdue and not deadlines:
                    continue  # nothing to brief
                lines = [f"☀️ {b('Good morning!')} Here's your day:", ""]
                lines.append(f"<i>{esc(now.strftime('%A, %d %B'))}</i>\n")
                if todays:
                    high = [t for t in todays if len(t) > 5 and t[5] == "high"]
                    lines.append(f"📅 {b(str(len(todays)) + ' task(s) today')}")
                    for t in (high or todays)[:5]:
                        dot = "🔴" if (len(t) > 5 and t[5] == "high") else "🟡"
                        tm = f" ⏰ {esc(t[3])}" if len(t) > 3 and t[3] else ""
                        lines.append(f"   {dot} {esc(t[1])}{tm}")
                    lines.append("")
                if overdue:
                    lines.append(f"⚠️ {b(str(len(overdue)) + ' overdue')} — consider /review")
                    lines.append("")
                if deadlines:
                    lines.append(f"📌 {b('Deadlines soon:')}")
                    for d in deadlines[:3]:
                        lines.append(f"   • {esc(d[1])} ({esc(d[2] or '?')})")
                    lines.append("")
                if goals:
                    lines.append(f"🎯 {len(goals)} active goal(s) — tap below to review")
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📅 Today", callback_data="dash:today"),
                    InlineKeyboardButton("🏠 Dashboard", callback_data="dash:home"),
                ]])
                try:
                    await context.bot.send_message(chat_id=uid, text="\n".join(lines).rstrip(),
                                                   parse_mode=HTML, reply_markup=kb)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"morning_briefing failed: {e}")

    app.job_queue.run_daily(morning_briefing,
        time=datetime.strptime("08:00", "%H:%M").time(),
        name="morning_briefing")

    # ── v10.0: Weekly Report (Sunday 20:00) ──────────────
    async def weekly_report(context):
        """Automated weekly digest — sent every Sunday at 20:00."""
        try:
            for uid in get_all_active_user_ids():
                if is_quiet_hours(uid):
                    continue
                data = get_weekly_report_data(uid)
                if data["done_this_week"] == 0 and data["created_this_week"] == 0:
                    continue
                lines = [
                    f"📊 {b('Weekly Report')}",
                    f"<i>{datetime.now(IST).strftime('%d %b')} — week ending</i>",
                    "",
                    f"✅ Completed: {b(data['done_this_week'])}",
                    f"📝 Created: {b(data['created_this_week'])}",
                    f"📋 Still pending: {b(data['pending'])}",
                ]
                if data["overdue"]:
                    lines.append(f"⚠️ Overdue: {b(data['overdue'])}")
                lines.append(f"\n📈 Completion rate: {b(str(data['completion_rate']) + '%')}")
                if data["top_habits"]:
                    lines.append(f"\n🌱 {b('Top Habits')}")
                    for title, streak, longest in data["top_habits"]:
                        fire = "🔥" * min(streak or 0, 5) if streak else "○"
                        lines.append(f"   {fire} {esc(title)} — streak {streak or 0} (best {longest or 0})")
                lines.append(f"\n<i>Keep it up! 💪</i>")
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🏠 Dashboard", callback_data="dash:home"),
                    InlineKeyboardButton("📊 Full Stats", callback_data="dash:stats"),
                ]])
                try:
                    await context.bot.send_message(
                        chat_id=uid, text="\n".join(lines),
                        parse_mode=HTML, reply_markup=kb)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"weekly_report failed: {e}")

    # Run on Sundays at 20:00 (days=(6,) = Sunday)
    app.job_queue.run_daily(weekly_report,
        time=datetime.strptime("20:00", "%H:%M").time(),
        days=(6,), name="weekly_report")

    # ── v10.1: Smart Pre-Deadline Buffer Reminders ───────
    # Buffer thresholds — each is (label, seconds_remaining_max).
    # When a deadline is within this many seconds and the matching label
    # hasn't been sent yet, send the warning. Largest buffer fires first.
    BUFFER_STAGES = [
        ("7d", 7 * 24 * 3600,  "7 days"),
        ("3d", 3 * 24 * 3600,  "3 days"),
        ("1d", 24 * 3600,      "1 day"),
        ("6h", 6 * 3600,       "6 hours"),
        ("1h", 3600,           "1 hour"),
    ]

    async def deadline_buffer_check(context):
        """Send buffer reminders BEFORE deadlines, scaling with time-remaining."""
        try:
            now = datetime.now(IST)
            for d in get_pending_deadlines():
                tid, uid, title, ddate, dtime, priority, sent_str, category = d
                if is_quiet_hours(uid):
                    continue
                already_sent = parse_buffer_sent(sent_str)
                try:
                    deadline_dt = datetime.strptime(
                        f"{ddate} {dtime}", "%Y-%m-%d %H:%M").replace(tzinfo=IST)
                except Exception:
                    continue
                seconds_left = (deadline_dt - now).total_seconds()
                if seconds_left <= 0:
                    continue  # already passed → handled by normal reminders
                # Find the smallest buffer threshold this deadline currently fits in
                # that we haven't sent yet. Iterate small-to-large so we send the
                # most urgent unsent buffer.
                fire_label = None
                fire_text = None
                for label, threshold, human in BUFFER_STAGES:
                    if seconds_left <= threshold and label not in already_sent:
                        fire_label = label
                        fire_text = human
                        # Don't break — keep looking for smaller (more urgent) buffer
                # If still nothing, check larger ones (case: just created, many days away)
                if not fire_label:
                    for label, threshold, human in BUFFER_STAGES:
                        if seconds_left <= threshold and label not in already_sent:
                            fire_label = label
                            fire_text = human
                            break
                if not fire_label:
                    continue
                # Build the warning message
                priority_emoji = "🔴" if priority == "high" else "🟢" if priority == "low" else "🟡"
                # Compute a friendly countdown
                if seconds_left > 24 * 3600:
                    countdown = f"{int(seconds_left / 86400)} days"
                elif seconds_left > 3600:
                    countdown = f"{int(seconds_left / 3600)} hours"
                else:
                    countdown = f"{int(seconds_left / 60)} minutes"
                msg = (
                    f"⏳ {b('Deadline Approaching')}\n\n"
                    f"{priority_emoji} {b(title)}\n"
                    f"<i>🏷 {esc(category or 'General')}</i>\n\n"
                    f"📅 Due: {esc(ddate)} at {esc(dtime)}\n"
                    f"⏱ {b('Time remaining: ' + countdown)}\n\n"
                    f"💡 <i>This is your {fire_text}-out warning. "
                    f"Plan ahead — don't leave it for the deadline!</i>"
                )
                kb = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Done now", callback_data=f"done:{tid}"),
                        InlineKeyboardButton("🔨 Break down", callback_data=f"dobreak:{tid}"),
                    ],
                    [
                        InlineKeyboardButton("📅 Plan today", callback_data="dash:today"),
                        InlineKeyboardButton("🔕 Mute buffers", callback_data=f"unflagdeadline:{tid}"),
                    ],
                ])
                try:
                    await context.bot.send_message(chat_id=uid, text=msg,
                                                   parse_mode=HTML, reply_markup=kb)
                    mark_buffer_sent(tid, fire_label)
                    logger.info(f"[deadline] sent {fire_label} buffer for task {tid}")
                except Exception as e:
                    logger.error(f"deadline_buffer send failed: {e}")
        except Exception as e:
            logger.error(f"deadline_buffer_check failed: {e}")

    # Check every 30 min — frequent enough for hour-scale buffers
    app.job_queue.run_repeating(deadline_buffer_check, interval=1800, first=180)

    # ── v11.0: Daily AI Observation Engine ──────────────
    async def observation_engine(context):
        """
        Once a day at 22:00 — AI looks at user's week, generates suggestions.
        This is the autonomous behavior: BAKA proactively notices patterns
        instead of waiting to be asked.
        """
        try:
            for uid in get_all_active_user_ids():
                # Skip if user has many pending suggestions already (don't pile up)
                existing = get_pending_observations(uid, limit=5)
                if len(existing) >= 5:
                    continue
                # Get rich context
                try:
                    user_ctx = get_user_context_for_ai(uid)
                except Exception:
                    continue
                if not user_ctx.get("recent_completions") and not user_ctx.get("open_tasks_by_category"):
                    continue  # not enough data yet

                # Build the analysis prompt
                ctx_lines = [
                    "You are BAKA. Analyze this user's recent activity and identify "
                    "1-3 USEFUL observations or suggestions. Be specific and actionable. "
                    "Return ONLY valid JSON in this exact format:",
                    '{"observations":[{"observation":"...","suggestion":"...","action_type":null}]}',
                    "",
                    "action_type can be 'create_habit' if you spot a recurring activity worth tracking.",
                    "Otherwise leave action_type as null.",
                    "",
                    "DATA:",
                    f"Today: {user_ctx.get('today_date')} ({user_ctx.get('weekday')})",
                ]
                if user_ctx.get("recent_completions"):
                    ctx_lines.append("Recent completions:")
                    for t in user_ctx["recent_completions"][:10]:
                        ctx_lines.append(f"  - {t[0]} ({t[1] or 'General'}) at {t[2] or '?'}")
                if user_ctx.get("open_tasks_by_category"):
                    ctx_lines.append(f"Open tasks by category: {user_ctx['open_tasks_by_category']}")
                if user_ctx.get("overdue_count"):
                    ctx_lines.append(f"Overdue: {user_ctx['overdue_count']}")
                if user_ctx.get("active_habits"):
                    ctx_lines.append("Active habits:")
                    for h in user_ctx["active_habits"]:
                        ctx_lines.append(f"  - {h[0]} (streak {h[1]})")

                prompt = "\n".join(ctx_lines)

                # Use the FAST model — this is a quick periodic check, not deep reasoning
                try:
                    raw = await run_blocking(call_fast, [
                        {"role": "system", "content": "You return ONLY valid JSON. No prose, no markdown."},
                        {"role": "user", "content": prompt}
                    ], temperature=0.3, max_tokens=400)
                except Exception as e:
                    logger.error(f"observation_engine AI call failed: {e}")
                    continue

                # Parse the JSON
                try:
                    import json as _json
                    import re as _re
                    # Extract JSON block
                    m = _re.search(r'\{.*\}', raw or "", _re.DOTALL)
                    if not m:
                        continue
                    parsed = _json.loads(m.group())
                    obs_list = parsed.get("observations", [])
                except Exception as e:
                    logger.error(f"observation_engine parse failed: {e}")
                    continue

                # Store observations
                added = 0
                for obs in obs_list[:3]:
                    if not isinstance(obs, dict):
                        continue
                    observation = obs.get("observation", "").strip()
                    suggestion = obs.get("suggestion", "").strip() or None
                    action_type = obs.get("action_type")
                    if not observation or len(observation) < 10:
                        continue
                    add_observation(uid, observation, suggestion, action_type, None)
                    added += 1

                logger.info(f"[observation_engine] added {added} observations for user {uid}")
        except Exception as e:
            logger.error(f"observation_engine failed: {e}")

    # Run once daily at 22:00
    app.job_queue.run_daily(observation_engine,
        time=datetime.strptime("22:00", "%H:%M").time(),
        name="observation_engine")

    # ── v12.0: Project Stagnation Reminder ──────────────
    async def project_nudge(context):
        """
        Daily 20:00: for each active project:
        - if no worklog entry in 7+ days AND deadline < 30 days away → gentle nudge
        - if materials still pending AND deadline < 3 days away → urgent alert
        """
        try:
            for uid in get_all_active_user_ids():
                if is_quiet_hours(uid):
                    continue
                projects = get_active_projects(uid)
                for gid, title, deadline in projects:
                    if not deadline:
                        continue
                    try:
                        dl = datetime.strptime(deadline[:10], "%Y-%m-%d").replace(tzinfo=IST)
                        days_left = (dl.date() - datetime.now(IST).date()).days
                    except Exception:
                        continue
                    if days_left < 0:
                        continue  # already past — different job handles overdue

                    proj = get_project_overview(uid, gid)
                    if not proj:
                        continue

                    # Case A: deadline < 3 days, materials still missing → urgent
                    missing = proj["materials_total"] - proj["materials_acquired"]
                    if days_left <= 3 and missing > 0:
                        pending = [m[1] for m in proj["materials"] if not m[3]][:5]
                        pending_str = ", ".join(esc(p) for p in pending)
                        msg = (f"⚠️ {b('Deadline approaching')} — {b(esc(title))}\n\n"
                               f"📅 {b(str(days_left) + ' day(s) left')}\n"
                               f"📦 Still need: {pending_str}\n\n"
                               f"<i>You've got materials to gather before the deadline.</i>")
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton("📊 Project", callback_data=f"proj:view:{gid}"),
                            InlineKeyboardButton("🛒 Shopping list", callback_data="proj:shopping"),
                        ]])
                        try:
                            await context.bot.send_message(chat_id=uid, text=msg,
                                                           parse_mode=HTML, reply_markup=kb)
                        except Exception:
                            pass
                        continue

                    # Case B: stagnation (no work in 7+ days, deadline < 30 days)
                    days_idle = get_last_worklog_days(uid, gid)
                    if (days_left <= 30 and days_idle is not None
                            and days_idle >= 7 and proj["work_state"] != "finished"):
                        msg = (f"💤 {b(esc(title))} hasn't moved in {days_idle} days\n\n"
                               f"📅 Deadline: {esc(deadline)} ({days_left}d left)\n"
                               f"🔨 Last state: {esc(proj['work_state'])}\n"
                               f"📊 Progress: {proj['progress']}%\n\n"
                               f"<i>Ping me with an update when you make progress.</i>")
                        kb = InlineKeyboardMarkup([[
                            InlineKeyboardButton("📊 View", callback_data=f"proj:view:{gid}"),
                            InlineKeyboardButton("🚀 Log progress", callback_data=f"proj:started:{gid}"),
                        ]])
                        try:
                            await context.bot.send_message(chat_id=uid, text=msg,
                                                           parse_mode=HTML, reply_markup=kb)
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"project_nudge failed: {e}")

    app.job_queue.run_daily(project_nudge,
        time=datetime.strptime("20:00", "%H:%M").time(),
        name="project_nudge")

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

    # v15.0-beta.1: register the Workspace sync-drain worker on the existing
    # scheduler -- ONLY when WORKSPACE is ON. When OFF this is a no-op and
    # the job set is identical to v14.26.
    workspace_app.register_workers(app)

    logger.info("🤖 BAKA is online!")
    print("🤖 BAKA is running! Check bot.log for logs.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    # Python 3.14: asyncio.run() is the canonical entry point.
    # PTB's run_polling() manages its own event loop internally,
    # so we call main() directly — it calls app.run_polling() which handles async.
    try:
        main()
    except instance_lock.InstanceAlreadyRunningError:
        # Message already printed/logged inside instance_lock.acquire();
        # distinct exit code (2) so this is distinguishable from a real
        # crash (1) if anything scripted around run.sh ever cares to check.
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n⛔ BAKA stopped by user.")
        sys.exit(0)
    except Exception as exc:
        print(f"\n❌ Fatal error: {exc}")
        logging.getLogger(__name__).critical("Fatal startup error", exc_info=True)
        sys.exit(1)