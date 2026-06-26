# BAKA Telegram Bot — Complete Feature List

## Project Overview
A conversational AI-powered Telegram personal assistant bot built in Python.
Named BAKA (like Iron Man's assistant). The bot understands natural language
in English, Hindi, and Hinglish without requiring commands or structured input.

## Tech Stack
- Language: Python 3.12
- Telegram Library: python-telegram-bot 20.7 (async)
- AI Model: NVIDIA NIM API — meta/llama-3.1-8b-instruct (free tier)
- Database: SQLite (planner.db)
- Scheduler: APScheduler via PTB job_queue
- Date/Time Parser: Custom deterministic regex engine (date_parser.py)
- Timezone: Asia/Kolkata (IST, UTC+5:30)
- Platform: Ubuntu WSL on Windows
- Version Control: GitHub

---

## FEATURE LIST

### 1. Natural Language Task Creation
User can type tasks in plain conversational language without any commands.
The bot understands the intent, extracts structured information, and asks
for confirmation before saving.
Example: "I need to finish my physics assignment by Friday"

### 2. Confirmation Flow (BAKA-style)
Before saving any task, the bot always shows a summary and asks the user
to confirm with Yes/No buttons. Nothing is saved without user approval.
This prevents accidental saves and duplicate tasks.

### 3. Hindi Language Support
The bot understands pure Hindi date and time expressions.
- "Kal" = tomorrow
- "Aaj" = today
- "Parso" = day after tomorrow
- "Subah" = morning (AM)
- "Raat" = night (PM)
- "Shaam" = evening (PM)
- "Dopahar" = afternoon (PM)
- "Har roz" = every day
- "Har hafte" = every week

### 4. Hinglish Language Support
Mixed Hindi-English (Hinglish) is fully supported.
Example: "Bhai kal 9 baje meeting yaad dila dena"
Example: "Next Friday assignment submit karna hai"
Example: "Aaj raat 10 baje assignment complete karna hai"

### 5. Deterministic Date Parsing
A custom regex-based date parser (date_parser.py) handles all date formats
reliably without depending on the AI model. This fixes the common problem
where LLMs return NULL for "today" or "tomorrow".
Supported formats:
- today, tomorrow, day after tomorrow
- next Monday, this Friday, Sunday ko
- 25 December, December 25, 25 Dec 2026
- YYYY-MM-DD format
- in 3 days

### 6. Relative Time Parsing
The bot understands time expressions relative to the current moment.
- "in 2 hours" → current time + 2 hours
- "in 30 minutes" → current time + 30 minutes
- "after 1 hour" → current time + 1 hour

### 7. Ambiguous Time Detection (Baje Fix)
When user says "3 baje" without context (morning or evening), the bot
detects the ambiguity and asks "Did you mean 3 AM or 3 PM?" with
clickable buttons instead of silently guessing.
Context words (subah/raat/shaam) resolve the ambiguity automatically.

### 8. Invalid Time Validation
The bot detects impossible times like "25 PM" or "13 AM" and shows an
error message asking the user to correct it before saving.

### 9. Past Date Detection
If a user says "yesterday" or provides a date that has already passed,
the bot flags it with a warning instead of silently saving a past task.

### 10. Task Scheduling with Date and Time
Every task can have an optional due date and due time.
Users can skip either one if not needed.
Tasks are stored with full metadata: title, date, time, category, priority.

### 11. Task Categories
Every task can be categorized:
- Study
- Health
- Work
- Personal
- Other
Categories are shown with emoji indicators in the task list.

### 12. Task Priority
Every task has a priority level: high, medium, or low.
Priority is shown with colored dot emojis in task lists:
🔴 High, 🟡 Medium, 🟢 Low

### 13. Recurring Tasks
The bot supports three types of recurring tasks stored in the database:
- Daily: fires every day at the set time
- Weekly: fires on a specific weekday at the set time
- Monthly: fires on a specific day of the month
Example: "Go to gym every day at 6 AM"
Example: "Call parents every Sunday"
Example: "Pay rent on the 1st of every month"

### 14. Multiple Tasks in One Message
When the user mentions more than one task in a single message using
"and", "aur", or similar separators, the bot detects multiple tasks,
shows them all in a confirmation summary, and saves them all at once.
Example: "Tomorrow buy groceries and call mom"

### 15. Reminder Notifications
The bot sends automatic Telegram notifications when a task is due.
The scheduler checks every minute using IST timezone (not UTC).
Reminders include the task title, date, time, and a quick-complete button.

### 16. Recurring Reminder Scheduler
The scheduler handles all three recurrence types:
- Daily tasks fire at the same time every day
- Weekly tasks fire only on their designated weekday
- Monthly tasks fire only on their designated day of month
Duplicate reminder prevention using de-duplication logic.

### 17. Memory System
The bot can store and retrieve personal facts about the user.
User says: "Remember that my exam is on June 20"
Bot stores it with a key-value pair.
User says: "When are my exams?"
Bot retrieves and displays the stored memory.
Memory persists across conversations in the database.

### 18. Task Editing via Natural Language
User can modify existing tasks by describing the change naturally.
Example: "Move my gym task to tomorrow"
Example: "Change homework time to 6pm"
Also supports /edit <id> command for direct editing.

### 19. Task Deletion via Natural Language
User can delete tasks by name or ID naturally.
Example: "Delete my homework task"
Example: "Remove the gym reminder"
The bot shows a confirmation before deleting.

### 20. Mark Task Complete
Users can mark tasks done via command (/done <id>) or natural language.
Example: "Mark gym task complete"
Completed tasks are hidden from the pending list.

### 21. Multiple View Modes
Users can view their tasks filtered by time period:
- Today's tasks
- Tomorrow's tasks
- This week (next 7 days)
- This month (next 30 days)
- This year
- All pending tasks

### 22. Goal Setting
The bot understands when a user is setting a long-term goal rather than
a specific task. Goals are stored separately with optional deadlines.
Example: "I want to get fit by December"

### 23. Smart Scheduling / Study Plans
When a user asks for a plan, the bot generates an AI-powered day-by-day
study or work schedule broken into sessions.
Example: "Plan my week"
Example: "Help me prepare for exams"

### 24. Productivity Analysis
The /analyze command (or natural language trigger) analyzes all pending
and completed tasks and gives:
- Overall productivity pattern
- Overdue or urgent tasks
- 3 improvement tips
- Today's recommended focus

### 25. Task Suggestions from Goals
/suggest <goal> generates 5 specific actionable tasks to achieve a goal.
Example: "/suggest pass my semester exams"

### 26. AI Chat Mode
Users can ask the bot anything using /ai <question> or naturally.
Example: "How do I focus better while studying?"
The bot responds conversationally using the NVIDIA LLM.

### 27. Conversation History Context
The bot maintains a short history of recent messages per user and injects
it into the AI prompt so the model can understand follow-up messages
and references to previous turns.

### 28. Intent Detection Engine
Every incoming message is classified into one of these intents before
any action is taken:
TASK, EDIT, DELETE, VIEW, MEMORY_SAVE, MEMORY_GET,
GOAL, PLAN, ADVICE, CHAT, MULTIPLE
This prevents casual messages from being treated as tasks.

### 29. State Machine Conversation Flow
The bot tracks conversation state per user:
- idle: ready for new input
- gathering: collecting missing information
- confirming: waiting for yes/no on a pending action
- editing: modifying a specific task
States are stored in module-level dicts (not session data) so they
survive bot restarts.

### 30. Menu Keyboard
A persistent reply keyboard with quick-access buttons for all major
features. Buttons work the same as typed commands.

### 31. Yes/No Confirmation Buttons
A one-time keyboard with "Yes, save it!" and "No, cancel" appears
whenever the bot needs confirmation, making mobile use easy.

### 32. API Health Status Check
/status command runs a live diagnostic of the NVIDIA API and shows:
- Online/offline status
- Response time in milliseconds with speed rating
- Token usage for the last request
- Free tier limits (1000 calls/month, 40 req/minute)
- Error type if offline (rate limited, invalid key, server down)

### 33. Comprehensive Error Handling
All API calls have 3 retry attempts with 2-second delays.
JSON parse failures have a keyword-based fallback classifier.
All errors are caught and shown to users with helpful messages.

### 34. Full Logging System
All bot activity is logged to bot.log with timestamps.
Logs include: user messages, detected intents, extracted entities,
API errors, reminder fires, and all exceptions with stack traces.

### 35. Auto-Restart Script (run.sh)
A shell script that automatically restarts the bot if it crashes,
with a 5-second delay between restarts.

### 36. Screen Session Persistence
The bot runs inside a Linux screen session so it stays alive even
when the terminal is closed or the SSH session ends.
Commands: screen -S plannerbot to start, Ctrl+A D to detach,
screen -r plannerbot to reattach.

### 37. Timezone-Aware Reminders
All date and time operations use IST (Asia/Kolkata, UTC+5:30).
The system clock runs on UTC but all user-facing times are in IST.
This prevents reminders from firing at wrong times.

### 38. Duplicate Task Prevention
Before saving any task, the bot checks if an identical task with the
same title and date already exists for that user.
If it does, the bot shows the existing task ID instead of creating
a duplicate.

### 39. Multi-User Support
The bot is designed to serve multiple users simultaneously.
All database queries are scoped by user_id so each user has a
completely separate task list, memories, and goals.

### 40. GitHub Version Control
Full codebase is version controlled on GitHub with .gitignore
configured to exclude secrets (.env), database (planner.db),
logs (bot.log), and virtual environment (venv/).

---

## Files and Their Roles

| File | Purpose |
|------|---------|
| main.py | All Telegram handlers, conversation flow, intent routing |
| baka_brain.py | NVIDIA NIM API calls, intent detection, AI responses |
| database.py | SQLite operations for tasks, memories, goals |
| date_parser.py | Deterministic regex date/time parser (English+Hindi+Hinglish) |
| conversation_state.py | Module-level state machine per user |
| scheduler.py | Reminder checker with recurring task support |
| bot_state.py | Legacy state module (kept for compatibility) |
| ai_helper.py | Legacy AI module (kept for compatibility) |
| run.sh | Auto-restart shell script |
| .env | BOT_TOKEN and NVIDIA_API_KEY (never committed to git) |

---

## Known Limitations / Future Work

- Smart scheduling creates a text plan but does not auto-generate
  individual database tasks from it yet
- Analytics are triggered by /analyze command but not yet by all
  casual natural language phrasings
- Productivity scoring (tasks completed vs missed per week) not yet tracked
- Proactive suggestions (bot notices postponed tasks and offers to split
  them) not yet implemented
- No web dashboard — all interaction is through Telegram only
- Currently hosted locally (WSL), not yet deployed to Railway cloud