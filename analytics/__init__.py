import os
"""
analytics — v15.7 AI Usage Monitoring & Analytics

Public API:
    log_ai_request()    — record a single AI call (auto from baka_brain)
    log_image_request() — record an image generation
    init_usage_table()  — create the schema (called by database.init_db)

Dashboard queries (used by main.py commands):
    get_today_overview, get_lifetime_overview, get_most_used,
    get_recent_activity, get_recent_errors, get_error_breakdown,
    get_daily_trend, get_model_stats, get_fastest_slowest,
    get_most_reliable, detect_degraded_models,
    latency_percentiles, get_trends, estimate_cost
"""
from .usage_logger import (
    log_ai_request,
    log_ai_request_sync,
    log_image_request,
    init_usage_table,
    get_session_id,
)
from .usage_service import (
    get_today_overview,
    get_lifetime_overview,
    get_most_used,
    get_recent_activity,
    get_recent_errors,
    get_error_breakdown,
    get_daily_trend,
)
from .model_metrics import (
    get_model_stats,
    get_fastest_slowest,
    get_most_reliable,
    detect_degraded_models,
)
from .performance_tracker import (
    latency_percentiles,
    get_trends,
)
from .token_counter import (
    estimate_cost,
    get_provider_for_model,
    MODEL_COSTS,
)

__all__ = [
    "log_ai_request", "log_ai_request_sync", "log_image_request", "init_usage_table", "get_session_id",
    "get_today_overview", "get_lifetime_overview", "get_most_used",
    "get_recent_activity", "get_recent_errors", "get_error_breakdown",
    "get_daily_trend", "get_model_stats", "get_fastest_slowest",
    "get_most_reliable", "detect_degraded_models",
    "latency_percentiles", "get_trends",
    "estimate_cost", "get_provider_for_model", "MODEL_COSTS",
]