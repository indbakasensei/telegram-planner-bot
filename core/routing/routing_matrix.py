"""
routing_matrix.py -- static routing data for the Routing Layer.

Deliberately separated from confidence.py's decision *logic*: per
DRG-001 Section 11's closing note, keeping destination-assignment DATA
(this module) distinct from decision CODE (confidence.py) is what lets
Stage 2's migration progress become a data change (flip a set membership
here) rather than a structural code change, one command group at a time.
"""
from __future__ import annotations

from enum import Enum, auto

from core.intent.intent_types import Intent


class WriteClass(Enum):
    """
    Per-intent risk class, mirroring INTENT_ENGINE.md's already-approved
    per-intent-class confidence thresholds (read-only / reversible-write /
    destructive-write) plus a fourth class for intents that are AI-shaped
    by definition regardless of confidence (DRG-001 Section 6's table).
    """

    READ_ONLY = auto()
    REVERSIBLE_WRITE = auto()
    DESTRUCTIVE_WRITE = auto()
    ALWAYS_AI = auto()


# Grounded in core/intent/intent_types.py's shipped Intent enum (11 values)
# and DRG-001 Section 7's Routing Matrix. GREETING/HELP/SETTINGS/FILE are
# read/lookup-shaped in practice today (main.py's real handlers for these
# are non-AI, static/structured responses) -- classified READ_ONLY for the
# same "wrong guess costs nothing" reasoning INTENT_ENGINE.md gives for
# QUERY_TASK. UNKNOWN is ALWAYS_AI per INTENT_ENGINE.md's explicit rule:
# "No match at all... always routes to AI Router."
INTENT_WRITE_CLASS: dict[Intent, WriteClass] = {
    Intent.QUERY_TASK: WriteClass.READ_ONLY,
    Intent.GREETING: WriteClass.READ_ONLY,
    Intent.HELP: WriteClass.READ_ONLY,
    Intent.SETTINGS: WriteClass.READ_ONLY,
    Intent.FILE: WriteClass.READ_ONLY,
    Intent.ADD_TASK: WriteClass.REVERSIBLE_WRITE,
    Intent.EDIT_TASK: WriteClass.REVERSIBLE_WRITE,
    Intent.DELETE_TASK: WriteClass.DESTRUCTIVE_WRITE,
    Intent.CHAT: WriteClass.ALWAYS_AI,
    Intent.MEDIA: WriteClass.ALWAYS_AI,
    Intent.UNKNOWN: WriteClass.ALWAYS_AI,
}

# INTENT_ENGINE.md's approved per-intent-class thresholds (0.0-1.0 scale,
# matching IntentResult.confidence -- not a separately-scaled number, see
# DRG-001 Section 6's explicit reasoning against a second confidence scale).
OFFLINE_THRESHOLD: dict[WriteClass, float] = {
    WriteClass.READ_ONLY: 0.6,
    WriteClass.REVERSIBLE_WRITE: 0.75,
    WriteClass.DESTRUCTIVE_WRITE: 0.95,
}

# Below this, a classification carries too little deterministic signal to
# recommend even a clarifying re-prompt over a write-class intent -- escalate
# straight to AI Router instead (INTENT_ENGINE.md's confidence bands: the
# 0.3-0.59 "weak keyword-only" band and below).
CLARIFY_BAND_LOW = 0.6

# DRG-001 Section 6, point 2: ambiguity is a first-class gate, independent
# of confidence. Above this, cap at LEGACY regardless of how high raw
# confidence is. Provisional -- DRG-001 Open Question 3 flags the exact
# value as needing revisiting once real ambiguity-distribution data exists.
AMBIGUITY_CAP = 0.5

# Which intents the Offline Engine currently implements. Empty: Stage 2
# (OFFLINE_ENGINE.md) has not started -- this sprint (v14.1B) is Routing
# Layer infrastructure only, per this task's explicit "DO NOT implement
# Offline Engine" constraint. Growing this set, one command group at a
# time as OFFLINE_ENGINE.md's own migration order lands, is the only code
# change Stage 2's progress requires in this module -- see DRG-001 Section
# 7's closing note and Section 11's "Future scalability."
OFFLINE_ENGINE_IMPLEMENTED_INTENTS: frozenset[Intent] = frozenset()
