"""
core.workspace.adapters -- synchronization adapters (v15.0-alpha.6).

Each adapter implements core.workspace.sync.SyncAdapter for one delivery
target. Telegram is the first; more (and the AI Orchestrator's consumers,
alpha.7) plug in the same way without touching the Sync Engine.
"""
from __future__ import annotations

from core.workspace.adapters.telegram import TelegramAdapter  # noqa: F401
