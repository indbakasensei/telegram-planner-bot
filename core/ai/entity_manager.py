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
from fmt import esc

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
- If the user wants to RETRIEVE/FIND/SHOW entities OR a specific entity, set
  intent to "retrieve" and query to their full question. Set entity_name to the
  entity's name if one is specifically named, otherwise leave it empty.
- If the message is NOT about entity management, set intent to "none".

Response format:
{"intent": "create|update|retrieve|none", "entity_name": "", "fields": {}, "query": ""}

Example - Create:
  Input:  "Create character Furina"
  Output: {"intent": "create", "entity_name": "Furina", "fields": {}, "query": ""}

Example - Create:
  Input:  "Add a new entity called Hu Tao"
  Output: {"intent": "create", "entity_name": "Hu Tao", "fields": {}, "query": ""}

Example - Update single field:
  Input:  "Furina is level 90"
  Output: {"intent": "update", "entity_name": "Furina", "fields": {"level": 90}, "query": ""}

Example - Update multiple fields:
  Input:  "Hu Tao reached level 80 and has high priority"
  Output: {"intent": "update", "entity_name": "Hu Tao", "fields": {"level": 80, "priority": "high"}, "query": ""}

Example - Update with weapon:
  Input:  "Furina uses Fleuve Cendre Ferryman"
  Output: {"intent": "update", "entity_name": "Furina", "fields": {"weapon": "Fleuve Cendre Ferryman"}, "query": ""}

Example - Update with weapon type:
  Input:  "Xiao uses a polearm"
  Output: {"intent": "update", "entity_name": "Xiao", "fields": {"weapon_type": "Polearm"}, "query": ""}

Example - Update via "is now" / "got":
  Input:  "Furina is now level 91"
  Output: {"intent": "update", "entity_name": "Furina", "fields": {"level": 91}, "query": ""}
  Input:  "Hu Tao finally got to level 90"
  Output: {"intent": "update", "entity_name": "Hu Tao", "fields": {"level": 90}, "query": ""}

Example - Retrieve specific entity:
  Input:  "Show Furina"
  Output: {"intent": "retrieve", "entity_name": "Furina", "fields": {}, "query": "Show Furina"}

Example - Retrieve by field value:
  Input:  "Show all level 90 characters"
  Output: {"intent": "retrieve", "entity_name": "", "fields": {}, "query": "Show all level 90 characters"}

Example - Retrieve filtered:
  Input:  "Who is level 90?"
  Output: {"intent": "retrieve", "entity_name": "", "fields": {}, "query": "Who is level 90?"}

Example - Retrieve by element:
  Input:  "Show Hydro characters"
  Output: {"intent": "retrieve", "entity_name": "", "fields": {}, "query": "Show Hydro characters"}

Example - Retrieve by weapon:
  Input:  "Who uses Fleuve Cendre Ferryman?"
  Output: {"intent": "retrieve", "entity_name": "", "fields": {}, "query": "Who uses Fleuve Cendre Ferryman?"}

Example - Retrieve by weapon type:
  Input:  "Show everyone using a sword"
  Output: {"intent": "retrieve", "entity_name": "", "fields": {}, "query": "Show everyone using a sword"}

Example - Retrieve by priority:
  Input:  "Show all high priority characters"
  Output: {"intent": "retrieve", "entity_name": "", "fields": {}, "query": "Show all high priority characters"}

Example - View / Open entity:
  Input:  "Open Furina"
  Output: {"intent": "retrieve", "entity_name": "Furina", "fields": {}, "query": "Open Furina"}
  Input:  "View Furina"
  Output: {"intent": "retrieve", "entity_name": "Furina", "fields": {}, "query": "View Furina"}
  Input:  "Display Furina"
  Output: {"intent": "retrieve", "entity_name": "Furina", "fields": {}, "query": "Display Furina"}

Example - Plural:
  Input:  "List all characters"
  Output: {"intent": "retrieve", "entity_name": "", "fields": {}, "query": "List all characters"}

