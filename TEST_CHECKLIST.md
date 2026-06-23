# JARVIS Bot — Test Checklist

## How to Use This
1. Open your bot in Telegram
2. Send `/debug` first (so you see what the bot understood after each message)
3. Send each test message below one at a time
4. Compare what happened to the "Expected" column
5. If something is wrong, send `/report <what went wrong>` immediately —
   the bot auto-saves your last message and what it understood
6. After testing, send `/bugs` to see everything that failed
7. Copy that list and send it to your AI helper to fix

When testing is done, send `/debug` again to turn debug mode off.

---

## v1.0 — Debug System Tests

| # | Send this | Expected result |
|---|-----------|-----------------|
| 1 | `/debug` | "Debug mode is now ON" |
| 2 | `/selftest` | Shows the full checklist of test messages |
| 3 | `Study Physics today at 8 PM` | Confirmation with date=today, time=20:00, + debug box showing intent=TASK |
| 4 | `/trace` | Shows last interaction: input, intent, entities, reply |
| 5 | `/report the time looks wrong` | "Bug #X saved with full context" |
| 6 | `/bugs` | Lists bug #X with your message attached |
| 7 | `/resolve 1` | "Bug #1 marked resolved" |
| 8 | `/debug` | "Debug mode is now OFF" |

---

## Core Feature Tests (run with /debug ON)

### Task Creation
| Send this | Expected |
|-----------|----------|
| `Study Physics today at 8 PM` | TASK, date=today, time=20:00, asks confirm |
| `Remind me to call mom today` | TASK, date=today, no time, asks confirm |
| `Finish assignment by Friday` | TASK, date=next Friday |

### Hindi / Hinglish
| Send this | Expected |
|-----------|----------|
| `Kal subah 8 baje gym yaad dila dena` | TASK, title=Gym, date=tomorrow, time=08:00 |
| `Aaj raat 10 baje assignment submit karna hai` | TASK, date=today, time=22:00 |
| `Parso doctor appointment hai` | TASK, date=day after tomorrow |
| `Bhai kal 9 baje meeting yaad dila dena` | TASK, title=Meeting, date=tomorrow, time=09:00 |

### Date / Time Parsing
| Send this | Expected |
|-----------|----------|
| `Remind me in 2 hours` | time = current + 2 hours |
| `Remind me after 30 minutes` | time = current + 30 min |
| `Schedule meeting next Monday` | correct next Monday date |
| `Remind me on 25 December at 6 PM` | date=Dec 25, time=18:00 |

### Ambiguity & Validation
| Send this | Expected |
|-----------|----------|
| `3 baje meeting hai` | Asks "3 AM or 3 PM?" with buttons |
| `Create task tomorrow at 25 PM` | Rejects — invalid time error |
| `Remind me yesterday` | Warns — past date |

### Recurring
| Send this | Expected |
|-----------|----------|
| `Go to gym every day at 6 AM` | Recurring daily, time=06:00 |
| `Call parents every Sunday` | Recurring weekly (Sunday) |
| `Pay rent on the 1st of every month` | Recurring monthly (day 1) |

### Multiple Tasks
| Send this | Expected |
|-----------|----------|
| `Tomorrow buy groceries and call mom` | MULTIPLE — 2 tasks shown, save both |

### Views
| Send this | Expected |
|-----------|----------|
| `What do I have today?` | Today's task list |
| `Show my tasks tomorrow` | Tomorrow's list |
| `What's this week?` | Week list |
| `Show this month` | Month list (30 days) |

### Memory
| Send this | Expected |
|-----------|----------|
| `Remember my exam is on June 20` | "Remembered!" |
| `When is my exam?` | Retrieves the stored memory |
| `/memory` | Shows all stored memories |

### Edit / Delete / Complete
| Send this | Expected |
|-----------|----------|
| `Move my gym task to tomorrow` | Updates the gym task date |
| `Delete my homework task` | Asks to confirm, then deletes |
| `/done 1` | Marks task 1 complete |

### Chat / Advice
| Send this | Expected |
|-----------|----------|
| `How do I focus better while studying?` | Conversational AI reply, no task created |
| `Hey JARVIS` | Friendly greeting, no task created |

---

## What To Do When You Find a Bug

Right after the bot does something wrong, send:
```
/report <describe what went wrong>
```
Example:
```
/report I said "3 baje" and it saved 03:00 without asking AM or PM
```

The bot automatically attaches:
- The exact message you sent before
- What intent it detected
- What entities (title/date/time) it extracted

Then when you talk to your AI helper, just send `/bugs`, copy the list,
and paste it. The AI will have everything needed to fix it.