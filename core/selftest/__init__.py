"""
core.selftest -- BAKA's admin-only runtime Self-Test framework (v14.22).

A registration-based regression runner that verifies BAKA's major
features still work in a LIVE process (real DB, scheduler, engines, AI
provider) -- complementary to the offline pytest suite, not a
replacement. Accessed by admins only, from the Debug Menu's
"🧪 Self Test" button (main.py). See DEBUGGING.md's "Self-Test
framework" section and docs/selftest.md.

Public surface:
  run()                -- discover + execute + aggregate -> SelfTestReport
  registered_tests()   -- introspection (what's registered)
  categories()         -- the category grouping for the UI
  selftest(...)        -- the registration decorator (for test authors)
  SelfTestReport / SelfTestResult / Status  -- the result contract
"""
from core.selftest.models import (
    SELFTEST_USER_ID, SelfTestFail, SelfTestResult, SelfTestSkip,
    SelfTestWarning, Status,
)
from core.selftest.registry import (
    categories, registered_tests, selftest,
)
from core.selftest.results import SelfTestReport
from core.selftest.runner import discover, run

__all__ = [
    "run", "discover", "registered_tests", "categories", "selftest",
    "SelfTestReport", "SelfTestResult", "Status",
    "SelfTestFail", "SelfTestWarning", "SelfTestSkip", "SELFTEST_USER_ID",
]
