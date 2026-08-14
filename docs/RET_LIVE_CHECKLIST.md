# M7 Cross-Reference Retrieval — Live Test Checklist

**Version:** v15.5.0-alpha.1+fix1
**Date:** 2026-08-14
**Status:** Ready for owner execution

This checklist maps every RET-001…038 regression test to exact Telegram inputs, expected results, and PASS conditions. The owner performs these tests against a live bot.

---

## Test Data Setup

Before running these tests, ensure the following test data exists in your database:

### Workspace A (Genshin — typically WS1)
- **Entities:** M7_Ace_Test, M7_TenZ_Test, M7_1v4_Test, M7_1v3_Test
- **Tags:** M7_1v4_Test, M7_1v3_Test
- **Notes:** At least one note linked to Ace + 1v4 entity, tagged with 1v4 tag
- **Media:** At least one video linked to Ace + 1v4 entity, tagged with 1v4 tag

### Workspace B (Valorant — typically WS8)
- **Entities:** M7_Ace_Test, M7_1v4_Test (identical names to WS_A)
- **Tags:** M7_1v4_Test
- **Notes/Media:** At least one item linked to WS_B's Ace entity

---

## RET-001…038 Live Test Matrix

### M7-A: Unified Cross-Reference Search

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-001** | `/control` → **Search** → Query: `test` → **🔍 Search** | Results show both notes and media. Each row has a type badge (`[note]` or `[media]`) | Both types appear; no fabrication |
| **RET-002** | `/control` → **Search** → Scope: `Notes` → Query: `test` → **🔍 Search** | Only notes returned (all have `[note]` badge) | Zero media in results |
| **RET-003** | `/control` → **Search** → Scope: `Media` → Query: `test` → **🔍 Search** | Only media returned (all have `[media]` badge) | Zero notes in results |

### M7-B: Entity Filter AND/OR Semantics

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-004** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test, M7_1v4_Test` → **🔀 AND/OR**: `and and` → **🔍 Search** | Only items linked to BOTH entities returned | Ace-only item excluded; both-entity item present |
| **RET-005** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test, M7_TenZ_Test` → **🔀 AND/OR**: `or and` → **🔍 Search** | All three media returned (Ace-linked, TenZ-linked, both) | Each matches at least one entity |
| **RET-006** | `/control` → **Search** → 📦 Entities: `#<id>` (use actual entity ID) → **🔍 Search** | Same results as using entity name | Both formats work identically |
| **RET-007** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test, #<1v4_id>` (mixed format) → **🔀 AND/OR**: `and and` → **🔍 Search** | Items linked to both entities | Mixed name/#id format accepted |

### M7-C: Tag Filter AND/OR Semantics

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-008** | `/control` → **Search** → 🏷 Tags: `M7_1v4_Test, M7_1v3_Test` → **🔀 AND/OR**: `and and` → **🔍 Search** | Only items with BOTH tags | 1v4-only item excluded |
| **RET-009** | `/control` → **Search** → 🏷 Tags: `M7_1v4_Test, M7_1v3_Test` → **🔀 AND/OR**: `and or` → **🔍 Search** | Items with either tag | All tagged items returned |

### M7-D: Combined Entity + Tag Filters

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-010** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test, M7_1v4_Test` (AND) → 🏷 Tags: `M7_1v4_Test` (AND) → **🔍 Search** | Only items matching ALL three filters | Items missing any filter excluded |
| **RET-011** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test, M7_TenZ_Test` (OR) → 🏷 Tags: `M7_1v4_Test` (AND) → **🔍 Search** | (Ace OR TenZ) AND 1v4 tag | Both Ace+1v4 and TenZ+1v4 media returned |

