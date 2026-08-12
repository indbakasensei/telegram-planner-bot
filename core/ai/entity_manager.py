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
from core.workspace.render import format_entity_card, format_entity_update
from core.ai.reference_context import Referent, ReferenceContext
from core.ai.reference_resolver import (
    ENTITY_TYPE,
    ReferenceResolver,
    is_ordinal_phrase,
)
from fmt import esc

logger = logging.getLogger(__name__)

# Singleton cache for the default AI call (lazy, set once).
_DEFAULT_AI_CALL: Callable | None = None

# ── Deterministic single-field update extraction (M1 acceptance fix) ──────
# Patterns like "Sucrose is level 70" / "set her level to 90" are recognised
# WITHOUT the LLM so a cheap classifier can't misroute an update to
# `retrieve`. Field names come from the template specs, never hardcoded.
_UPDATE_LEAD_VERBS = re.compile(r"^(?:set|make|update|change|edit|put)\s+")
_UPDATE_LEAD_PRONOUNS = re.compile(
    r"^(?:he|him|his|she|her|hers|it|its|they|them|their|this|that)\s+")
_QUESTION_INTROS = ("what", "which", "how", "why", "when", "where", "who",
                    "whose")
# A captured value whose first token is one of these is almost certainly a
# question/aux/clause phrasing ("level is she", "level of the ..."), not a
# real field value — let the LLM decide those.
_UPDATE_BAD_VALUE_FIRST = frozenset({
    "does", "do", "did", "is", "are", "was", "were", "use", "using", "used",
    "he", "him", "his", "she", "her", "hers", "it", "its", "they", "them",
    "their", "i", "you", "we", "my", "your", "our",
    "of", "for", "from", "in", "on", "at", "as", "than", "about",
})

# ── v15.2 M4.x safety invariants ────────────────────────────────────────────
# 1. NOT_FOUND must NEVER fall back to the active entity for a mutation. A
#    message that LEADS with a create-intent verb and names an entity that is
#    not in the workspace is CREATE for a NEW entity ("Create Citlali and set
#    her level to 83" must create Citlali -- never "update Diona").
_CREATE_INTENT_LEAD = re.compile(r"^(?:create|make|new|add|introduce|start)\b",
                                 re.IGNORECASE)
