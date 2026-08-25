"""Integration tests for analytics infrastructure — real temp DB write→query round-trips."""
import pytest
import sqlite3


@pytest.fixture
def analytics_temp_db(monkeypatch, tmp_path):
    """Fresh temp DB with analytics modules patched to use it."""
    db_path = str(tmp_path / "test_analytics.db")

    # Patch all analytics modules' DB_NAME (token_counter has no DB_NAME)
    import analytics.usage_logger as ul
    import analytics.usage_service as us
    import analytics.model_metrics as mm
    import analytics.performance_tracker as pt

    for mod in (ul, us, mm, pt):
        monkeypatch.setattr(mod, "DB_NAME", db_path)

    # Also patch database module for init_db call
    import database as db
    monkeypatch.setattr(db, "DB_NAME", db_path)

    # Initialize the database (this calls init_usage_table)
    db.init_db()

    yield db_path


class TestAnalyticsInfrastructure:
    """End-to-end tests with real SQLite."""

    def test_full_write_read_roundtrip(self, analytics_temp_db):
        """Insert via log_ai_request → query via get_today_overview returns correct counts."""
        import analytics

        user_id = 12345

        # Write a successful AI request
        analytics.log_ai_request_sync(
            model_name="z-ai/glm-5.2",
            latency_ms=150,
            status="success",
            user_id=user_id,
            request_type="CHAT",
            intent="TASK_CREATION",
            prompt_tokens=100,
            completion_tokens=50,
            response_text="Here is your task.",
        )

        # Query today's overview
        today = analytics.get_today_overview(user_id)
        assert today["requests_today"] == 1
        assert today["tokens_today"] == 150
        assert today["successes"] == 1
        assert today["errors"] == 0
        assert today["success_rate"] == 100.0
        assert today["avg_latency_ms"] == 150

        # Verify cost estimation worked
        assert today["cost_today"] > 0

    def test_image_write_path(self, analytics_temp_db):
        """log_image_request → get_recent_errors can retrieve entry."""
        import analytics

        user_id = 12346

        analytics.log_image_request(
            model_name="black-forest-labs/flux.1-schnell",
            latency_ms=2000,
            status="success",
            user_id=user_id,
            prompt_text="a beautiful sunset",
            image_count=2,
        )

        # Should appear in recent activity
        recent = analytics.get_recent_activity(user_id, limit=5)
        assert len(recent) == 1
        ts, model, rtype, lat, tok, status = recent[0]
        assert model == "black-forest-labs/flux.1-schnell"
        assert rtype == "IMAGE_GENERATION"
        assert status == "success"
        assert lat == 2000

    def test_multi_user_isolation(self, analytics_temp_db):
        """Two user_ids → each query returns only own data."""
        import analytics

        user_a = 111
        user_b = 222

        analytics.log_ai_request_sync(
            model_name="z-ai/glm-5.2", latency_ms=100, status="success",
            user_id=user_a, request_type="CHAT", prompt_tokens=10, completion_tokens=5,
        )
        analytics.log_ai_request_sync(
            model_name="z-ai/glm-5.2", latency_ms=200, status="success",
            user_id=user_b, request_type="CHAT", prompt_tokens=20, completion_tokens=10,
        )

        today_a = analytics.get_today_overview(user_a)
        today_b = analytics.get_today_overview(user_b)

        assert today_a["requests_today"] == 1
        assert today_a["tokens_today"] == 15
        assert today_b["requests_today"] == 1
        assert today_b["tokens_today"] == 30

        # Cross-check: A's query shouldn't see B's data
        assert today_a["lifetime_requests"] if hasattr(today_a, 'lifetime_requests') else today_a["requests_today"] == 1

    def test_batch_ingestion(self, analytics_temp_db):
        """Rapid-fire log calls → all appear in DB after writer drain."""
        import analytics
        import time

        user_id = 333

        # Fire multiple requests rapidly using sync version (no background thread delay)
        for i in range(10):
            analytics.log_ai_request_sync(
                model_name="z-ai/glm-5.2",
                latency_ms=100 + i * 10,
                status="success",
                user_id=user_id,
                request_type="BATCH_TEST",
                prompt_tokens=10,
                completion_tokens=5,
            )

        today = analytics.get_today_overview(user_id)
        assert today["requests_today"] == 10
        assert today["tokens_today"] == 150

        # Verify all latencies recorded
        conn = sqlite3.connect(analytics_temp_db)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM ai_usage WHERE user_id=? AND request_type='BATCH_TEST'", (user_id,))
        count = c.fetchone()[0]
        conn.close()
        assert count == 10

    def test_schema_idempotency(self, analytics_temp_db):
        """Double init_usage_table() → no error, table unchanged."""
        import analytics
        import database as db

        # First init already happened in fixture; call again
        analytics.init_usage_table()
        analytics.init_usage_table()

        # Should still work
        today = analytics.get_today_overview(999)
        assert today["requests_today"] == 0

        # Verify table structure still correct
        conn = sqlite3.connect(analytics_temp_db)
        c = conn.cursor()
        c.execute("PRAGMA table_info(ai_usage)")
        cols = {row[1] for row in c.fetchall()}
        assert "id" in cols
        assert "timestamp" in cols
        conn.close()

    def test_error_logging_and_breakdown(self, analytics_temp_db):
        """log_ai_request with status=error → get_error_breakdown reflects it."""
        import analytics

        user_id = 444

        analytics.log_ai_request_sync(
            model_name="z-ai/glm-5.2",
            latency_ms=5000,
            status="error",
            user_id=user_id,
            request_type="CHAT",
            prompt_tokens=100,
            completion_tokens=0,
            error_message="Rate limit exceeded",
            fallback_used=True,
        )

        bd = analytics.get_error_breakdown(user_id)
        assert bd["total_errors"] == 1
        assert bd["fallback_activations"] == 1
        assert len(bd["top_errors"]) == 1
        assert "Rate limit" in bd["top_errors"][0][0]
        assert bd["models_with_errors"][0][0] == "z-ai/glm-5.2"

        recent = analytics.get_recent_errors(user_id, limit=5)
        assert len(recent) == 1
        assert "Rate limit" in recent[0][3]

    def test_model_stats_aggregation(self, analytics_temp_db):
        """Multiple calls to different models → get_model_stats returns per-model breakdown."""
        import analytics

        user_id = 555

        # Log calls to different models
        analytics.log_ai_request_sync(
            model_name="z-ai/glm-5.2", latency_ms=1000, status="success",
            user_id=user_id, request_type="CHAT", prompt_tokens=50, completion_tokens=25,
        )
        analytics.log_ai_request_sync(
            model_name="meta/llama-3.1-8b-instruct", latency_ms=200, status="success",
            user_id=user_id, request_type="CHAT", prompt_tokens=30, completion_tokens=15,
        )
        analytics.log_ai_request_sync(
            model_name="z-ai/glm-5.2", latency_ms=1200, status="error",
            user_id=user_id, request_type="CHAT", prompt_tokens=40, completion_tokens=0,
            error_message="Timeout",
        )

        stats = analytics.get_model_stats(user_id)
        assert len(stats) == 2

        # Find GLM 5.2 stats
        glm_stats = next(s for s in stats if s["model"] == "z-ai/glm-5.2")
        assert glm_stats["total_requests"] == 2
        assert glm_stats["success_count"] == 1
        assert glm_stats["error_count"] == 1
        assert glm_stats["success_rate"] == 50.0

        # Find Llama stats
        llama_stats = next(s for s in stats if s["model"] == "meta/llama-3.1-8b-instruct")
        assert llama_stats["total_requests"] == 1
        assert llama_stats["success_count"] == 1
        assert llama_stats["success_rate"] == 100.0

    def test_performance_percentiles(self, analytics_temp_db):
        """latency_percentiles returns correct p50/p95/p99 for known distribution."""
        import analytics

        user_id = 666

        # Insert known latency values: 100, 200, 300, 400, 500
        for lat in [100, 200, 300, 400, 500]:
            analytics.log_ai_request_sync(
                model_name="z-ai/glm-5.2", latency_ms=lat, status="success",
                user_id=user_id, request_type="PERF_TEST", prompt_tokens=10, completion_tokens=5,
            )

        perc = analytics.latency_percentiles(user_id, days=7)
        assert perc["n"] == 5
        assert perc["p50"] == 300  # median
        assert perc["p95"] == 500  # 95th percentile (index 4 = 500)
        assert perc["p99"] == 500  # 99th percentile (index 4 = 500)

    def test_trends_calculation(self, analytics_temp_db):
        """get_trends returns daily/weekly/monthly counts."""
        import analytics

        user_id = 777

        analytics.log_ai_request_sync(
            model_name="z-ai/glm-5.2", latency_ms=100, status="success",
            user_id=user_id, request_type="CHAT", prompt_tokens=10, completion_tokens=5,
        )

        trends = analytics.get_trends(user_id)
        assert trends["daily"] == 1
        assert trends["weekly"] >= 1
        assert trends["monthly"] >= 1
        assert "→" in trends["daily_trend"] or "↑" in trends["daily_trend"]


