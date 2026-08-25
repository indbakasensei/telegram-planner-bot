"""Self-tests: database health (category Database)."""
from core.selftest.models import SelfTestFail
from core.selftest.registry import selftest


@selftest(name="Database Connection", category="Database")
def check_database_connection():
    """Open a connection and confirm the schema is intact (all required
    tables/indexes present). Uses the runner's temporary database on the local
    filesystem to avoid WSL network share locking issues."""
    import database as db

    # The runner's _setup_temp_db() has already created a temp DB and patched
    # db.DB_NAME before discover() runs. Just verify schema integrity.
    report = db.verify_schema_integrity()
    if not report.get("ok"):
        missing = report.get("missing_tables", []) + report.get("missing_indexes", [])
        raise SelfTestFail("schema integrity check failed",
                           details=f"missing: {missing}")
    return (f"schema ok · v{report.get('schema_version')} · "
            f"journal={report.get('journal_mode')}")
