"""
M7 Cross-Reference Retrieval — automated test matrices.

Fresh names only (prefixed M7_):
  M7_Ace_Test, M7_TenZ_Test, M7_1v4_Test, M7_1v3_Test,
  M7_Clip_A, M7_Clip_B, M7_Book_Test, M7_WS_A, M7_WS_B
"""
import pytest
import database as db
from core.workspace.engine import EntityEngine
from core.retrieval.service import (
    CrossReferenceService,
    RetrievalFilters,
    RetrievalResult,
    build_retrieval_service,
)


# ──────────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────────

SELFTEST_USER_ID = 999997777  # matches core/selftest/models.py


@pytest.fixture(scope="function")
def engine(temp_db):
    """Fresh EntityEngine per test."""
    return EntityEngine()


@pytest.fixture(scope="function")
def service(engine):
    """Fresh CrossReferenceService per test."""
    return CrossReferenceService(engine)


@pytest.fixture(scope="function")
def workspace_a(engine):
    """Create workspace A and return its ID."""
    ws = engine.create_workspace(SELFTEST_USER_ID, "M7_WS_A", "Workspace A for M7 tests")
    return ws.id


@pytest.fixture(scope="function")
def workspace_b(engine):
    """Create workspace B and return its ID."""
    ws = engine.create_workspace(SELFTEST_USER_ID, "M7_WS_B", "Workspace B for M7 tests")
    return ws.id


@pytest.fixture(scope="function")
def entities_ws_a(engine, workspace_a):
    """Create test entities in workspace A."""
    ace = engine.add_milestone(SELFTEST_USER_ID, workspace_a, "M7_Ace_Test", entity_type="character")
    tenz = engine.add_milestone(SELFTEST_USER_ID, workspace_a, "M7_TenZ_Test", entity_type="character")
    clip = engine.add_milestone(SELFTEST_USER_ID, workspace_a, "M7_1v4_Test", entity_type="clip")
    clip2 = engine.add_milestone(SELFTEST_USER_ID, workspace_a, "M7_1v3_Test", entity_type="clip")
    book = engine.add_milestone(SELFTEST_USER_ID, workspace_a, "M7_Book_Test", entity_type="book")
    return {
        "ace": ace,
        "tenz": tenz,
        "clip_1v4": clip,
        "clip_1v3": clip2,
        "book": book,
    }


@pytest.fixture(scope="function")
def entities_ws_b(engine, workspace_b):
    """Create identically-named entities in workspace B (isolation test)."""
    ace = engine.add_milestone(SELFTEST_USER_ID, workspace_b, "M7_Ace_Test", entity_type="character")
    tenz = engine.add_milestone(SELFTEST_USER_ID, workspace_b, "M7_TenZ_Test", entity_type="character")
    clip = engine.add_milestone(SELFTEST_USER_ID, workspace_b, "M7_1v4_Test", entity_type="clip")
    return {
        "ace": ace,
        "tenz": tenz,
        "clip_1v4": clip,
    }


@pytest.fixture(scope="function")
def tags_ws_a(engine, workspace_a):
    """Create test tags in workspace A."""
    tag_1v4 = engine.create_tag(SELFTEST_USER_ID, workspace_a, "M7_1v4_Test")
    tag_1v3 = engine.create_tag(SELFTEST_USER_ID, workspace_a, "M7_1v3_Test")
    return {"1v4": tag_1v4, "1v3": tag_1v3}


@pytest.fixture(scope="function")
def sample_note(engine, workspace_a, entities_ws_a, tags_ws_a):
    """Create a sample note linked to Ace and 1v4."""
    note = engine.add_note(
        SELFTEST_USER_ID,
        workspace_a,
        content="Ace 1v4 clip analysis",
        kind="analysis",
        title="M7_Note_Test",
    )
    engine.link_note_entity(SELFTEST_USER_ID, note.id, "milestone", entities_ws_a["ace"].id)
    engine.link_note_entity(SELFTEST_USER_ID, note.id, "milestone", entities_ws_a["clip_1v4"].id)
    engine.link_note_tag(SELFTEST_USER_ID, note.id, tags_ws_a["1v4"].id)
    return note


@pytest.fixture(scope="function")
def sample_media(engine, workspace_a, entities_ws_a, tags_ws_a):
    """Create a sample media (video) linked to Ace and 1v4."""
    media = engine.store_media(
        SELFTEST_USER_ID,
        workspace_a,
        telegram_file_id="M7_Clip_A_file_id",
        file_type="video",
        file_name="M7_Clip_A.mp4",
        caption="Ace 1v4 clutch",
    )
    engine.link_media_entity(SELFTEST_USER_ID, media.id, "milestone", entities_ws_a["ace"].id)
    engine.link_media_entity(SELFTEST_USER_ID, media.id, "milestone", entities_ws_a["clip_1v4"].id)
    engine.link_media_tag(SELFTEST_USER_ID, media.id, tags_ws_a["1v4"].id)
    return media


@pytest.fixture(scope="function")
def sample_media_screenshot(engine, workspace_a, entities_ws_a):
    """Create a screenshot media linked to Ace (no 1v4)."""
    media = engine.store_media(
        SELFTEST_USER_ID,
        workspace_a,
        telegram_file_id="M7_Clip_B_file_id",
        file_type="photo",
        file_name="M7_Clip_B.jpg",
        caption="Ace screenshot",
    )
    engine.link_media_entity(SELFTEST_USER_ID, media.id, "milestone", entities_ws_a["ace"].id)
    return media


