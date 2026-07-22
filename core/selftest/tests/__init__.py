"""
core.selftest.tests -- the registered self-test modules.

Every module here decorates one or more check functions with
@selftest(...). The runner auto-imports this package's modules
(runner.discover()), so a new test is added by dropping a file here --
nothing central is edited. Modules lazy-import their heavy dependencies
(database, baka_brain, scheduler, ui) INSIDE the check functions, so
merely discovering the tests stays cheap and import-safe.

pytest never collects these files: pytest.ini sets `testpaths = tests`
(the repo-root suite), and this is a proper package, so even a stray
`pytest core/` would import them under fully-qualified names without
basename collisions.
"""
