# 🤖 BAKA — AI Personal Assistant Bot for Telegram

A conversational AI-powered Telegram bot that manages your tasks, reminders, goals, and productivity through natural language — in **English, Hindi, and Hinglish**.

Unlike typical reminder bots, BAKA **owns your tasks until they're done** — it keeps reminding you with escalating urgency, respects your sleep hours, and carries forward anything you miss.

---

## ✨ Key Features

### 💬 Natural Language — Just Talk
No commands needed. Just type like you're texting a friend.
```
"Remind me to call mom tomorrow at 5pm"
"Kal 8 baje gym yaad dila dena"
"Physics assignment next Friday tak complete karni hai"
"What do I have today?"
```

### 🔔 Persistent Reminders
- Reminders come with **tap-able buttons**: ✅ Done, ⏰ Snooze 10m, 🕐 Snooze 1h, 📅 Tomorrow
- **Keeps reminding** overdue tasks at configurable intervals
- **Escalates** near deadlines (30min → 15min → 10min → 5min)
- **Quiet hours** — no pings while you sleep (default 11PM–7AM)
- **Auto carry-forward** — overdue tasks move to today at midnight

### 🧠 AI-Powered
- Understands intent: task, reminder, goal, memory, chat, plan
- Stores personal facts: _"Remember my exam is June 20"_ → retrieves later
- Productivity analysis and task suggestions
- Study plan generation

### 📊 Tracking & Organization
- View tasks by: today, week, month, year, or all
- Overdue detection with visual indicators
- Deadline warnings (3-day lookahead)
- Tags for custom organization
- Priority levels (🔴 high, 🟡 medium, 🟢 low)
- Recurring tasks: daily, weekly, monthly

---

## 🚀 Quick Setup

