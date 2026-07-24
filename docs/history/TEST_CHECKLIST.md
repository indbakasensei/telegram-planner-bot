# BAKA Bot — Complete Testing & Debug Checklist (v1.0 → v5.0)

This is your testing bible. Run through each section to validate the entire bot is working. When something fails, use `/report <description>` and the bot will auto-capture context.

## How to Use This Document

1. Send `/debug` ON before starting — you'll see what the bot understood for each message
2. Test ONE section at a time in order
3. If something fails, immediately send `/report <what went wrong>`
4. After each section, send `/bugs` to see if anything was logged
5. Tell me which test numbers failed and paste the `/bugs` output

---

# SECTION A — v1.0 Debug System (8 tests)

| # | Send this | Expected behavior |
|---|-----------|-------------------|
| A1 | `/debug` | "Debug mode is now ON" |
| A2 | `Study Physics today at 8 PM` | Confirmation appears AND a debug box shows `Intent: TASK` + entities |
| A3 | `/trace` | Shows: input, intent, entities (JSON), reply, time |
| A4 | `/report Test bug 1` | "Bug #X saved with full context" |
| A5 | `/bugs` | Lists your test bug with user_input and intent attached |
| A6 | `/resolve 1` (or whatever ID) | "Bug #X marked resolved" |
| A7 | `/selftest` | Shows the test message checklist |
| A8 | `/debug` (again) | "Debug mode is now OFF" |

---

# SECTION B — Basic Task Creation (12 tests)

Re-enable debug for this section: `/debug`

| # | Send this | Expected |
|---|-----------|----------|
| B1 | `Study Physics today at 8 PM` | TASK confirmed, date=today, time=20:00, priority=medium |
| B2 | `Remind me to call mom today` | TASK, date=today, time=null, asks for confirmation |
| B3 | `Tomorrow at 7 AM go for a run` | TASK, date=tomorrow, time=07:00 |
| B4 | `Finish report at 17:00` | time=17:00 (24hr format) |
| B5 | `Submit at 3pm` | time=15:00 (PM converted) |
| B6 | `Submit at 3am` | time=03:00 (AM stays) |
| B7 | `Meeting at noon` | time=12:00 |
| B8 | `Buy groceries` (no time) | TASK, gathers missing info, asks "What date?" |
| B9 | `Read book` then reply `tomorrow at 8pm` | Date+time get applied, saves |
| B10 | Reply `Yes, save it!` to any confirmation | Task saved with green checkmark |
| B11 | Reply `❌ No, cancel` | "Cancelled!" |
| B12 | `Same task today at 8 PM` (duplicate) | "Already saved as [id]. Use /done id" — no duplicate created |

---

# SECTION C — Hindi & Hinglish (12 tests)

| # | Send this | Expected |
|---|-----------|----------|
| C1 | `Kal subah 8 baje gym yaad dila dena` | Tomorrow, 08:00 |
| C2 | `Aaj raat 10 baje assignment submit karna hai` | Today, 22:00 |
| C3 | `Parso doctor appointment hai` | Day after tomorrow |
| C4 | `Bhai kal 9 baje meeting yaad dila dena` | Tomorrow, 09:00 ("Bhai" ignored) |
| C5 | `Shaam ko meeting hai` | Today, 18:00 (evening default) |
| C6 | `Dopahar mein lunch` | Today, 14:00 (afternoon) |
| C7 | `Subah 7 baje yoga` | Tomorrow 07:00 |
| C8 | `Raat 11 baje dawai` | Today, 23:00 |
| C9 | `Har roz exercise karna hai` | Recurring daily habit |
| C10 | `Har Monday gym jana hai` | Recurring weekly (Monday) |
| C11 | `Jaldi karo, urgent task hai` | priority=high, time=now+30min |
| C12 | `Whenever, koi jaldi nahi` | priority=low |

---

# SECTION D — Date & Time Parsing (15 tests)

