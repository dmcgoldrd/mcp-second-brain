"""Tests for src.consolidation — 5-phase nightly consolidation engine."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import TEST_BANK_ID, TEST_USER_ID

VALID_USER_ID = TEST_USER_ID
VALID_BANK_ID = TEST_BANK_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AsyncCtx:
    """Minimal async context manager wrapper for mocks."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        return False


def _make_pool_with_conn():
    """Create a mock pool that supports `async with pool.acquire() as conn:`."""
    conn = AsyncMock()
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AsyncCtx(conn))
    # Also mock pool.fetch/execute for consolidate_all_active_users
    pool.fetch = AsyncMock(return_value=[])
    pool.execute = AsyncMock()
    return pool, conn


def _patch_pool(mock_pool):
    """Return a context manager that patches get_pool to return mock_pool."""
    return patch("src.consolidation.get_pool", new_callable=AsyncMock, return_value=mock_pool)


def _patch_openai(mock_client):
    """Return a context manager that patches get_openai_client to return mock_client."""
    return patch("src.consolidation.get_openai_client", return_value=mock_client)


def _make_openai_chat_response(content: str):
    """Create a mock OpenAI chat completion response."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# Phase 1: Importance Scoring
# ---------------------------------------------------------------------------


class TestPhase1ImportanceScoring:
    async def test_scores_memories_based_on_recency_and_access(self):
        from src.consolidation import _phase_importance_scoring

        conn = AsyncMock()
        # SQL UPDATE returns "UPDATE 15" meaning 15 rows updated
        conn.execute = AsyncMock(return_value="UPDATE 15")

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        count = await _phase_importance_scoring(conn, user_uuid, bank_uuid)

        assert count == 15
        # Verify the UPDATE query was called with the correct UUIDs
        conn.execute.assert_any_call(
            conn.execute.call_args_list[0].args[0],
            user_uuid,
            bank_uuid,
        )
        # Verify a log action was written (second execute call)
        assert conn.execute.call_count == 2

    async def test_scoring_skips_archived_memories(self):
        from src.consolidation import _phase_importance_scoring

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 5")

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        await _phase_importance_scoring(conn, user_uuid, bank_uuid)

        # Verify the SQL contains the archived_at IS NULL filter
        sql = conn.execute.call_args_list[0].args[0]
        assert "archived_at IS NULL" in sql

    async def test_scoring_returns_count_updated(self):
        from src.consolidation import _phase_importance_scoring

        conn = AsyncMock()
        conn.execute = AsyncMock(return_value="UPDATE 0")

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        count = await _phase_importance_scoring(conn, user_uuid, bank_uuid)

        assert count == 0
        # When count is 0, no log action should be written
        assert conn.execute.call_count == 1


# ---------------------------------------------------------------------------
# Phase 2: Duplicate Merge
# ---------------------------------------------------------------------------


class TestPhase2DuplicateMerge:
    async def test_merges_high_similarity_pairs(self):
        from src.consolidation import _phase_duplicate_merge

        id_a = uuid.uuid4()
        id_b = uuid.uuid4()

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id_a": id_a,
                    "id_b": id_b,
                    "score_a": 0.8,
                    "score_b": 0.3,
                    "similarity": 0.95,
                }
            ]
        )
        conn.execute = AsyncMock()

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        merge_count = await _phase_duplicate_merge(conn, user_uuid, bank_uuid)

        assert merge_count == 1

    async def test_keeps_higher_scored_memory_as_survivor(self):
        from src.consolidation import _phase_duplicate_merge

        id_a = uuid.uuid4()
        id_b = uuid.uuid4()

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id_a": id_a,
                    "id_b": id_b,
                    "score_a": 0.3,
                    "score_b": 0.9,
                    "similarity": 0.92,
                }
            ]
        )
        conn.execute = AsyncMock()

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        await _phase_duplicate_merge(conn, user_uuid, bank_uuid)

        # The archive UPDATE should set superseded_by = id_b (higher score)
        # and archive id_a (lower score)
        archive_call = conn.execute.call_args_list[0]
        archive_sql = archive_call.args[0]
        assert "superseded_by" in archive_sql
        # survivor_id = id_b (score 0.9), loser_id = id_a (score 0.3)
        assert archive_call.args[1] == id_b  # superseded_by = survivor
        assert archive_call.args[2] == id_a  # WHERE id = loser

    async def test_archives_duplicate_with_superseded_by(self):
        from src.consolidation import _phase_duplicate_merge

        id_a = uuid.uuid4()
        id_b = uuid.uuid4()

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id_a": id_a,
                    "id_b": id_b,
                    "score_a": 0.7,
                    "score_b": 0.2,
                    "similarity": 0.93,
                }
            ]
        )
        conn.execute = AsyncMock()

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        await _phase_duplicate_merge(conn, user_uuid, bank_uuid)

        # First execute call is the archive UPDATE
        archive_call = conn.execute.call_args_list[0]
        archive_sql = archive_call.args[0]
        assert "archived_reason = 'duplicate'" in archive_sql
        assert "superseded_by" in archive_sql

    async def test_no_merge_below_threshold(self):
        from src.consolidation import _phase_duplicate_merge

        conn = AsyncMock()
        # No rows returned means no pairs above the similarity threshold
        conn.fetch = AsyncMock(return_value=[])

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        merge_count = await _phase_duplicate_merge(conn, user_uuid, bank_uuid)

        assert merge_count == 0
        # No execute calls should be made when there are no duplicate pairs
        conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 3: Conflict Resolution
# ---------------------------------------------------------------------------


class TestPhase3ConflictResolution:
    async def test_resolves_update_by_archiving_older(self):
        from src.consolidation import _phase_conflict_resolution

        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        now = datetime.now(UTC)

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id_a": id_a,
                    "content_a": "I prefer Python",
                    "created_a": now - timedelta(days=30),
                    "score_a": 0.5,
                    "type_a": "preference",
                    "id_b": id_b,
                    "content_b": "I prefer TypeScript",
                    "created_b": now,
                    "score_b": 0.8,
                    "type_b": "preference",
                    "similarity": 0.85,
                }
            ]
        )
        conn.execute = AsyncMock()

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_chat_response("UPDATE")
        )

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        with _patch_openai(mock_client):
            resolved = await _phase_conflict_resolution(conn, user_uuid, bank_uuid)

        assert resolved == 1
        # The older memory (id_a) should be archived, newer (id_b) kept
        archive_call = conn.execute.call_args_list[0]
        archive_sql = archive_call.args[0]
        assert "conflict_resolved" in archive_sql
        # newer_id = id_b, older_id = id_a
        assert archive_call.args[1] == id_b  # superseded_by = newer
        assert archive_call.args[2] == id_a  # WHERE id = older

    async def test_keeps_both_when_llm_says_keep(self):
        from src.consolidation import _phase_conflict_resolution

        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        now = datetime.now(UTC)

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id_a": id_a,
                    "content_a": "Meeting with Alice about project X",
                    "created_a": now - timedelta(days=10),
                    "score_a": 0.6,
                    "type_a": "observation",
                    "id_b": id_b,
                    "content_b": "Meeting with Alice about project Y",
                    "created_b": now,
                    "score_b": 0.7,
                    "type_b": "observation",
                    "similarity": 0.82,
                }
            ]
        )
        conn.execute = AsyncMock()

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_chat_response("KEEP_BOTH")
        )

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        with _patch_openai(mock_client):
            resolved = await _phase_conflict_resolution(conn, user_uuid, bank_uuid)

        assert resolved == 0
        # Only a log action should be written (no archive UPDATE)
        # The execute call should be the log INSERT, not an archive UPDATE
        for call in conn.execute.call_args_list:
            sql = call.args[0]
            assert "archived_at" not in sql

    async def test_defaults_to_keep_both_on_llm_error(self):
        from src.consolidation import _phase_conflict_resolution

        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        now = datetime.now(UTC)

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id_a": id_a,
                    "content_a": "Some content A",
                    "created_a": now - timedelta(days=5),
                    "score_a": 0.5,
                    "type_a": "observation",
                    "id_b": id_b,
                    "content_b": "Some content B",
                    "created_b": now,
                    "score_b": 0.6,
                    "type_b": "observation",
                    "similarity": 0.88,
                }
            ]
        )
        conn.execute = AsyncMock()

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API timeout"))

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        with _patch_openai(mock_client):
            resolved = await _phase_conflict_resolution(conn, user_uuid, bank_uuid)

        # On error, defaults to KEEP_BOTH so no memories archived
        assert resolved == 0


# ---------------------------------------------------------------------------
# Phase 4: Entity Extraction
# ---------------------------------------------------------------------------


class TestPhase4EntityExtraction:
    async def test_extracts_entities_from_memories(self):
        from src.consolidation import _phase_entity_extraction

        mem_id = uuid.uuid4()

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {
                    "id": mem_id,
                    "content": "Meeting with Alice at Google HQ",
                    "memory_type": "observation",
                }
            ]
        )
        conn.execute = AsyncMock()

        llm_response = json.dumps(
            {
                "entities": [
                    [
                        {"name": "Alice", "type": "person", "relationship": "met with"},
                        {
                            "name": "Google",
                            "type": "organization",
                            "relationship": "location of meeting",
                        },
                    ]
                ]
            }
        )

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_chat_response(llm_response)
        )

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        with _patch_openai(mock_client):
            total = await _phase_entity_extraction(conn, user_uuid, bank_uuid)

        assert total == 2

    async def test_upserts_entities_into_memory_entities_table(self):
        from src.consolidation import _phase_entity_extraction

        mem_id = uuid.uuid4()

        conn = AsyncMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"id": mem_id, "content": "Alice joined Stripe", "memory_type": "observation"}
            ]
        )
        conn.execute = AsyncMock()

        llm_response = json.dumps(
            {
                "entities": [
                    [
                        {"name": "Alice", "type": "person", "relationship": "joined company"},
                    ]
                ]
            }
        )

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_make_openai_chat_response(llm_response)
        )

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        with _patch_openai(mock_client):
            await _phase_entity_extraction(conn, user_uuid, bank_uuid)

        # Find the INSERT INTO memory_entities call
        entity_upsert_found = False
        for call in conn.execute.call_args_list:
            sql = call.args[0]
            if "INSERT INTO memory_entities" in sql:
                entity_upsert_found = True
                assert "ON CONFLICT" in sql
                # Verify the entity_name was passed as "Alice"
                assert call.args[3] == "Alice"
                assert call.args[4] == "person"
                break

        assert entity_upsert_found, "Expected an INSERT INTO memory_entities call"

    async def test_skips_memories_already_processed(self):
        from src.consolidation import _phase_entity_extraction

        conn = AsyncMock()
        # No rows returned means all memories already have entity metadata
        conn.fetch = AsyncMock(return_value=[])

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        # Should not even need the OpenAI client
        total = await _phase_entity_extraction(conn, user_uuid, bank_uuid)

        assert total == 0
        # No execute calls should be made
        conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 5: Archive Stale
# ---------------------------------------------------------------------------


class TestPhase5ArchiveStale:
    async def test_archives_old_low_importance_unaccessed_memories(self):
        from src.consolidation import _phase_archive_stale

        stale_id = uuid.uuid4()

        conn = AsyncMock()
        conn.fetch = AsyncMock(return_value=[{"id": stale_id}])
        conn.execute = AsyncMock()

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        archived = await _phase_archive_stale(conn, user_uuid, bank_uuid)

        assert archived == 1
        # Verify the SQL checks for low importance, old age, and zero access
        sql = conn.fetch.call_args.args[0]
        assert "importance_score" in sql
        assert "access_count" in sql
        assert "archived_reason = 'low_importance_decay'" in sql

    async def test_does_not_archive_recently_accessed(self):
        from src.consolidation import _phase_archive_stale

        conn = AsyncMock()
        # No rows returned means no memories met the stale criteria
        conn.fetch = AsyncMock(return_value=[])

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        archived = await _phase_archive_stale(conn, user_uuid, bank_uuid)

        assert archived == 0
        # No log action should be written when nothing was archived
        conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: consolidate_user
# ---------------------------------------------------------------------------


class TestConsolidateUser:
    async def test_consolidate_user_runs_all_phases(self):
        from src.consolidation import consolidate_user

        pool, conn = _make_pool_with_conn()

        # Phase 1: importance scoring
        # Phase 2: duplicate merge (fetch returns no pairs)
        # Phase 3: conflict resolution (fetch returns no pairs)
        # Phase 4: entity extraction (fetch returns no memories)
        # Phase 5: archive stale (fetch returns no rows)

        # conn.execute returns "UPDATE 10" for phase 1
        conn.execute = AsyncMock(return_value="UPDATE 10")
        # conn.fetch returns empty for phases 2-5
        conn.fetch = AsyncMock(return_value=[])

        with _patch_pool(pool):
            summary = await consolidate_user(VALID_USER_ID, VALID_BANK_ID)

        assert summary["user_id"] == VALID_USER_ID
        assert summary["bank_id"] == VALID_BANK_ID
        assert summary["scores_updated"] == 10
        assert summary["duplicates_merged"] == 0
        assert summary["conflicts_resolved"] == 0
        assert summary["entities_extracted"] == 0
        assert summary["stale_archived"] == 0
        assert summary["error"] is None
        assert "started_at" in summary
        assert "completed_at" in summary

    async def test_consolidate_user_logs_to_consolidation_log(self):
        from src.consolidation import consolidate_user

        pool, conn = _make_pool_with_conn()

        # Phase 1 scores 5 memories, triggering a log action
        execute_calls = []

        async def track_execute(*args, **kwargs):
            execute_calls.append(args)
            return "UPDATE 5"

        conn.execute = AsyncMock(side_effect=track_execute)
        conn.fetch = AsyncMock(return_value=[])

        with _patch_pool(pool):
            await consolidate_user(VALID_USER_ID, VALID_BANK_ID)

        # Find the consolidation_log INSERT among execute calls
        log_inserts = [
            call for call in execute_calls if len(call) > 0 and "consolidation_log" in call[0]
        ]
        assert len(log_inserts) > 0, "Expected at least one INSERT INTO consolidation_log"

    async def test_consolidate_user_handles_invalid_uuid(self):
        from src.consolidation import consolidate_user

        result = await consolidate_user("not-a-valid-uuid", VALID_BANK_ID)

        assert "error" in result
        assert "Invalid" in result["error"]

    async def test_consolidate_user_handles_phase_exception(self):
        from src.consolidation import consolidate_user

        pool, conn = _make_pool_with_conn()

        # Simulate a database error in phase 1
        conn.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with _patch_pool(pool):
            summary = await consolidate_user(VALID_USER_ID, VALID_BANK_ID)

        assert summary["error"] is not None
        assert "DB connection lost" in summary["error"]
        assert "completed_at" in summary


# ---------------------------------------------------------------------------
# Integration: consolidate_all_active_users
# ---------------------------------------------------------------------------


class TestConsolidateAllActiveUsers:
    async def test_consolidate_all_active_users_processes_active_users(self):
        from src.consolidation import consolidate_all_active_users

        user_uuid = uuid.UUID(VALID_USER_ID)
        bank_uuid = uuid.UUID(VALID_BANK_ID)

        pool, conn = _make_pool_with_conn()

        # pool.fetch returns one active user+bank pair
        pool.fetch = AsyncMock(return_value=[{"user_id": user_uuid, "bank_id": bank_uuid}])
        pool.execute = AsyncMock()

        # conn for the inner consolidate_user call
        conn.execute = AsyncMock(return_value="UPDATE 3")
        conn.fetch = AsyncMock(return_value=[])

        with _patch_pool(pool):
            results = await consolidate_all_active_users()

        assert results["users_processed"] == 1
        assert results["total_scores_updated"] == 3
        assert "started_at" in results
        assert "completed_at" in results
        # last_consolidation_at should be updated for the user
        pool.execute.assert_called_once()
        update_sql = pool.execute.call_args.args[0]
        assert "last_consolidation_at" in update_sql

    async def test_consolidate_all_no_active_users(self):
        from src.consolidation import consolidate_all_active_users

        pool, _conn = _make_pool_with_conn()
        pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(pool):
            results = await consolidate_all_active_users()

        assert results["users_processed"] == 0
        assert results["errors"] == []
        # No pool.execute call for updating last_consolidation_at
        pool.execute.assert_not_called()
