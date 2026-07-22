"""
core.regression.suites -- the authored regression test specs.

Each module registers RegressionTest specs for a feature cluster via
register(...). core.regression.discover() auto-imports them. A new
feature adds its tests by editing/adding a module here -- nothing
central changes (the growing-forever model, QA_SYSTEM_DESIGN Part 1).

This milestone authors the Quick Release Suite only (tests tagged
Suite.QUICK). MAJOR/FULL tests are added in later milestones.

Not collected by pytest: pytest.ini sets `testpaths = tests`, and this
is a proper package (no test_*.py basenames).
"""
