"""
rules.py -- deterministic, tiered classification rules for the Intent
Engine (docs/adr/ADR-002-intent-engine.md: rule-based, not ML-based).

Each tier function takes plain text (plus `now` where needed) and
returns either None (no match) or a 5-tuple:

    (Intent, confidence, entities, reasoning, tier)

Priority order (per the v14.0 Stage 1 brief), and what each reuses:

  0. Existing parser signals   -- main.py's slashless command tables
  1. Existing date parser      -- date_parser.parse_all(): date/time
  2. Existing scheduler keywords -- date_parser.parse_all(): recurrence
  3. Regex                     -- new: greeting/help/small-talk patterns
                                   not covered by 0-2
  4. Keyword heuristics        -- new: weak single-keyword fallback
  5. Unknown fallback          -- handled by IntentEngine, not here

Tier 0 duplication, explained: main.py's `_starts_with_handlers` and
`_exact_handlers` (handle_message(), main.py:1049-1165) are local
variables inside a function, not importable, and main.py cannot be
imported from this package without pulling in python-telegram-bot and
this app's full dependency graph (and would be circular besides, since
main.py imports this package for Shadow Mode). The tables below are a
deliberately hand-maintained mirror of that real routing data, verified
against main.py at the time this was written -- not guessed. Keeping
them in sync when main.py's command tables change is accepted technical
debt (see Risk Assessment in the deliverables report), not solved here.

Tiers 1-2 are genuine reuse, not duplication: date_parser.py has no
Telegram/database/AI dependencies of its own, so its functions are
imported and called directly.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from date_parser import parse_all

from core.intent.entities import entities_from_parsed_date, extract_numeric_id
from core.intent.intent_types import Intent

RuleMatch = tuple[Intent, float, dict[str, Any], str, int]


# ── Tier 0: mirrors main.py's _starts_with_handlers (prefix, handler, args) ──
# Trimmed to (prefixes, Intent) -- Shadow Mode only observes, so no handler
# reference is needed. Mapping choices for commands that don't map cleanly
# onto the brief's 11-value Intent enum (e.g. "report "/"resolve " are
# diagnostic, not task CRUD) are noted inline.
_PREFIX_COMMANDS: list[tuple[list[str], Intent]] = [
    (["plan today", "plan my day", "today's plan", "schedule my day",
      "make a plan", "what should i do today"], Intent.CHAT),
    (["plan week", "plan my week", "weekly plan", "week ahead",
      "plan this week"], Intent.CHAT),
    (["breakdown ", "break down ", "split task ", "subtasks for "], Intent.CHAT),
    (["reschedule ", "move task ", "shift task "], Intent.EDIT_TASK),
    (["snooze "], Intent.EDIT_TASK),
    (["pause "], Intent.EDIT_TASK),
    (["resume "], Intent.EDIT_TASK),
    (["tag "], Intent.EDIT_TASK),
    (["tagged ", "tasks with tag "], Intent.QUERY_TASK),
    (["stopreminder ", "stop reminder ", "stop reminders for "], Intent.EDIT_TASK),
    (["delreminder ", "delete reminder "], Intent.DELETE_TASK),
    (["done ", "complete task ", "finish task ", "mark done "], Intent.EDIT_TASK),
    (["delete ", "remove ", "del "], Intent.DELETE_TASK),
    (["edit "], Intent.EDIT_TASK),
    (["report ", "bug "], Intent.SETTINGS),          # diagnostic/meta, closest fit
    (["resolve "], Intent.SETTINGS),                  # diagnostic/meta, closest fit
    (["forget ", "delete memory ", "remove memory ",
      "delete remembered ", "remove remembered "], Intent.DELETE_TASK),
    (["quiethours ", "quiet hours ", "set quiet "], Intent.SETTINGS),
    (["interval ", "reminder interval ", "set interval "], Intent.SETTINGS),
    (["suggest "], Intent.CHAT),
    (["search ", "find ", "look for "], Intent.QUERY_TASK),
    (["think ", "ask ", "what should i ", "should i ",
      "help me decide", "what do you think", "your opinion"], Intent.CHAT),
    (["image ", "generate image", "create image", "draw "], Intent.MEDIA),
    (["need ", "materials ", "add materials", "components ",
      "add components", "i need "], Intent.ADD_TASK),
    (["got ", "have ", "acquired ", "purchased ", "bought "], Intent.EDIT_TASK),
    (["worklog ", "log ", "note ", "progress on ", "update on "], Intent.ADD_TASK),
    (["started ", "starting ", "begin work on ", "starting work on "], Intent.EDIT_TASK),
    (["finished ", "completed ", "done with ", "finished the ", "khatam "], Intent.EDIT_TASK),
    (["project ", "how is my ", "status of ", "how is the "], Intent.QUERY_TASK),
    (["video ", "generate video", "create video", "make a video"], Intent.MEDIA),
    (["savetemplate ", "save template "], Intent.SETTINGS),
    (["template ", "use template "], Intent.ADD_TASK),
    (["streak "], Intent.QUERY_TASK),
    (["habitlog ", "habit log "], Intent.EDIT_TASK),
    (["addhabit ", "add habit ", "new habit "], Intent.ADD_TASK),
    (["skiphabit ", "skip habit ", "reset streak "], Intent.EDIT_TASK),
]

# ── Tier 0: mirrors main.py's _exact_handlers (full-message phrase -> handler) ──
_EXACT_COMMANDS: list[tuple[tuple[str, ...], Intent]] = [
    (("list", "my tasks", "show tasks", "all tasks", "show all"), Intent.QUERY_TASK),
    (("today", "today's tasks", "show today", "what's today",
      "what do i have today", "schedule today"), Intent.QUERY_TASK),
    (("week", "this week", "weekly", "show week", "what's this week"), Intent.QUERY_TASK),
    (("status", "api status", "check status", "is api working",
      "is the bot online", "health check"), Intent.SETTINGS),
    (("settings", "my settings", "view settings", "show settings"), Intent.SETTINGS),
    (("debug", "toggle debug", "turn on debug", "enable debug",
      "debug mode on", "turn off debug", "disable debug", "debug mode off"), Intent.SETTINGS),
    (("bugs", "show bugs", "list bugs", "view bugs", "what bugs", "open bugs"), Intent.SETTINGS),
    (("trace", "trace this", "what did you understand",
      "what was my last message"), Intent.SETTINGS),
    (("selftest", "self test", "run tests", "run self test", "test"), Intent.SETTINGS),
    (("overdue", "show overdue", "my overdue", "what is overdue",
      "what's overdue"), Intent.QUERY_TASK),
    (("deadlines", "show deadlines", "my deadlines", "what deadlines",
      "upcoming deadlines"), Intent.QUERY_TASK),
    (("memory", "show memory", "show memories", "my memories",
      "what do you remember"), Intent.QUERY_TASK),
    (("paused", "show paused", "paused tasks"), Intent.QUERY_TASK),
    (("overload", "am i overloaded", "show overload",
      "load check", "busy days"), Intent.QUERY_TASK),
    (("habits", "show habits", "my habits", "list habits"), Intent.QUERY_TASK),
    (("dashboard", "home", "show dashboard", "open dashboard",
      "main menu", "overview"), Intent.QUERY_TASK),
    (("goals", "my goals", "show goals", "goal dashboard"), Intent.QUERY_TASK),
    (("stats", "statistics", "productivity dashboard",
      "my stats", "show stats"), Intent.QUERY_TASK),
    (("insights", "what have you learned", "my patterns",
      "learned behavior", "what do you know about me"), Intent.QUERY_TASK),
    (("review", "review tasks", "stale tasks", "what needs review",
      "old tasks"), Intent.QUERY_TASK),
    (("carryforward", "carry forward", "move overdue to today"), Intent.EDIT_TASK),
    (("analyze", "analyse", "analyze me", "productivity",
      "how productive", "analyse productivity"), Intent.CHAT),
    (("help", "show help", "what can you do", "help me",
      "guide me", "commands"), Intent.HELP),
    (("cancel", "stop", "nevermind", "never mind", "abort"), Intent.CHAT),
    (("checktasks", "check tasks", "diagnose tasks", "task diagnostics"), Intent.QUERY_TASK),
    (("templates", "my templates", "show templates", "list templates"), Intent.QUERY_TASK),
    (("projects", "my projects", "show projects",
      "list projects", "active projects"), Intent.QUERY_TASK),
    (("shopping", "shopping list", "my shopping list",
      "what do i need to buy", "buy list"), Intent.QUERY_TASK),
    (("export", "export data", "backup", "export my data"), Intent.FILE),
    (("deadline mode", "what is deadline mode",
      "deadline help", "deadlines"), Intent.HELP),
    (("suggestions", "my suggestions", "ai suggestions",
      "what do you suggest", "show suggestions"), Intent.QUERY_TASK),
]


def tier0_command_match(text: str) -> RuleMatch | None:
    """Mirrors main.py's slashless command table (handle_message())."""
    low = text.strip().lower()
    if not low:
        return None

    for prefixes, intent in _PREFIX_COMMANDS:
        for prefix in prefixes:
            if low.startswith(prefix):
                entities: dict[str, Any] = {}
                task_id = extract_numeric_id(text[len(prefix):])
                if task_id is not None:
                    entities["task_id"] = task_id
                return (intent, 1.0, entities,
                        f"Tier 0: matched command prefix '{prefix.strip()}'", 0)

    for phrases, intent in _EXACT_COMMANDS:
        if low in phrases:
            return (intent, 1.0, {}, f"Tier 0: matched exact command phrase '{low}'", 0)

    return None


