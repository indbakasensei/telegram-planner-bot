"""
token_counter.py — v11.1
Cost estimation per model. Prices are USD per 1 million tokens.
Source: NVIDIA NIM free tier (1000 calls/month) + reference from each provider.

The free tier means real-money cost = 0 today, but tracking estimated cost
prepares us for when we move to paid tiers or other providers.
"""

# USD per 1M tokens — input / output split where the provider differentiates
MODEL_COSTS = {
    # NVIDIA NIM (paid tier estimates — free tier = $0)
    "z-ai/glm-5.1":                            {"in": 0.30, "out": 0.50, "provider": "NVIDIA NIM"},
    "z-ai/glm-5.2":                            {"in": 0.40, "out": 0.80, "provider": "NVIDIA NIM"},
    "meta/llama-3.1-8b-instruct":              {"in": 0.10, "out": 0.10, "provider": "NVIDIA NIM"},
    "meta/llama-3.1-70b-instruct":             {"in": 0.40, "out": 0.40, "provider": "NVIDIA NIM"},
    "meta/llama-3.2-90b-vision-instruct":      {"in": 0.40, "out": 0.40, "provider": "NVIDIA NIM"},
    "black-forest-labs/flux.1-dev":            {"in": 0,    "out": 0,    "provider": "NVIDIA NIM", "per_image": 0.04},
    "nvidia/cosmos-1.0-7b-text2world":         {"in": 0,    "out": 0,    "provider": "NVIDIA NIM", "per_video": 0.20},
    "stabilityai/stable-video-diffusion":      {"in": 0,    "out": 0,    "provider": "NVIDIA NIM", "per_video": 0.10},
    "deepseek-ai/deepseek-r1":                 {"in": 0.55, "out": 2.19, "provider": "NVIDIA NIM"},

    # OpenAI (for future)
    "gpt-4o":                                  {"in": 2.50, "out": 10.00, "provider": "OpenAI"},
    "gpt-4o-mini":                             {"in": 0.15, "out": 0.60,  "provider": "OpenAI"},

    # Anthropic
    "claude-3-5-sonnet":                       {"in": 3.00, "out": 15.00, "provider": "Anthropic"},
    "claude-3-5-haiku":                        {"in": 1.00, "out": 5.00,  "provider": "Anthropic"},

    # Google
    "gemini-1.5-pro":                          {"in": 1.25, "out": 5.00,  "provider": "Google"},
    "gemini-1.5-flash":                        {"in": 0.075,"out": 0.30,  "provider": "Google"},

    # Local
    "ollama-local":                            {"in": 0,    "out": 0,     "provider": "Ollama"},
}


def estimate_cost(model_name: str, prompt_tokens: int = 0,
                  completion_tokens: int = 0, images: int = 0,
                  videos: int = 0) -> float:
    """
    Returns estimated USD cost for an AI request.
    Returns 0.0 if model unknown (graceful default — never raises).
    """
    if not model_name:
        return 0.0
    info = MODEL_COSTS.get(model_name)
    if not info:
        # Try a loose match (e.g. "glm-5.1" matches "z-ai/glm-5.1")
        for known, data in MODEL_COSTS.items():
            if model_name in known or known in model_name:
                info = data
                break
    if not info:
        return 0.0
    cost = 0.0
    cost += (prompt_tokens / 1_000_000) * info.get("in", 0)
    cost += (completion_tokens / 1_000_000) * info.get("out", 0)
    cost += images * info.get("per_image", 0)
    cost += videos * info.get("per_video", 0)
    return round(cost, 6)


def get_provider_for_model(model_name: str) -> str:
    """Returns the provider name for a model, or 'Unknown' if not found."""
    if not model_name:
        return "Unknown"
    info = MODEL_COSTS.get(model_name)
    if info:
        return info["provider"]
    for known, data in MODEL_COSTS.items():
        if model_name in known or known in model_name:
            return data["provider"]
    return "Unknown"


def get_model_capabilities(model_name: str) -> dict:
    """Returns capability tags for a model — used by the dashboard."""
    if "vision" in (model_name or "").lower():
        return {"text": True, "image_in": True, "image_out": False}
    if "flux" in (model_name or "").lower() or "image" in (model_name or "").lower():
        return {"text": False, "image_in": False, "image_out": True}
    if "cosmos" in (model_name or "").lower() or "video" in (model_name or "").lower():
        return {"text": False, "image_in": False, "image_out": False, "video_out": True}
    return {"text": True, "image_in": False, "image_out": False}