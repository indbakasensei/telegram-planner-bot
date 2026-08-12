"""Self-tests: v15.2 M4.x — entity-resolution trace + /diag surface (category AI).

The ResolutionTrace (core/ai/resolution_trace.py) is the "find WHY the wrong
entity was updated" instrument: every entity resolution decision (Worker tool
adapters AND the legacy EntityManager) records a non-secret entry, and the
admin `/diag` command renders it as "Requested: X → Resolved: Y".

Probes:
  1. "Resolution trace records + renders" — a fresh trace returns newest-first
     and the UI.diagnostics_card renders each decision with no secret fields.
  2. "Resolution trace wired into entity tools" — a create_entity call through
     the real registry records a trace entry (proving the adapter records),
     and a not-found update records resolution=NOT_FOUND (the invariant: it
     must never fall back to the active entity for a mutation).

Both are fully offline and clean up their workspace in finally blocks.
"""
import database as db
from core.ai.resolution_trace import ResolutionTrace
from core.ai.tool_adapters import build_tool_registry
from core.selftest.models import SELFTEST_USER_ID, SelfTestFail
from core.selftest.registry import selftest
from core.workspace.engine import EntityEngine


@selftest(name="Resolution trace records + renders", category="AI")
def check_resolution_trace_records_renders():
    """A fresh trace stores newest-first and the /diag card renders it with
    no secret material."""
    from ui import diagnostics_card
    t = ResolutionTrace()
    t.record(user_id=SELFTEST_USER_ID, workspace_id=1, action="create",
             requested="Citlali", kind="character",
             resolution="NOT_FOUND", fallback="NONE")
    t.record(user_id=SELFTEST_USER_ID, workspace_id=1, action="update",
             requested="Citlali", kind="character",
             resolution="FOUND", fallback="EXACT",
             entity_title="Citlali", entity_id=7)
    entries = t.recent(SELFTEST_USER_ID)
    if len(entries) != 2 or entries[0].action != "update":
        raise SelfTestFail(f"expected newest-first 2 entries, got {entries}")
    text, _ = diagnostics_card(entries)
    for needle in ("Requested: Citlali", "Resolved:", "Citlali",
                   "NOT_FOUND", "fallback=NONE"):
        if needle not in text:
            raise SelfTestFail(f"/diag card missing {needle!r}")
    for secret in ("BOT_TOKEN", "AI_API_KEY", "NVIDIA_API_KEY", "token"):
        if secret.lower() in text.lower():
            raise SelfTestFail(f"/diag card leaked {secret!r}")


@selftest(name="Resolution trace wired into entity tools", category="AI")
def check_resolution_trace_wired():
    """create_entity records a trace entry; an update on a not-found name
    records resolution=NOT_FOUND and NEVER touches the active entity."""
    eng = EntityEngine()
    ws = eng.create_workspace(SELFTEST_USER_ID, "[selftest] diag",
                              template="game", seed_milestones=False)
    try:
        db.tg_set_active(SELFTEST_USER_ID, ws.id)
        reg = build_tool_registry(SELFTEST_USER_ID, engine=eng)

        r = reg.execute("create_entity", {"name": "Citlali"})
        if not r.ok:
            raise SelfTestFail(f"create_entity failed: {r.output}")

        from core.ai.resolution_trace import get_resolution_trace
        get_resolution_trace().clear(SELFTEST_USER_ID)
        reg.execute("create_entity", {"name": "Citlali"})   # duplicate → EXISTS
        miss = reg.execute("update_entity",
                           {"entity": "NoSuchEntity",
                            "fields": {"level": 90}})
        entries = get_resolution_trace().recent(SELFTEST_USER_ID)
        resolutions = {e.action: e.resolution for e in entries}
        if resolutions.get("create") != "EXISTS":
            raise SelfTestFail(f"create should record EXISTS, got {resolutions}")
        if resolutions.get("update") != "NOT_FOUND":
            raise SelfTestFail(f"not-found update should record NOT_FOUND, "
                               f"got {resolutions}")
        if miss.ok or "no entity matches" not in miss.output:
            raise SelfTestFail("not-found update must error, never create/mutate")
    finally:
        db.delete_workspace(ws.id, SELFTEST_USER_ID)
        db.tg_clear_active(SELFTEST_USER_ID)
