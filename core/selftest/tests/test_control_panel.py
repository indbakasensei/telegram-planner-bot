"""Self-tests: v15.3 M5 — Manual Control Plane (category AI).

Offline health probes for the Manual Control Plane (core/control/):
(1) the control registry builds without any Telegram projection and exposes
the M5 lifecycle tools with honest risk classification + confirmation gates;
(2) the control pages render over the live database (no-active state) and the
ONE shared M5-F confirm flow (core/control/actions) captures a pending action
that cancel_all clears without executing anything.

Both probes are read-only with respect to user data: no rows are created or
mutated under SELFTEST_USER_ID, so they leave no residue and are safe to
re-run against a live bot.
"""
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest

# The v15.3 M5 lifecycle tools the control plane adds (see
# V15_3_MANUAL_CONTROL_PLANE.md): thin wrappers over the SAME domain
# services the Worker uses -- never a second business-logic layer.
_M5_LIFECYCLE_TOOLS = frozenset({
    "create_workspace", "rename_workspace", "close_workspace",
    "archive_workspace", "delete_entity", "repair_topics", "equip_item",
})

_DESTRUCTIVE_M5 = frozenset({"archive_workspace", "delete_entity"})


@selftest(name="Manual Control Plane Registry", category="AI")
def check_control_registry():
    """The Manual Control Plane builds the SAME ToolRegistry the AI Worker
    uses (no second registry, no second logic layer). Offline (no projection
    wired) it must still expose every M5 lifecycle tool, with the destructive
    ones carrying the confirmation gate the Worker also honors."""
    from core.ai.tools import RiskLevel
    from core.control.registry import build_control_registry, build_context

    ctx = build_context(SELFTEST_USER_ID)   # no projection factory (offline)
    reg = build_control_registry(ctx)
    names = set(reg.names())
    missing = _M5_LIFECYCLE_TOOLS - names
    if missing:
        raise SelfTestFail(f"control tools missing: {sorted(missing)}")
    for name in sorted(_M5_LIFECYCLE_TOOLS):
        spec = reg.get(name).spec
        if spec.risk is RiskLevel.READ_ONLY:
            raise SelfTestFail(f"{name} misclassified as READ_ONLY")
    for name in sorted(_DESTRUCTIVE_M5):
        spec = reg.get(name).spec
        if spec.risk is not RiskLevel.DESTRUCTIVE:
            raise SelfTestFail(f"{name} not classified DESTRUCTIVE")
        if not spec.confirmation_message:
            raise SelfTestFail(f"{name} DESTRUCTIVE without confirmation message")
    if any(t.spec.risk is RiskLevel.SYSTEM for t in reg.all()):
        raise SelfTestFail("a control tool is classified SYSTEM")
    return (f"control registry ok · {len(names)} tools, offline-safe, "
            f"{len(_DESTRUCTIVE_M5)} destructive with confirmations")


@selftest(name="Manual Control Plane Pages + Confirm", category="AI")
def check_control_pages_confirm():
    """The control pages render over the live DB without a Telegram client,
    and the ONE shared M5-F confirm flow captures a pending action that
    cancel_all drops -- nothing executes, nothing is written."""
    from core.control import pages
    from core.control.actions import begin_confirm, cancel_all, pending_for
    from core.control.registry import build_context

    ctx = build_context(SELFTEST_USER_ID)
    # No-active state must render (and not raise) for the main pages.
    for render in (pages.control_home, pages.workspace_page, pages.topic_center,
                   pages.equip_home):
        text, kb = render(ctx)
        if not text or kb is None:
            raise SelfTestFail(f"{render.__name__} rendered empty")

    # M5-F: a destructive action captures a pending confirm (spec wording),
    # and cancel_all clears it without ever executing the tool.
    begin_confirm(ctx, "archive_workspace", {"workspace": 0},
                  return_to="ctl:ws:home")
    pending = pending_for(SELFTEST_USER_ID)
    if pending is None:
        raise SelfTestFail("begin_confirm did not capture a pending action")
    if "archive" not in pending.question.lower():
        raise SelfTestFail("confirm wording did not come from the tool spec")
    cancel_all(SELFTEST_USER_ID)
    if pending_for(SELFTEST_USER_ID) is not None:
        raise SelfTestFail("cancel_all did not clear the pending action")
    return "control pages render offline; M5-F confirm captured + cancelled"