| # | Send this | Expected |
|---|-----------|----------|
| D1 | `Remind me in 2 hours` | time = current + 2 hours |
| D2 | `Remind me in 30 minutes` | time = current + 30 min |
| D3 | `Remind me in 1 min to test` | time = current + 1 min (NOT 01:00!) |
| D4 | `After 45 minutes call dad` | time = current + 45 min |
| D5 | `Schedule meeting next Monday` | Date = next Monday's date |
| D6 | `Remind me on 25 December at 6 PM` | Date=Dec 25, time=18:00 |
| D7 | `Meeting at 1400` | time = 14:00 (military time) |
| D8 | `Call at 0930 hrs` | time = 09:30 |
| D9 | `Submit on 2026-12-25` | ISO format works |
| D10 | `Remind me yesterday` | ⚠️ warning: past date |
| D11 | `Create task tomorrow at 25 PM` | ⚠️ invalid time, rejected |
| D12 | `Meeting at 13 AM` | ⚠️ invalid time |
| D13 | `Meeting at 25:99` | ⚠️ invalid time format |
| D14 | `3 baje meeting hai` (ambiguous) | Asks "3 AM or 3 PM?" with buttons |
| D15 | Tap "3 PM" button | Updates to 15:00, shows confirmation |

---

# SECTION E — Vague Time (v3.0 — 10 tests)

| # | Send this | Expected |
|---|-----------|----------|
| E1 | `Call mom later` | time = current + 2 hours |
| E2 | `Do it soon` | time = current + 30 min |
| E3 | `Meeting this evening` | time = 18:00 |
| E4 | `Gym tomorrow morning` | tomorrow, time = 08:00 |
| E5 | `Submit report end of day` | today, time = 17:00 |
| E6 | `Call tonight` | today, time = 21:00 |
| E7 | `Lunch meeting` | time = 13:00 |
| E8 | `Finish end of week` | next Friday's date |
| E9 | `URGENT submit assignment` | priority=high, time=now+30min |
| E10 | `Wake me at midnight` | time = 00:00, date inferred correctly |

---

# SECTION F — Recurring Tasks (8 tests)

| # | Send this | Expected |
|---|-----------|----------|
| F1 | `Go to gym every day at 6 AM` | Recurring daily, time=06:00, NO date asked |
| F2 | `Call parents every Sunday` | Recurring weekly (Sunday) |
| F3 | `Pay rent on the 1st of every month` | Recurring monthly (day 1) |
| F4 | `Workout every Monday at 7 AM` | Weekly (Monday), 07:00 |
| F5 | `Stand-up daily at 9 AM` | Daily, 09:00 |
| F6 | `list` | Recurring tasks show with 🔄 icon |
| F7 | Tap ✅ Done on a daily recurring task | Marked done for today |
| F8 | Wait until next day → reminder fires again | Re-fires for new day |

---

# SECTION G — Reminders & Inline Buttons (12 tests — v1.1)

Create a task due 2 minutes from now first.

| # | Action | Expected |
|---|--------|----------|
| G1 | Wait for reminder | Notification with title + 6 buttons |
| G2 | Buttons present | ✅ Done, ⏰ Snooze 10m, 🕐 Snooze 1h, 📅 Tomorrow, 🔕 Stop, 🗑 Delete |
| G3 | Tap **✅ Done** | "Done! Completed: <task>" |
| G4 | Tap **⏰ Snooze 10m** on another | "Snoozed for 10 minutes" |
| G5 | Wait 10 min after G4 | Reminder fires again ✅ |
| G6 | Tap **🕐 Snooze 1h** | "Snoozed for 1 hour" |
| G7 | Tap **📅 Tomorrow** | Task moved to tomorrow |
| G8 | `/snooze 5 45` | "Snoozed for 45 min" — custom snooze |
| G9 | Tap **🔕 Stop Reminders** | Task stays but no more pings |
| G10 | Tap **🗑 Delete Task** | Task removed |
| G11 | `/checktasks` | Diagnostic view of all task states |
| G12 | `/pause 5` then `/paused` then `/resume 5` | Pause cycle works |

---

# SECTION H — Overdue & Deadlines (v1.2 — 8 tests)

Set up: create a task with date = 2 days ago using `/edit <id>`.