# 2. Goal-domain vocabulary: a message carrying one of these is a GOAL/TASK
#    deadline operation. The goal domain OWNS deadlines; a workspace
#    character/weapon/artifact never does. Such a message must never be
#    classified as an entity field update ("Set its deadline to this month
#    end" → "Wolf's Gravestone target_level → 30", DEBUGGING.md F6/M4).
_GOAL_DEADLINE_SIGNALS = ("deadline", "due date")


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
                 ai_call: Callable | None = None,
                 resolver: ReferenceResolver | None = None,
                 ref_context: ReferenceContext | None = None):
        self._eng = engine or EntityEngine()
        self._s = storage or Storage()
        self._ai_call = ai_call or _default_ai
        # M1: reference resolution context is owned by this EntityManager so
        # tests get a fresh instance and production (one singleton) shares
        # one context across users, keyed by user_id.
        self._ref_ctx = ref_context or ReferenceContext()
        self._resolver = resolver or ReferenceResolver(
            storage=self._s, engine=self._eng, context=self._ref_ctx)

    # ── Public entry point ───────────────────────────────────────────────────

    def process(self, user_id: int, text: str,
                projection=None) -> tuple[bool, str]:
        """Interpret *text* as an entity-management command for the user's
        active workspace.

        ``projection`` is an optional injected duck-typed Telegram projection
        (default None). When present, a successful create/update ALSO projects
        to the entity's Telegram topic (initial card / append-only update).
        EntityManager itself stays Telegram-agnostic: it never imports a
        Telegram module -- the projection is a plain object supplied by the
        caller (main.py injects the live one; tests inject a fake), and a
        projection failure never fails the DB operation.

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

        # 3.  Resolve conversational references (M1) against the context just
        #     established: the DB-backed active entity + recent/ordered
        #     mentions. This runs BEFORE the keyword pre-check and the LLM so
        #     a resolved referent reaches the prompt and the handlers.
        resolved = self._resolver.resolve(user_id, text, ws_id, entities)
        if resolved.ambiguous:
            logger.info("EntityManager[%s] ambiguous reference — asking to clarify",
                        user_id)
            return True, self._clarify_message(resolved)
        if resolved.stale_active:
            logger.info("EntityManager[%s] active entity dangling — clearing",
                        user_id)
            self._s.tg_bindings.clear_active(user_id)
        active_entity = resolved.entity   # Milestone | None
        logger.debug("EntityManager[%s] reference resolution: kind=%s ref=%s",
                     user_id, resolved.kind,
                     active_entity.title if active_entity else None)

        # 3b. GOAL/TASK deadline guard (v15.2 M4.x): a message carrying
        #     deadline vocabulary is a goal/task operation -- the goal domain
        #     owns deadlines and a workspace character/weapon/artifact never
        #     does. Route it deterministically to the goal domain (or ask)
        #     and NEVER let it fall through to an entity field update (which
        #     previously wrote "Set its deadline…" to Wolf's Gravestone
        #     target_level). Runs BEFORE the pre-check so it is never
        #     swallowed by a classification pre-filter.
        if self._has_goal_deadline_signal(text):
            reply = self._goal_deadline_reply(user_id, text)
            logger.info("EntityManager[%s] goal-domain deadline → %s",
                        user_id, reply[:80])
            return True, reply

        # 4.  Quick keyword pre-check — bail early if nothing looks
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
        # A resolved referent that carries an entity signal (or is a bare
        # reference) is strong evidence of entity intent, even without a
        # keyword ("her", "the first one").
        if active_entity is not None and (resolved.has_signal
                                          or self._is_bare_reference(text)):
            has_active_keyword = True
        logger.debug("EntityManager[%s] pre-check: keyword=%s mentions_entity=%s",
                     user_id, has_active_keyword, mentions_entity)

        if not has_active_keyword and not mentions_entity:
            logger.info("EntityManager[%s] pre-check miss — falling through", user_id)
            return False, ""

        # 5.  A *bare* reference ("show her", "the first one") needs no LLM
        #     to decide the operation — resolve and show deterministically.
        if active_entity is not None and self._is_bare_reference(text):
            logger.info("EntityManager[%s] bare reference '%s' → direct retrieve %s",
                        user_id, text, active_entity.title)
            return True, self._handle_retrieve(
                user_id, ws_id, text, preferred=active_entity)

        # 5b. Deterministic single-field update extraction (M1 acceptance fix):
        #     "Sucrose is level 70", "<title> <field> is <value>",
        #     "<title>'s <field> is <value>", "set her <field> to <value>"
        #     are recognised without the LLM, so a cheap classifier
        #     misreading them as `retrieve` can no longer swallow an update.
        extracted = self._try_extract_update(text, entities, active_entity, ws)
        if extracted is not None:
            name, fields, used_active = extracted
            logger.info("EntityManager[%s] deterministic update '%s' fields=%s",
                        user_id, name, fields)
            return True, self._handle_update(
                user_id, ws_id, name, fields, entities,
                preferred=active_entity if used_active else None,
                projection=projection)

        # 6.  Classify via LLM.
        prompt = self._build_prompt(
            text, ws.title, ws.template, field_info, entity_titles,
            active_entity=active_entity)
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

        # 7.  Route to the appropriate handler.  A resolved referent wins over
        #     the LLM's entity_name (the referent is authoritative).
        if intent == "create" and entity_name:
            logger.info("EntityManager[%s] → create '%s'", user_id, entity_name)
            return True, self._handle_create(
                user_id, ws_id, entity_name, projection=projection)

        if intent == "update" and (entity_name or active_entity is not None):
            fields = data.get("fields")
            if isinstance(fields, dict) and fields:
                logger.info("EntityManager[%s] → update '%s' fields=%s",
                            user_id, entity_name or active_entity.title, fields)
                return True, self._handle_update(
                    user_id, ws_id, entity_name, fields, entities,
                    preferred=active_entity, projection=projection)
            target_name = entity_name or (active_entity.title if active_entity else "it")
            logger.info("EntityManager[%s] → update '%s' but no fields",
                        user_id, target_name)
            return True, (
                f"I understood you want to update {target_name}, "
                f"but I couldn't tell what to change. "
                f"Try something like \"{target_name} level is 70\"."
            )

        if intent == "retrieve":
            query = (data.get("query") or text).strip()
            logger.info("EntityManager[%s] → retrieve query='%s'", user_id, query)
            return True, self._handle_retrieve(
                user_id, ws_id, query, preferred=active_entity)

        logger.info("EntityManager[%s] intent='%s' not recognised — falling through",
                     user_id, intent)
        return False, ""

    # ── Intent handlers ──────────────────────────────────────────────────────

    # ── M1 reference-lifecycle helpers ──────────────────────────────────────

    def _activate_entity(self, user_id: int, ws_id: int, milestone) -> None:
        """Mark `milestone` as the active conversational entity (M1).

        Durable state lives in the DB-backed tg_active_context row (the same
        source of truth WorkspaceGroups uses); mention order is kept in the
        in-memory ReferenceContext. The last ordered list is intentionally
        KEPT: a single-entity focus does not invalidate it, so the user can
        navigate a just-shown list across ordinals ("the first one" → "the
        last one"). A later list-producing retrieve replaces it via
        `_note_list`; a deleted entity is re-validated against fresh data by
        the resolver, so a stale list can never resolve to a ghost.
        """
        self._s.tg_bindings.set_active(
            user_id, ws_id, ENTITY_TYPE, milestone.id)
        self._ref_ctx.note_mention(user_id, Referent(
            kind=ENTITY_TYPE, id=milestone.id, title=milestone.title,
            workspace_id=ws_id))

    def _note_list(self, user_id: int, ws_id: int, matched: list) -> None:
        """Remember an ordered list shown to the user (M1): both as the
        ordered context for "the first one" and as individual mentions so a
        later pronoun has candidates (and can be flagged as ambiguous)."""
        refs = [Referent(kind=ENTITY_TYPE, id=m.id, title=m.title,
                         workspace_id=ws_id)
                for m in matched]
        self._ref_ctx.note_ordered(user_id, refs)
        for r in refs:
            self._ref_ctx.note_mention(user_id, r)

    def _is_bare_reference(self, text: str) -> bool:
        """True when the message is essentially just a resolved reference —
        "show her", "the first one", "him" — so the operation (retrieve) can
        be decided deterministically without an LLM call (M1, requirement H)."""
        low = text.lower().strip()
        if is_ordinal_phrase(low):
            return True
        for verb in ("show", "display", "view", "see", "get"):
            if low == verb:
                return True
            if low.startswith(verb + " "):
                rest = low[len(verb) + 1:].strip()
                if rest in ("he", "him", "his", "she", "her", "hers",
                            "it", "its", "they", "them", "their",
                            "this", "that", "this one", "that one",
                            "the current one", "the current character",
                            "the current entity", "the one"):
                    return True
        return low in ("he", "him", "his", "she", "her", "hers",
                       "it", "its", "they", "them", "their",
                       "this", "that", "this one", "that one",
                       "the current one", "the current character",
                       "the current entity", "the one")

    @staticmethod
    def _has_goal_deadline_signal(text: str) -> bool:
        """True when `text` carries goal/task deadline vocabulary. Deadlines
        belong to the GOAL/TASK domain; no workspace entity (character /
        weapon / artifact) has one, so such a message must never be routed to
        an entity mutation (see _GOAL_DEADLINE_SIGNALS)."""
        low = (text or "").lower()
        return any(s in low for s in _GOAL_DEADLINE_SIGNALS)

    def _goal_deadline_reply(self, user_id: int, text: str) -> str:
        """Deterministically handle a goal/task deadline message in the LEGACY
        path (the Worker's update_goal_deadline tool is the primary path; this
        is the safe fallback when the Worker declined/fell through). Reuses
        the SAME GoalStorage facade the Worker tool uses -- no new data layer.

        Resolution order: explicit goal title in the text wins; a pronoun
        ("its", "it") or bare "the goal" resolves to the MOST RECENT goal.
        If no goal can be resolved confidently, ASK -- never touch another
        domain."""
        goals = list(self._s.goals.get_all_full(user_id))  # most recent first
        low = text.lower()
        # 1. Explicit goal title mentioned in the text (longest first so a
        #    longer goal name wins over a substring).
        gid = title = None
        for row in sorted(goals, key=lambda r: len(str(r[1])), reverse=True):
            t = str(row[1])
            if len(t) > 1 and t.lower() in low:
                gid, title = row[0], t
                break
        # 2. Pronoun / bare "the goal" → most recent goal.
        if gid is None and goals and any(
                w in low for w in ("its", "it", "the goal", "this goal",
                                   "my goal")):
            gid, title = goals[0][0], str(goals[0][1])
        if gid is None:
            if goals:
                names = ", ".join(f"<b>{esc(str(r[1]))}</b>" for r in goals[:4])
                return ("That looks like a goal/task deadline. Which goal do "
                        f"you mean? ({names}…) Say something like "
                        "<code>set the deadline of &lt;goal&gt; to &lt;date&gt;"
                        "</code>.")
            return ("That looks like a goal/task deadline, but I don't see "
                    "any goals yet. Create one first, e.g. "
                    '<code>add goal Read 5 Books</code>.')

        from date_parser import parse_all
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        date = parse_all(text, now).get("date")
        self._s.goals.update_deadline(gid, user_id, date)
        if date:
            return (f"✅ Set the deadline of <b>{esc(title)}</b> to "
                    f"<b>{esc(date)}</b>.")
        return f"✅ Cleared the deadline of <b>{esc(title)}</b>."

    def _try_extract_update(self, text: str, entities: list,
                            active_entity: object | None, ws) -> tuple | None:
        """Deterministically recognise a single-field update without the LLM.

        Handles "<title> is <field> <value>", "<title> <field> is <value>",
        "<title>'s <field> is <value>", "set <title> <field> to <value>", and
        the pronoun/possessive forms ("set her level to 90") resolved against
        the active entity. Template-agnostic: field names come from the
        active template's field specs and entity titles from the workspace.

        Returns (entity_name, {field: value}, used_active) — `used_active`
        True only when the target came from the active entity (pronoun form),
        so the caller passes it as the preferred referent. Returns None when
        the message isn't a clear deterministic update (questions, unknown
        fields, no target), letting the LLM handle it.
        """
        text = (text or "").strip()
        if not text or "?" in text:
            return None
        low = text.lower()

        # Target title: the longest known entity title present in the text
        # (explicit mention wins), else the active entity (pronoun form).
        used_active = False
        title = None
        for ent in sorted(entities, key=lambda e: len(e.title), reverse=True):
            if len(ent.title) > 2 and ent.title.lower() in low:
                title = ent.title
                break
        if title is None and active_entity is not None:
            if _CREATE_INTENT_LEAD.match(low):
                # NOT_FOUND ≠ ACTIVE (M4.x invariant): "Create Citlali and
                # set her level to 83" is CREATE for a NEW entity. Redirecting
                # the fresh name to the active entity (Diona) is exactly the
                # corruption this guard exists to forbid. Hand the message to
                # the LLM classify path, which produces a create.
                logger.info(
                    "EntityManager create-intent + fresh name → refusing "
                    "active-entity fallback for a mutation")
                return None
            title = active_entity.title
            used_active = True
        if title is None:
            return None

        # Remove the title (and a following possessive) once.
        rest = low.replace(title.lower() + "'s", " ", 1)
        if rest == low:
            rest = low.replace(title.lower(), " ", 1)
        rest = rest.strip()
        if not rest or rest.startswith(_QUESTION_INTROS):
            return None

        # Drop leading update verbs and (when active) pronouns that precede
        # the field name: "set her level to 90" → "level to 90".
        rest = _UPDATE_LEAD_VERBS.sub("", rest).strip()
        if active_entity is not None:
            rest = _UPDATE_LEAD_PRONOUNS.sub("", rest).strip()
        if not rest:
            return None

        # Match a field name (longest first so "target_level" wins over
        # "level"), allowing spaces/underscores between word parts. Two
        # shapes: a separator ("level 70", "level is 70", "level = 70") or a
        # value glued straight on ("level70" — the digit lookahead keeps it
        # from matching inside "leveling").
        specs = entity_field_specs(ws.template) if ws else ()
        for fname in sorted({s.name for s in specs}, key=len, reverse=True):
            base = r"\b" + r"[\s_]*".join(re.escape(p) for p in fname.split("_"))
            m = re.search(
                base + r"\b\s+(?:(?:is|to|at)\s+|=|:)?(.+)$", rest)
            if not m:
                m = re.search(base + r"(?=\d)(.+)$", rest)
            if not m:
                continue
            value = m.group(1).strip()
            # A value can't be empty, a question, or an aux/pronoun tail
            # ("level is she" → "she" is not a value).
            if not value or value.split()[0].lower() in _UPDATE_BAD_VALUE_FIRST:
                continue
            # Single-field update: cut trailing co-ordinates ("70 and
            # priority high" → "70"). Multi-field is M2's job.
            value = re.split(
                r"\s+(?:and|or|but|with|then|also)\s+", value, maxsplit=1)[0]
            value = value.rstrip(".,!;")
            if value:
                return title, {fname: value}, used_active
        return None

    @staticmethod
    def _clarify_message(resolved) -> str:
        """Ask which entity the user meant (requirement G: never guess when
        several candidates could match)."""
        lines = ["🤔 I found a few possibilities — which one do you mean?"]
        for i, r in enumerate(resolved.candidates, 1):
            name = r.title or f"{r.kind} #{r.id}"
            lines.append(f"{i}. {esc(name)}")
        lines.append("Just name it, e.g. <i>\"show Furina\"</i>.")
        return "\n".join(lines)

    def _handle_create(self, user_id: int, ws_id: int,
                       name: str, projection=None) -> str:
        """Create a new entity (milestone) in the workspace.

        When a projection is injected, the entity's Telegram topic is ensured
        through the SAME contract WorkspaceGroups uses
        (ensure_entity_topic with the entity's current card as the initial
        message) -- so NL creation and /add can never diverge. A projection
        failure is logged and surfaced as a warning note; the DB entity is
        never lost and never rolled back."""
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

        # M1: a successful NL creation establishes the active conversational
        # entity (so "show her" right after resolves to it).
        self._activate_entity(user_id, ws_id, m)

        # alpha.13: project the new entity to its Telegram topic via the same
        # single contract WorkspaceGroups uses. Best-effort: the entity is
        # already safely stored; a topic failure is logged + reported, and
        # /topicbackfill can repair it later.
        topic_note = ""
        if projection is not None:
            try:
                topic_id = projection.ensure_entity_topic(
                    user_id, ws_id, ENTITY_TYPE, m.id, m.title,
                    initial_message=format_entity_card(
                        m, with_timestamp=True))
                topic_note = (
                    " · topic created"
                    if topic_id
                    else " · (link a group with /linkhere for a topic)")
            except Exception:
                logger.exception(
                    "EntityManager[%s] topic creation failed for '%s'",
                    user_id, name)
                topic_note = (
                    " · ⚠️ Telegram topic NOT created "
                    "(repair with /topicbackfill)")

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
            f"{topic_note}"
        )

    def _handle_update(self, user_id: int, ws_id: int,
                       entity_name: str, fields: dict,
                       entities: list,
                       preferred: object | None = None,
                       projection=None) -> str:
        """Update fields on an existing entity (milestone).

        `preferred` is an M1 resolved referent (Milestone): when the user
        referred to the entity by pronoun/ordinal, the referent is
        authoritative and wins over the LLM's entity_name.

        When a projection is injected, a successful update appends a
        minimal activity message to the entity's Telegram topic (previous
        value shown only when it was safely read from the pre-update DB
        state -- never invented). Append-only: old messages are untouched.
        A projection failure is logged; the DB update stands.
        """
        # M1: a resolved referent (pronoun/ordinal) is authoritative, but an
        # EXPLICIT entity name in the message wins over any active referent —
        # "set Xiao's level to 85" updates Xiao, never the active entity; and
        # a not-found explicit name NEVER falls back to the active entity
        # (NOT_FOUND ≠ ACTIVE, M4.x invariant).
        target = (self._find_entity(entity_name, entities)
                  if entity_name else None)
        # Only an EMPTY entity_name (pure pronoun/ordinal form) may fall back
        # to the active referent. An explicit-but-not-found name must NEVER
        # resolve to the active entity (NOT_FOUND ≠ ACTIVE, M4.x invariant):
        # "Create Citlali and set her level to 83" classified as an update
        # on "Citlali" must not write level 83 onto the active Diona.
        if target is None and not entity_name:
            target = preferred
        if target is None:
            logger.info("EntityManager[%s] update '%s' → entity not found",
                        user_id, entity_name)
            if entity_name:
                return (
                    f"I don't see an entity called <b>{esc(entity_name)}</b> "
                    f"in this workspace. Want to create it first? "
                    f"Say something like <code>Create {esc(entity_name)}"
                    f"</code>."
                )
            return ("I couldn't tell which entity to update. Say its name, "
                    'e.g. <code>Xiao level is 85</code> or '
                    '<code>set Xiao level to 85</code>.')

        logger.info("EntityManager[%s] update entity id=%s '%s' fields=%s",
                    user_id, target.id, target.title, fields)

        # M4.x: record the resolution into the shared trace so `/diag` shows
        # "Requested: X → Resolved: Y" even for the legacy (non-Worker) path
        # where the historical "Citlali → Diona" corruption happened.
        try:
            from core.ai.resolution_trace import get_resolution_trace
            get_resolution_trace().record(
                user_id=user_id, workspace_id=ws_id, action="update",
                requested=entity_name or "(pronoun/active)",
                kind=target.entity_type or "entity",
                resolution="FOUND",
                fallback="REFERENT" if (not entity_name and preferred
                                        and preferred.id == target.id) else "EXACT",
                entity_title=target.title, entity_id=target.id)
        except Exception:
            logger.debug("resolution-trace record failed", exc_info=True)

        # Apply each field — unknown keys are allowed (forward-compat).
        # Capture the PRE-update DB state for the projection's change list;
        # a field absent from the stored entity is None (→ shown as "set").
        old_values = {k: target.fields.get(k) for k in fields}
        applied: dict = {}
        results: list[str] = []
        last_updated = None   # the freshest post-update milestone (for cards)
        for field_name, field_value in fields.items():
            try:
                last_updated = self._eng.update_field(
                    user_id, target.id, field_name, field_value)
                logger.info("EntityManager[%s] set %s.%s = %s",
                            user_id, target.title, field_name, field_value)
                applied[field_name] = field_value
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

        # M1: a successful update keeps the entity as the active referent.
        self._activate_entity(user_id, ws_id, target)

        # alpha.13: append a minimal update message to the entity's Telegram
        # topic. Old values come ONLY from the pre-update DB read above; the
        # topic is self-healed (created + CURRENT initial card) if it never
        # existed -- `last_updated` is the fresh post-update milestone, so the
        # card never shows a stale field. Best-effort: a projection failure is
        # logged, the DB update stands.
        if projection is not None and applied:
            try:
                changes = {f: (old_values.get(f), v) for f, v in applied.items()}
                card_target = last_updated if last_updated is not None else target
                projection.post_entity_update(
                    user_id, ws_id, ENTITY_TYPE, target.id, target.title,
                    format_entity_update(card_target, changes),
                    initial_message=format_entity_card(
                        card_target, with_timestamp=True))
            except Exception:
                logger.exception(
                    "EntityManager[%s] topic update post failed for '%s'",
                    user_id, entity_name)

        reply = f"✅ Updated <b>{esc(entity_name)}</b>:\n" + "\n".join(f"  • {r}" for r in results)
        logger.info("EntityManager[%s] update '%s' reply: %s", user_id, entity_name, reply[:100])
        return reply

    def _handle_retrieve(self, user_id: int, ws_id: int,
                         query: str,
                         preferred: object | None = None) -> str:
        """Retrieve entities by name, field filter, or broad recall.

        `preferred` is an M1 resolved referent (Milestone): a resolved
        pronoun/ordinal reference means the user wants THAT entity, so it
        wins over name matching and is shown directly.
        """
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

        # 1b. M1: a resolved referent is shown directly (and becomes active).
        if preferred is not None:
            logger.info("EntityManager[%s] retrieve → resolved referent '%s' (id=%s)",
                        user_id, preferred.title, preferred.id)
            self._activate_entity(user_id, ws_id, preferred)
            return self._format_entity_card(preferred)

        # 2.  Try to show a specific entity by name.
        #     Use the full original text so embedded names like "Show Furina" match.
        entity = self._find_entity(query, entities)
        if entity:
            logger.info("EntityManager[%s] retrieve → single entity '%s' (id=%s)",
                        user_id, entity.title, entity.id)
            self._activate_entity(user_id, ws_id, entity)
            return self._format_entity_card(entity)

        # 3.  Filter entities by field values matching the query tokens.
        ws = self._eng.get_workspace_or_none(user_id, ws_id)
        specs = entity_field_specs(ws.template) if ws else ()
        filtered = self._filter_entities_by_query(query, entities, specs)
        if filtered is not None:
            logger.info("EntityManager[%s] retrieve → %d filtered results out of %d entities",
                        user_id, len(filtered), len(entities))
            # M1: remember this ordered list so "the first one"/"the last one"
            # resolve against it.
            self._note_list(user_id, ws_id, filtered)
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
                # M1: the broad-recall path can also *show* the entity list
                # ("show all characters" → list_entities tool). Record that
                # ordered list so "the first one"/"the last one" resolve
                # against it, exactly like the filter / fallback branches.
                if any(step.tool == "list_entities" for step in res.plan.steps):
                    self._note_list(user_id, ws_id, entities)
                return res.answer
        except Exception:
            logger.warning("EntityManager[%s] CognitiveEngine failed", user_id, exc_info=True)

        # 5.  Ultimate fallback — show all entities.
        logger.info("EntityManager[%s] retrieve → no filter match, showing full list", user_id)
        self._note_list(user_id, ws_id, entities)
        return self._format_entity_list(entities, entities, query, ws)

    # ── Retrieval helpers ──────────────────────────────────────────────────

    def _format_entity_card(self, entity) -> str:
        """Format a single entity with all its fields as a clean card.

        Delegates to the shared renderer (core/workspace/render.py) so the
        chat reply and the Telegram topic's initial card can never diverge."""
        logger.info("EntityManager formatted card for '%s'",
                    entity.title)
        return format_entity_card(entity)

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
                      field_info: str, entity_titles: list[str],
                      active_entity: object | None = None) -> str:
        titles = ", ".join(entity_titles) if entity_titles else "(none yet)"
        active_line = ""
        if active_entity is not None:
            active_line = (
                f"Active entity: {active_entity.title} (id={active_entity.id})\n"
                "If the user refers to the active entity with a pronoun "
                "(he/she/him/her/it/this/that/one) or as \"the current one\", "
                "treat the active entity as the target entity.\n"
            )
        return (
            f"Workspace: \"{ws_title}\" (template: {template_key})\n"
            f"{active_line}"
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
