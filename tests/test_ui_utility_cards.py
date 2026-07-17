"""
Characterization tests for the utility-screen builders — extracted
verbatim in Phase 5R (v14.18, the before-picture) and redesigned onto
the component library in Phase 5 (v14.19, pinned here). Every field,
variant branch, permission-dependent section, and the one keyboard's
callback identity survive the redesign; the layout pins below are the
after-picture. help_cards() kept its v14.12 design (already
spec-styled); selftest_report() is unchanged from 5R.
"""
import pytest

import ui


# ── settings_card ────────────────────────────────────────────────────────

PREFS = {"quiet_start": "22:00", "quiet_end": "07:00",
         "interval": 30, "max_reminders": 5}


def test_settings_card_fields_and_quiet_variants():
    text = ui.settings_card(PREFS, is_quiet=False)
    first = text.splitlines()[0]
    assert first.startswith("⚙️") and "settings" in first.lower()
    assert "🌙 Quiet hours: 22:00 — 07:00" in text
    assert "🔁 Reminder interval: 30 min" in text
    assert "📊 Max reminders per task: 5" in text
    assert "quiethours &lt;start&gt; &lt;end&gt;" in text     # footer hint, escaped
    quiet = ui.settings_card(PREFS, is_quiet=True)
    assert "Quiet hours active now 🔕" in quiet
    assert "(active now)" in quiet


# ── debug_toggle_card ────────────────────────────────────────────────────

def test_debug_toggle_card_both_states():
    on = ui.debug_toggle_card(True)
    assert on.startswith("✅ <b>Debug mode ON</b>")
    assert "detected intent and entities" in on
    off = ui.debug_toggle_card(False)
    assert off.startswith("ℹ️ <b>Debug mode OFF</b>")
    assert "Back to normal responses." in off


# ── bugs_card ────────────────────────────────────────────────────────────

def test_bugs_card_empty_and_populated():
    empty = ui.bugs_card([])
    assert "🛠" in empty and "open bugs" in empty.splitlines()[0].lower()
    assert "ℹ️ <b>No entries.</b>" in empty                    # §14 dev empty
    assert "nothing reported since last review" in empty
    bugs = [(3, "auto_exception", "IndexError in parser", "kal subah gym"),
            (4, "user_report", "saved wrong time", None)]
    text = ui.bugs_card(bugs)
    assert "<i>2 open</i>" in text
    # v14.21: DBG-prefixed independent bug ids.
    assert "💥 <b>DBG-0003</b> — IndexError in parser" in text  # auto icon
    assert "<i>on: kal subah gym</i>" in text
    assert "📝 <b>DBG-0004</b> — saved wrong time" in text       # report icon
    assert "Use resolve &lt;id&gt; to close one." in text


# ── trace_card ───────────────────────────────────────────────────────────

def test_trace_card_none_and_populated():
    none = ui.trace_card(None)
    assert "🔍" in none and "trace" in none.splitlines()[0].lower()
    assert "ℹ️ <b>No entries.</b>" in none
    assert "send a message first" in none
    trace = {"user_input": "kal gym", "intent": "ADD_TASK",
             "entities": {"time": "08:00"}, "response": "Saved!",
             "time": "2026-07-17 10:00"}
    text = ui.trace_card(trace)
    assert "📥 You said: kal gym" in text
    assert "🎯 Intent: ADD_TASK" in text
    assert "📤 Reply: Saved!" in text
    assert '<pre><code class="language-json">' in text          # dev code block
    assert '"time": "08:00"' in text


# ── insights_card ────────────────────────────────────────────────────────

def test_insights_card_not_enough_data_uses_canonical_empty():
    text = ui.insights_card({"total_tasks": 2})
    assert "📊" in text
    assert "Not enough data yet — complete a few tasks and check back." in text


def test_insights_card_full_render():
    data = {
        "total_tasks": 12,
        "insights": ["You finish most tasks before noon"],
        "active_hours_top3": [(9, 14), (21, 8)],
        "snooze_patterns": [("College", 4, 22.5)],
        "category_focus": {"College": 7, "Health": 3},
    }
    text = ui.insights_card(data)
    first = text.splitlines()[0]
    assert first.startswith("📊") and "insights" in first.lower()
    assert "<i>based on last 30 days · 12 tasks</i>" in text
    assert "• You finish most tasks before noon" in text
    assert "<b>Active hours</b>" in text and "09:00 (14 interactions)" in text
    assert "<b>Snooze patterns</b>" in text and "College: 4x (avg 22m)" in text
    assert "<b>Top categories</b>" in text and "College: 7 tasks" in text
    assert "tweak settings for better defaults" in text


# ── admin_panel_card ─────────────────────────────────────────────────────

