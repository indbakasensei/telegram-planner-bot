"""
core.ai -- reliable AI foundation (v15.1.0-alpha.2).

The stable, provider-agnostic base the future AI Intelligence Layer builds
on. This milestone ships FOUNDATION only -- configuration, reliability, and
the retrieval + tool interfaces -- not the planner/orchestrator.

  * provider    -- env → ProviderConfig, with GLM / NVIDIA-NIM / local presets
  * reliability -- typed AI errors + retry/backoff policy
  * retrieval   -- Retriever interface (+ NullRetriever)
  * tools       -- Tool interface + ToolRegistry
"""
from __future__ import annotations

from core.ai.provider import (  # noqa: F401
    DEFAULT_PROVIDER,
    PRESETS,
    ProviderConfig,
    ProviderPreset,
    get_preset,
    provider_names,
    resolve_config,
)
from core.ai.reliability import (  # noqa: F401
    AIBadRequest,
    AIError,
    AIRateLimited,
    AITimeout,
    AIUnavailable,
    RetryPolicy,
    call_with_retry,
    classify_status,
)
from core.ai.retrieval import Document, NullRetriever, Retriever  # noqa: F401
from core.ai.tools import Tool, ToolRegistry, ToolSpec  # noqa: F401
# v15.1.0-alpha.3 Cognitive Engine (Phase 1: planner + tool orchestration).
from core.ai.cognition import (  # noqa: F401
    CognitiveContext,
    CognitiveEngine,
    CognitiveResult,
    Plan,
    Planner,
    PlanStep,
    RuleBasedPlanner,
    ToolResult,
    execute,
)
from core.ai.llm_planner import KNOWN_TOOLS, LLMPlanner  # noqa: F401
from core.ai.workspace_tools import build_workspace_registry  # noqa: F401
from core.ai.workspace_retriever import RecallTool, WorkspaceRetriever  # noqa: F401
from core.ai.entity_manager import EntityManager  # noqa: F401