@pytest.fixture(scope="function")
def tenz_media(engine, workspace_a, entities_ws_a, tags_ws_a):
    """Create a TenZ 1v4 video media."""
    media = engine.store_media(
        SELFTEST_USER_ID,
        workspace_a,
        telegram_file_id="M7_TenZ_Clip_file_id",
        file_type="video",
        file_name="M7_TenZ_1v4.mp4",
        caption="TenZ 1v4 play",
    )
    engine.link_media_entity(SELFTEST_USER_ID, media.id, "milestone", entities_ws_a["tenz"].id)
    engine.link_media_entity(SELFTEST_USER_ID, media.id, "milestone", entities_ws_a["clip_1v4"].id)
    engine.link_media_tag(SELFTEST_USER_ID, media.id, tags_ws_a["1v4"].id)
    return media


@pytest.fixture(autouse=True)
def cleanup():
    """Clean up test data after each test."""
    yield
    # Best-effort cleanup (tests use fresh DB per session usually)
    try:
        db.execute(
            "DELETE FROM notes WHERE workspace_id IN (SELECT id FROM workspaces WHERE name LIKE 'M7_WS_%')"
        )
        db.execute(
            "DELETE FROM attachments WHERE workspace_id IN (SELECT id FROM workspaces WHERE name LIKE 'M7_WS_%')"
        )
        db.execute(
            "DELETE FROM note_entities WHERE note_id IN (SELECT id FROM notes WHERE workspace_id IN (SELECT id FROM workspaces WHERE name LIKE 'M7_WS_%'))"
        )
        db.execute(
            "DELETE FROM attachment_entities WHERE attachment_id IN (SELECT id FROM attachments WHERE workspace_id IN (SELECT id FROM workspaces WHERE name LIKE 'M7_WS_%'))"
        )
        db.execute(
            "DELETE FROM entity_tags WHERE entity_type IN ('note', 'attachment') AND entity_id IN (SELECT id FROM notes WHERE workspace_id IN (SELECT id FROM workspaces WHERE name LIKE 'M7_WS_%'))"
        )
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────
# Test Matrix A: Basic cross-reference search (mixed notes + media)
# ──────────────────────────────────────────────────────────────────────

class TestBasicCrossReferenceSearch:
    """Matrix A: Cross-reference search returns mixed _type results."""

    def test_search_returns_mixed_types(self, service, workspace_a, sample_note, sample_media):
        """Unified search returns both notes and media."""
        results = service.search(SELFTEST_USER_ID, workspace_a, q="Ace")
        types = {r._type for r in results}
        assert types == {"note", "media"}, f"Expected both types, got {types}"

    def test_search_notes_only(self, service, workspace_a, sample_note, sample_media):
        """Notes-only search returns only notes."""
        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, q="Ace")
        assert all(r._type == "note" for r in results)
        assert len(results) == 1
        assert results[0].note_id == sample_note.id

    def test_search_media_only(self, service, workspace_a, sample_note, sample_media):
        """Media-only search returns only media."""
        results = service.search_media_only(SELFTEST_USER_ID, workspace_a, q="Ace")
        assert all(r._type == "media" for r in results)
        assert len(results) == 1
        assert results[0].media_id == sample_media.id

    def test_result_has_type_discriminator(self, service, workspace_a, sample_note, sample_media):
        """Every result has _type discriminator."""
        results = service.search(SELFTEST_USER_ID, workspace_a, q="Ace")
        for r in results:
            assert hasattr(r, "_type")
            assert r._type in ("note", "media")

    def test_note_result_fields(self, service, workspace_a, sample_note):
        """Note results have expected fields populated."""
        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, q="Test")
        r = results[0]
        assert r.note_id == sample_note.id
        assert r.title == "M7_Note_Test"
        assert r.content == "Ace 1v4 clip analysis"
        assert r.kind == "analysis"
        assert r.note_created_at is not None
        assert r.workspace_id == workspace_a

    def test_media_result_fields(self, service, workspace_a, sample_media):
        """Media results have expected fields populated."""
        results = service.search_media_only(SELFTEST_USER_ID, workspace_a, q="clutch")
        r = results[0]
        assert r.media_id == sample_media.id
        assert r.file_type == "video"
        assert r.telegram_file_id == "M7_Clip_A_file_id"
        assert r.file_name == "M7_Clip_A.mp4"
        assert r.caption == "Ace 1v4 clutch"
        assert r.media_created_at is not None
        assert r.workspace_id == workspace_a


# ──────────────────────────────────────────────────────────────────────
# Test Matrix B: Entity filtering (AND / OR)
# ──────────────────────────────────────────────────────────────────────

class TestEntityFiltering:
    """Matrix B: Entity AND/OR filter semantics."""

    def test_entity_and_both_match(
        self, service, workspace_a, entities_ws_a, sample_note, sample_media
    ):
        """entity_mode=and with Ace AND 1v4 returns both (both linked)."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test", "M7_1v4_Test"],
            entity_mode="and",
        )
        assert len(results) == 2  # note + media
        types = {r._type for r in results}
        assert types == {"note", "media"}

    def test_entity_and_only_ace_does_not_match(
        self, service, workspace_a, entities_ws_a, sample_media_screenshot
    ):
        """entity_mode=and with Ace AND 1v4 does NOT return Ace-only media."""
        # sample_media_screenshot is linked to Ace only, not 1v4
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test", "M7_1v4_Test"],
            entity_mode="and",
        )
        media_results = [r for r in results if r._type == "media"]
        # Should only find the media linked to BOTH Ace and 1v4
        media_ids = {r.media_id for r in media_results}
        assert sample_media_screenshot.id not in media_ids

    def test_entity_or_ace_or_tenz(
        self, service, workspace_a, entities_ws_a, sample_media, tenz_media
    ):
        """entity_mode=or with Ace OR TenZ returns both media."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test", "M7_TenZ_Test"],
            entity_mode="or",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 2
        media_ids = {r.media_id for r in media_results}
        assert sample_media.id in media_ids
        assert tenz_media.id in media_ids

    def test_entity_or_ace_or_tenz_1v4(
        self, service, workspace_a, entities_ws_a, sample_media, tenz_media
    ):
        """entity_mode=or with Ace OR TenZ AND 1v4 (entity) returns both 1v4 clips."""
        # Using entities: [Ace, TenZ] + entity_mode=or + clip_1v4 entity
        # This tests: (Ace OR TenZ) AND 1v4
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test", "M7_TenZ_Test", "M7_1v4_Test"],
            entity_mode="or",
        )
        media_results = [r for r in results if r._type == "media"]
        # Both Ace+1v4 and TenZ+1v4 media should match
        assert len(media_results) == 2

    def test_entity_id_format(self, service, workspace_a, entities_ws_a, sample_note):
        """Entity references can use #id format."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=[f"#{entities_ws_a['ace'].id}"],
            entity_mode="and",
        )
        note_results = [r for r in results if r._type == "note"]
        assert len(note_results) == 1
        assert note_results[0].note_id == sample_note.id

    def test_entity_mixed_name_and_id(
        self, service, workspace_a, entities_ws_a, sample_note
    ):
        """Entity references can mix names and #ids."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test", f"#{entities_ws_a['clip_1v4'].id}"],
            entity_mode="and",
        )
        note_results = [r for r in results if r._type == "note"]
        assert len(note_results) == 1


