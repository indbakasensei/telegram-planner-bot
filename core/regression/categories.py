"""
categories.py -- the fixed set of regression categories (v14.23,
QA Phase 1). One source of truth for category names, used by the
registry to validate every registered test's `category`.

The 23 categories are from QA_SYSTEM_DESIGN.md Part 4. New categories
are added HERE first (a deliberate speed-bump so category names stay
consistent as the suite grows).
"""

CATEGORIES: tuple[str, ...] = (
    "Core",
    "Tasks",
    "Reminders",
    "Scheduler",
    "Dashboard",
    "Habits",
    "Goals",
    "Projects",
    "Memory",
    "AI",
    "Vision",
    "Media",
    "Search/Files",
    "Notifications",
    "Settings",
    "Developer",
    "Admin",
    "Debug",
    "Routing",
    "Offline Engine",
    "Intent Engine",
    "Performance",
    "Security",
    "Documentation",
    # v15.1: Workspace groups (Telegram photo-journal) + Cognitive Engine.
    "Workspace Groups",
)

_CATEGORY_SET = frozenset(CATEGORIES)


def is_valid_category(name: str) -> bool:
    return name in _CATEGORY_SET