### M7-E: Media Type Filter

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-012** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test` → 📎 Media type: `video` → **🔍 Search** | Only video media; notes still returned | Photos excluded; notes present |

### M7-F: Free-Text Search

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-013** | `/control` → **Search** → Query: `strategy` → **🔍 Search** | Note with "strategy" in title/content found | Match in title OR content |
| **RET-014** | `/control` → **Search** → Query: `clutch` → **🔍 Search** | Media with "clutch" in caption/filename found | Match in caption OR filename OR extracted_text |
| **RET-015** | `/control` → **Search** → Query: `ACE` → **🔍 Search** | Same results as query: `ace` | Case-insensitive |

### M7-G: Date Range Filters

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-016** | `/control` → **Search** → 📅 Dates: `<tomorrow's date>` (after only) → **🔍 Search** | 0 results (no items created in future) | Honest zero, no error |
| **RET-017** | `/control` → **Search** → 📅 Dates: `<yesterday's date> <tomorrow's date>` (after before) → **🔍 Search** | Items created today returned | Date range inclusive |

### M7-H: Workspace Isolation (CRITICAL SAFETY INVARIANT)

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-018** | In **WS_A**: `/control` → **Search** → 📦 Entities: `M7_Ace_Test` → **🔍 Search** | Only WS_A items returned | Zero WS_B items appear |
| **RET-019** | In **WS_A**: `/control` → **Search** → 🏷 Tags: `M7_1v4_Test` → **🔍 Search** | Only WS_A items with WS_A's 1v4 tag | WS_B items with same tag name excluded |

### M7-I: Kind Filter

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-020** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test` → Scope: `Notes` (kind filter via scope) → **🔍 Search** | Only notes of specified kind; media still returned | Kind applies to notes only |

### M7-J: Limit and Sorting

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-021** | Create 60+ notes linked to one entity. `/control` → **Search** → 📦 Entities: `<entity>` → **🔍 Search** | First 50 returned (default limit) | Default limit = 50 |
| **RET-022** | `/control` → **Search** → Query: `test` → **🔍 Search** | Newer items appear before older items | Sorted by created_at DESC |

### M7-K: Empty Results

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-023** | `/control` → **Search** → Query: `nonexistent_term_xyz_12345` → **🔍 Search** | "0 match(es)" message, no error | Empty list, no crash, no fabrication |

### M7-L: Original Use Cases

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-024** | `/control` → **Search** → 🏷 Tags: `M7_1v4_Test` (AND) → 📎 Media type: `video` → **🔍 Search** | Video clips tagged 1v4 | No photos, no untagged videos |
| **RET-025** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test` (AND) → **🔍 Search** | Media linked to Ace entity | Ace-linked media present |
| **RET-026** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test` (AND) → 🏷 Tags: `M7_1v4_Test` (AND) → **🔍 Search** | Media linked to Ace AND tagged 1v4 | Only both-matching items |
| **RET-027** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test` (AND) → 📎 Media type: `photo` → **🔍 Search** | Only photo media (no video) | Video excluded |
| **RET-028** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test` (AND) → 🏷 Tags: `M7_1v4_Test` (AND) → **🔍 Search** (when both Ace and TenZ have 1v4 media) | Only Ace+1v4 media returned | TenZ+1v4 media excluded |
| **RET-029** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test, M7_TenZ_Test` (OR) → 🏷 Tags: `M7_1v4_Test` (AND) → **🔍 Search** | Both Ace+1v4 and TenZ+1v4 media | All matching entity OR + tag AND |
| **RET-030** | In **WS_A**: `/control` → **Search** → 📦 Entities: `M7_Ace_Test, M7_1v4_Test` (AND) → 🏷 Tags: `M7_1v4_Test` (AND) → **🔍 Search** | Only WS_A media | Zero WS_B leakage (CRITICAL) |

### M7-M: Worker Integration

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-031** | Send: `What search tools do you have?` | Worker lists: `search_knowledge`, `search_notes_cross`, `search_media_cross` | All 3 M7 tools registered, READ_ONLY |
| **RET-032** | Send: `Search my workspace for Ace 1v4` | Worker calls `search_knowledge`, returns mixed note+media with `_type` | Worker synthesizes answer from tool results |
| **RET-033** | Send: `Search my notes for Ace` | Worker calls `search_notes_cross`, all results have `_type=note` | No media in results |
| **RET-034** | Send: `Search my media for 1v4 clips` | Worker calls `search_media_cross`, all results have `_type=media` | No notes in results |