### Prerequisites
- Python 3.10+
- A Telegram account
- [NVIDIA NIM API key](https://build.nvidia.com) (free tier)

### 1. Create your Telegram bot
1. Open Telegram → search **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the bot token

### 2. Get NVIDIA API key
1. Go to [build.nvidia.com](https://build.nvidia.com)
2. Find **z-ai/glm-5.1**
3. Click **Get API Key**

### 3. Clone and setup
```bash
git clone https://github.com/indbakasensei/telegram-planner-bot.git
cd telegram-planner-bot

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### 4. Configure
Create a `.env` file:
```
BOT_TOKEN=your_telegram_bot_token
NVIDIA_API_KEY=your_nvidia_api_key
```

### 5. Run
```bash
python3 main.py
```

For persistent running (survives terminal close):
```bash
screen -S baka
bash run.sh
# Press Ctrl+A then D to detach
```

---

## 📱 Bot Commands

### Task Management
| Command | What it does |
|---------|-------------|
| `/list` | Show all pending tasks |
| `/today` | Today's schedule |
| `/week` | This week's tasks |
| `/done <id>` | Mark a task complete |
| `/edit <id>` | Modify a task |
| `/delete <id>` | Remove a task |

### Reminders
| Command | What it does |
|---------|-------------|
| `/pause <id>` | Stop reminders for a task |
| `/resume <id>` | Restart reminders |
| `/paused` | View paused tasks |

### Tracking
| Command | What it does |
|---------|-------------|
| `/overdue` | List overdue tasks |
| `/deadlines` | Tasks due in 3 days |
| `/carryforward` | Move all overdue to today |
| `/tag <id> <tags>` | Add tags to a task |
| `/tagged <tag>` | Find tasks by tag |

### AI Features
| Command | What it does |
|---------|-------------|
| `/memory` | View stored memories |
| `/analyze` | Productivity analysis |
| `/suggest <goal>` | Get task suggestions |

### Settings
| Command | What it does |
|---------|-------------|
| `/settings` | View all preferences |
| `/quiethours <start> <end>` | Set sleep hours (no reminders) |
| `/interval <minutes>` | Change reminder frequency |
| `/status` | Check AI API health |

### Debug
| Command | What it does |
|---------|-------------|
| `/debug` | Toggle debug mode (shows AI reasoning) |
| `/report <issue>` | Report a bug (auto-captures context) |
| `/bugs` | View reported bugs |
| `/selftest` | Get test checklist |

---

## 🏗 Architecture

```
main.py               → Telegram handlers, conversation flow, state machine
baka_brain.py        → NVIDIA NIM API, intent detection, AI responses
database.py            → SQLite operations (tasks, memories, goals, preferences)
date_parser.py         → Regex date/time parser (English + Hindi + Hinglish)
conversation_state.py  → Per-user state machine (idle/gathering/confirming/editing)
scheduler.py           → Reminder engine with escalation + quiet hours
debug_system.py        → In-bot bug tracking + interaction tracing
```

### How Messages Are Processed
1. User sends a message in any language
2. Keyword shortcuts checked first (fast path for "show", "list", etc.)
3. State machine checked (are we mid-conversation?)
4. Deterministic regex parser extracts date/time/recurrence
5. AI classifies intent and extracts task title
6. Parser results override AI for dates (regex is more reliable)
7. Bot shows confirmation → user approves → task saved

---

## 🗄 Database Schema

### tasks
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Auto-increment primary key |
| user_id | INTEGER | Telegram user ID |
| title | TEXT | Task name |
| due_date | TEXT | YYYY-MM-DD |
| due_time | TEXT | HH:MM |
| category | TEXT | Study/Health/Work/Personal/Other |
| priority | TEXT | high/medium/low |
| done | INTEGER | 0=pending, 1=complete |
| recurrence_type | TEXT | daily/weekly/monthly |
| paused | INTEGER | 0=active, 1=paused |
| snooze_until | TEXT | Snooze expiry timestamp |
| reminder_count | INTEGER | Times reminded |
| tags | TEXT | Space-separated tags |

### memories
| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Telegram user ID |
| key | TEXT | Lowercased memory key |
| value | TEXT | What to remember |

### user_preferences
| Column | Type | Description |
|--------|------|-------------|
| user_id | INTEGER | Primary key |
| quiet_start | TEXT | Quiet hours start (HH:MM) |
| quiet_end | TEXT | Quiet hours end (HH:MM) |
| reminder_interval | INTEGER | Minutes between re-reminders |
| max_reminders_per_task | INTEGER | Stop after N reminders |

---

## 🌍 Language Support

| Language | Example |
|----------|---------|
| English | "Remind me to study at 8 PM" |
| Hindi | "Kal subah 8 baje gym yaad dila dena" |
| Hinglish | "Bhai next Friday assignment submit karna hai" |

**Hindi date/time words understood:**
`aaj` (today), `kal` (tomorrow), `parso` (day after),
`subah` (morning), `dopahar` (afternoon), `shaam` (evening), `raat` (night),
`baje` (o'clock), `har roz` (daily), `har hafte` (weekly)

---

## ⚙️ Configuration

All settings are configurable via Telegram:

| Setting | Default | Command |
|---------|---------|---------|
| Quiet hours | 11 PM – 7 AM | `/quiethours 23:00 07:00` |
| Reminder interval | 30 min | `/interval 30` |
| Max reminders | 5 per task | Via settings |

---

## 🔧 Tech Stack

- **Python 3.12** with async/await
- **python-telegram-bot 20.7** (Telegram API)
- **NVIDIA NIM API** — z-ai/glm-5.1 (free tier: 1000 calls/month)
- **SQLite** — zero-config database
- **pytz** — IST timezone handling
- **APScheduler** — reminder scheduling

---

## 📝 Version History

| Version | What was added |
|---------|---------------|
| v1.0 | Debug system — /debug, /report, /bugs, /trace, /selftest |
| v1.1 | Snooze, postpone, pause/resume, inline reminder buttons |
| v1.2 | Overdue handling, deadline warnings, tags, carry-forward |
| v2.0 | Passive PA — remind until done, escalation, quiet hours, batching |

See [VERSION.md](VERSION.md) for full changelog.

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Enable debug mode in the bot: `/debug`
4. Test with `/selftest` checklist
5. Report issues with `/report` from inside the bot
6. Push and open a PR

---

## 📜 License

MIT License — use it, modify it, make it yours.

---

Built with ❤️ using Claude AI + NVIDIA NIM