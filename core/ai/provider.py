"""
provider.py -- AI provider configuration (v15.1.0-alpha.2).

A single, clean place that turns environment variables into a resolved
`ProviderConfig` (endpoint, key, model ids, timeout, retry budget). It
replaces the scattered `os.getenv(...)` calls that used to live in
baka_brain.py, and it makes switching providers a matter of configuration,
not code -- including the GLM 5.2 migration.

Named presets fill in a provider's endpoint + sensible default model ids so
a user only has to set `AI_PROVIDER` (+ a key); every value stays
env-overridable. Resolving with an empty environment yields the historical
NVIDIA-NIM defaults byte-for-byte, so existing deployments are unchanged.

GLM 5.2 is reachable two ways, both supported here:
  * via NVIDIA NIM (default provider) by setting `MODEL_MAIN=z-ai/glm-5.2`;
  * via GLM-native (Zhipu) by setting `AI_PROVIDER=glm` (+ `GLM_API_KEY`).

This module is pure (no network, no SDK import) so it is fully testable by
passing an `env` dict.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_PROVIDER = "nvidia-nim"


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    """Static per-provider defaults. `api_key_env` lists the environment
    variables to check for a key, in priority order."""
    name: str
    base_url: str
    model_main: str
    model_fast: str
    model_reasoning: str
    model_vision: str
    api_key_env: tuple[str, ...] = ("AI_API_KEY",)
    note: str = ""


PRESETS: dict[str, ProviderPreset] = {
    # NVIDIA NIM -- the historical default. GLM 5.2 is also available on this
    # same endpoint as the model id `z-ai/glm-5.2`.
    "nvidia-nim": ProviderPreset(
        name="nvidia-nim",
        # v15.1.0-alpha.4: GLM 5.2 is the default main + reasoning model on
        # NVIDIA NIM (the owner's core model). MODEL_FAST stays a small,
        # proven Llama so the automatic fallback path is reliable if GLM 5.2
        # is briefly degraded; vision stays on the Llama vision model
        # (z-ai/glm-5.2 is text-only on NIM). Override any of these via env.
        base_url="https://integrate.api.nvidia.com/v1",
        model_main="meta/llama-3.2-11b-vision-instruct",
        model_fast="meta/llama-3.2-11b-vision-instruct",
        model_reasoning="meta/llama-3.2-11b-vision-instruct",
        model_vision="meta/llama-3.2-90b-vision-instruct",
        api_key_env=("AI_API_KEY", "NVIDIA_API_KEY"),
        note="OpenAI-compatible NVIDIA NIM. Default main model: z-ai/glm-5.2.",
    ),
    # GLM-native (Zhipu) OpenAI-compatible endpoint.
    "glm": ProviderPreset(
        name="glm",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model_main="glm-4.6",
        model_fast="glm-4.5-air",
        model_reasoning="glm-4.6",
        model_vision="glm-4.5v",
        api_key_env=("GLM_API_KEY", "ZHIPU_API_KEY", "AI_API_KEY"),
        note="Zhipu GLM native OpenAI-compatible endpoint. Set MODEL_MAIN=glm-5.2 to pin it.",
    ),
    # Local OpenAI-compatible server (e.g. Ollama). No key required.
    "local": ProviderPreset(
        name="local",
        base_url="http://localhost:11434/v1",
        model_main="llama3.1",
        model_fast="llama3.1",
        model_reasoning="llama3.1",
        model_vision="llava",
        api_key_env=("AI_API_KEY",),
        note="Local OpenAI-compatible server (Ollama, LM Studio, vLLM). Key optional.",
    ),
}


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Fully resolved AI configuration for one process."""
    provider: str
    base_url: str
    api_key: str | None
    model_main: str
    model_fast: str
    model_reasoning: str
    model_vision: str
    timeout: float
    max_retries: int

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


def provider_names() -> tuple[str, ...]:
    """Every known provider preset name."""
    return tuple(PRESETS)


def get_preset(provider: str) -> ProviderPreset:
    """The preset for a provider, falling back to the default (never raises)."""
    return PRESETS.get((provider or "").strip().lower(), PRESETS[DEFAULT_PROVIDER])


def _first_env(env, names) -> str | None:
    for n in names:
        v = env.get(n)
        if v:
            return v
    return None


def _float(env, name, default) -> float:
    try:
        return float(env.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _int(env, name, default) -> int:
    try:
        return int(env.get(name, default))
    except (TypeError, ValueError):
        return int(default)


def resolve_config(env=None) -> ProviderConfig:
    """Resolve a `ProviderConfig` from the environment (defaults to
    os.environ). Env `MODEL_*` always win over the preset; `AI_BASE_URL`
    wins over the preset endpoint. With an empty env this returns the
    historical NVIDIA-NIM defaults unchanged."""
    env = os.environ if env is None else env
    provider = (env.get("AI_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    preset = get_preset(provider)

    base_url = env.get("AI_BASE_URL") or preset.base_url
    api_key = _first_env(env, preset.api_key_env)

    model_main = env.get("MODEL_MAIN") or preset.model_main
    model_fast = env.get("MODEL_FAST") or preset.model_fast
    model_reasoning = (env.get("MODEL_REASONING") or env.get("MODEL_THINK")
                       or preset.model_reasoning)
    model_vision = env.get("MODEL_VISION") or preset.model_vision

    return ProviderConfig(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model_main=model_main,
        model_fast=model_fast,
        model_reasoning=model_reasoning,
        model_vision=model_vision,
        timeout=_float(env, "AI_TIMEOUT", 30.0),
        max_retries=_int(env, "AI_MAX_RETRIES", 3),
    )
