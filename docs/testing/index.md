# BAKA Bot — Testing Guide

This document consolidates all testing workflows for the BAKA bot.

---

## 1. Offline Test Suite (pytest)

The automated test suite runs entirely offline — no Telegram, no network calls, no external services.

### Running Tests

```bash
# From project root with venv activated
source venv3/bin/activate
pytest tests/ -v

# Run specific test modules
pytest tests/behavior/test_habit_behavior.py -v
pytest tests/behavior/test_habit_snapshot.py -v
pytest tests/behavior/test_callback_behavior.py -v

# Run characterization/regression suites
pytest tests/behavior/ -v  # All 132 Phase 4 tests
```

### Test Categories

| Category | Location | Tests | Description |
|----------|----------|-------|-------------|
| **Phase 4A: Habit Characterization** | `tests/behavior/test_habit_behavior.py` | 37 | Freeze current habit behavior as baseline |
| **Phase 4B: Snapshot Regression** | `tests/behavior/test_habit_snapshot.py` | 37 | Golden-file snapshots of habit flows |
| **Phase 4C: Callback Regression** | `tests/behavior/test_callback_behavior.py` | 58 | All 20+ callback actions verified |
| **Self-Test Framework** | `tests/test_selftest_framework.py` | 14 | Runner, registration, UI probes |
| **Workspace Self-Test** | `tests/test_workspace_selftest.py` | 7 | Template, engine, groups, retrieval |
| **Tool Contract/Adapters** | `tests/test_tool_contract.py` | 79 | M2 contract + 24 M3 adapters |
| **Worker** | `tests/test_worker.py` + `test_worker_parser.py` | 61 | Bounded executor, parser |
| **M5 Control Plane** | `tests/test_control_panel.py` | 38 | Manual dashboard, lifecycle |
| **M5 Adversarial** | `tests/test_m5_adversarial.py` | 41 | 14-scenario matrix |
| **M6 Knowledge/Media** | `tests/test_m6_knowledge.py` | 35 | Notes, media, tags |
| **M6 Adversarial** | `tests/test_m6_adversarial.py` | 21 | Edge cases |
| **M7 Retrieval** | `tests/test_m7_retrieval.py` | 73 | Cross-reference search |

**Total offline tests: 1631+ passing**

### Test Infrastructure

- **Database isolation**: `temp_db` fixture (monkeypatches `DB_NAME` to temp SQLite per test)
- **IST timezone**: All tests use `date_parser._now()` = `datetime.now(IST)`
- **Storage Facade**: Tests use `database.py` facade — no raw SQL
- **Mock fixtures**: Comprehensive `Update`/`Context` mocks in `tests/conftest.py`

---

## 2. Self-Test Framework (Runtime Health)

Admin-only runtime health checks reachable via `/debug` → 🧪 Self Test.

```bash
# Run all self-tests
python run_selftest_all.py

# Run AI category only
python run_selftest_ai.py
```

### Self-Test Categories

| Category | Probes | Description |
|----------|--------|-------------|
| **AI** | 17 | Retrieval service, tool registry, control plane, worker |
| **Workspace** | 7 | Template, engine, groups, cognitive, retrieval |
| **Core** | 14 | Framework registration, runner, discovery |

**Output**: `Passed: N, Failed: 0, Warnings: M, Skipped: 0`

---

## 3. Regression Test Specs (Manual Behaviour)

Authored specs in `core/regression/suites/` for manual verification:

| Suite | Tests | Status |
|-------|-------|--------|
| `retrieval_m7.py` (RET-001…038) | 38 | Documented |
| `control_m5.py` (CTRL-001…010) | 10 | Documented |
| `knowledge_m6.py` (KNOW-001…012) | 12 | Documented |
| `topic_projection_m13.py` (TOP-001…009) | 9 | Documented |

See [docs/regression.md](../regression.md) for the regression system design.

---

## 4. Live Telegram Acceptance Testing (Playwright)

**Phase 4D** — Real Telegram Web automation against QA bot (`Baka_qa_bot`).

### Prerequisites

1. QA Telegram account (NOT personal account)
2. Bot running: `python start_bot.py` (or `python main.py`)
3. Playwright installed: `cd testing/playwright && npm install`
4. Chromium persistent profile at `testing/playwright/profile/`

### Test Suite Structure

```
testing/playwright/
├── playwright.config.ts      # Config: workers=1, fullyParallel=false
├── tests/
│   ├── 00_bootstrap_login.spec.ts  # Login Telegram Web, save session
│   ├── 01_start.spec.ts          # /start command execution
│   └── 02_commands.spec.ts       # /help, /tasks commands
├── profile/                    # Persistent Chromium profile (session state)
├── screenshots/                # Test screenshots
├── traces/                     # Playwright traces on failure
└── reports/                    # HTML reports
```

### Running Tests

```bash
cd testing/playwright

# Run all tests (sequential, no parallel)
npx playwright test

# Run specific test
npx playwright test 01_start.spec.ts

# View HTML report
npx playwright show-report ../reports/html
```

### Configuration Highlights

```typescript
// playwright.config.ts
export default defineConfig({
  testDir: './tests',
  timeout: 360000,
  fullyParallel: false,  // Critical: prevents profile reuse conflicts
  workers: 1,            // Single worker for session persistence
  use: {
    browserName: 'chromium',
    headless: false,     // Must be false for Telegram Web login
    viewport: null,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
});
```

### Test Design Principles

1. **No new browser contexts** — reuse persistent profile for session
2. **Multiple selector fallbacks** — Telegram Web UI changes frequently
3. **Wait for visibility** — `waitFor({ state: 'visible', timeout: 30000 })` before interactions
4. **Crash/close handlers** — `page.on('crash')`, `page.on('close')` for debugging
5. **IST-aware** — Bot uses IST; tests account for timezone in assertions

### Screenshots

Captured on each test:
- `screenshots/start-command.png` — `/start` response
- `screenshots/help-command.png` — `/help` response
- `screenshots/tasks-command.png` — `/tasks` response

### Debugging

```bash
# Run with headed mode (default)
npx playwright test --headed

# Debug with Playwright Inspector
npx playwright test --debug

# View trace on failure
npx playwright show-trace traces/<trace-file>.zip
```

---

## 5. CI/CD Integration (Future)

Current state: **Manual only**. All test layers are run locally by owner.

| Layer | Automation | Notes |
|-------|------------|-------|
| Pytest | Manual | `pytest tests/` |
| Self-Test | Manual | `/selftest` in live bot or `python run_selftest_all.py` |
| Regression Specs | Manual | Owner runs documented checklists |
| Playwright | Manual | Requires live bot + QA Telegram account |

---

## 6. Quick Reference

```bash
# Full offline validation
pytest tests/behavior/ -v                    # 132 Phase 4 tests
pytest tests/ -v --ignore=tests/test_worker* # All except openai-dependent

# Runtime health
python run_selftest_all.py                   # 38 passed, 0 failed

# Live acceptance
cd testing/playwright && npx playwright test # 3/3 tests

# Check bot is running
pgrep -f main.py
```

---

## 7. Key Files

| File | Purpose |
|------|---------|
| `pytest.ini` | Pytest config (asyncio, paths) |
| `testing/playwright/playwright.config.ts` | Playwright config |
| `testing/playwright/tests/*.spec.ts` | Live acceptance tests |
| `core/selftest/runner.py` | Self-test runner |
| `core/selftest/tests/*.py` | Self-test probes |
| `core/regression/suites/*.py` | Manual regression specs |
| `docs/regression.md` | Regression system design |
| `docs/selftest.md` | Self-test framework design |