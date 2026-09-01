import os
"""
performance_tracker.py — v15.7
Latency percentiles + trend math for the /performance dashboard.
"""
import sqlite3
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
DB_NAME = os.getenv("DB_NAME", "planner.db")


def latency_percentiles(user_id: int, days: int = 7) -> dict:
    """Returns p50/p95/p99 latency over the last N days."""
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""SELECT latency_ms FROM ai_usage
                 WHERE user_id=? AND timestamp >= ? AND latency_ms > 0
                 ORDER BY latency_ms""", (user_id, cutoff))
    values = [r[0] for r in c.fetchall()]
    conn.close()
    if not values:
        return {"p50": 0, "p95": 0, "p99": 0, "n": 0}
    def pct(p):
        idx = int(len(values) * p / 100)
        return values[min(idx, len(values) - 1)]
    return {
        "p50": pct(50),
        "p95": pct(95),
        "p99": pct(99),
        "n": len(values),
    }


def get_trends(user_id: int) -> dict:
    """Daily/weekly/monthly request counts for the trend display."""
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    today = datetime.now(IST).strftime("%Y-%m-%d")
    week_ago = (datetime.now(IST) - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now(IST) - timedelta(days=30)).strftime("%Y-%m-%d")
    yest = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d")

    def count(where_clause, params):
        c.execute(f"SELECT COUNT(*) FROM ai_usage WHERE user_id=? {where_clause}",
                  [user_id] + params)
        return c.fetchone()[0] or 0

    daily = count("AND substr(timestamp,1,10)=?", [today])
    yesterday = count("AND substr(timestamp,1,10)=?", [yest])
    weekly = count("AND substr(timestamp,1,10) >= ?", [week_ago])
    monthly = count("AND substr(timestamp,1,10) >= ?", [month_ago])
    conn.close()

    # Trend direction
    if yesterday == 0:
        trend_label = "↑ new activity" if daily > 0 else "—"
    elif daily > yesterday * 1.1:
        trend_label = f"↑ +{daily - yesterday}"
    elif daily < yesterday * 0.9:
        trend_label = f"↓ -{yesterday - daily}"
    else:
        trend_label = "→ steady"

    return {
        "daily": daily,
        "yesterday": yesterday,
        "weekly": weekly,
        "monthly": monthly,
        "daily_trend": trend_label,
    }