class TestPricing:
    """Token counter / pricing tests."""

    def test_estimate_cost_known_models(self):
        """estimate_cost returns expected values for current production models."""
        from analytics.token_counter import estimate_cost

        # GLM 5.2
        cost = estimate_cost("z-ai/glm-5.2", prompt_tokens=1_000_000, completion_tokens=1_000_000)
        assert cost == round(0.40 + 0.80, 6)

        # Llama 8B
        cost = estimate_cost("meta/llama-3.1-8b-instruct", prompt_tokens=1_000_000, completion_tokens=1_000_000)
        assert cost == round(0.10 + 0.10, 6)

        # Flux image
        cost = estimate_cost("black-forest-labs/flux.1-schnell", images=1)
        assert cost == 0.03

        # SVD video
        cost = estimate_cost("stabilityai/stable-video-diffusion", videos=1)
        assert cost == 0.10

    def test_estimate_cost_unknown_model(self):
        """Unknown model returns 0.0."""
        from analytics.token_counter import estimate_cost

        cost = estimate_cost("unknown/model-xyz", prompt_tokens=1000, completion_tokens=1000)
        assert cost == 0.0

    def test_get_provider_for_model(self):
        """get_provider_for_model returns correct provider strings."""
        from analytics.token_counter import get_provider_for_model

        assert get_provider_for_model("z-ai/glm-5.2") == "NVIDIA NIM"
        assert get_provider_for_model("meta/llama-3.1-8b-instruct") == "NVIDIA NIM"
        assert get_provider_for_model("gpt-4o") == "OpenAI"
        assert get_provider_for_model("claude-3-5-sonnet") == "Anthropic"
        assert get_provider_for_model("gemini-1.5-pro") == "Google"
        assert get_provider_for_model("ollama-local") == "Ollama"
        assert get_provider_for_model("unknown/model") == "Unknown"
        assert get_provider_for_model("") == "Unknown"