### M7-N: Control Plane Search UI Actions

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-035** | `/control` → **Search** → Query: `test` → **🔍 Search** → **Open** on a note → **Open** on a media | Note Open → note detail page; Media Open → media detail page | Correct detail page opened |
| **RET-036** | `/control` → **Search** → Query: `test` → **🔍 Search** → **Send** on a media result | Media file sent to chat via stored `telegram_file_id` | Correct file sent |
| **RET-037** | `/control` → **Search** → Query: `test` → **🔍 Search** → **Link Entity** on a result → pick entity → confirm | Link created; result now linked to entity | Link appears in detail view |

### M7-O: Pagination

| RET ID | Action | Expected | PASS Condition |
|--------|--------|----------|----------------|
| **RET-038** | Create 100+ notes. `/control` → **Search** → 📦 Entities: `<entity>` → **🔍 Search** → **Next Page** | Page 1: 50 items; Page 2: next 50; no duplicates across pages | Pagination works correctly |

---

## State Accumulation Tests (UI State Machine)

These tests verify the stateful search builder fix. Each filter should persist across selections.

| Test | Action | Expected | PASS Condition |
|------|--------|----------|----------------|
| **State-01** | `/control` → **Search** → Query: `test` → 📦 Entities: `M7_Ace_Test` → **🔍 Search** | Both `q=test` AND `entities=M7_Ace_Test` applied | Query persists after setting entities |
| **State-02** | `/control` → **Search** → Query: `test` → 📦 Entities: `M7_Ace_Test` → 🏷 Tags: `M7_1v4_Test` → **🔍 Search** | All three filters applied | All filters persist |
| **State-03** | `/control` → **Search** → Query: `test` → 📦 Entities: `M7_Ace_Test` → **✕ Clear** → **🔍 Search** | No filters applied (empty search) | Clear resets all filters |
| **State-04** | `/control` → **Search** → 📦 Entities: `M7_Ace_Test` → 🏷 Tags: `M7_1v4_Test` → **🔀 AND/OR**: `or or` → **🔍 Search** | Entity mode=OR, Tag mode=OR | Mode filters persist |

---

## Workspace Isolation Verification (CRITICAL)

**This is the most important safety check.**

1. Switch to **Workspace A** (e.g., Genshin)
2. `/control` → **Search** → 📦 Entities: `M7_Ace_Test` → **🔍 Search**
3. Note the result IDs (note_id, media_id)
4. Switch to **Workspace B** (e.g., Valorant)
5. `/control` → **Search** → 📦 Entities: `M7_Ace_Test` → **🔍 Search**
6. Note the result IDs

**PASS Condition:** No ID appears in both result sets. WS_A results ≠ WS_B results.

---

## Files Changed

| File | Change |
|------|--------|
| `conversation_state.py` | Added `get_search_state`, `set_search_state`, `clear_search_state` for stateful search builder |
| `core/control/router.py` | Fixed all 8 gather handlers to use `set_search_state`/`get_search_state`; added `_gather_search_entities` handler; added `ctl:search:clear` and `ctl:search:entities` callback routing |
| `core/control/pages.py` | Reorganized search UI buttons; added 📦 Entities button; repositioned ✕ Clear button |
| `docs/engineering/V15_5_CROSS_REFERENCE_RETRIEVAL.md` | Added section 12 documenting the bug, root cause, fix, and UI changes |
| `tests/test_m7_retrieval.py` | Added Matrix Q (UI State Machine) and Matrix R (Control Plane Integration) tests |

---

## Verification Gates

Run these commands before live testing:

```bash
# M7 retrieval tests (should be 73 passed)
python -m pytest tests/test_m7_retrieval.py -v

# Full pytest suite (should be 1887+ passed with only known date flakes)
python -m pytest --tb=short

# Selftest (should be 18+ passed)
python -m pytest core/selftest/ -v

# Syntax check
python -m py_compile conversation_state.py core/control/router.py core/control/pages.py tests/test_m7_retrieval.py

# Git diff check
git diff --check
```

---

## Known Issues

- Date-related tests may flake near midnight IST due to timezone boundary. If a date test fails, re-run after a few minutes.

---

**End of Checklist**

The owner should execute each RET test and mark PASS/FAIL. Report any failures with:
1. RET ID
2. Exact input sent
3. Actual result observed
4. Screenshot if applicable
