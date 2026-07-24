"""
reliability.py -- provider-agnostic AI call reliability (v15.1.0-alpha.2).

A small, dependency-free retry/backoff foundation plus a typed error
taxonomy, so the AI layer can fail predictably and recover from transient
provider problems (timeouts, 429s, 5xx, a model briefly gone). This is the
reusable core that future AI code (planner, tool orchestration) builds on;
it deliberately does NOT import any SDK -- the caller passes a plain
callable, which keeps it fully offline-testable.

Design: `call_with_retry(fn, policy)` runs `fn()` and retries only on the
RETRIABLE typed errors, with exponential backoff + jitter; anything else
(including a non-retriable AIError) propagates immediately. `classify_status`
maps an HTTP status to the right typed error so adapters can translate SDK
exceptions into this taxonomy.
"""
from __future__ import annotations

import random
import time as _time
from dataclasses import dataclass


class AIError(Exception):
    """Base for AI-layer failures."""


class AITimeout(AIError):
    """The provider did not respond in time (retriable)."""


class AIRateLimited(AIError):
    """The provider rejected the call for rate limiting -- HTTP 429 (retriable)."""


class AIUnavailable(AIError):
    """The provider/model is temporarily unavailable -- 5xx, or a model that
    is gone/degraded (retriable, then fall back)."""


class AIBadRequest(AIError):
    """The request itself is invalid -- 4xx other than 429 (NOT retriable)."""


# Only these justify a retry against the same model.
RETRIABLE: tuple[type[AIError], ...] = (AITimeout, AIRateLimited, AIUnavailable)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential-backoff parameters. Delay for attempt n (1-based) is
    min(max_delay, base_delay * backoff**(n-1)), plus up to `jitter` of that
    as random jitter."""
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 20.0
    backoff: float = 2.0
    jitter: float = 0.1


def classify_status(status_code) -> type[AIError] | None:
    """Map an HTTP status to a typed error class, or None if it isn't an
    error we model (e.g. 2xx)."""
    if status_code is None:
        return None
    if status_code == 429:
        return AIRateLimited
    if status_code == 408:
        return AITimeout
    if status_code == 410:      # model gone (e.g. NVIDIA EOL'd z-ai/glm-5.1)
        return AIUnavailable
    if 500 <= status_code < 600:
        return AIUnavailable
    if 400 <= status_code < 500:
        return AIBadRequest
    return None


def backoff_delay(attempt: int, policy: RetryPolicy, rand: float) -> float:
    """The delay before the given (1-based) attempt's retry. `rand` is a
    0..1 value (injected for deterministic tests)."""
    base = min(policy.max_delay, policy.base_delay * (policy.backoff ** (attempt - 1)))
    return base + base * policy.jitter * rand


def call_with_retry(fn, policy: RetryPolicy | None = None, *,
                    sleep=_time.sleep, rng=random.random):
    """Call `fn()` and return its result. On a RETRIABLE error, retry with
    exponential backoff up to `policy.max_attempts`; non-retriable errors
    propagate immediately. After the last attempt the final retriable error
    is re-raised. `sleep`/`rng` are injectable for tests."""
    policy = policy or RetryPolicy()
    last: AIError | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except RETRIABLE as e:
            last = e
            if attempt >= policy.max_attempts:
                break
            sleep(backoff_delay(attempt, policy, rng()))
    raise last