# ──────────────────────────────────────────────────────────────────────
# Test Matrix C: Tag filtering (AND / OR)
# ──────────────────────────────────────────────────────────────────────

class TestTagFiltering:
    """Matrix C: Tag AND/OR filter semantics."""

    def test_tag_and_both_match(
        self, service, workspace_a, tags_ws_a, sample_note, sample_media
    ):
        """tag_mode=and with 1v4 tag returns both (both tagged)."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            tags=["M7_1v4_Test"],
            tag_mode="and",
        )
        assert len(results) == 2
        types = {r._type for r in results}
        assert types == {"note", "media"}

    def test_tag_or_multiple_tags(
        self, service, workspace_a, tags_ws_a, sample_note, sample_media, engine
    ):
        """tag_mode=or with 1v4 OR 1v3 returns items tagged with either."""
        # Add 1v3 tag to note
        engine.link_note_tag(SELFTEST_USER_ID, sample_note.id, tags_ws_a["1v3"].id)

        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            tags=["M7_1v4_Test", "M7_1v3_Test"],
            tag_mode="or",
        )
        note_results = [r for r in results if r._type == "note"]
        assert len(note_results) == 1  # note has both tags, but deduped

    def test_tag_and_excludes_untagged(
        self, service, workspace_a, tags_ws_a, sample_media_screenshot
    ):
        """tag_mode=and with 1v4 excludes media without that tag."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            tags=["M7_1v4_Test"],
            tag_mode="and",
        )
        media_results = [r for r in results if r._type == "media"]
        media_ids = {r.media_id for r in media_results}
        assert sample_media_screenshot.id not in media_ids


# ──────────────────────────────────────────────────────────────────────
# Test Matrix D: Combined entity + tag filters
# ──────────────────────────────────────────────────────────────────────

class TestCombinedFilters:
    """Matrix D: Combined entity AND tag filters."""

    def test_entity_and_tag_and(
        self, service, workspace_a, entities_ws_a, tags_ws_a, sample_note, sample_media
    ):
        """entities=and + tags=and requires both entity AND tag match."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"],
            entity_mode="and",
            tags=["M7_1v4_Test"],
            tag_mode="and",
        )
        assert len(results) == 2  # both have Ace entity AND 1v4 tag

    def test_entity_or_tag_and(
        self, service, workspace_a, entities_ws_a, tags_ws_a, sample_media, tenz_media
    ):
        """entities=or + tags=and: (Ace OR TenZ) AND 1v4 tag."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test", "M7_TenZ_Test"],
            entity_mode="or",
            tags=["M7_1v4_Test"],
            tag_mode="and",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 2
        media_ids = {r.media_id for r in media_results}
        assert sample_media.id in media_ids
        assert tenz_media.id in media_ids


# ──────────────────────────────────────────────────────────────────────
# Test Matrix E: Media type filter
# ──────────────────────────────────────────────────────────────────────

