"""
intent_engine.py -- BAKA v14.0 Stage 1 Intent Engine (Shadow Mode).

Pure, stateless, deterministic message classifier. Implements the
approved design in INTENT_ENGINE.md and docs/adr/ADR-002-intent-engine.md.
Runs in Shadow Mode: main.py's handle_message() calls classify() and
logs the result, but no routing decision anywhere in the codebase
depends on it yet.

MUST NOT (and does not): call AI, call database.py, call scheduler.py,
import telegram.Update/telegram.Bot/ContextTypes, mutate
conversation_state.py, dispatch commands, execute handlers, send
replies, or perform any I/O beyond a debug log line.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from core.intent.intent_types import ConversationContext, Intent, IntentResult
from core.intent.rules import (
    RuleMatch,
    tier0_command_match,
    tier3_anchored_smalltalk,
    tier3_help,
    tier4_keyword_heuristics,
    tier_date_and_recurrence,
)

logger = logging.getLogger(__name__)


class IntentEngine:
    """
    Stage 1 Intent Engine: deterministic, tiered, rule-based
    classification only (no LLM, no embeddings, no ML model -- see
    ADR-002 for why). Holds no state between calls; every classify()
    call is independent of every other.
    """

    def classify(self, text: str, context: ConversationContext) -> IntentResult:
        """
        Classify `text` given `context`. Never raises for ordinary input
        (falls through to Intent.UNKNOWN); never touches the network,
        database, filesystem, or Telegram.
        """
        start = time.perf_counter()
        stripped = text.strip()

        if not stripped:
            result = IntentResult(Intent.UNKNOWN, 0.0, {}, 0.0, "Tier 5: empty input", 5, 0.0)
            result.latency_ms = round((time.perf_counter() - start) * 1000, 4)
            self._log(stripped, result)
            return result

        # "Authoritative" tiers match the *whole* message against a fixed
        # command or pattern, which makes them unambiguous by construction
        # -- a match short-circuits immediately, the same way main.py's own
        # command routing would. Tier 0 is checked first (exact commands
        # take precedence over everything); the anchored greeting/small-talk
        # check comes next, deliberately before the date parser -- see
        # tier3_anchored_smalltalk's docstring for the concrete "good
        # morning" misclassification (vague-time word "morning" resolved by
        # date_parser.py) this ordering exists to fix.
        authoritative: tuple[Callable[[], RuleMatch | None], ...] = (
            lambda: tier0_command_match(stripped),
            lambda: tier3_anchored_smalltalk(stripped),
        )
        # Remaining tiers may each independently match the same message
        # with different intents (e.g. a date signal and a weak "cancel"
        # keyword both firing); all their candidates are collected so the
        # highest-confidence one can be chosen and ambiguity can be scored
        # against the runner-up.
        accumulating: tuple[Callable[[], RuleMatch | None], ...] = (
            lambda: tier_date_and_recurrence(stripped, context.now),
            lambda: tier3_help(stripped),
            lambda: tier4_keyword_heuristics(stripped),
        )

        candidates: list[RuleMatch] = []
        for tier_func in authoritative:
            match = tier_func()
            if match is not None:
                candidates.append(match)
                break
        if not candidates:
            for tier_func in accumulating:
                match = tier_func()
                if match is not None:
                    candidates.append(match)

        if not candidates:
            intent, confidence, entities, reasoning, tier = (
                Intent.UNKNOWN, 0.0, {}, "Tier 5: no rule matched", 5,
            )
            ambiguity = 0.0
        else:
            candidates.sort(key=lambda c: c[1], reverse=True)
            intent, confidence, entities, reasoning, tier = candidates[0]
            runner_up = next((c for c in candidates[1:] if c[0] != intent), None)
            ambiguity = round(runner_up[1] / confidence, 4) if runner_up and confidence > 0 else 0.0

        latency_ms = round((time.perf_counter() - start) * 1000, 4)
        result = IntentResult(intent, confidence, entities, ambiguity, reasoning, tier, latency_ms)
        self._log(stripped, result)
        return result

    @staticmethod
    def _log(input_text: str, result: IntentResult) -> None:
        # Lazy %-style formatting: the (cheap but non-zero) string-join
        # work only happens if the debug level is actually enabled.
        logger.debug(
            "[Intent]\nInput:\n%r\nIntent:\n%s\nConfidence:\n%.2f\nEntities:\n%s\n"
            "Ambiguity:\n%.2f\nReason:\n%s\nLatency:\n%.2f ms",
            input_text,
            result.intent.name,
            result.confidence,
            ", ".join(f"{k}={v}" for k, v in result.entities.items()) or "(none)",
            result.ambiguity,
            result.reasoning,
            result.latency_ms,
        )
