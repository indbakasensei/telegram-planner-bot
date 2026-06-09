import os
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from database import (
    init_db, add_task, get_tasks, get_tasks_by_date,
    get_tasks_by_week, mark_done, delete_task
)
from ai_helper import chat_with_ai, suggest_tasks, analyze_productivity, auto_schedule
from datetime import datetime, timedelta

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Conversation states
TITLE, DATE, TIME, CATEGORY = range(4)

# ─── /start ───────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to your *Personal Planner Bot!*\n\n"
        "📌 *Task Commands:*\n"
        "/add — Add a new task\n"
        "/list — View all pending tasks\n"
        "/today — Tasks for today\n"
        "/week — Tasks for this week\n"
        "/year — Tasks for this year\n"
        "/done <id> — Mark task complete\n"
        "/delete <id> — Delete a task\n\n"
        "🤖 *AI Commands:*\n"
        "/ai <question> — Chat with AI\n"
        "/suggest <goal> — Get task suggestions\n"
        "/analyze — Productivity analysis\n"
        "/smart <text> — Auto-schedule a task\n\n"
        "❓ /help — Show this menu again",
        parse_mode="Markdown"
    )

# ─── /help ────────────────────────────────────────────
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

# ─── /add (conversation) ──────────────────────────────
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 What's the task title?")
    return TITLE

async def add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['title'] = update.message.text
    await update.message.reply_text(
        "📅 Enter due date (YYYY-MM-DD) or type *skip*:",
        parse_mode="Markdown"
    )
    return DATE

async def add_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == 'skip':
        context.user_data['due_date'] = None
    else:
        try:
            datetime.strptime(text, "%Y-%m-%d")
            context.user_data['due_date'] = text
        except ValueError:
            await update.message.reply_text("❌ Invalid format. Use YYYY-MM-DD or type *skip*:", parse_mode="Markdown")
            return DATE
    await update.message.reply_text("⏰ Enter due time (HH:MM) or type *skip*:", parse_mode="Markdown")
    return TIME

async def add_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == 'skip':
        context.user_data['due_time'] = None
    else:
        try:
            datetime.strptime(text, "%H:%M")
            context.user_data['due_time'] = text
        except ValueError:
            await update.message.reply_text("❌ Invalid format. Use HH:MM or type *skip*:", parse_mode="Markdown")
            return TIME

    keyboard = [['📚 Study', '💪 Health'], ['💼 Work', '🎯 Personal'], ['📦 Other']]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("🏷 Choose a category:", reply_markup=reply_markup)
    return CATEGORY