def tier_date_and_recurrence(text: str, now: datetime | None) -> RuleMatch | None:
    """
    Tiers 1 (date/time) and 2 (recurrence keywords), evaluated from a
    single date_parser.parse_all() call -- both signals come from that
    one pure function, so calling it twice would be wasted work for no
    behavioural difference. Which conceptual tier fired is still
    reported distinctly via the returned tier number.
    """
    parsed = parse_all(text, now)
    entities = entities_from_parsed_date(parsed)

    has_date_or_time = bool(parsed["date"] or parsed["time"])
    has_recurrence = bool(parsed["recurrence"])

    if not has_date_or_time and not has_recurrence:
        return None

    if has_date_or_time:
        resolved = sum(1 for k in ("date", "time") if parsed[k])
        confidence = 0.95 if resolved == 2 else 0.75
        reasoning = ("Tier 1: date parser resolved date and time"
                     if resolved == 2 else
                     "Tier 1: date parser resolved a date or time")
        return Intent.ADD_TASK, confidence, entities, reasoning, 1

    # Recurrence only, no explicit date/time -- e.g. "remind me daily to drink water".
    return (Intent.ADD_TASK, 0.7, entities,
            "Tier 2: date parser matched a recurring-schedule keyword", 2)


# ── Tier 3: regex for phrasing date_parser.py doesn't cover (greetings/help/small talk) ──
_GREETING_RE = re.compile(
    r"^\s*(hi+|hello+|hey+|yo|namaste|good\s*(morning|afternoon|evening|night))\s*[!.,]*\s*$",
    re.IGNORECASE,
)
_HELP_RE = re.compile(
    r"\b(help|what can you do|how (do|does) (this|it) work|guide me)\b",
    re.IGNORECASE,
)
_SMALLTALK_RE = re.compile(
    r"^\s*(how are you|what'?s up|sup|thanks|thank you|thx|lol|haha|ok(ay)?|nice|cool|great)\s*[!.,]*\s*$",
    re.IGNORECASE,
)


