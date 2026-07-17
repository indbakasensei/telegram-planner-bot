# Repository Cleanup Audit — v14.21 (Maintenance Sprint)

Classification of every potentially removable item, per the v14.21
brief. **Nothing was deleted in this audit** — no item satisfied all
five deletion criteria (auto-generated + gitignored + auto-recreated +
no user data + zero architectural value) *and* needed deleting from
the repository itself; regenerable local caches are handled by
`dev_reset.sh` on explicit developer execution instead.

Prior art: the v14.12 Production Readiness sprint already deleted the
known-dead code (`ai_helper.py`, `bot_state.py`, the six stranded
analytics files, `main.py.save`, `.env.save`, `"h origin main"`). This
audit covers what remains.

| Path | Category | Why it exists | Removal assessment | Risk if deleted | Recommendation |
|---|---|---|---|---|---|
| `__pycache__/` (all) | Generated at runtime | Python bytecode caches | Regenerated on next import; gitignored; no data | None | `dev_reset.sh` removes locally; never commit |
| `.pytest_cache/`, `.coverage` | Generated at runtime | pytest/coverage state | Regenerated; gitignored | None | `dev_reset.sh` |
| `debugbot.log`(+rotations) | Generated at runtime (v14.21) | Dedicated debug log | Recreated lazily; gitignored; may contain sanitized traces | None | `dev_reset.sh`; safe to delete any time |
| `bot.log` | Generated at runtime | **Production** log (sanitizer target) | Regenerated, gitignored — but it is the operational diagnostic record | Loses incident history | **Keep.** Retirement assessed (Task 4): NOT retired — it remains the INFO-level production record; debugbot.log supplements, never replaces |
| `bugs.db` | Generated at runtime | User bug reports + interaction traces | Contains USER DATA | Loses all bug reports | **Keep** — fails the no-user-data criterion |
| `planner.db` / `backups/` | Generated at runtime | Primary user database + pre-migration backups | USER DATA | Data loss | **Keep**, obviously |
| `bot.pid`, `admin_id.txt`, `.env` | Generated at runtime / user config | Instance lock, admin lock, secrets | Config/secrets | Lockout/secret loss | **Keep** |
| `.claude/settings.local.json` | Unknown (tracked tooling config) | Claude Code local permissions | Usually gitignored by convention, but tracked here — presumably intentional | None functional; noise in diffs | Leave tracked; owner may untrack at will |
| `AI_DIAGNOSTIC_REPORT.md`, `ENGINEERING_AUDIT.md`, `RC_v14_ARCHITECTURE_VALIDATION.md`, `DRG-001_Intent_Aware_Routing.md` | Historical | Point-in-time engineering records, cited by CHANGELOG/ADRs | Cross-referenced by living docs | Breaks documented history | **Keep** (brief: never remove historical documentation) |
| `AI_ROUTER.md`, `PLUGIN_SYSTEM.md`, `DESIGN_SPEC_v14_AUTONOMOUS_CORE.md`, `COMMAND_PIPELINE.md`, `DATA_FLOW.md`, `STATE_MACHINE.md`, `INTENT_ENGINE.md`, `OFFLINE_ENGINE.md` | Historical / forward specs | v14 design corpus; AI_ROUTER + PLUGIN_SYSTEM are v15 specs | Referenced by ADRs and ROADMAP | Loses design rationale | **Keep** |
| `VERSION.md` | Legacy (pointer) | Redirects to CHANGELOG.md (v-history move) | One-line pointer; inbound references may exist | Broken references | **Keep** (cheap, documented) |
| `TEST_CHECKLIST.md`, `feature_list.md` | Historical (pointer notices) | Superseded by TESTING.md/API.md; carry pointer notes by design | Deliberate pointers per the 2026-07 doc pass | Confusion for old links | **Keep** |
| `run.sh` | Unknown | Launch helper | Not referenced by docs reviewed; may be the owner's habit | Breaks owner's workflow | **Keep**; owner may confirm and delete |
| `main.py` — 40 pyflakes findings | Legacy (code, not files) | Stale imports accrued pre-v14 | Removal is a code change, not file cleanup | Low, but needs a code sprint | v15 hygiene item (tracked since the RC audit) |
| 91 `parse_mode="Markdown"` sites | Legacy (code) | Pre-v7.1 conversational replies | See DEBUGGING.md inventory (v14.20) | Per-flow verification needed | v15 item |

**Deletions performed this sprint: none.** Local regenerable caches are
the developer's explicit call via `./dev_reset.sh`.