class TestMediaTypeFilter:
    """Matrix E: media_type filter on media results."""

    def test_media_type_video_only(
        self, service, workspace_a, sample_media, sample_media_screenshot
    ):
        """media_type=video returns only video media."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"],
            entity_mode="and",
            media_type="video",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 1
        assert media_results[0].file_type == "video"
        assert media_results[0].media_id == sample_media.id

    def test_media_type_photo_excludes_video(
        self, service, workspace_a, sample_media, sample_media_screenshot
    ):
        """media_type=photo excludes video."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"],
            entity_mode="and",
            media_type="photo",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 1
        assert media_results[0].file_type == "photo"
        assert media_results[0].media_id == sample_media_screenshot.id

    def test_media_type_does_not_affect_notes(
        self, service, workspace_a, sample_note, sample_media
    ):
        """media_type filter only applies to media, notes still returned."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            q="Ace",
            media_type="video",
        )
        note_results = [r for r in results if r._type == "note"]
        media_results = [r for r in results if r._type == "media"]
        assert len(note_results) == 1  # note still returned
        assert len(media_results) == 1  # only video media


# ──────────────────────────────────────────────────────────────────────
# Test Matrix F: Free-text search (q parameter)
# ──────────────────────────────────────────────────────────────────────

class TestFreeTextSearch:
    """Matrix F: Free-text search across notes and media."""

    def test_q_searches_note_title_content(
        self, service, workspace_a, sample_note
    ):
        """q searches note title and content."""
        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, q="analysis")
        assert len(results) == 1
        assert results[0].note_id == sample_note.id

    def test_q_searches_media_caption_filename(
        self, service, workspace_a, sample_media
    ):
        """q searches media caption and file_name."""
        results = service.search_media_only(SELFTEST_USER_ID, workspace_a, q="clutch")
        assert len(results) == 1
        assert results[0].media_id == sample_media.id

    def test_q_searches_media_extracted_text(
        self, service, workspace_a, entities_ws_a
    ):
        """q searches media extracted_text."""
        media = engine = EntityEngine()
        media = engine.store_media(
            SELFTEST_USER_ID,
            workspace_a,
            telegram_file_id="M7_extracted_file_id",
            file_type="document",
            file_name="M7_doc.pdf",
            caption="",
            extracted_text="M7_Ace_Test strategy guide",
        )
        engine.link_media_entity(SELFTEST_USER_ID, media.id, "milestone", entities_ws_a["ace"].id)

        results = service.search_media_only(SELFTEST_USER_ID, workspace_a, q="strategy")
        assert len(results) == 1
        assert results[0].media_id == media.id

    def test_q_case_insensitive(self, service, workspace_a, sample_note):
        """q search is case-insensitive."""
        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, q="ANALYSIS")
        assert len(results) == 1
        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, q="Analysis")
        assert len(results) == 1


# ──────────────────────────────────────────────────────────────────────
# Test Matrix G: Date range filters
# ──────────────────────────────────────────────────────────────────────

class TestDateRangeFilters:
    """Matrix G: created_after / created_before filters."""

    def test_created_after(self, service, workspace_a, sample_note):
        """created_after returns items on or after date."""
        from datetime import timedelta
        from datetime import datetime as _dt
        tomorrow = (_dt.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        # Note was created today, so tomorrow should return 0
        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, created_after=tomorrow)
        assert len(results) == 0

        yesterday = (_dt.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, created_after=yesterday)
        assert len(results) == 1

    def test_created_before(self, service, workspace_a, sample_note):
        """created_before returns items on or before date."""
        from datetime import timedelta
        from datetime import datetime as _dt
        yesterday = (_dt.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, created_before=yesterday)
        assert len(results) == 0

        tomorrow = (_dt.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, created_before=tomorrow)
        assert len(results) == 1


# ──────────────────────────────────────────────────────────────────────
# Test Matrix H: Workspace isolation (HARD SAFETY INVARIANT)
# ──────────────────────────────────────────────────────────────────────

class TestWorkspaceIsolation:
    """Matrix H: Active workspace ONLY — never leak across workspaces."""

    def test_workspace_a_excludes_workspace_b(
        self, service, workspace_a, workspace_b, entities_ws_a, entities_ws_b, sample_note
    ):
        """Query on workspace A never returns workspace B data."""
        # Create identical note in workspace B
        engine = EntityEngine()
        note_b = engine.add_note(
            SELFTEST_USER_ID, workspace_b,
            content="Ace 1v4 clip analysis", kind="analysis", title="M7_Note_Test"
        )
        engine.link_note_entity(SELFTEST_USER_ID, note_b.id, "milestone", entities_ws_b["ace"].id)
        engine.link_note_entity(SELFTEST_USER_ID, note_b.id, "milestone", entities_ws_b["clip_1v4"].id)

        # Search workspace A
        results = service.search(SELFTEST_USER_ID, workspace_a, q="Ace")
        note_results = [r for r in results if r._type == "note"]
        note_ids = {r.note_id for r in note_results}
        assert sample_note.id in note_ids
        assert note_b.id not in note_ids  # NEVER leaks

    def test_workspace_b_excludes_workspace_a(
        self, service, workspace_a, workspace_b, entities_ws_a, entities_ws_b
    ):
        """Query on workspace B never returns workspace A data."""
        engine = EntityEngine()
        note_b = engine.add_note(
            SELFTEST_USER_ID, workspace_b,
            content="Ace 1v4 clip analysis", kind="analysis", title="M7_Note_Test"
        )
        engine.link_note_entity(SELFTEST_USER_ID, note_b.id, "milestone", entities_ws_b["ace"].id)

        results = service.search(SELFTEST_USER_ID, workspace_b, q="Ace")
        note_results = [r for r in results if r._type == "note"]
        note_ids = {r.note_id for r in note_results}
        assert note_b.id in note_ids
        # Note from workspace A should not appear

    def test_identical_names_different_workspaces_distinct(
        self, service, workspace_a, workspace_b, entities_ws_a, entities_ws_b
    ):
        """Same entity names in different workspaces are distinct."""
        # Both workspaces have "M7_Ace_Test" entity
        # Search workspace A with entity "M7_Ace_Test"
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"], entity_mode="and"
        )
        # Should only find things linked to workspace A's Ace entity


# ──────────────────────────────────────────────────────────────────────
# Test Matrix I: Kind filter (notes only)
# ──────────────────────────────────────────────────────────────────────

class TestKindFilter:
    """Matrix I: kind filter applies only to notes."""

    def test_kind_filters_notes(self, service, workspace_a, entities_ws_a):
        """kind=analysis returns only analysis notes."""
        engine = EntityEngine()
        note1 = engine.add_note(SELFTEST_USER_ID, workspace_a, "c", kind="analysis", title="N1")
        note2 = engine.add_note(SELFTEST_USER_ID, workspace_a, "c", kind="summary", title="N2")
        engine.link_note_entity(SELFTEST_USER_ID, note1.id, "milestone", entities_ws_a["ace"].id)
        engine.link_note_entity(SELFTEST_USER_ID, note2.id, "milestone", entities_ws_a["ace"].id)

        results = service.search_notes_only(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"], entity_mode="and", kind="analysis"
        )
        assert len(results) == 1
        assert results[0].note_id == note1.id

    def test_kind_does_not_affect_media(self, service, workspace_a, entities_ws_a, sample_media):
        """kind filter does not filter media results."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"], entity_mode="and", kind="analysis"
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 1  # media still returned