| # | Send this | Expected |
|---|-----------|----------|
| H1 | `/overdue` | Shows backdated task with 🔴 indicator |
| H2 | `/list` | Same task shows ⏰ *(OVERDUE)* tag |
| H3 | `/deadlines` | Tasks due in next 3 days with urgency colors |
| H4 | `/carryforward` | "Moved X task(s) to today" |
| H5 | `/list` after H4 | Tasks now dated today |
| H6 | `/tag 5 exam urgent` | Tags set |
| H7 | `/tagged exam` | Lists tasks with that tag |
| H8 | `/tag 5` (no tags) | Shows usage help |

---

# SECTION I — Passive PA (v2.0 — 12 tests)

| # | Action | Expected |
|---|--------|----------|
| I1 | `/settings` | Shows quiet hours, interval, max reminders |
| I2 | `/quiethours 22:00 06:00` | Updated to 22-06 |
| I3 | `/interval 15` | Reminder interval set to 15 min |
| I4 | `/interval 3` | Rejected — min is 5 minutes |
| I5 | Create task 1hr in past | After ~5 min, follow-up reminder fires |
| I6 | Leave overdue 30 more min | Second follow-up arrives |
| I7 | After 5 follow-ups | Stops nagging (max cap) |
| I8 | Create 3+ overdue tasks | Follow-up is BATCHED in one message |
| I9 | `/quiethours 00:00 23:59` | Reminders stop firing |
| I10 | `/quiethours off` | "Disabled" |
| I11 | After midnight | Overdue auto-carries forward |
| I12 | `/checktasks` | Shows last_reminded + reminder_count |

---

# SECTION J — Habits (v5.0 — 15 tests)

| # | Send this | Expected |
|---|-----------|----------|
| J1 | `I want to drink water at 9 AM every day` | HABIT intent detected |
| J2 | Tap Yes | "Habit saved!" with streak note |
| J3 | `/habits` | Lists with streak=0 |
| J4 | `habits` (no slash) | Same as J3 |
| J5 | When reminder fires, tap ✅ Done | "🔥 Streak: 1 day!" |
| J6 | Tap ✅ Done again same day | "(already logged today)" |
| J7 | `/streak 1` | 14-day grid with one 🟩 |
| J8 | `streak 1` (no slash) | Same |
| J9 | `/habitlog 1` | 30-day log |
| J10 | `/addhabit Read 20 pages at 21:00 daily` | Quick creation works |
| J11 | `addhabit Meditate at 7 AM` (no slash) | Same |
| J12 | `/skiphabit 1` | "Streak reset" |
| J13 | After J12, `/streak 1` | streak=0 |
| J14 | `Yoga every Sunday at 8 AM` | Recurrence=weekly, weekday=Sun |
| J15 | `Har roz exercise karna hai` | Hindi habit creates correctly |

---

# SECTION K — Smart Planning (v4.0/v4.1 — 12 tests)

Create 4-5 tasks for today with different times first.

| # | Send this | Expected |
|---|-----------|----------|
| K1 | `/plan today` | Time-blocked schedule + "Apply this plan?" |
| K2 | Tap Yes on K1 | "Plan applied! Updated X tasks" |
| K3 | `plan my day` (no slash) | Same as K1 |
| K4 | `/list` after K2 | Tasks have new times |
| K5 | `/plan week` | 7-day plan with overload warnings |
| K6 | Create vague task: `Prepare for math exam` |  |
| K7 | `/breakdown <id>` | 3-5 subtasks suggested, asks Yes/No |
| K8 | Tap Yes on K7 | Subtasks saved with parent link |
| K9 | `breakdown 5` (no slash) | Same |
| K10 | Create 5+ tasks for same date |  |
| K11 | `/overload` | Date flagged ⚠️ overloaded |
| K12 | `/reschedule <id>` on overloaded day | AI suggests conflict-free time |

---

# SECTION L — Memory System (v1.0+ — 10 tests)

