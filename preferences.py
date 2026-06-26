"""
preferences.py — v6.0 Behavioral Adaptive Knowledge module

Analyzes user behavior logs to derive learned preferences:
- Preferred completion hours
- Snooze patterns (avoidance signals)
- Tone preference (gentle vs strict based on completion rate)
- Suggested default times by category
- Active hours for nudge timing

These insights are used by main.py to give smarter suggestions when
creating tasks, and to auto-tune reminder intervals.
"""
from datetime import datetime, timedelta
from database import (
    get_active_hours, get_completion_patterns, get_snooze_patterns,
    get_category_distribution, get_typical_time_for_category,
)


def analyze_user(user_id, days=30) -> dict:
    """
    Returns a snapshot of learned behavior:
    {
        "active_hours_top3": [(hour, count), ...],
        "snooze_patterns": [(category, count, avg_min), ...],
        "category_focus": {category: count},
        "tone": "gentle" | "strict" | "balanced",
        "completion_rate": 0.0..1.0,
        "suggested_intervals": {category: minutes},
        "insights": ["sentence", "sentence", ...]
    }
    """
    active = get_active_hours(user_id, days=days)
    completions = get_completion_patterns(user_id, days=days)
    snoozes = get_snooze_patterns(user_id, days=days)
    categories = get_category_distribution(user_id, days=days)

    # Top 3 most active hours
    active_top3 = sorted(active.items(), key=lambda x: -x[1])[:3]

    # Snooze patterns — categories with most avoidance
    snooze_summary = [(c or "General", n, round(m or 0, 1)) for c, n, m in snoozes][:5]

    # Tone heuristic: high snooze count = gentle, low = strict
    total_snoozes = sum(s[1] for s in snoozes) if snoozes else 0
    total_tasks = sum(categories.values()) if categories else 0
    if total_tasks == 0:
        tone = "balanced"
    else:
        snooze_ratio = total_snoozes / max(total_tasks, 1)
        if snooze_ratio > 0.5:
            tone = "gentle"
        elif snooze_ratio < 0.15:
            tone = "strict"
        else:
            tone = "balanced"

    # Completion rate
    completions_count = sum(c[2] for c in completions) if completions else 0
    completion_rate = round(completions_count / max(total_tasks, 1), 2) if total_tasks else 0.0

    # Suggested reminder intervals per category
    # Heavy snoozers → longer interval (less nagging)
    suggested = {}
    for cat, snz_cnt, avg_min in snooze_summary:
        if snz_cnt >= 5:
            suggested[cat] = max(int(avg_min) + 5, 30)  # respect the avoidance
        elif snz_cnt >= 2:
            suggested[cat] = 30
        else:
            suggested[cat] = 15  # they actually do it — shorter interval is fine

    # Build human-friendly insights
    insights = []
    if active_top3:
        h, n = active_top3[0]
        period = "morning" if 5 <= h < 12 else "afternoon" if 12 <= h < 17 else "evening" if 17 <= h < 21 else "night"
        insights.append(f"You're most active in the {period} (around {h:02d}:00)")
    if categories:
        top_cat = max(categories.items(), key=lambda x: x[1])
        insights.append(f"Most of your tasks are *{top_cat[0]}* ({top_cat[1]} this month)")
    if snooze_summary:
        top_snooze = snooze_summary[0]
        if top_snooze[1] >= 3:
            insights.append(f"You snooze *{top_snooze[0]}* tasks often — consider scheduling them differently")
    if tone == "gentle":
        insights.append("Your style: 🌸 *gentle* — I'll keep reminders relaxed")
    elif tone == "strict":
        insights.append("Your style: 🎯 *focused* — high completion rate, you don't need much nagging")
    if completion_rate > 0.7:
        insights.append(f"✨ Completion rate: {int(completion_rate*100)}% — solid execution!")
    elif completion_rate < 0.3 and total_tasks > 5:
        insights.append("Tasks pile up faster than you complete them — try smaller, focused goals")

    return {
        "active_hours_top3": active_top3,
        "snooze_patterns": snooze_summary,
        "category_focus": categories,
        "tone": tone,
        "completion_rate": completion_rate,
        "total_tasks": total_tasks,
        "total_completions": completions_count,
        "suggested_intervals": suggested,
        "insights": insights,
    }


def suggest_time_for_task(user_id, category, current_default=None) -> str | None:
    """
    Given a new task in <category>, suggest a time the user usually completes
    such tasks at. Returns HH:MM or None if no pattern yet.
    """
    return get_typical_time_for_category(user_id, category, days=60)


def suggest_interval_for_task(user_id, category, base_interval=30) -> int:
    """Auto-tune reminder interval for a specific category."""
    snoozes = get_snooze_patterns(user_id, days=30)
    for cat, count, avg_min in snoozes:
        if cat == category:
            if count >= 5:
                return max(int(avg_min or 0) + 5, 30)
            elif count >= 2:
                return 30
    return base_interval