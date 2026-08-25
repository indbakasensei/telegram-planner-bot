"""
usage_service.py — v15.7
Query functions for the analytics dashboards. Pure read operations.
"""
import sqlite3
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
DB_NAME = "planner.db"


def _connect():
    return sqlite3.connect(DB_NAME)


def get_today_overview(user_id: int) -> dict:
    """Counts + averages for today only."""
    conn = _connect(); c = conn.cursor()
    today = datetime.now(IST).strftime("%Y-%m-%d")
    c.execute("""SELECT COUNT(*),
                        AVG(latency_ms),
                        SUM(total_tokens),
                        SUM(estimated_cost),
                        SUM(CASE WHEN status='success' THEN 1 ELSE 0 END),
                        SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)
                 FROM ai_usage
                 WHERE user_id=? AND substr(timestamp,1,10)=?""",
              (user_id, today))
    row = c.fetchone()
    conn.close()
    total, avg_lat, tokens, cost, success, errors = row
    total = total or 0
    return {
        "requests_today": total,
        "avg_latency_ms": round(avg_lat or 0),
        "tokens_today": tokens or 0,
        "cost_today": round(cost or 0, 4),
        "successes": success or 0,
        "errors": errors or 0,
        "success_rate": round((success or 0) / total * 100, 1) if total else 100.0,
    }


def get_lifetime_overview(user_id: int) -> dict:
    """All-time totals for a user."""
    conn = _connect(); c = conn.cursor()
    c.execute("""SELECT COUNT(*), SUM(total_tokens), SUM(estimated_cost),
                        AVG(latency_ms),
                        SUM(CASE WHEN status='success' THEN 1 ELSE 0 END)
                 FROM ai_usage WHERE user_id=?""", (user_id,))
    row = c.fetchone()
    conn.close()
    total, tokens, cost, avg_lat, success = row
    total = total or 0
    return {
        "lifetime_requests": total,
        "lifetime_tokens": tokens or 0,
        "lifetime_cost": round(cost or 0, 4),
        "avg_latency_ms": round(avg_lat or 0),
        "lifetime_success_rate": round((success or 0) / total * 100, 1) if total else 100.0,
    }


def get_most_used(user_id: int, field: str, limit: int = 5) -> list:
    """Top values for a field (model_name, provider, request_type, intent)."""
    if field not in ("model_name", "provider", "request_type", "intent"):
        return []
    conn = _connect(); c = conn.cursor()
    c.execute(f"""SELECT {field}, COUNT(*) FROM ai_usage
                  WHERE user_id=? AND {field} IS NOT NULL
                  GROUP BY {field} ORDER BY COUNT(*) DESC LIMIT ?""",
              (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def get_recent_activity(user_id: int, limit: int = 10) -> list:
    """Recent calls for the activity feed."""
    conn = _connect(); c = conn.cursor()
    c.execute("""SELECT timestamp, model_name, request_type, latency_ms,
                        total_tokens, status
                 FROM ai_usage WHERE user_id=?
                 ORDER BY id DESC LIMIT ?""", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def get_recent_errors(user_id: int, limit: int = 10) -> list:
    """Recent error rows for the /errors dashboard."""
    conn = _connect(); c = conn.cursor()
    c.execute("""SELECT timestamp, model_name, request_type, error_message
                 FROM ai_usage WHERE user_id=? AND status='error'
                 ORDER BY id DESC LIMIT ?""", (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows


def get_error_breakdown(user_id: int) -> dict:
    """Counts of total errors + top error messages + model causing most errors."""
    conn = _connect(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM ai_usage WHERE user_id=? AND status='error'", (user_id,))
    total_errors = c.fetchone()[0] or 0
    c.execute("""SELECT error_message, COUNT(*) FROM ai_usage
                 WHERE user_id=? AND status='error' AND error_message IS NOT NULL
                 GROUP BY error_message ORDER BY COUNT(*) DESC LIMIT 5""",
              (user_id,))
    top_errors = c.fetchall()
    c.execute("""SELECT model_name, COUNT(*) FROM ai_usage
                 WHERE user_id=? AND status='error'
                 GROUP BY model_name ORDER BY COUNT(*) DESC LIMIT 3""", (user_id,))
    top_models = c.fetchall()
    c.execute("""SELECT COUNT(*) FROM ai_usage
                 WHERE user_id=? AND fallback_used=1""", (user_id,))
    fallbacks = c.fetchone()[0] or 0
    conn.close()
    return {
        "total_errors": total_errors,
        "top_errors": top_errors,
        "models_with_errors": top_models,
        "fallback_activations": fallbacks,
    }


def get_daily_trend(user_id: int, days: int = 7) -> list:
    """Returns [(date, requests, avg_latency, total_tokens), ...] for trend lines."""
    conn = _connect(); c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d")
    c.execute("""SELECT substr(timestamp,1,10) AS d,
                        COUNT(*), AVG(latency_ms), SUM(total_tokens)
                 FROM ai_usage WHERE user_id=? AND timestamp >= ?
                 GROUP BY d ORDER BY d""",
              (user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    return [(d, n, round(avg or 0), tokens or 0) for d, n, avg, tokens in rows]