async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category = update.message.text.strip()
    user_id = update.message.from_user.id

    add_task(
        user_id,
        context.user_data['title'],
        context.user_data.get('due_date'),
        context.user_data.get('due_time'),
        category
    )

    await update.message.reply_text(
        f"✅ Task added!\n\n"
        f"📌 *{context.user_data['title']}*\n"
        f"📅 Date: {context.user_data.get('due_date') or 'No date'}\n"
        f"⏰ Time: {context.user_data.get('due_time') or 'No time'}\n"
        f"🏷 Category: {category}",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ─── /list ────────────────────────────────────────────
async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    tasks = get_tasks(user_id)
    if not tasks:
        await update.message.reply_text("🎉 No pending tasks!")
        return
    msg = "📋 *Your Pending Tasks:*\n\n"
    for t in tasks:
        msg += f"*[{t[0]}]* {t[1]}\n"
        msg += f"      📅 {t[2] or 'No date'}  ⏰ {t[3] or 'No time'}  🏷 {t[4]}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── /today ───────────────────────────────────────────
async def today_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    tasks = get_tasks_by_date(user_id, today)
    if not tasks:
        await update.message.reply_text(f"✅ No tasks for today ({today})!")
        return
    msg = f"📅 *Tasks for Today ({today}):*\n\n"
    for t in tasks:
        msg += f"*[{t[0]}]* {t[1]}  ⏰ {t[3] or 'No time'}  🏷 {t[4]}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── /week ────────────────────────────────────────────
async def week_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    today = datetime.now()
    start = today.strftime("%Y-%m-%d")
    end = (today + timedelta(days=7)).strftime("%Y-%m-%d")
    tasks = get_tasks_by_week(user_id, start, end)
    if not tasks:
        await update.message.reply_text("✅ No tasks for the next 7 days!")
        return
    msg = "🗓 *Tasks for This Week:*\n\n"
    for t in tasks:
        msg += f"*[{t[0]}]* {t[1]}\n"
        msg += f"      📅 {t[2]}  ⏰ {t[3] or 'No time'}  🏷 {t[4]}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── /year ────────────────────────────────────────────
async def year_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    today = datetime.now()
    start = today.strftime("%Y-%m-%d")
    end = f"{today.year}-12-31"
    tasks = get_tasks_by_week(user_id, start, end)
    if not tasks:
        await update.message.reply_text("✅ No upcoming tasks for this year!")
        return
    msg = "📆 *Tasks for This Year:*\n\n"
    for t in tasks:
        msg += f"*[{t[0]}]* {t[1]}\n"
        msg += f"      📅 {t[2]}  ⏰ {t[3] or 'No time'}  🏷 {t[4]}\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# ─── /done ────────────────────────────────────────────
async def done_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("Usage: /done <task_id>\nExample: /done 3")
        return
    task_id = int(context.args[0])
    mark_done(task_id, user_id)
    await update.message.reply_text(f"✅ Task [{task_id}] marked as done!")

# ─── /delete ──────────────────────────────────────────
async def delete_task_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("Usage: /delete <task_id>\nExample: /delete 3")
        return
    task_id = int(context.args[0])
    delete_task(task_id, user_id)
    await update.message.reply_text(f"🗑 Task [{task_id}] deleted!")

# ─── /ai ──────────────────────────────────────────────
async def ai_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ai <your question>\nExample: /ai how to study better?")
        return
    user_message = " ".join(context.args)
    await update.message.reply_text("🤔 Thinking...")
    response = chat_with_ai(user_message)
    await update.message.reply_text(f"🤖 {response}")

# ─── /suggest ─────────────────────────────────────────
async def ai_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /suggest <your goal>\nExample: /suggest pass my exams")
        return
    goal = " ".join(context.args)
    await update.message.reply_text("🧠 Generating task suggestions...")
    response = suggest_tasks(goal)
    await update.message.reply_text(f"🎯 *Tasks to achieve your goal:*\n\n{response}", parse_mode="Markdown")

# ─── /analyze ─────────────────────────────────────────
async def ai_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    tasks = get_tasks(user_id)
    await update.message.reply_text("📊 Analyzing your productivity...")
    response = analyze_productivity(tasks)
    await update.message.reply_text(f"📊 *Productivity Analysis:*\n\n{response}", parse_mode="Markdown")

# ─── /smart ───────────────────────────────────────────
async def ai_smart_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /smart <task in plain text>\n"
            "Example: /smart remind me to submit assignment tomorrow at 3pm"
        )
        return
    user_id = update.message.from_user.id
    user_input = " ".join(context.args)
    await update.message.reply_text("🗓 Processing your task...")
    result = auto_schedule(user_input)

    if 'error' in result:
        await update.message.reply_text(f"❌ Error: {result['error']}")
        return

    add_task(
        user_id,
        result.get('title', user_input),
        result.get('due_date'),
        result.get('due_time'),
        result.get('category', 'General')
    )

    await update.message.reply_text(
        f"✅ *Task auto-scheduled!*\n\n"
        f"📌 *{result.get('title')}*\n"
        f"📅 Date: {result.get('due_date') or 'No date'}\n"
        f"⏰ Time: {result.get('due_time') or 'No time'}\n"
        f"🏷 Category: {result.get('category')}",
        parse_mode="Markdown"
    )

# ─── MAIN ─────────────────────────────────────────────
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('add', add_start)],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_title)],
            DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_date)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_time)],
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_category)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('list', list_tasks))
    app.add_handler(CommandHandler('today', today_tasks))
    app.add_handler(CommandHandler('week', week_tasks))
    app.add_handler(CommandHandler('year', year_tasks))
    app.add_handler(CommandHandler('done', done_task))
    app.add_handler(CommandHandler('delete', delete_task_cmd))
    app.add_handler(CommandHandler('ai', ai_chat))
    app.add_handler(CommandHandler('suggest', ai_suggest))
    app.add_handler(CommandHandler('analyze', ai_analyze))
    app.add_handler(CommandHandler('smart', ai_smart_add))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
