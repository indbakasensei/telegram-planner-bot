"""
entity_manager.py -- Natural Language Entity Management (v15.1.0-alpha.10).

Translates conversational free-text into Entity Engine operations (create,
update, retrieve) using the LLM as a lightweight NL → structured-data
classifier. The architecture is template-agnostic: field schemas from the
active workspace's template are passed to the LLM prompt so it can map
natural language to the correct field names, types, and values without
hardcoding any domain.

The LLM is injected as `ai_call(prompt) -> str`; the default lazily
resolves baka_brain.call_fast at call time (no import-time dependency).
When the LLM doesn't recognise entity intent, process() returns
(False, "") and the caller falls through to normal AI chat.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable

from core.storage import Storage
from core.workspace.engine import EntityEngine
from core.workspace.errors import EntityValidationError, EntityNotFound
from core.workspace.templates.registry import entity_field_specs

logger = logging.getLogger(__name__)

# Singleton cache for the default AI call (lazy, set once).
_DEFAULT_AI_CALL: Callable | None = None


def _default_ai(prompt_text: str) -> str:
    """Build messages in OpenAI format and send through call_fast.
    Matches the pattern in LLMPlanner._ai() — uses the system prompt
    for entity classification and wraps the user's context as a user
    message. The caller (llm_planner.py) is the reference."""
    global _DEFAULT_AI_CALL
    if _DEFAULT_AI_CALL is None:
        import baka_brain
        _DEFAULT_AI_CALL = (
            getattr(baka_brain, "call_fast", None)
            or getattr(baka_brain, "call_nvidia")
        )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": prompt_text},
    ]
    return _DEFAULT_AI_CALL(messages)


_SYSTEM_PROMPT = """You interpret entity management commands for a workspace system.

The user's active workspace template defines entity fields with names and types.
Your job: determine what the user wants to do with their entities and extract
structured data from their natural-language request.

Rules:
- Return ONLY valid JSON, no preamble or explanation.
- If the user wants to CREATE an entity, set intent to "create" and entity_name
  to the entity's name. Leave fields empty.
- If the user wants to UPDATE an entity's field(s), set intent to "update",
  entity_name to the entity name, and fields to a dict of field_name: value.
  Only include fields the user explicitly mentioned.
- If the user wants to RETRIEVE/FIND/SHOW entities, set intent to "retrieve"
  and query to their question.
- If the message is NOT about entity management, set intent to "none".

Response format:
{"intent": "create|update|retrieve|none", "entity_name": "", "fields": {}, "query": ""}

