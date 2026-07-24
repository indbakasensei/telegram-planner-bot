"""
Tests for v15.1.0-alpha.2 -- the core.ai foundation (provider config,
reliability, retrieval + tool interfaces). All pure/offline: no network,
no SDK, no Telegram.
"""
import pytest

from core.ai import (
    AIBadRequest, AIRateLimited, AITimeout, AIUnavailable,
    Document, NullRetriever, Retriever, RetryPolicy, ToolRegistry, ToolSpec,
    Tool, call_with_retry, classify_status, get_preset, provider_names,
    resolve_config,
)
from core.ai.reliability import backoff_delay


# ── Provider config ───────────────────────────────────────────────────────

def test_default_nim_config():
    # v15.1.0-alpha.4: GLM 5.2 is the default main + reasoning model on NIM;
    # fast stays Llama-8b (reliable fallback), vision stays Llama-vision.
    cfg = resolve_config(env={})
    assert cfg.provider == "nvidia-nim"
    assert cfg.base_url == "https://integrate.api.nvidia.com/v1"
    assert cfg.model_main == "z-ai/glm-5.2"
    assert cfg.model_reasoning == "z-ai/glm-5.2"
    assert cfg.model_fast == "meta/llama-3.1-8b-instruct"
    assert cfg.model_vision == "meta/llama-3.2-90b-vision-instruct"
    assert cfg.timeout == 30.0 and cfg.max_retries == 3


def test_glm_provider_preset():
    cfg = resolve_config(env={"AI_PROVIDER": "glm", "GLM_API_KEY": "k"})
    assert cfg.provider == "glm"
    assert "bigmodel" in cfg.base_url
    assert cfg.model_main.startswith("glm")
    assert cfg.api_key == "k"


def test_glm_via_nim_by_model_id():
    # GLM 5.2 on the NIM endpoint is just a model id override.
    cfg = resolve_config(env={"MODEL_MAIN": "z-ai/glm-5.2"})
    assert cfg.provider == "nvidia-nim"
    assert cfg.model_main == "z-ai/glm-5.2"
    assert cfg.base_url == "https://integrate.api.nvidia.com/v1"


def test_env_overrides_win_over_preset():
    cfg = resolve_config(env={"AI_PROVIDER": "glm",
                              "AI_BASE_URL": "https://example/v1",
                              "MODEL_MAIN": "glm-5.2"})
    assert cfg.base_url == "https://example/v1"
    assert cfg.model_main == "glm-5.2"


def test_local_provider_preset():
    cfg = resolve_config(env={"AI_PROVIDER": "local"})
    assert "11434" in cfg.base_url
    assert cfg.has_key is False


def test_reasoning_prefers_MODEL_REASONING_then_THINK():
    assert resolve_config(env={"MODEL_THINK": "t"}).model_reasoning == "t"
    assert resolve_config(env={"MODEL_REASONING": "r", "MODEL_THINK": "t"}
                          ).model_reasoning == "r"


def test_unknown_provider_falls_back_to_default_endpoint():
    cfg = resolve_config(env={"AI_PROVIDER": "made-up"})
    assert cfg.base_url == get_preset("nvidia-nim").base_url


def test_api_key_priority_order():
    # glm preset checks GLM_API_KEY, then ZHIPU_API_KEY, then AI_API_KEY
    cfg = resolve_config(env={"AI_PROVIDER": "glm", "ZHIPU_API_KEY": "z", "AI_API_KEY": "a"})
    assert cfg.api_key == "z"


def test_provider_names_lists_presets():
    assert set(provider_names()) >= {"nvidia-nim", "glm", "local"}


# ── Reliability ───────────────────────────────────────────────────────────

def test_classify_status_taxonomy():
    assert classify_status(429) is AIRateLimited
    assert classify_status(408) is AITimeout
    assert classify_status(410) is AIUnavailable
    assert classify_status(503) is AIUnavailable
    assert classify_status(400) is AIBadRequest
    assert classify_status(200) is None


def test_backoff_delay_is_exponential_and_capped():
    p = RetryPolicy(base_delay=1, backoff=2, max_delay=5, jitter=0)
    assert backoff_delay(1, p, 0) == 1
    assert backoff_delay(2, p, 0) == 2
    assert backoff_delay(3, p, 0) == 4
    assert backoff_delay(4, p, 0) == 5      # capped


def test_call_with_retry_recovers_after_transient_failures():
    calls = {"n": 0}
    slept = []

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise AITimeout("slow")
        return "ok"

    out = call_with_retry(fn, RetryPolicy(max_attempts=3, jitter=0),
                          sleep=slept.append, rng=lambda: 0)
    assert out == "ok" and calls["n"] == 3
    assert len(slept) == 2                    # slept before each retry


def test_call_with_retry_exhausts_and_raises_last():
    def fn():
        raise AIUnavailable("down")

    with pytest.raises(AIUnavailable):
        call_with_retry(fn, RetryPolicy(max_attempts=2, jitter=0),
                        sleep=lambda d: None, rng=lambda: 0)


def test_non_retriable_error_propagates_without_sleeping():
    slept = []

    def fn():
        raise AIBadRequest("nope")

    with pytest.raises(AIBadRequest):
        call_with_retry(fn, sleep=slept.append)
    assert slept == []                        # never retried


# ── Retrieval (foundation) ────────────────────────────────────────────────

def test_null_retriever_returns_nothing():
    r = NullRetriever()
    assert isinstance(r, Retriever)
    assert r.retrieve("anything", k=10) == []


def test_document_defaults():
    d = Document(id="1", text="hi")
    assert d.score == 0.0 and d.metadata == {}


# ── Tools (foundation) ────────────────────────────────────────────────────

class _Echo(Tool):
    @property
    def spec(self):
        return ToolSpec(name="echo", description="Echo text",
                        parameters={"type": "object",
                                    "properties": {"text": {"type": "string"}}})

    def run(self, **kwargs):
        return str(kwargs.get("text", ""))


def test_tool_registry_register_get_and_run():
    reg = ToolRegistry()
    reg.register(_Echo())
    assert reg.has("echo")
    assert reg.get("echo").run(text="hey") == "hey"
    assert [s.name for s in reg.specs()] == ["echo"]


def test_toolspec_to_openai_shape():
    spec = ToolSpec(name="echo", description="d")
    o = spec.to_openai()
    assert o["type"] == "function"
    assert o["function"]["name"] == "echo"
    assert o["function"]["parameters"]["type"] == "object"


def test_registry_rejects_non_tool():
    with pytest.raises(TypeError):
        ToolRegistry().register(object())


def test_registry_register_is_idempotent_by_name():
    reg = ToolRegistry()
    reg.register(_Echo())
    reg.register(_Echo())
    assert len(reg.all()) == 1
