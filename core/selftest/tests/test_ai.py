"""Self-tests: AI provider health (category AI).

The ONLY test that makes a network call -- a fast liveness probe of the
configured AI provider. Mapped honestly to the framework's statuses:
online -> PASS, rate-limited or main-model-degraded -> WARNING (the
bot's fallback path still works), invalid key -> FAIL. Because this
probe hits the network, the offline pytest suite excludes the AI
category (runner.run(exclude={'AI'})).
"""
from core.selftest.models import SelfTestFail, SelfTestWarning
from core.selftest.registry import selftest


@selftest(name="AI Provider", category="AI")
def check_ai_provider():
    from baka_brain import check_api_status
    status = check_api_status()          # never raises; returns a dict
    state = status.get("status")
    if state == "online":
        return (f"online · {status.get('model')} · "
                f"{status.get('response_time_ms')}ms")
    if state == "rate_limited":
        raise SelfTestWarning("rate limited (429) — provider throttling")
    if state == "invalid_key":
        raise SelfTestFail("invalid API key — check AI_API_KEY")
    raise SelfTestWarning(
        f"main model unavailable — fallback path applies "
        f"({status.get('error', state)})")
