# 🤖 BAKA — AI Personal Assistant (Telegram)

**Behavioral Adaptive Knowledge Assistant** — A multi-model AI Telegram bot that manages your tasks, deadlines, habits, goals, and productivity through natural conversation in **English, Hindi, and Hinglish**.

> BAKA doesn't just remind you — it **owns your tasks until they're done**, learns your patterns, monitors its own AI performance, and gets smarter every day.

---

## ✨ What makes BAKA different

| Feature | Other reminder bots | BAKA |
|---------|---------------------|------|
| Language | English only | English + Hindi + Hinglish |
| Reminders | Fires once | Persists until done, escalates |
| Intelligence | Rule-based | Multi-model AI (GLM 5.1 + Llama 3.1 + Vision) |
| Learning | None | Learns your patterns, active hours, tone |
| Deadlines | At the time | **Before** — warns 7d/3d/1d/6h/1h ahead |
| Habits | Not built-in | Full habit engine with streaks + grid |
| Analytics | None | Tracks every AI call — latency, tokens, cost |
| Dashboard | None | Interactive hub with inline buttons |
| Photos | Not supported | Llama 3.2 Vision understands images |

---

## 🚀 Quick Setup

### Prerequisites
- Python 3.12+
- A Telegram account
- [NVIDIA NIM API key](https://build.nvidia.com) (free tier: 1,000 calls/month)

### 1. Clone and install

```bash
git clone https://github.com/indbakasensei/telegram-planner-bot
cd telegram-planner-bot
python3 -m venv venv
source venv/bin/activate
pip install python-telegram-bot[job-queue]==20.7 httpx==0.25.2 openai python-dotenv pytz
```

### 2. Get your tokens

**Telegram Bot Token:**
```
Open Telegram → @BotFather → /newbot → copy the token
```

**NVIDIA NIM API Key:**
```
Go to build.nvidia.com → find z-ai/glm-5.1 → Generate API Key
```

### 3. Create `.env`

```bash
cat > .env << 'EOF'
BOT_TOKEN=your_telegram_bot_token_here
NVIDIA_API_KEY=nvapi-your_nvidia_key_here
EOF
```

### 4. Run

```bash
python3 main.py
```

### 5. Claim admin (first run)

In Telegram, send `/claimadmin` — this locks admin access permanently to your Telegram ID.

---

## 💬 Just Talk

No commands needed. Just type naturally:

```
"Remind me to submit assignment by Friday 5pm"    → saves as deadline, warns 7d/3d/1d/6h/1h before
"Kal subah 8 baje gym yaad dila dena"             → tomorrow 08:00 task
"Go to gym every day at 6 AM"                     → daily habit with streak tracking
"I want to read 12 books this year"               → goal with progress dashboard
"think what should I focus on today?"             → AI reasons with your actual task list
"search physics"                                  → finds tasks + memories + habits + goals
```

Slash is optional for every command:
```
/list  =  list  =  "show my tasks"
/done 5  =  done 5
```

---

## 📋 Commands Reference

### Tasks
| Command | What it does |
|---------|-------------|
| `list` | All pending tasks |
| `today` | Today's schedule |
| `week` | This week's plan |
| `done <id>` | Mark complete |
| `edit <id>` | Modify a task |
| `delete <id>` | Remove a task |
| `deadline <id>` | Toggle pre-deadline warnings |

### Reminders
Every reminder has tap-able buttons: ✅ Done · ⏰ 10m · 🕐 1h · 📅 Tomorrow · 🔕 Stop · 🗑 Delete

| Command | What it does |
|---------|-------------|
| `snooze <id> <min>` | Custom snooze duration |
| `pause <id>` | Stop reminders temporarily |
| `resume <id>` | Restart reminders |
| `paused` | View all paused tasks |

### Deadlines ⏳
Say "due by", "submit by", "deliver before", "tak karna hai" and BAKA auto-enables deadline mode — warns you **before** the deadline at:

```
7 days → 3 days → 1 day → 6 hours → 1 hour before
```

Each warning has: ✅ Done now · 🔨 Break down · 📅 Plan today · 🔕 Mute

### Habits 🌱
| Command | What it does |
|---------|-------------|
| `habits` | All active habits with streaks |
| `streak <id>` | 14-day visual grid |
| `habitlog <id>` | 30-day history |
| `addhabit <title>` | Quick creation |
| `skiphabit <id>` | Skip (resets streak) |

### Goals 🎯
| Command | What it does |
|---------|-------------|
| `goals` | Progress dashboard with bars |
| Say "I want to X" | Auto-detected as goal |
| ➕/➖ buttons | Adjust progress inline |

### AI & Planning 🧠
| Command | What it does |
|---------|-------------|
| `think <question>` | Free-form AI reasoning with your data |
| `plan today` | Time-blocked AI plan (asks to apply) |
| `plan week` | 7-day schedule with overload warnings |
| `breakdown <id>` | Split big task into subtasks |
| `reschedule <id>` | AI picks a conflict-free time |
| `analyze` | Productivity report |
| `insights` | What BAKA learned about you |
| `suggestions` | Daily AI-generated suggestions |
| `approve <id>` | Apply a suggestion (auto-creates if applicable) |

### Search & Tools 🔍
| Command | What it does |
|---------|-------------|
| `search <keyword>` | Search tasks, memories, habits, goals |
| `template` | List saved templates |
| `template <name>` | Create task from template |
| `savetemplate <name> <id>` | Save task as template |
| `export` | Full data backup as plain text |

### AI Models (v11.0) 🤖
| Command | What it does |
|---------|-------------|
| `models` | All 6 model statuses with real usage |
| `image <prompt>` | Generate an image (opt-in) |
| Send a photo | Llama Vision describes it or extracts todos |

### AI Analytics (v11.1) 📊
| Command | What it does |
|---------|-------------|
| `usage` | Today + lifetime AI call stats |
| `performance` | p50/p95/p99 latency + trends |
| `errors` | Error timeline + breakdown |
| `status` | Quick 3-test AI benchmark |
| `status full` | Deep 6-test benchmark (graded A+-F) |

### Settings ⚙️
| Command | What it does |
|---------|-------------|
| `settings` | View all preferences |
| `quiethours <start> <end>` | Sleep window (no pings) |
| `interval <min>` | Reminder frequency |
| `wellness on/off` | 💧 Water/break/eye nudges |
| `proactive` | All automatic features panel |

### Debug 🐞
| Command | What it does |
|---------|-------------|
| `debug` | Toggle verbose debug mode |
| `report <issue>` | File a bug (auto-captures context) |
| `bugs` | View open bug reports |
| `trace` | Last AI interaction details |
| `selftest` | Step-by-step test checklist (50 tests) |

### Admin (owner only) 👑
These commands are invisible to non-admins. Only the account that ran `/claimadmin` can use them.

| Command | What it does |
|---------|-------------|
| `admin` | Control panel with data stats |
| `adminmode` | Toggle verbose debug |
| `resettasks` | Delete all tasks + reset IDs to 1 |
| `resetall` | Nuclear wipe (requires `YES NUKE EVERYTHING`) |
| `sql <query>` | Read-only SQL for debugging |
| `misses` | View what AI couldn't handle |
| `myid` | Your Telegram ID |

---

## 🤖 AI Architecture (v11.0)

BAKA uses 6 specialized models via NVIDIA NIM:

| Role | Model | Purpose |
|------|-------|---------|
| 🧠 Main Brain | `z-ai/glm-5.1` | Intent detection, planning, save logic |
| ⚡ Fast | `meta/llama-3.1-8b-instruct` | Quick classification, daily observations |
| 💭 Think | `z-ai/glm-5.1` | `/think` free-form reasoning |
| 👀 Vision | `meta/llama-3.2-90b-vision-instruct` | Image understanding |
| 🎨 Image | `black-forest-labs/flux.1-dev` | Image generation |
| 🎬 Video | `nvidia/cosmos-1.0-7b-text2world` | Video generation |

Feature toggles in `baka_brain.py`:
```python
ENABLE_FAST_ROUTING = False  # Llama 8B pre-filter (saves credits)
ENABLE_VISION       = True   # Image understanding
ENABLE_IMAGE_GEN    = False  # Opt-in (costs more credits)
ENABLE_VIDEO_GEN    = False  # Opt-in (expensive)
```

---

## 📊 AI Analytics (v11.1)

Every AI call is automatically logged to a `ai_usage` SQLite table with:
- Provider, model, latency, token counts, estimated cost
- Success/failure status, error messages, fallback activations
- Session tracking

Zero overhead — uses an async background-thread writer (0.017ms per call).

---

## 🗄️ File Structure

```
telegram-planner-bot/
├── main.py              — All handlers, dashboard, state machine, scheduler
├── baka_brain.py        — Multi-model AI, intent detection, reasoning
├── database.py          — SQLite CRUD + all migrations
├── date_parser.py       — Regex date/time parser (EN/Hindi/Hinglish)
├── scheduler.py         — Reminder engine (snooze/escalation/quiet-hours)
├── conversation_state.py — State machine (idle/gathering/confirming/editing)
├── debug_system.py      — Bug tracking, selftest messages
├── preferences.py       — Behavioral analysis (v6.0 learning)
├── fmt.py               — HTML formatting helpers
├── ui.py                — Dashboard card components
├── analytics/           — AI usage monitoring package (v11.1)
│   ├── __init__.py
│   ├── usage_logger.py  — Async logger (background thread)
│   ├── usage_service.py — Dashboard query functions
│   ├── model_metrics.py — Per-model rollups + health detection
│   ├── token_counter.py — Cost estimation (15 models)
│   └── performance_tracker.py — Latency percentiles + trends
├── .env                 — Secrets (gitignored)
├── admin_id.txt         — Admin lock (gitignored)
├── planner.db           — Main database (gitignored)
└── bugs.db              — Bug tracker (gitignored)
```

---

## 🗃️ Database Schema

13 active tables in `planner.db`:

| Table | Purpose |
|-------|---------|
| `tasks` | Tasks + habits (24 columns inc. streak, snooze, deadline) |
| `memories` | Key-value personal facts |
| `goals` | Goals with progress + target columns |
| `habit_log` | Daily habit completion log |
| `user_preferences` | Quiet hours, interval, wellness settings |
| `completions_log` | v6.0 — when tasks were completed |
| `snooze_log` | v6.0 — snooze patterns by category |
| `interaction_log` | v6.0 — active-hours tracking |
| `task_templates` | Reusable task patterns |
| `missed_capabilities` | What AI couldn't handle (feature mining) |
| `ai_observations` | AI-generated daily suggestions |
| `ai_usage` | Every AI call: model, tokens, latency, cost |

---

## 🔄 Version History

| Version | Highlights |
|---------|-----------|
| v1.0 | Debug system, task lifecycle |
| v1.1 | Snooze/pause/postpone, inline buttons |
| v1.2 | Overdue detection, deadline warnings, tags |
| v2.0 | Passive PA — persistent reminders, quiet hours |
| v3.0 | Vague time (shaam/evening/morning), urgency detection |
| v4.0 | Smart planning, task breakdown, subtasks |
| v5.0 | Habit engine, streaks, 14-day grid |
| v5.1 | JARVIS → BAKA rebrand |
| v6.0 | Preference learning — learns your patterns |
| v6.1 | Admin mode — owner-only panel, task ID reset |
| v7.0 | Follow-up intelligence, repeated-snooze detection |
| v7.1 | Bug fixes from live logs, HTML formatting |
| v8.0 | Proactive wellness nudges, slot-crowding hints |
| v9.0 | Dashboard system — 6 card types, inline navigation |
| v9.1 | GLM 5.1 AI upgrade, enhanced /status benchmark |
| v10.0 | Search, templates, weekly report, export |
| v10.1 | Pre-deadline buffer reminders (7d/3d/1d/6h/1h) |
| v10.2 | AI autonomy foundation — context, /think, miss log |
| v11.0 | Multi-model AI — 6 models, vision, image gen, observation engine |
| v11.1 | AI analytics — every call logged, /usage /performance /errors |

---

## ⚠️ Important Notes

- **httpx must be pinned to 0.25.2** — newer versions break python-telegram-bot 20.7
- **All datetime must use IST** — system clock is UTC, never use bare `datetime.now()`
- **`.env` is gitignored** — never commit it; re-create after cloning
- **`admin_id.txt` is gitignored** — run `/claimadmin` after fresh deploy

---

## 📜 License

MIT — build on it freely.