Example - Create:  {"intent": "create", "entity_name": "Furina", "fields": {}, "query": ""}
Example - Update:  {"intent": "update", "entity_name": "Hu Tao", "fields": {"level": 80}, "query": ""}
Example - Retrieve: {"intent": "retrieve", "entity_name": "", "fields": {}, "query": "level 70 characters with polearm"}
Example - None:    {"intent": "none", "entity_name": "", "fields": {}, "query": ""}
"""


def _extract_json(text: str) -> dict | None:
    """Safely extract a JSON object from LLM output."""
    if not text:
        return None
    # Strip markdown fences.
    if "```" in text:
        blocks = text.split("```")
        for b in blocks:
            cleaned = b.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith("{") or cleaned.startswith("{"):
                text = cleaned
                break
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (ValueError, TypeError):
        return None


class EntityManager:
    """Natural language → Entity Engine operations.

    Inject `ai_call` for offline testability; the default lazily resolves
    baka_brain's fast chat.  Stateless beyond injected deps.
    """

    def __init__(self, engine: EntityEngine | None = None,
                 storage: Storage | None = None,
                 ai_call: Callable | None = None):
        self._eng = engine or EntityEngine()
        self._s = storage or Storage()
        self._ai_call = ai_call or _default_ai

    # ── Public entry point ───────────────────────────────────────────────────

    def process(self, user_id: int, text: str) -> tuple[bool, str]:
        """Interpret *text* as an entity-management command for the user's
        active workspace.

        Returns (handled, response).  ``handled=False`` means the text does
        not appear to be about entity management and the caller should fall
        through to the regular AI pipeline.
        """
        text = (text or "").strip()
        if not text:
            logger.debug("EntityManager[%s] empty text", user_id)
            return False, ""

        logger.info("EntityManager[%s] incoming: %s", user_id, text)

        # 1.  Quick pre-check — user must have an active workspace.
        active = self._s.tg_bindings.get_active(user_id)
        if not active or active[0] is None:
            logger.debug("EntityManager[%s] no active workspace — skipping", user_id)
            return False, ""
        ws_id = active[0]
        logger.info("EntityManager[%s] active workspace id=%s", user_id, ws_id)

        ws = self._eng.get_workspace_or_none(user_id, ws_id)
        if ws is None:
            logger.warning("EntityManager[%s] workspace %s not found", user_id, ws_id)
            return False, ""
        logger.info("EntityManager[%s] workspace='%s' template=%s",
                     user_id, ws.title, ws.template)

        # 2.  Build context for the LLM: existing entity titles, field specs.
        field_info = self._field_info(ws.template)
        entities = self._eng.list_milestones(user_id, ws_id)
        entity_titles = [m.title for m in entities]
        logger.info("EntityManager[%s] field_info='%s' entities=%s",
                     user_id, field_info[:80], entity_titles)

        # 3.  Quick keyword pre-check — bail early if nothing looks
        #     entity-related, avoiding a useless LLM call on every message.
        low = text.lower()
        # Entity keywords that suggest entity management intent.
        _KEYWORDS = frozenset({
            "create", "add ", "new ", "make ", "character", "entity",
            "level", "priority", "element", "weapon", "upgrade",
            "update", "change ", "set ", "status", "current",
            "show", "find ", "who ", "which ", "what ", "list ",
            "all ", "how many", "need ", "done", "complete",
            # Common entity field value patterns.
            "is now", "reached", "got", "finally", "just",
            "finished", "completed", "increased",
        })

        has_active_keyword = any(k in low for k in _KEYWORDS)
        # Also trigger if the text mentions an existing entity name.
        mentions_entity = any(
            t.lower() in low and len(t) > 2
            for t in entity_titles
        )
        logger.debug("EntityManager[%s] pre-check: keyword=%s mentions_entity=%s",
                      user_id, has_active_keyword, mentions_entity)

        if not has_active_keyword and not mentions_entity:
            logger.info("EntityManager[%s] pre-check miss — falling through", user_id)
            return False, ""

        # 4.  Classify via LLM.
        prompt = self._build_prompt(
            text, ws.title, ws.template, field_info, entity_titles)
        logger.info("EntityManager[%s] calling LLM for classification", user_id)
        try:
            raw = self._ai_call(prompt)
        except Exception:
            logger.warning("EntityManager[%s] LLM call failed", user_id, exc_info=True)
            return False, ""

        logger.debug("EntityManager[%s] LLM raw response: %s", user_id, raw)
        data = _extract_json(raw)
        if data is None:
            logger.warning("EntityManager[%s] LLM response not parseable: %s",
                           user_id, raw)
            return False, ""

        intent = data.get("intent", "none")
        entity_name = (data.get("entity_name") or "").strip()
        logger.info("EntityManager[%s] classified as intent=%s entity='%s'",
                     user_id, intent, entity_name)

        # 5.  Route to the appropriate handler.
        if intent == "create" and entity_name:
            logger.info("EntityManager[%s] → create '%s'", user_id, entity_name)
            return True, self._handle_create(user_id, ws_id, entity_name)

        if intent == "update" and entity_name:
            fields = data.get("fields")
            if isinstance(fields, dict) and fields:
                logger.info("EntityManager[%s] → update '%s' fields=%s",
                            user_id, entity_name, fields)
                return True, self._handle_update(
                    user_id, ws_id, entity_name, fields, entities)
            logger.info("EntityManager[%s] → update '%s' but no fields",
                        user_id, entity_name)
            return True, (
                f"I understood you want to update {entity_name}, "
                f"but I couldn't tell what to change. "
                f"Try something like \"{entity_name} level is 70\"."
            )

        if intent == "retrieve":
            query = (data.get("query") or text).strip()
            logger.info("EntityManager[%s] → retrieve query='%s'", user_id, query)
            return True, self._handle_retrieve(user_id, ws_id, query)

        logger.info("EntityManager[%s] intent='%s' not recognised — falling through",
                     user_id, intent)
        return False, ""

    # ── Intent handlers ──────────────────────────────────────────────────────

    def _handle_create(self, user_id: int, ws_id: int,
                       name: str) -> str:
        """Create a new entity (milestone) in the workspace."""
        # Check for duplicates.
        existing = self._eng.list_milestones(user_id, ws_id)
        for m in existing:
            if m.title.lower() == name.lower():
                return (
                    f"There's already a {name} in this workspace. "
                    f"Want to update it instead?"
                )

        try:
            m = self._eng.add_milestone(user_id, ws_id, name)
        except EntityValidationError as e:
            return f"Couldn't create {name}: {e}"
        except EntityNotFound:
            return "I couldn't find that workspace. Open one first with /use."

        ws = self._eng.get_workspace_or_none(user_id, ws_id)
        icon = ws.icon if ws else "📁"
        return (
            f"{icon} Created **{name}** in your workspace!\n\n"
            f"You can now tell me things about {name}, like "
            f"\"{name} priority high\" or \"{name} is level 50\"."
        )

    def _handle_update(self, user_id: int, ws_id: int,
                       entity_name: str, fields: dict,
                       entities: list) -> str:
        """Update fields on an existing entity (milestone)."""
        # Find the entity by name (fuzzy match).
        target = self._find_entity(entity_name, entities)
        if target is None:
            # Offer to create it.
            return (
                f"I don't see an entity called \"{entity_name}\" in this "
                f"workspace. Want to create it first? "
                f"Say something like \"Create {entity_name}\"."
            )

        # Validate what we can before touching the engine.
        # Apply each field — unknown keys are allowed (forward-compat).
        results: list[str] = []
        for field_name, field_value in fields.items():
            try:
                self._eng.update_field(user_id, target.id, field_name, field_value)
                results.append(f"**{field_name}** → {field_value}")
            except EntityValidationError as e:
                results.append(f"**{field_name}**: {e}")
            except EntityNotFound:
                return "That entity seems to have disappeared."

        if not results:
            return f"Updated {entity_name} — no fields changed."

        return f"✅ Updated {entity_name}:\n" + "\n".join(f"  • {r}" for r in results)

    def _handle_retrieve(self, user_id: int, ws_id: int,
                         query: str) -> str:
        """Use the Cognitive Engine's recall to answer a retrieval question."""
        from core.ai.cognition import CognitiveEngine

        try:
            res = CognitiveEngine(engine=self._eng,
                                   storage=self._s).handle(
                user_id, query)
        except Exception:
            return "I had trouble looking that up. Try asking differently."

        if res.grounded:
            return res.answer
        # Fallback: list matching entity titles with field values.
        entities = self._eng.list_milestones(user_id, ws_id)
        if not entities:
            return "There are no entities yet in the active workspace."
        # If recall came up empty but we have entities, show a listing.
        parts = []
        for m in entities:
            label = f"  • {m.title} [{m.status}]"
            if m.fields:
                extra = ", ".join(
                    f"{k}={v}" for k, v in m.fields.items()
                    if v is not None and not isinstance(v, (dict, list)))
                if extra:
                    label += f" — {extra}"
            parts.append(label)
        return (
            f"I don't have a specific answer to that. "
            f"Here's what's in the workspace:\n" + "\n".join(parts)
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _build_prompt(self, text: str, ws_title: str, template_key: str,
                      field_info: str, entity_titles: list[str]) -> str:
        titles = ", ".join(entity_titles) if entity_titles else "(none yet)"
        return (
            f"Workspace: \"{ws_title}\" (template: {template_key})\n"
            f"Entity fields: {field_info}\n"
            f"Existing entities: {titles}\n"
            f"User: {text}\n"
            f"\nRespond with JSON intent classification."
        )

    @staticmethod
    def _field_info(template_key: str) -> str:
        specs = entity_field_specs(template_key)
        if not specs:
            return "(this workspace has no custom entity fields)"
        parts = []
        for s in specs:
            desc = s.name
            if s.kind == "enum":
                desc += f" (enum: {', '.join(s.choices)})"
            elif s.kind == "int":
                lo = f"≥{s.minimum}" if s.minimum is not None else ""
                hi = f"≤{s.maximum}" if s.maximum is not None else ""
                desc += f" (int {lo}{' ' if lo and hi else ''}{hi})".strip()
            else:
                desc += f" ({s.kind})"
            parts.append(desc)
        return "; ".join(parts)

    @staticmethod
    def _find_entity(name: str, entities: list) -> object | None:
        """Find an entity (milestone) by name: exact match first, then
        case-insensitive, then partial."""
        name = name.strip()
        if not name:
            return None
        # Exact.
        for m in entities:
            if m.title == name:
                return m
        # Case-insensitive.
        low = name.lower()
        for m in entities:
            if m.title.lower() == low:
                return m
        # Partial.
        for m in entities:
            if low in m.title.lower():
                return m
        return None