def test_admin_panel_card_stats_and_mode():
    stats = {"active_tasks": 9, "done_tasks": 40, "habits": 3,
             "memories": 5, "goals": 2, "max_task_id": 61,
             "completions_logged": 38, "snoozes_logged": 12}
    text = ui.admin_panel_card(stats, in_mode=True)
    first = text.splitlines()[0]
    assert first.startswith("🛠") and "admin control panel" in first.lower()
    assert "<i>Debug mode 🟢 ON</i>" in text
    assert "Active tasks: <b>9</b>" in text and "Completed: <b>40</b>" in text
    assert "Highest task ID: <b>61</b>" in text
    assert "Learning logs: <b>38 done, 12 snoozed</b>" in text
    assert "<code>resetall</code> — ⚠️ nuke EVERYTHING + reset IDs" in text
    assert "<code>sql &lt;query&gt;</code>" in text
    assert "<i>Debug mode ⚪ OFF</i>" in ui.admin_panel_card(stats, in_mode=False)


# ── proactive_card ───────────────────────────────────────────────────────

def test_proactive_card_fields_and_wellness_toggle():
    text = ui.proactive_card({"on": True}, PREFS)
    first = text.splitlines()[0]
    assert first.startswith("⚙️") and "proactive features" in first.lower()
    assert "<b>Reminders</b> — always on" in text
    assert "<b>End-of-day summary</b> — 21:00 daily" in text
    assert "<b>Wellness nudges</b> — 🟢 ON" in text
    assert "<b>Quiet hours</b> — 22:00–07:00" in text
    assert "heads-up automatically" in text                     # footer
    assert "⚪ OFF" in ui.proactive_card({"on": False}, PREFS)


# ── help_cards (kept from v14.12 — pins unchanged) ───────────────────────

def test_help_cards_structure_and_version():
    msg1, msg2 = ui.help_cards("14.19", user_is_admin=False)
    assert "<b>BAKA</b> — Behavioral Adaptive Knowledge Assistant" in msg1
    assert "v14.19 · offline-first" in msg1
    assert "<b>slash is optional</b>" in msg1
    for sec in ("TASKS", "REMINDERS", "HABITS"):
        assert f"<b>{sec}</b>" in msg1
    for sec in ("GOALS &amp; PROJECTS", "AI &amp; PLANNING", "MEDIA",
                "MEMORY, SEARCH &amp; TEMPLATES", "SETTINGS &amp; UTILITIES"):
        assert f"<b>{sec}</b>" in msg2
    assert "<blockquote expandable>" in msg1 and "<blockquote expandable>" in msg2
    assert "performance" not in msg2                # broken analytics unadvertised


def test_help_cards_admin_visibility():
    _, without = ui.help_cards("14.19", user_is_admin=False)
    assert "ADMIN" not in without
    _, with_admin = ui.help_cards("14.19", user_is_admin=True)
    assert "<b>ADMIN (visible only to you)</b>" in with_admin
    assert "resettasks" in with_admin and "sql &lt;query&gt;" in with_admin


# ── ai_status cards ──────────────────────────────────────────────────────

@pytest.mark.parametrize("status,marker", [
    ("rate_limited", "⚠️ <b>Rate limited</b>"),
    ("invalid_key", "❌ <b>Invalid API key</b>"),
    ("error", "❌ <b>AI error</b>"),
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
    first = text.splitlines()[0]
    assert first.startswith("🧠") and "ai diagnostics" in first.lower()
    assert "Model: m/x" in text
    assert "Ping: 700ms ⚡ Fast" in text
    assert "Tokens: 10→20 (30 total)" in text
    assert "<b>Benchmark 3/3</b>" in text and "Grade: <b>A</b>" in text
    assert "⚠️ 1/2 tests passed" in text                        # worst-wins status
    assert "✅ Echo (600ms)" in text and "❌ Math (1200ms)" in text
    assert "Error: timeout &lt;T&gt;" in text                   # escaped caption
    assert "status full" in text                                # quick-mode hint
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
    first = text.splitlines()[0]
    assert first.startswith("🧠") and "multi-model ai status" in first.lower()
    assert "<i>3 models probed</i>" in text
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


# ── selftest_report (unchanged from 5R) ──────────────────────────────────

CHECKS_OK = [(True, "Database read", "3 open tasks · 1ms"),
             (True, "Scheduler", "0 due now · 0ms")]


def test_selftest_report_all_ok():
    text = ui.selftest_report(
        "14.19", "3.12.3", "nvidia-nim", "m/main", "m/fast", "m/think",
        "planner.db", "120 KB", 85.0,
        [("OFFLINE_TASKS", False), ("OFFLINE_HABITS", True)],
        CHECKS_OK, 42.0)
    assert "<b>BAKA Diagnostics</b>" in text
    assert "<b>✅ ALL SYSTEMS OPERATIONAL</b>" in text
    assert "✅ <b>Database read</b> — 3 open tasks · 1ms" in text
    assert "BAKA <b>v14.19</b> · Python <code>3.12.3</code>" in text
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
        "14.19", "3.12.3", "p", "a", "b", "c", "db", "1 KB", 10.0,
        [], checks, 5.0)
    assert "<b>⚠️ 1 CHECK(S) FAILED</b>" in text
    assert "❌ <b>Routing Layer</b> — RuntimeError: boom" in text
