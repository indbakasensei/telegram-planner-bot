"""Self-tests: dashboard render (category Dashboard).

Pure render sanity -- no data mutation. Feeds synthetic data to the
real ui.dashboard_card() builder and confirms it produces a
non-trivial message plus a keyboard whose callbacks are intact.
"""
from core.selftest.models import SelfTestFail
from core.selftest.registry import selftest


@selftest(name="Dashboard Render", category="Dashboard")
def check_dashboard_render():
    import ui
    data = {"date_str": "selftest", "today_count": 1, "overdue": 0,
            "pending": 1, "done_today": 0, "goals": [], "habits": [],
            "completion_rate": 0.5}
    text, keyboard = ui.dashboard_card(data)
    if not text or "DASHBOARD" not in text.upper():
        raise SelfTestFail("dashboard text missing or malformed")
    cbs = {b.callback_data for row in keyboard.inline_keyboard for b in row}
    if "dash:home" not in cbs:
        raise SelfTestFail("dashboard keyboard missing dash:home", details=str(cbs))
    return f"rendered · {len(cbs)} buttons"
