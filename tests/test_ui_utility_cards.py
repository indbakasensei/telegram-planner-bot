"""
Characterization tests for the Phase 5R utility-screen builders
(UI_SPEC_v1.md §15) — the presentation extracted verbatim from main.py
handlers in v14.18. These pins are the offline "after" picture of a
byte-for-byte move: the builders were relocated without reformatting,
and every field, variant branch, callback, and permission-dependent
section is asserted here so the (finally possible) Phase 5 redesign has
its mandated before-picture.

The handlers themselves (thin wrappers now) still need the TESTING.md
live smoke checklist — main.py remains unimportable offline.
"""
import pytest

import ui


# ── settings_card ────────────────────────────────────────────────────────

PREFS = {"quiet_start": "22:00", "quiet_end": "07:00",
         "interval": 30, "max_reminders": 5}


def test_settings_card_fields_and_quiet_variants():
    text = ui.settings_card(PREFS, is_quiet=False)
    assert "⚙️ *Your Settings*" in text
    assert "🌙 Quiet hours: *22:00 — 07:00* (inactive 🔔)" in text
    assert "🔁 Reminder interval: *30 min*" in text
    assert "📊 Max reminders per task: *5*" in text
    assert "/quiethours <start> <end>" in text
    assert "(active now 🔕)" in ui.settings_card(PREFS, is_quiet=True)


# ── debug_toggle_card ────────────────────────────────────────────────────

def test_debug_toggle_card_both_states():
    on = ui.debug_toggle_card(True)
    assert "🐞 Debug mode is now *ON*." in on
    assert "detected intent and entities" in on
    off = ui.debug_toggle_card(False)
    assert "*OFF*" in off and "Back to normal responses." in off


# ── bugs_card ────────────────────────────────────────────────────────────

def test_bugs_card_empty_and_populated():
    assert ui.bugs_card([]) == "🎉 No open bugs!"
    bugs = [(3, "auto_exception", "IndexError in parser", "kal subah gym"),
            (4, "user_report", "saved wrong time", None)]
    text = ui.bugs_card(bugs)
    assert "🐞 *Open Bugs:*" in text
    assert "💥 *#3* — IndexError in parser" in text     # auto icon
    assert "_on: kal subah gym_" in text
    assert "📝 *#4* — saved wrong time" in text          # report icon
    assert "Use /resolve <id> to close one." in text


# ── trace_card ───────────────────────────────────────────────────────────

def test_trace_card_none_and_populated():
    assert ui.trace_card(None) == "No interaction traced yet. Send a message first."
    trace = {"user_input": "kal gym", "intent": "ADD_TASK",
             "entities": {"time": "08:00"}, "response": "Saved!",
             "time": "2026-07-17 10:00"}
    text = ui.trace_card(trace)
    assert "🔍 *Last Interaction Trace:*" in text
    assert "📥 You said: `kal gym`" in text
    assert "🎯 Intent: `ADD_TASK`" in text
    assert '"time": "08:00"' in text
    assert "📤 Reply: Saved!" in text


# ── insights_card ────────────────────────────────────────────────────────

def test_insights_card_not_enough_data_variant():
    text = ui.insights_card({"total_tasks": 2})
    assert "*Not enough data yet*" in text
    assert "at least 3 tasks" in text


def test_insights_card_full_render():
    data = {
        "total_tasks": 12,
        "insights": ["You finish most tasks before noon"],
        "active_hours_top3": [(9, 14), (21, 8)],
        "snooze_patterns": [("College", 4, 22.5)],
        "category_focus": {"College": 7, "Health": 3},
    }
    text = ui.insights_card(data)
    assert "*What I've learned about you*" in text
    assert "_(based on last 30 days, 12 tasks)_" in text
    assert "• You finish most tasks before noon" in text
    assert "09:00 (14 interactions)" in text
    assert "College: 4x (avg 22m)" in text
    assert "College: 7 tasks" in text
    assert "tweak `/settings`" in text


# ── admin_panel_card ─────────────────────────────────────────────────────

def test_admin_panel_card_stats_and_mode():
    stats = {"active_tasks": 9, "done_tasks": 40, "habits": 3,
             "memories": 5, "goals": 2, "max_task_id": 61,
             "completions_logged": 38, "snoozes_logged": 12}
    text = ui.admin_panel_card(stats, in_mode=True)
    assert "*ADMIN CONTROL PANEL*" in text
    assert "Debug mode: 🟢 ON" in text
    assert "Active tasks: 9" in text and "Completed: 40" in text
    assert "Highest task ID: 61" in text
    assert "Learning logs: 38 done, 12 snoozed" in text
    assert "/resetall — ⚠️ nuke EVERYTHING + reset IDs" in text
    assert "Debug mode: ⚪ OFF" in ui.admin_panel_card(stats, in_mode=False)


# ── proactive_card ───────────────────────────────────────────────────────

def test_proactive_card_fields_and_wellness_toggle():
    text = ui.proactive_card({"on": True}, PREFS)
    assert "<b>Proactive Features</b>" in text
    assert "<b>Reminders</b> — always on" in text
    assert "<b>End-of-day summary</b> — 21:00 daily" in text
    assert "<b>Wellness nudges</b> — 🟢 ON" in text
    assert "<b>Quiet hours</b> — 22:00–07:00" in text
    assert "⚪ OFF" in ui.proactive_card({"on": False}, PREFS)


# ── help_cards ───────────────────────────────────────────────────────────