Example - None (not entity management):
  Input:  "What's the weather today?"
  Output: {"intent": "none", "entity_name": "", "fields": {}, "query": ""}
  Input:  "Tell me a joke"
  Output: {"intent": "none", "entity_name": "", "fields": {}, "query": ""}
  Input:  "Remind me to buy groceries"
  Output: {"intent": "none", "entity_name": "", "fields": {}, "query": ""}
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
                logger.info("EntityManager[%s] create '%s' — duplicate exists", user_id, name)
                return (
                    f"There's already a <b>{esc(name)}</b> in this workspace. "
                    f"Want to update it instead?"
                )

        try:
            m = self._eng.add_milestone(user_id, ws_id, name)
            logger.info("EntityManager[%s] created milestone id=%s '%s'",
                        user_id, m.id, name)
        except EntityValidationError as e:
            logger.warning("EntityManager[%s] create '%s' failed: %s", user_id, name, e)
            return f"Couldn't create <b>{esc(name)}</b>: {e}"
        except EntityNotFound:
            logger.warning("EntityManager[%s] workspace %s not found for create", user_id, ws_id)
            return "I couldn't find that workspace. Open one first with /use."

        ws = self._eng.get_workspace_or_none(user_id, ws_id)
        icon = ws.icon if ws else "📁"

        # Get field names for the template to suggest what can be updated.
        field_names = [s.name for s in entity_field_specs(ws.template)] if ws else []
        suggestion = ""
        if field_names:
            examples = [f"{name} {fn} ..." for fn in field_names[:3]]
            suggestion = (
                f"\n\nYou can set its fields, like: "
                f"<code>{esc(examples[0])}</code>"
            )

        logger.info("EntityManager[%s] create '%s' → success", user_id, name)
        return (
            f"{icon} Created <b>{esc(name)}</b> in your workspace!"
            f"{suggestion}"
        )

    def _handle_update(self, user_id: int, ws_id: int,
                       entity_name: str, fields: dict,
                       entities: list) -> str:
        """Update fields on an existing entity (milestone)."""
        # Find the entity by name (fuzzy match).
        target = self._find_entity(entity_name, entities)
        if target is None:
            logger.info("EntityManager[%s] update '%s' → entity not found", user_id, entity_name)
            return (
                f"I don't see an entity called <b>{esc(entity_name)}</b> in this "
                f"workspace. Want to create it first? "
                f"Say something like <code>Create {esc(entity_name)}</code>."
            )

        logger.info("EntityManager[%s] update entity id=%s '%s' fields=%s",
                    user_id, target.id, target.title, fields)

        # Apply each field — unknown keys are allowed (forward-compat).
        results: list[str] = []
        for field_name, field_value in fields.items():
            try:
                self._eng.update_field(user_id, target.id, field_name, field_value)
                logger.info("EntityManager[%s] set %s.%s = %s",
                            user_id, target.title, field_name, field_value)
                results.append(f"<b>{esc(field_name)}</b> → {esc(str(field_value))}")
            except EntityValidationError as e:
                logger.warning("EntityManager[%s] set %s.%s failed: %s",
                               user_id, target.title, field_name, e)
                results.append(f"<b>{esc(field_name)}</b>: {esc(str(e))}")
            except EntityNotFound:
                logger.warning("EntityManager[%s] entity %s disappeared during update",
                               user_id, target.id)
                return "That entity seems to have disappeared."

        if not results:
            logger.info("EntityManager[%s] update '%s' — no fields changed", user_id, entity_name)
            return f"Updated <b>{esc(entity_name)}</b> — no fields changed."

        reply = f"✅ Updated <b>{esc(entity_name)}</b>:\n" + "\n".join(f"  • {r}" for r in results)
        logger.info("EntityManager[%s] update '%s' reply: %s", user_id, entity_name, reply[:100])
        return reply

    def _handle_retrieve(self, user_id: int, ws_id: int,
                         query: str) -> str:
        """Retrieve entities by name, field filter, or broad recall."""
        logger.info("EntityManager[%s] retrieve query='%s'", user_id, query)

        # 1.  Fetch all entities from the DB (always fresh — Requirement 5).
        try:
            entities = self._eng.list_milestones(user_id, ws_id)
            logger.info("EntityManager[%s] fetched %d entities from DB",
                        user_id, len(entities))
        except Exception:
            logger.exception("EntityManager[%s] failed to list milestones", user_id)
            return "I had trouble reading your workspace. Try again?"

        if not entities:
            logger.info("EntityManager[%s] retrieve — no entities in workspace", user_id)
            return "Your workspace doesn't have any entities yet."

        # 2.  Try to show a specific entity by name.
        #     Use the full original text so embedded names like "Show Furina" match.
        entity = self._find_entity(query, entities)
        if entity:
            logger.info("EntityManager[%s] retrieve → single entity '%s' (id=%s)",
                        user_id, entity.title, entity.id)
            return self._format_entity_card(entity)

        # 3.  Filter entities by field values matching the query tokens.
        ws = self._eng.get_workspace_or_none(user_id, ws_id)
        specs = entity_field_specs(ws.template) if ws else ()
        filtered = self._filter_entities_by_query(query, entities, specs)
        if filtered is not None:
            logger.info("EntityManager[%s] retrieve → %d filtered results out of %d entities",
                        user_id, len(filtered), len(entities))
            return self._format_entity_list(filtered, entities, query, ws)

        # 4.  Fallback: try CognitiveEngine for broad recall.
        logger.info("EntityManager[%s] retrieve → trying CognitiveEngine recall", user_id)
        try:
            from core.ai.cognition import CognitiveEngine
            res = CognitiveEngine(engine=self._eng,
                                   storage=self._s).handle(user_id, query)
            if res.grounded:
                logger.info("EntityManager[%s] retrieve → CognitiveEngine grounded: %s",
                            user_id, res.answer[:80])
                return res.answer
        except Exception:
            logger.warning("EntityManager[%s] CognitiveEngine failed", user_id, exc_info=True)

        # 5.  Ultimate fallback — show all entities.
        logger.info("EntityManager[%s] retrieve → no filter match, showing full list", user_id)
        return self._format_entity_list(entities, entities, query, ws)

    # ── Retrieval helpers ──────────────────────────────────────────────────

    def _format_entity_card(self, entity) -> str:
        """Format a single entity with all its fields as a clean card."""
        title = entity.title
        status = entity.status.replace("_", " ").title()

        lines = [f"<b>{esc(title)}</b>\n📌 Status: {status}"]

        # Add structured fields if present.
        if entity.fields:
            for fname, fvalue in entity.fields.items():
                if fvalue is None or isinstance(fvalue, (dict, list)):
                    continue
                display_name = fname.replace("_", " ").title()
                lines.append(f"{display_name}: {esc(str(fvalue))}")

        logger.info("EntityManager formatted card for '%s' (%d lines)",
                    title, len(lines))
        return "\n".join(lines)

    def _format_entity_list(self, matched: list, all_entities: list,
                            query: str, ws) -> str:
        """Format a list of entities with their key field values."""
        if not matched:
            ws_icon = ws.icon if ws else "📁"
            return (
                f"{ws_icon} No entities match that description in "
                f"<b>{esc(ws.title if ws else 'workspace')}</b>."
            )

        # Build a compact listing: title [status] — key field values.
        lines = [self._list_header(matched, ws)]
        template_specs = entity_field_specs(ws.template) if ws else ()
        for entity in matched:
            label = f"  • <b>{esc(entity.title)}</b> [{entity.status}]"
            if entity.fields:
                extras = []
                for fname, fvalue in entity.fields.items():
                    if fvalue is None or isinstance(fvalue, (dict, list)):
                        continue
                    extras.append(f"{fname}={fvalue}")
                if extras:
                    label += f" — {', '.join(extras)}"
            lines.append(label)

        if len(matched) < len(all_entities):
            remaining = len(all_entities) - len(matched)
            lines.append(f"\n<i>({remaining} other entit{'y' if remaining==1 else 'ies'} not shown)</i>")

        return "\n".join(lines)

    @staticmethod
    def _list_header(matched: list, ws) -> str:
        """Build the header line for a filtered entity list."""
        ws_icon = ws.icon if ws else "📁"
        ws_title = ws.title if ws else "Workspace"
        count = len(matched)
        entity_word = "entit" + ("y" if count == 1 else "ies")
        return f"{ws_icon} <b>{count} {entity_word}</b> in <b>{esc(ws_title)}</b>:"

    def _filter_entities_by_query(self, query: str, entities: list,
                                  specs: tuple) -> list | None:
        """Filter entities whose field values match query tokens.

        Returns:
            A filtered list of entities (may be empty), or *None* if the
            query doesn't look like a field-filter query at all (so the
            caller should try another strategy).
        """
        low_q = query.lower()
        q_tokens = self._query_tokens(low_q)
        if not q_tokens:
            return None

        # Build a map of field name → value hints for matching.
        # For enum fields, pre-compute their choices as a set for fast lookup.
        enum_choices: dict[str, frozenset[str]] = {}
        field_names: set[str] = set()
        for s in specs:
            field_names.add(s.name)
            if s.kind == "enum":
                enum_choices[s.name] = frozenset(c.lower() for c in s.choices)
            elif s.kind == "int":
                # Store that this field accepts numeric values.
                pass

        has_any_match = False
        scored: list[tuple[object, int]] = []

        for entity in entities:
            if not entity.fields:
                continue
            score = 0
            matched_something = False

            for fname, fvalue in entity.fields.items():
                if fvalue is None or isinstance(fvalue, (dict, list)):
                    continue
                fstr = str(fvalue).lower()
                fname_low = fname.lower()

                # Strong match: field value appears verbatim in query
                # (e.g. query contains "Hydro" and entity has element=Hydro).
                if len(fstr) > 1 and fstr in low_q:
                    score += 3
                    matched_something = True
                    continue

                # Token overlap: any query token matches any token in the value
                # (e.g. query "uses Fleuve Cendre Ferryman" matches entity weapon).
                f_tokens = self._query_tokens(fstr)
                overlap = q_tokens & f_tokens
                if overlap:
                    score += len(overlap)
                    matched_something = True
                    continue


            if matched_something:
                has_any_match = True
                scored.append((entity, score))

        if not has_any_match:
            # No scoring at all — return None to signal "try another strategy"
            logger.debug("EntityManager _filter: no field matches found in query '%s'", query)
            return None

        # Sort by score descending.
        scored.sort(key=lambda x: -x[1])
        logger.debug("EntityManager _filter: %d entities matched query '%s'",
                     len(scored), query)
        return [e for e, _ in scored]

    @staticmethod
    def _query_tokens(text: str) -> set[str]:
        """Split text into lowercase alphanumeric tokens, ignoring short words."""
        tokens = set(re.findall(r"[a-z0-9']+", text))
        # Filter out very short tokens and common stop words.
        stop = frozenset({
            "a", "an", "the", "of", "to", "in", "on", "for", "and", "or",
            "is", "are", "was", "were", "be", "been", "what", "when", "where",
            "who", "which", "why", "how", "do", "does", "did", "my", "your",
            "me", "i", "you", "it", "its", "this", "that", "about", "tell",
            "show", "find", "search", "have", "has", "had", "can", "could",
            "would", "should", "any", "all", "with", "at", "as", "but", "not",
            "no", "so", "if", "up", "out", "use", "get", "got", "just",
            "now", "then", "than", "too", "very", "also", "using", "everyone",
            "every", "character", "characters", "entity", "entities",
        })
        return {t for t in tokens if len(t) > 1 and t not in stop}

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
        case-insensitive, then entity-title-in-query (reverse partial),
        then partial."""
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
        # Reverse partial — entity title is a substring of query
        # (handles "Show Furina", "Open Furina", etc.)
        for m in entities:
            t = m.title.lower()
            if t and len(t) > 1 and t in low:
                return m
        # Partial — query is a substring of entity title.
        for m in entities:
            if low in m.title.lower():
                return m
        return None