| # | Send this | Expected |
|---|-----------|----------|
| L1 | `Remember my exam is on June 20` | "Remembered!" |
| L2 | `When is my exam?` | Retrieves "exam: June 20" |
| L3 | `/memory` | Shows all memories |
| L4 | `Remember my favorite color is blue` | New memory saved |
| L5 | `Remember my favorite color is red` | UPDATES (no duplicate) |
| L6 | `/memory` after L5 | Color shows "red" only |
| L7 | `/forget exam` | "Forgot: exam" |
| L8 | `forget exam` (no slash) | Same (idempotent) |
| L9 | `Delete memory color` | Removes color memory |
| L10 | `/forget nonexistent` | "No memory found..." |

---

# SECTION M — Slashless Commands (v4.1 — 15 tests)

| # | Send this | Expected |
|---|-----------|----------|
| M1 | `list` | All tasks |
| M2 | `today` | Today's tasks |
| M3 | `week` | This week |
| M4 | `done 5` | Marks task 5 complete |
| M5 | `delete 5` | Asks to delete task 5 |
| M6 | `edit 5` | Enters edit mode |
| M7 | `overdue` | Overdue list |
| M8 | `deadlines` | Upcoming deadlines |
| M9 | `settings` | Settings panel |
| M10 | `status` | API health |
| M11 | `analyze` | Productivity report |
| M12 | `breakdown 5` | Breaks down task 5 |
| M13 | `snooze 5 30` | Snoozes task 5 for 30 min |
| M14 | `tag 5 urgent` | Tags task 5 |
| M15 | `help` | Full help menu |

---

# SECTION N — Multiple Tasks in One Message (5 tests)

| # | Send this | Expected |
|---|-----------|----------|
| N1 | `Tomorrow buy groceries and call mom` | 2 tasks detected |
| N2 | Tap Yes on N1 | Both saved |
| N3 | `Tomorrow go to gym at 7 and study at 8` | 2 tasks, different times |
| N4 | `Finish Physics by Friday and Chemistry by Saturday` | 2 tasks, different dates |
| N5 | After saving, `/list` | Both appear separately |

---

# SECTION O — Edit & Delete (8 tests)

| # | Send this | Expected |
|---|-----------|----------|
| O1 | `/edit 1` | Edit mode, shows current values |
| O2 | After O1, type `Set time to 6pm` | Updates time to 18:00 |
| O3 | `Move my gym task to tomorrow` | Finds gym by name, updates date |
| O4 | `Delete my homework task` | Asks confirmation, deletes |
| O5 | `/delete 99` (nonexistent) | "Task [99] not found" — no crash |
| O6 | `delete save` (memory key) | No crash from int() |
| O7 | `/done 99` (nonexistent) | "Task [99] not found" |
| O8 | `/edit 99` (nonexistent) | "Task [99] not found" |

---

# SECTION P — Edge Cases & Error Handling (15 tests)

| # | Send this | Expected |
|---|-----------|----------|
| P1 | `Remind me to call mom` (no date) | Asks for date/time |
| P2 | `Tomorrow.` (no task) | Asks "What should I remind you about?" |
| P3 | `Set reminder` (alone) | Asks for details |
| P4 | `Remind me in` (incomplete) | Asks about what |
| P5 | Empty/whitespace message | No crash, gentle handling |
| P6 | Very long message (500+ chars) | No crash |
| P7 | `😀😀😀` (emoji-only) | No crash |
| P8 | Long Hindi sentence | Parsed correctly |
| P9 | `Bhai kal evening urgent meeting` | high priority, tomorrow, 18:00 |
| P10 | `What time is it?` | Current IST time |
| P11 | `What's today's date?` | Today's date |
| P12 | `Show plan for today` | VIEW intent (today), NOT task creation |
| P13 | `I'm tired today` | CHAT — no task created |
| P14 | `How are you?` | Conversational reply |
| P15 | `/cancel` mid-action | "Cancelled!" — clears state |

---

# SECTION Q — Stress Tests (10 tests)