def test_help_cards_structure_and_version():
    msg1, msg2 = ui.help_cards("14.18", user_is_admin=False)
    assert "<b>BAKA</b> — Behavioral Adaptive Knowledge Assistant" in msg1
    assert "v14.18 · offline-first" in msg1
    assert "<b>slash is optional</b>" in msg1
    for sec in ("TASKS", "REMINDERS", "HABITS"):
        assert f"<b>{sec}</b>" in msg1
    for sec in ("GOALS &amp; PROJECTS", "AI &amp; PLANNING", "MEDIA",
                "MEMORY, SEARCH &amp; TEMPLATES", "SETTINGS &amp; UTILITIES"):
        assert f"<b>{sec}</b>" in msg2
    assert "<blockquote expandable>" in msg1 and "<blockquote expandable>" in msg2
    # Known-broken analytics commands are not advertised.
    assert "usage" not in msg2.replace("UTILITIES", "")
    assert "performance" not in msg2


def test_help_cards_admin_visibility():
    _, without = ui.help_cards("14.18", user_is_admin=False)
    assert "ADMIN" not in without
    _, with_admin = ui.help_cards("14.18", user_is_admin=True)
    assert "<b>ADMIN (visible only to you)</b>" in with_admin
    assert "resettasks" in with_admin and "sql &lt;query&gt;" in with_admin


# ── ai_status cards ──────────────────────────────────────────────────────

@pytest.mark.parametrize("status,marker", [
    ("rate_limited", "Rate Limited"),
    ("invalid_key", "Invalid API Key"),
    ("error", "<b>Error</b>"),
])
def test_ai_status_error_card_variants(status, marker):
    text = ui.ai_status_error_card({"status": status, "error": "boom"})
    assert marker in text


BENCH = {"score": "3/3", "grade": "A", "avg_latency_ms": 850,
         "tests": [{"name": "Echo", "passed": True, "latency_ms": 600},
                    {"name": "Math", "passed": False, "latency_ms": 1200,
                     "error": "timeout <T>"}]}


def test_ai_status_card_fields_and_rerun_callback():
    result = {"status": "online", "response_time_ms": 700, "model": "m/x",
              "prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    text, kb = ui.ai_status_card(result, BENCH, full=False)
    assert "<b>BAKA AI Diagnostics</b>" in text
    assert "Ping: 700ms ⚡ Fast" in text
    assert "Tokens: 10→20 (30 total)" in text
    assert "🏆 <b>Benchmark: 3/3</b> (Grade: <b>A</b>)" in text
    assert "✅ Echo (600ms)" in text and "❌ Math (1200ms)" in text
    assert "Error: timeout &lt;T&gt;" in text                  # escaped
    assert "Run <code>status full</code>" in text              # quick-mode hint
    assert kb.inline_keyboard[0][0].text == "🔄 Re-run"
    assert kb.inline_keyboard[0][0].callback_data == "dash:home"
    full_text, _ = ui.ai_status_card(result, BENCH, full=True)
    assert "status full" not in full_text


# ── models_card ──────────────────────────────────────────────────────────

def test_models_card_online_offline_and_usage():
    health = {
        "main": {"model": "m/main", "online": True, "ms": 500},
        "fast": {"model": "m/fast", "online": False},
        "vision": {"model": "m/vis", "online": "skipped"},
    }
    stats = {"m/main": {"total_requests": 40, "today_requests": 5,
                         "health": "healthy", "avg_latency_ms": 900,
                         "success_rate": 98}}
    text = ui.models_card(health, stats)
    assert "<b>Multi-Model AI Status</b>" in text
    assert "<b>Main Brain</b> — 🟢 500ms" in text
    assert "Today: <b>5</b> · Total: <b>40</b> · 🟢 healthy" in text
    assert "<b>Fast Tasks</b> — 🔴 offline" in text
    assert "<b>Image Understanding</b> — ⚪ skipped" in text
    assert "All visual models always on · 100% NVIDIA NIM" in text


def test_models_card_without_analytics_stats():
    # The pre-existing production state: analytics import fails, stats={}.
    health = {"main": {"model": "m/main", "online": True, "ms": 100}}
    text = ui.models_card(health, {})
    assert "Today:" not in text


# ── selftest_report ──────────────────────────────────────────────────────

CHECKS_OK = [(True, "Database read", "3 open tasks · 1ms"),
             (True, "Scheduler", "0 due now · 0ms")]


def test_selftest_report_all_ok():
    text = ui.selftest_report(
        "14.18", "3.12.3", "nvidia-nim", "m/main", "m/fast", "m/think",
        "planner.db", "120 KB", 85.0,
        [("OFFLINE_TASKS", False), ("OFFLINE_HABITS", True)],
        CHECKS_OK, 42.0)
    assert "<b>BAKA Diagnostics</b>" in text
    assert "<b>✅ ALL SYSTEMS OPERATIONAL</b>" in text
    assert "✅ <b>Database read</b> — 3 open tasks · 1ms" in text
    assert "BAKA <b>v14.18</b> · Python <code>3.12.3</code>" in text
    assert "AI provider: <code>nvidia-nim</code>" in text
    assert "reasoning <code>m/think</code>" in text
    assert "Database: <code>planner.db</code> · 120 KB" in text
    assert "Memory (peak RSS): <code>85 MB</code>" in text
    assert "⚪ <code>OFFLINE_TASKS</code> off" in text
    assert "🟢 <code>OFFLINE_HABITS</code> ON" in text
    assert "2 live checks · report generated in 42ms" in text


def test_selftest_report_failure_verdict():
    checks = CHECKS_OK + [(False, "Routing Layer", "RuntimeError: boom")]
    text = ui.selftest_report(
        "14.18", "3.12.3", "p", "a", "b", "c", "db", "1 KB", 10.0,
        [], checks, 5.0)
    assert "<b>⚠️ 1 CHECK(S) FAILED</b>" in text
    assert "❌ <b>Routing Layer</b> — RuntimeError: boom" in text
