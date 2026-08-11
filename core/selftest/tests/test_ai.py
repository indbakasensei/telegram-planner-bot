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


@selftest(name="AI Configuration", category="AI")
def check_ai_configuration():
    """Offline: the provider config resolves cleanly (endpoint + model + a
    key). Reports the active provider/model so a GLM 5.2 migration is visible
    at a glance -- no network call."""
    from core.ai.provider import resolve_config
    cfg = resolve_config()
    if not cfg.base_url or not cfg.model_main:
        raise SelfTestFail("provider config missing base_url or model")
    if not cfg.has_key:
        raise SelfTestWarning(
            f"{cfg.provider} · {cfg.model_main} · no API key set (AI calls will fail)")
    return f"{cfg.provider} · {cfg.model_main} · {cfg.base_url}"


@selftest(name="AI Tool Contract", category="AI")
def check_ai_tool_contract():
    """Offline: the v15.2 M2 tool contract is healthy in the live app — a
    tool registers, executes through the registry with validated args, and
    invalid args / duplicate names are rejected before a handler runs. No
    Telegram surface yet (the AI Worker is a later milestone)."""
    from core.ai.tools import (
        RiskLevel, Tool, ToolRegistry, ToolRegistryError, ToolSpec,
    )

    class _Probe(Tool):
        @property
        def spec(self):
            return ToolSpec(
                name="probe", description="M2 self-test probe",
                parameters={"type": "object",
                            "properties": {"x": {"type": "integer"}}},
                risk=RiskLevel.MUTATING)

        def run(self, **kwargs):
            return f"x={kwargs['x']}"

    reg = ToolRegistry()
    reg.register(_Probe())

    good = reg.execute("probe", {"x": 2})
    if not good.ok or good.output != "x=2":
        raise SelfTestFail(f"valid tool call failed: {good.output!r}")

    bad = reg.execute("probe", {"x": "not-an-int"})
    if bad.ok or bad.error_code != "invalid_args":
        raise SelfTestFail("invalid args reached the tool handler")

    try:
        reg.register(_Probe())           # duplicate name must be refused
    except ToolRegistryError:
        pass
    else:
        raise SelfTestFail("duplicate tool name was not rejected")

    return "register → validate → execute → contain OK"


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
