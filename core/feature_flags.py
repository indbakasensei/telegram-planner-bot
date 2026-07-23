"""
feature_flags.py -- gradual-rollout flags for the Offline Engine's
per-domain migration (DESIGN_SPEC_v14_AUTONOMOUS_CORE.md Stage 2,
DRG-001_Intent_Aware_Routing.md's Sub-stage C).

Every flag defaults OFF. Read once, at import time, from environment
variables -- the same .env-backed configuration convention this project
already uses for BOT_TOKEN/OWNER_ID/NVIDIA_API_KEY (main.py, baka_brain.py),
so a flag can be flipped by editing .env and restarting the process,
without a code change.

v14.1C introduces these flags; nothing in the codebase reads them yet --
no Offline Engine exists to gate (Stage 2 not started), and
core/routing/'s Routing Layer remains behaviorally identical regardless
of any flag's value (DRG-001's OFFLINE_ENGINE_IMPLEMENTED_INTENTS set,
not these flags, is what core/routing/confidence.py actually consults --
see DEBUGGING.md for how the two relate once Stage 2 begins).
"""
from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _flag(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in _TRUTHY


OFFLINE_TASKS: bool = _flag("OFFLINE_TASKS")
OFFLINE_HABITS: bool = _flag("OFFLINE_HABITS")
OFFLINE_GOALS: bool = _flag("OFFLINE_GOALS")
OFFLINE_PROJECTS: bool = _flag("OFFLINE_PROJECTS")

# v15.0-alpha.1 -- Workspace OS master flag (docs/v15/). Default OFF: the
# Workspace Foundation (schema, Repository, Service, Templates) ships
# complete but dormant, exactly like the Offline flags above shipped ahead
# of their engine. While OFF, nothing constructs or consumes the Workspace
# stack, so the bot behaves byte-identically to v14.26. A canary flips this
# in .env to begin rollout (docs/v15/MIGRATION.md §5).
WORKSPACE: bool = _flag("WORKSPACE")
