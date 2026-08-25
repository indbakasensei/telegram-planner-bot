"""
model_metrics.py — v15.7
Per-model performance rollups + automatic health-degradation detection.
"""
import sqlite3
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")
DB_NAME = "planner.db"


def get_model_stats(user_id: int, model_name: str = None) -> list:
    """
    Per-model stats. Returns a list of dicts ordered by request count desc.
    If model_name is given, returns just that model's row (still a list).
    """
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    today = datetime.now(IST).strftime("%Y-%m-%d")
    where_extra = " AND model_name=?" if model_name else ""
    params = [user_id]
    if model_name:
        params.append(model_name)
    c.execute(f"""SELECT model_name, provider,
                         COUNT(*) AS total,
                         AVG(latency_ms) AS avg_lat,
                         AVG(total_tokens) AS avg_tokens,
                         SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS ok,
                         SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS bad,
                         SUM(CASE WHEN substr(timestamp,1,10)=? THEN 1 ELSE 0 END) AS today_n,
                         MAX(timestamp) AS last_used
                  FROM ai_usage WHERE user_id=?{where_extra}
                  GROUP BY model_name ORDER BY total DESC""",
              [today] + params)
    rows = c.fetchall()
    conn.close()
    result = []
    for row in rows:
        model, provider, total, avg_lat, avg_tok, ok, bad, today_n, last_used = row
        success_rate = (ok / total * 100) if total else 100
        result.append({
            "model": model,
            "provider": provider or "Unknown",
            "total_requests": total or 0,
            "avg_latency_ms": round(avg_lat or 0),
            "avg_tokens": round(avg_tok or 0),
            "success_count": ok or 0,
            "error_count": bad or 0,
            "success_rate": round(success_rate, 1),
            "today_requests": today_n or 0,
            "last_used": last_used,
            "health": _health_label(avg_lat, success_rate),
        })
    return result


def _health_label(avg_latency, success_rate):
    """Heuristic health rating per model."""
    if success_rate is None:
        return "unknown"
    if success_rate < 80:
        return "degraded"
    if success_rate < 95:
        return "warning"
    if avg_latency and avg_latency > 8000:
        return "slow"
    return "healthy"


def get_fastest_slowest(user_id: int):
    """Returns (fastest_model_row, slowest_model_row) for /performance."""
    stats = get_model_stats(user_id)
    text_models = [s for s in stats if s["total_requests"] >= 3]  # need a sample
    if not text_models:
        return None, None
    fastest = min(text_models, key=lambda s: s["avg_latency_ms"])
    slowest = max(text_models, key=lambda s: s["avg_latency_ms"])
    return fastest, slowest


def get_most_reliable(user_id: int):
    """Highest success rate among models with enough samples."""
    stats = get_model_stats(user_id)
    sampled = [s for s in stats if s["total_requests"] >= 3]
    if not sampled:
        return None
    return max(sampled, key=lambda s: s["success_rate"])


def detect_degraded_models(user_id: int, lookback_minutes: int = 30) -> list:
    """
    Looks at the most recent calls; flags models with high error rate or latency.
    Used for proactive 'AI degraded' warnings.
    """
    conn = sqlite3.connect(DB_NAME); c = conn.cursor()
    cutoff = (datetime.now(IST) - timedelta(minutes=lookback_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""SELECT model_name,
                        COUNT(*) AS n,
                        AVG(latency_ms) AS avg_lat,
                        SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errs
                 FROM ai_usage WHERE user_id=? AND timestamp >= ?
                 GROUP BY model_name HAVING n >= 3""",
              (user_id, cutoff))
    rows = c.fetchall()
    conn.close()
    flagged = []
    for model, n, lat, errs in rows:
        err_rate = (errs / n * 100) if n else 0
        if err_rate >= 30 or (lat and lat > 10000):
            flagged.append({
                "model": model,
                "recent_calls": n,
                "error_rate": round(err_rate, 1),
                "avg_latency_ms": round(lat or 0),
            })
    return flagged