| # | Sequence | Expected |
|---|----------|----------|
| Q1 | Create task → cancel → create same | Saves cleanly 2nd time |
| Q2 | `/edit 5` → send other msg → `/edit 5` again | State recovers |
| Q3 | Task in 1min → reminder → snooze → wait → complete | Full lifecycle works |
| Q4 | Create 20 tasks rapidly | All saved, no race conditions |
| Q5 | `/status` 5x in row | No rate limit |
| Q6 | Ignore reminder 1 hour | Follow-up per interval, batched |
| Q7 | Quiet hours covering now + overdue task | No reminders during quiet |
| Q8 | After quiet hours end | Catch-up reminders fire |
| Q9 | Snooze 10m TWICE on same reminder | Second snooze extends |
| Q10 | Daily recurring done → wait til tomorrow | Re-fires for new day |

---

# SECTION R — Regression Tests (12 tests — old bugs)

These specifically catch bugs we already fixed:

| # | Send this | Expected (regression check) |
|---|-----------|----------------------------|
| R1 | `Remind me to call mom today` | Date = TODAY in IST (not yesterday from UTC) |
| R2 | `Wake me at morning` at 00:30 | Today's 08:00, not previous day |
| R3 | `Meeting at 1400` | 14:00, NOT confused with year |
| R4 | `Meeting 25 December 2026` | Dec 25, time=null (NOT 20:26) |
| R5 | `Remind me in 1 min` | now+1, NOT 01:00 |
| R6 | `forget exam` after saving "exam" | Actually deleted |
| R7 | `forget EXAM` (uppercase) | Case-insensitive delete works |
| R8 | `delete save` (memory key not task) | No int() crash |
| R9 | Tap Snooze 10m → wait 11 min | Reminder fires again |
| R10 | `/snooze 5 45` after prior reminder | Re-fires after 45 min |
| R11 | `Remember my study time is 7 PM` | Multi-word key saves |
| R12 | Restart bot, then `/memory` | Memory persists |

---

# How to Report Bugs

When ANY test fails:

```
/report <test_id>: <what went wrong>
```

Examples:
```
/report D3: bot saved 01:00 instead of now+1min
/report J5: streak shows 0 after marking done
```

Then send:
```
/bugs
```

Paste the output here and I'll diagnose.

---

# Quick Validation (Speed-Run — 20 essential tests)

If short on time, run JUST these:

1. **B1**: `Study Physics today at 8 PM` → confirm + save
2. **C1**: `Kal subah 8 baje gym` → tomorrow 08:00
3. **D1**: `Remind me in 2 hours` → now+2hrs
4. **D3**: `Remind me in 1 min` → now+1 (NOT 01:00)
5. **D14**: `3 baje meeting hai` → asks AM/PM
6. **E3**: `Meeting this evening` → 18:00
7. **F1**: `Gym every day at 6 AM` → recurring, no date asked
8. **G1-G3**: Live reminder → tap ✅ Done
9. **G5**: Snooze 10m → fires after 10 min
10. **H1**: `/overdue` → shows overdue
11. **I1**: `/settings` → shows preferences
12. **J1-J2**: `I want to drink water at 9 AM every day` → habit saved
13. **J5**: Mark habit done → streak=1
14. **K1-K2**: `/plan today` → applies plan
15. **K7-K8**: `/breakdown 5` → subtasks saved
16. **L1-L2**: Remember + retrieve memory
17. **L7**: `/forget exam` → deleted
18. **M1**: `list` (no slash) → works
19. **N1**: `Tomorrow buy groceries and call mom` → 2 tasks
20. **P10**: `What time is it?` → correct IST time

If all 20 pass, the bot is in good shape across all versions.

---

# Total Test Count

- A (Debug): 8
- B (Basic Tasks): 12
- C (Hindi/Hinglish): 12
- D (Date/Time): 15
- E (Vague Time): 10
- F (Recurring): 8
- G (Reminders): 12
- H (Overdue/Deadlines): 8
- I (Passive PA): 12
- J (Habits): 15
- K (Planning): 12
- L (Memory): 10
- M (Slashless): 15
- N (Multiple Tasks): 5
- O (Edit/Delete): 8
- P (Edge Cases): 15
- Q (Stress): 10
- R (Regression): 12

**Grand total: 197 tests** covering every feature from v1.0 to v5.0.