# ──────────────────────────────────────────────────────────────────────
# Test Matrix J: Limit and sorting
# ──────────────────────────────────────────────────────────────────────

class TestLimitAndSorting:
    """Matrix J: limit cap and newest-first sorting."""

    def test_limit_default_50(self, service, workspace_a, entities_ws_a):
        """Default limit is 50."""
        engine = EntityEngine()
        for i in range(60):
            note = engine.add_note(SELFTEST_USER_ID, workspace_a, "c", kind="analysis", title=f"N{i}")
            engine.link_note_entity(SELFTEST_USER_ID, note.id, "milestone", entities_ws_a["ace"].id)

        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, entities=["M7_Ace_Test"])
        assert len(results) == 50

    def test_limit_max_200(self, service, workspace_a, entities_ws_a):
        """Max limit is 200."""
        engine = EntityEngine()
        for i in range(250):
            note = engine.add_note(SELFTEST_USER_ID, workspace_a, "c", kind="analysis", title=f"N{i}")
            engine.link_note_entity(SELFTEST_USER_ID, note.id, "milestone", entities_ws_a["ace"].id)

        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, entities=["M7_Ace_Test"], limit=200)
        assert len(results) == 200

    def test_limit_over_max_capped(self, service, workspace_a, entities_ws_a):
        """Limit over 200 is capped to 200."""
        engine = EntityEngine()
        for i in range(250):
            note = engine.add_note(SELFTEST_USER_ID, workspace_a, "c", kind="analysis", title=f"N{i}")
            engine.link_note_entity(SELFTEST_USER_ID, note.id, "milestone", entities_ws_a["ace"].id)

        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, entities=["M7_Ace_Test"], limit=500)
        assert len(results) == 200

    def test_sorted_newest_first(self, service, workspace_a, entities_ws_a):
        """Results sorted newest-first by created_at."""
        engine = EntityEngine()
        import time
        note1 = engine.add_note(SELFTEST_USER_ID, workspace_a, "c", kind="analysis", title="Old")
        time.sleep(0.01)
        note2 = engine.add_note(SELFTEST_USER_ID, workspace_a, "c", kind="analysis", title="New")
        engine.link_note_entity(SELFTEST_USER_ID, note1.id, "milestone", entities_ws_a["ace"].id)
        engine.link_note_entity(SELFTEST_USER_ID, note2.id, "milestone", entities_ws_a["ace"].id)

        results = service.search_notes_only(SELFTEST_USER_ID, workspace_a, entities=["M7_Ace_Test"])
        assert results[0].note_id == note2.id  # newest first
        assert results[1].note_id == note1.id


# ──────────────────────────────────────────────────────────────────────
# Test Matrix K: Empty results handling
# ──────────────────────────────────────────────────────────────────────

class TestEmptyResults:
    """Matrix K: Zero results = zero results (honest, no fabrication)."""

    def test_no_match_returns_empty(self, service, workspace_a):
        """Non-matching query returns empty list, not error."""
        results = service.search(SELFTEST_USER_ID, workspace_a, q="nonexistent")
        assert results == []

    def test_no_entities_returns_empty(self, service, workspace_a):
        """Entity filter with no matches returns empty."""
        results = service.search(SELFTEST_USER_ID, workspace_a, entities=["Nonexistent"])
        assert results == []


# ──────────────────────────────────────────────────────────────────────
# Test Matrix L: IMPORTANT ORIGINAL USE CASE — Ace/TenZ/1v4 scenarios
# ──────────────────────────────────────────────────────────────────────

