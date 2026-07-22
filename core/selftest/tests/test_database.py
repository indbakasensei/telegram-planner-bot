"""Self-tests: database health (category Database)."""
from core.selftest.models import SelfTestFail
from core.selftest.registry import selftest


@selftest(name="Database Connection", category="Database")
def check_database_connection():
    """Open a connection and confirm the schema is intact (all required
    tables/indexes present). Read-only."""
    import database as db
    report = db.verify_schema_integrity()
    if not report.get("ok"):
        missing = report.get("missing_tables", []) + report.get("missing_indexes", [])
        raise SelfTestFail("schema integrity check failed",
                           details=f"missing: {missing}")
    return (f"schema ok · v{report.get('schema_version')} · "
            f"journal={report.get('journal_mode')}")