def tier3_anchored_smalltalk(text: str) -> RuleMatch | None:
    """
    Greeting/small-talk only, matched against the *whole* message
    (`^...$`). Deliberately evaluated by IntentEngine before Tier 1/2:
    a plain "good morning" was, before this split existed, misclassified
    as ADD_TASK (confidence 0.95) because date_parser.py resolves the
    vague-time word "morning" to a default clock time, and parse_all()'s
    own past-time-rolls-to-tomorrow logic then filled in a date too. That
    is correct, intentional behaviour for "remind me in the morning" --
    it is wrong when "morning" is the tail end of a greeting and nothing
    else in the message suggests scheduling anything. Since these
    patterns only ever match when the ENTIRE input is just a greeting or
    small talk, they carry more certainty than an incidental partial
    date/time hit and are safe to prefer over it -- this is the same
    "flat priority is fragile, make specificity explicit" lesson
    docs/adr/ADR-002-intent-engine.md already draws from date_parser.py's
    own "noon"-inside-"afternoon" bug, applied here to this package's
    own tiering instead of reimplemented independently.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if _GREETING_RE.match(stripped):
        return Intent.GREETING, 0.9, {}, "Tier 3: matched greeting pattern", 3
    if _SMALLTALK_RE.match(stripped):
        return Intent.CHAT, 0.6, {}, "Tier 3: matched small-talk pattern", 3
    return None


def tier3_help(text: str) -> RuleMatch | None:
    """Help phrasing, unanchored -- may appear inside a longer sentence."""
    stripped = text.strip()
    if not stripped:
        return None
    if _HELP_RE.search(stripped):
        return Intent.HELP, 0.85, {}, "Tier 3: matched help-request pattern", 3
    return None


# ── Tier 4: weak, single-keyword fallback -- checked most-specific first ──
_DELETE_KEYWORDS = re.compile(r"\b(delete|remove|cancel|scrap|drop)\b", re.IGNORECASE)
_EDIT_KEYWORDS = re.compile(r"\b(change|update|modify|reschedule|move|edit)\b", re.IGNORECASE)
_ADD_KEYWORDS = re.compile(
    r"\b(remind|remember|add|note down|don'?t forget|need to|have to|gotta)\b",
    re.IGNORECASE,
)
_QUERY_KEYWORDS = re.compile(r"\b(what|show|list|when is|do i have)\b", re.IGNORECASE)


def tier4_keyword_heuristics(text: str) -> RuleMatch | None:
    low = text.lower()
    if _DELETE_KEYWORDS.search(low):
        return Intent.DELETE_TASK, 0.45, {}, "Tier 4: weak keyword match for deletion", 4
    if _EDIT_KEYWORDS.search(low):
        return Intent.EDIT_TASK, 0.4, {}, "Tier 4: weak keyword match for an edit", 4
    if _ADD_KEYWORDS.search(low):
        return Intent.ADD_TASK, 0.4, {}, "Tier 4: weak keyword match for task creation", 4
    if _QUERY_KEYWORDS.search(low):
        return Intent.QUERY_TASK, 0.35, {}, "Tier 4: weak keyword match for a query", 4
    return None