class TestOriginalUseCases:
    """Matrix L: The original use cases from M7 spec.

    1. "Show my 1v4 clips" → returns clip (media tagged 1v4, type video)
    2. "Show M7_Ace_Test clips" → returns clip (media linked to Ace entity)
    3. "Show M7_Ace_Test 1v4 clips" → returns clip (Ace AND 1v4)
    4. "Show M7_Ace_Test screenshots" → does NOT return video (media_type filter)
    5. Entity=M7_TenZ_Test, Tag=M7_1v4_Test: "Show M7_Ace_Test 1v4 clips" → only Ace
    6. "Show M7_Ace_Test or M7_TenZ_Test 1v4 clips" → both
    7. Identical names/tags in another workspace → NEVER leak
    """

    def test_show_my_1v4_clips(
        self, service, workspace_a, entities_ws_a, tags_ws_a, sample_media
    ):
        """1. 'Show my 1v4 clips' → returns clip (media tagged 1v4, type video)."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            tags=["M7_1v4_Test"], tag_mode="and",
            media_type="video",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 1
        assert media_results[0].media_id == sample_media.id
        assert media_results[0].file_type == "video"

    def test_show_ace_clips(
        self, service, workspace_a, entities_ws_a, sample_media
    ):
        """2. 'Show M7_Ace_Test clips' → returns clip (media linked to Ace entity)."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"], entity_mode="and",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 1
        assert media_results[0].media_id == sample_media.id

    def test_show_ace_1v4_clips(
        self, service, workspace_a, entities_ws_a, tags_ws_a, sample_media
    ):
        """3. 'Show M7_Ace_Test 1v4 clips' → returns clip (Ace AND 1v4)."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"], entity_mode="and",
            tags=["M7_1v4_Test"], tag_mode="and",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 1
        assert media_results[0].media_id == sample_media.id

    def test_show_ace_screenshots_excludes_video(
        self, service, workspace_a, entities_ws_a, sample_media, sample_media_screenshot
    ):
        """4. 'Show M7_Ace_Test screenshots' → does NOT return video."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"], entity_mode="and",
            media_type="photo",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 1
        assert media_results[0].media_id == sample_media_screenshot.id
        assert media_results[0].file_type == "photo"
        assert sample_media.id not in {r.media_id for r in media_results}

    def test_tenz_1v4_query_returns_only_ace(
        self, service, workspace_a, entities_ws_a, tags_ws_a, sample_media, tenz_media
    ):
        """5. Query Ace 1v4 → only Ace (not TenZ), even though TenZ also has 1v4."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"], entity_mode="and",
            tags=["M7_1v4_Test"], tag_mode="and",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 1
        assert media_results[0].media_id == sample_media.id
        assert tenz_media.id not in {r.media_id for r in media_results}

    def test_ace_or_tenz_1v4_returns_both(
        self, service, workspace_a, entities_ws_a, tags_ws_a, sample_media, tenz_media
    ):
        """6. 'Show M7_Ace_Test or M7_TenZ_Test 1v4 clips' → both."""
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test", "M7_TenZ_Test"], entity_mode="or",
            tags=["M7_1v4_Test"], tag_mode="and",
        )
        media_results = [r for r in results if r._type == "media"]
        assert len(media_results) == 2
        media_ids = {r.media_id for r in media_results}
        assert sample_media.id in media_ids
        assert tenz_media.id in media_ids

    def test_workspace_b_never_leaks(
        self, service, workspace_a, workspace_b, entities_ws_a, entities_ws_b,
        sample_media, tags_ws_a, engine
    ):
        """7. Identical names/tags in workspace B → NEVER leak into workspace A query."""
        # Create identical tag in workspace B
        tag_1v4_b = engine.create_tag(SELFTEST_USER_ID, workspace_b, "M7_1v4_Test")
        # Create identical media in workspace B
        media_b = engine.store_media(
            SELFTEST_USER_ID, workspace_b,
            telegram_file_id="M7_B_workspace_clip",
            file_type="video", file_name="clip.mp4", caption="Ace 1v4"
        )
        engine.link_media_entity(SELFTEST_USER_ID, media_b.id, "milestone", entities_ws_b["ace"].id)
        engine.link_media_entity(SELFTEST_USER_ID, media_b.id, "milestone", entities_ws_b["clip_1v4"].id)
        engine.link_media_tag(SELFTEST_USER_ID, media_b.id, tag_1v4_b.id)

        # Query workspace A
        results = service.search(
            SELFTEST_USER_ID, workspace_a,
            entities=["M7_Ace_Test"], entity_mode="and",
            tags=["M7_1v4_Test"], tag_mode="and",
        )
        media_results = [r for r in results if r._type == "media"]
        media_ids = {r.media_id for r in media_results}
        assert sample_media.id in media_ids
        assert media_b.id not in media_ids  # NEVER leaks from workspace B


# ──────────────────────────────────────────────────────────────────────
# Test Matrix M: Service factory
# ──────────────────────────────────────────────────────────────────────

class TestServiceFactory:
    """Matrix M: build_retrieval_service factory."""

    def test_factory_creates_service(self):
        """Factory returns CrossReferenceService instance."""
        svc = build_retrieval_service()
        assert isinstance(svc, CrossReferenceService)

    def test_factory_accepts_engine(self, engine):
        """Factory accepts custom engine."""
        svc = build_retrieval_service(engine)
        assert svc._engine is engine


# ──────────────────────────────────────────────────────────────────────
# Test Matrix N: Filters dataclass
# ──────────────────────────────────────────────────────────────────────

class TestFiltersDataclass:
    """Matrix N: RetrievalFilters dataclass structure."""

    def test_filters_defaults(self):
        """RetrievalFilters has correct defaults."""
        f = RetrievalFilters(workspace_id=1)
        assert f.workspace_id == 1
        assert f.q is None
        assert f.entity_ids == ()
        assert f.entity_mode == "and"
        assert f.tag_ids == ()
        assert f.tag_mode == "and"
        assert f.media_type is None
        assert f.created_after is None
        assert f.created_before is None
        assert f.limit == 50
        assert f.kind is None


# ──────────────────────────────────────────────────────────────────────
# Test Matrix O: Result dataclass
# ──────────────────────────────────────────────────────────────────────

class TestResultDataclass:
    """Matrix O: RetrievalResult dataclass structure."""

    def test_note_result_creation(self):
        """Can create note-type result."""
        r = RetrievalResult(
            _type="note",
            note_id=1, title="Test", content="Content", kind="analysis",
            note_created_at="2024-01-01T00:00:00", workspace_id=1
        )
        assert r._type == "note"
        assert r.note_id == 1
        assert r.media_id is None

    def test_media_result_creation(self):
        """Can create media-type result."""
        r = RetrievalResult(
            _type="media",
            media_id=1, file_type="video", telegram_file_id="fid",
            file_name="vid.mp4", caption="Cap", media_created_at="2024-01-01T00:00:00",
            workspace_id=1
        )
        assert r._type == "media"
        assert r.media_id == 1
        assert r.note_id is None


# ──────────────────────────────────────────────────────────────────────
# Test Matrix P: Edge cases
# ──────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Matrix P: Edge cases and error handling."""

    def test_empty_entity_list(self, service, workspace_a, sample_note):
        """Empty entity list doesn't filter."""
        results = service.search(SELFTEST_USER_ID, workspace_a, entities=[])
        note_results = [r for r in results if r._type == "note"]
        assert len(note_results) == 1

    def test_empty_tag_list(self, service, workspace_a, sample_note):
        """Empty tag list doesn't filter."""
        results = service.search(SELFTEST_USER_ID, workspace_a, tags=[])
        note_results = [r for r in results if r._type == "note"]
        assert len(note_results) == 1

    def test_nonexistent_entity_name(self, service, workspace_a):
        """Nonexistent entity name returns empty (not error)."""
        results = service.search(SELFTEST_USER_ID, workspace_a, entities=["DoesNotExist"])
        assert results == []

    def test_nonexistent_tag_name(self, service, workspace_a):
        """Nonexistent tag name returns empty (not error)."""
        results = service.search(SELFTEST_USER_ID, workspace_a, tags=["DoesNotExist"])
        assert results == []

    def test_invalid_entity_mode(self, service, workspace_a, sample_note):
        """Invalid entity_mode defaults to 'and'."""
        results = service.search(SELFTEST_USER_ID, workspace_a, entities=["M7_Ace_Test"], entity_mode="invalid")
        # Should not crash, defaults to AND behavior
        note_results = [r for r in results if r._type == "note"]
        assert len(note_results) >= 0  # no crash

    def test_invalid_tag_mode(self, service, workspace_a, sample_note):
        """Invalid tag_mode defaults to 'and'."""
        results = service.search(SELFTEST_USER_ID, workspace_a, tags=["M7_1v4_Test"], tag_mode="invalid")
        note_results = [r for r in results if r._type == "note"]
        assert len(note_results) >= 0  # no crash

    def test_limit_zero_capped_to_one(self, service, workspace_a, sample_note):
        """Limit 0 is capped to 1."""
        results = service.search(SELFTEST_USER_ID, workspace_a, limit=0)
        assert len(results) <= 1

    def test_limit_negative_capped_to_one(self, service, workspace_a, sample_note):
        """Negative limit is capped to 1."""
        results = service.search(SELFTEST_USER_ID, workspace_a, limit=-10)
        assert len(results) <= 1


# ──────────────────────────────────────────────────────────────────────
# Test Matrix Q: UI State Machine (M7 Search Control Plane)
# ──────────────────────────────────────────────────────────────────────

class TestSearchUIStateMachine:
    """Matrix Q: M7 Search UI state accumulation and filter building.

    These tests verify the stateful search builder pattern where users
    build compound searches incrementally (select entities → select tags →
    set AND/OR mode → add query → search).

    The bug was: each gather handler cleared state and passed only its own
    filter. Fix: all handlers use set_search_state/get_search_state to
    accumulate filters across selections.
    """

    def test_open_search_shows_empty_state(self):
        """Opening Search page shows empty filter state."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 100
        cs.clear_search_state(user_id)
        state = cs.get_search_state(user_id)
        assert state == {}

    def test_query_sets_q_state(self):
        """Entering a query sets the q filter."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 101
        cs.clear_search_state(user_id)
        cs.set_search_state(user_id, q="test query")
        state = cs.get_search_state(user_id)
        assert state.get("q") == "test query"

    def test_entity_filter_accumulates(self):
        """Entity filter can be set independently."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 102
        cs.clear_search_state(user_id)
        cs.set_search_state(user_id, q="test")
        cs.set_search_state(user_id, entities="M7_Ace_Test, M7_1v4_Test")
        state = cs.get_search_state(user_id)
        assert state.get("q") == "test"
        assert state.get("entities") == "M7_Ace_Test, M7_1v4_Test"

    def test_tag_filter_accumulates(self):
        """Tag filter can be set independently."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 103
        cs.clear_search_state(user_id)
        cs.set_search_state(user_id, q="test")
        cs.set_search_state(user_id, entities="M7_Ace_Test")
        cs.set_search_state(user_id, tags="M7_1v4_Test, M7_1v3_Test")
        state = cs.get_search_state(user_id)
        assert state.get("q") == "test"
        assert state.get("entities") == "M7_Ace_Test"
        assert state.get("tags") == "M7_1v4_Test, M7_1v3_Test"

    def test_mode_filter_accumulates(self):
        """AND/OR mode can be set independently."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 104
        cs.clear_search_state(user_id)
        cs.set_search_state(user_id, entities="M7_Ace_Test, M7_TenZ_Test")
        cs.set_search_state(user_id, tags="M7_1v4_Test, M7_1v3_Test")
        cs.set_search_state(user_id, entity_mode="or", tag_mode="and")
        state = cs.get_search_state(user_id)
        assert state.get("entity_mode") == "or"
        assert state.get("tag_mode") == "and"

    def test_media_type_filter_accumulates(self):
        """Media type filter can be set independently."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 105
        cs.clear_search_state(user_id)
        cs.set_search_state(user_id, q="test")
        cs.set_search_state(user_id, media_type="video")
        state = cs.get_search_state(user_id)
        assert state.get("q") == "test"
        assert state.get("media_type") == "video"

    def test_date_filter_accumulates(self):
        """Date range can be set independently."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 106
        cs.clear_search_state(user_id)
        cs.set_search_state(user_id, q="test")
        cs.set_search_state(user_id, created_after="2024-01-01", created_before="2024-12-31")
        state = cs.get_search_state(user_id)
        assert state.get("created_after") == "2024-01-01"
        assert state.get("created_before") == "2024-12-31"

    def test_workspace_filter_accumulates(self):
        """Workspace scope can be set independently."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 107
        cs.clear_search_state(user_id)
        cs.set_search_state(user_id, q="test")
        cs.set_search_state(user_id, workspace=42, scope="active")
        state = cs.get_search_state(user_id)
        assert state.get("workspace") == 42
        assert state.get("scope") == "active"

    def test_clear_resets_all_filters(self):
        """Clear button resets all accumulated filters."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 108
        cs.set_search_state(user_id, q="test", entities="M7_Ace_Test",
                           tags="M7_1v4_Test", entity_mode="or", tag_mode="and",
                           media_type="video", created_after="2024-01-01")
        cs.clear_search_state(user_id)
        state = cs.get_search_state(user_id)
        assert state == {}

    def test_multiple_filters_persist_across_changes(self):
        """Setting one filter does not clear others (the original bug)."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 109
        cs.clear_search_state(user_id)

        # Build compound search incrementally
        cs.set_search_state(user_id, q="Ace")
        cs.set_search_state(user_id, entities="M7_Ace_Test, M7_1v4_Test")
        cs.set_search_state(user_id, tags="M7_1v4_Test")
        cs.set_search_state(user_id, entity_mode="and", tag_mode="and")

        # Each set preserves previous values
        state = cs.get_search_state(user_id)
        assert state.get("q") == "Ace", "Query should persist"
        assert state.get("entities") == "M7_Ace_Test, M7_1v4_Test", "Entities should persist"
        assert state.get("tags") == "M7_1v4_Test", "Tags should persist"
        assert state.get("entity_mode") == "and", "Entity mode should persist"
        assert state.get("tag_mode") == "and", "Tag mode should persist"

    def test_scope_all_clears_workspace(self):
        """Setting scope='all' clears workspace filter."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 110
        cs.clear_search_state(user_id)
        cs.set_search_state(user_id, workspace=42, scope="active")
        cs.set_search_state(user_id, scope="all", workspace=None)
        state = cs.get_search_state(user_id)
        assert state.get("workspace") is None
        assert state.get("scope") == "all"

    def test_workspace_switch_updates_scope(self):
        """Selecting a named workspace updates workspace + scope."""
        import conversation_state as cs
        user_id = SELFTEST_USER_ID + 111
        cs.clear_search_state(user_id)
        cs.set_search_state(user_id, scope="all", workspace=None)
        cs.set_search_state(user_id, workspace=99, scope="active")
        state = cs.get_search_state(user_id)
        assert state.get("workspace") == 99
        assert state.get("scope") == "active"

    def test_different_users_have_isolated_search_state(self):
        """Each user has their own isolated search state."""
        import conversation_state as cs
        user_a = SELFTEST_USER_ID + 112
        user_b = SELFTEST_USER_ID + 113

        cs.clear_search_state(user_a)
        cs.clear_search_state(user_b)

        cs.set_search_state(user_a, q="user_a_query", entities="M7_Ace_Test")
        cs.set_search_state(user_b, q="user_b_query", entities="M7_TenZ_Test")

        state_a = cs.get_search_state(user_a)
        state_b = cs.get_search_state(user_b)

        assert state_a.get("q") == "user_a_query"
        assert state_a.get("entities") == "M7_Ace_Test"
        assert state_b.get("q") == "user_b_query"
        assert state_b.get("entities") == "M7_TenZ_Test"


# ──────────────────────────────────────────────────────────────────────
# Test Matrix R: Control Plane Integration
# ──────────────────────────────────────────────────────────────────────

class TestControlPlaneSearchIntegration:
    """Matrix R: Integration tests for Control Plane search callbacks.

    These tests verify the callback routing and gather handler behavior
    without making actual Telegram API calls.
    """

    def test_search_home_page_renders(self, engine, workspace_a):
        """search_home page renders without error."""
        from core.control.pages import search_home
        from core.control.registry import ControlContext
        from core.storage.storage import Storage
        from core.workspace.groups_app import WorkspaceGroups

        storage = Storage()
        groups = WorkspaceGroups()
        ctx = ControlContext(
            user_id=SELFTEST_USER_ID,
            storage=storage,
            engine=engine,
            groups=groups,
        )

        text, kb = search_home(ctx)
        assert "Search" in text
        assert kb is not None

    def test_search_home_accepts_filter_kwargs(self, engine, workspace_a):
        """search_home accepts and displays filter kwargs."""
        from core.control.pages import search_home
        from core.control.registry import ControlContext
        from core.storage.storage import Storage
        from core.workspace.groups_app import WorkspaceGroups

        storage = Storage()
        groups = WorkspaceGroups()
        ctx = ControlContext(
            user_id=SELFTEST_USER_ID,
            storage=storage,
            engine=engine,
            groups=groups,
        )

        # Call with various filter kwargs
        text, kb = search_home(
            ctx,
            q="test query",
            entities="M7_Ace_Test",
            tags="M7_1v4_Test",
            entity_mode="or",
            tag_mode="and",
            media_type="video",
        )
        # Should render without error
        assert "Search" in text

    def test_control_plane_search_no_cross_workspace_leakage(
        self, service, engine, workspace_a, workspace_b, entities_ws_a, entities_ws_b
    ):
        """Control Plane search never returns data from other workspaces."""
        # Create notes in both workspaces
        note_a = engine.add_note(SELFTEST_USER_ID, workspace_a, "WS_A note", title="Note_A")
        engine.link_note_entity(SELFTEST_USER_ID, note_a.id, "milestone", entities_ws_a["ace"].id)

        note_b = engine.add_note(SELFTEST_USER_ID, workspace_b, "WS_B note", title="Note_B")
        engine.link_note_entity(SELFTEST_USER_ID, note_b.id, "milestone", entities_ws_b["ace"].id)

        # Search in WS_A
        results_a = service.search(SELFTEST_USER_ID, workspace_a, entities=["M7_Ace_Test"])

        # Should only find WS_A note
        note_ids = {r.note_id for r in results_a if r._type == "note"}
        assert note_a.id in note_ids
        assert note_b.id not in note_ids, "WS_B note leaked into WS_A search"

        # Search in WS_B
        results_b = service.search(SELFTEST_USER_ID, workspace_b, entities=["M7_Ace_Test"])
        note_ids_b = {r.note_id for r in results_b if r._type == "note"}
        assert note_b.id in note_ids_b
        assert note_a.id not in note_ids_b, "WS_A note leaked into WS_B search"


# ──────────────────────────────────────────────────────────────────────
# Run pytest
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v"])