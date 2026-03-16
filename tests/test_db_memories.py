"""Tests for src.db.memories — Memory CRUD + hybrid search."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import FAKE_EMBEDDING, TEST_BANK_ID, TEST_USER_ID

VALID_USER_ID = TEST_USER_ID
VALID_BANK_ID = TEST_BANK_ID
VALID_MEMORY_ID = str(uuid.uuid4())


def _patch_pool(mock_pool):
    """Return a context manager that patches get_pool to return mock_pool."""
    return patch("src.db.memories.get_pool", new_callable=AsyncMock, return_value=mock_pool)


class _AsyncCtx:
    """Minimal async context manager wrapper for mocks."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *args):
        return False


def _make_transactional_pool(fetchrow_return=None):
    """Create a mock pool that supports pool.acquire() → conn.transaction() → conn.fetchrow()."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    conn.transaction = MagicMock(return_value=_AsyncCtx(None))

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

    return pool, conn


# ===== create_memory =====


class TestCreateMemory:
    async def test_inserts_and_returns_row(self):
        from src.db.memories import create_memory

        fake_row = {
            "id": uuid.uuid4(),
            "content": "hello",
            "metadata": {},
            "memory_type": "observation",
            "tags": [],
            "source": "mcp",
            "created_at": datetime.utcnow(),
        }
        pool, conn = _make_transactional_pool(fetchrow_return=fake_row)

        with _patch_pool(pool):
            result = await create_memory(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                content="hello",
                embedding=FAKE_EMBEDDING,
                metadata={"key": "val"},
                memory_type="observation",
                tags=["test"],
                source="mcp",
            )

        assert result["content"] == "hello"
        assert result["memory_type"] == "observation"
        conn.fetchrow.assert_called_once()

    async def test_defaults_metadata_to_empty_dict(self):
        from src.db.memories import create_memory

        pool, conn = _make_transactional_pool(fetchrow_return={"id": uuid.uuid4()})

        with _patch_pool(pool):
            await create_memory(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                content="test",
                embedding=FAKE_EMBEDDING,
            )

        call_args = conn.fetchrow.call_args
        # metadata arg (index 6 in positional args — query, id, user_uuid, bank_uuid, content, embedding, metadata)
        # Passed as JSON string for $6::jsonb parameter
        assert call_args.args[6] == "{}"

    async def test_defaults_tags_to_empty_list(self):
        from src.db.memories import create_memory

        pool, conn = _make_transactional_pool(fetchrow_return={"id": uuid.uuid4()})

        with _patch_pool(pool):
            await create_memory(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                content="test",
                embedding=FAKE_EMBEDDING,
            )

        call_args = conn.fetchrow.call_args
        # tags arg (index 8)
        assert call_args.args[8] == []

    async def test_returns_empty_dict_when_no_row(self):
        from src.db.memories import create_memory

        pool, _conn = _make_transactional_pool(fetchrow_return=None)

        with _patch_pool(pool):
            result = await create_memory(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                content="test",
                embedding=FAKE_EMBEDDING,
            )

        assert result == {}

    async def test_invalid_uuid_returns_error(self):
        from src.db.memories import create_memory

        # create_memory validates UUIDs before calling get_pool
        result = await create_memory(
            user_id="not-a-uuid",
            bank_id=VALID_BANK_ID,
            content="test",
            embedding=FAKE_EMBEDDING,
        )

        assert "error" in result

    async def test_memory_limit_enforced_atomically(self):
        """F-05: Atomic limit check via SELECT FOR UPDATE."""
        from src.db.memories import create_memory

        pool, conn = _make_transactional_pool()
        # First fetchrow = limit check (returns count at limit)
        # No second fetchrow because limit is exceeded
        conn.fetchrow = AsyncMock(return_value={"memory_count": 1000})

        with _patch_pool(pool):
            result = await create_memory(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                content="test",
                embedding=FAKE_EMBEDDING,
                memory_limit=1000,
            )

        assert result["error"] == "memory_limit_reached"
        assert result["count"] == 1000


# ===== search_memories =====


class TestSearchMemories:
    async def test_hybrid_search_with_text(self):
        from src.db.memories import search_memories

        fake_rows = [
            {
                "id": uuid.uuid4(),
                "content": "match",
                "score": 0.9,
                "metadata": {},
                "memory_type": "observation",
                "tags": [],
                "source": "mcp",
                "created_at": datetime.utcnow(),
            },
        ]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=fake_rows)

        with _patch_pool(mock_pool):
            results = await search_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                query_embedding=FAKE_EMBEDDING,
                query_text="match",
                limit=5,
            )

        assert len(results) == 1
        assert results[0]["content"] == "match"
        call_sql = mock_pool.fetch.call_args.args[0]
        assert "hybrid_search" in call_sql

    async def test_semantic_search_without_text(self):
        from src.db.memories import search_memories

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            results = await search_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                query_embedding=FAKE_EMBEDDING,
                query_text="",
                limit=10,
            )

        assert results == []
        call_sql = mock_pool.fetch.call_args.args[0]
        assert "embedding <=>" in call_sql

    async def test_returns_list_of_dicts(self):
        from src.db.memories import search_memories

        fake_rows = [{"id": uuid.uuid4(), "content": "a"}, {"id": uuid.uuid4(), "content": "b"}]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=fake_rows)

        with _patch_pool(mock_pool):
            results = await search_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                query_embedding=FAKE_EMBEDDING,
                query_text="test",
            )

        assert len(results) == 2
        assert all(isinstance(r, dict) for r in results)

    async def test_invalid_uuid_returns_empty(self):
        from src.db.memories import search_memories

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            results = await search_memories(
                user_id="bad-uuid",
                bank_id=VALID_BANK_ID,
                query_embedding=FAKE_EMBEDDING,
                query_text="test",
            )

        assert results == []


# ===== list_memories =====


class TestListMemories:
    async def test_list_without_type_filter(self):
        from src.db.memories import list_memories

        fake_rows = [
            {"id": uuid.uuid4(), "content": "mem1"},
            {"id": uuid.uuid4(), "content": "mem2"},
        ]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=fake_rows)

        with _patch_pool(mock_pool):
            results = await list_memories(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, limit=20, offset=0
            )

        assert len(results) == 2

    async def test_list_with_type_filter(self):
        from src.db.memories import list_memories

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            await list_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                limit=10,
                offset=0,
                memory_type="task",
            )

        call_sql = mock_pool.fetch.call_args.args[0]
        assert "memory_type" in call_sql

    async def test_list_passes_correct_args(self):
        from src.db.memories import list_memories

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            await list_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                limit=5,
                offset=10,
            )

        call_args = mock_pool.fetch.call_args.args
        assert 5 in call_args
        assert 10 in call_args

    async def test_invalid_uuid_returns_empty(self):
        from src.db.memories import list_memories

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            results = await list_memories(user_id="bad", bank_id=VALID_BANK_ID)

        assert results == []


# ===== delete_memory =====


class TestDeleteMemory:
    async def test_returns_true_on_delete(self):
        from src.db.memories import delete_memory

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value="DELETE 1")

        with _patch_pool(mock_pool):
            result = await delete_memory(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, memory_id=VALID_MEMORY_ID
            )

        assert result is True

    async def test_returns_false_when_not_found(self):
        from src.db.memories import delete_memory

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value="DELETE 0")

        with _patch_pool(mock_pool):
            result = await delete_memory(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, memory_id=VALID_MEMORY_ID
            )

        assert result is False

    async def test_invalid_uuid_returns_false(self):
        from src.db.memories import delete_memory

        # delete_memory validates UUIDs before calling get_pool
        result = await delete_memory(
            user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, memory_id="bad-uuid"
        )
        assert result is False


# ===== get_memory_stats =====


class TestGetMemoryStats:
    async def test_returns_stats_dict(self):
        from src.db.memories import get_memory_stats

        fake_row = {
            "total_memories": 42,
            "type_count": 3,
            "oldest_memory": datetime(2024, 1, 1),
            "newest_memory": datetime(2024, 6, 1),
            "type_breakdown": {"observation": 20, "task": 15, "idea": 7},
        }
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=fake_row)

        with _patch_pool(mock_pool):
            result = await get_memory_stats(user_id=VALID_USER_ID, bank_id=VALID_BANK_ID)

        assert result["total_memories"] == 42
        assert result["type_breakdown"]["observation"] == 20

    async def test_returns_default_when_no_row(self):
        from src.db.memories import get_memory_stats

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with _patch_pool(mock_pool):
            result = await get_memory_stats(user_id=VALID_USER_ID, bank_id=VALID_BANK_ID)

        assert result == {"total_memories": 0}

    async def test_invalid_uuid_returns_default(self):
        from src.db.memories import get_memory_stats

        # get_memory_stats validates UUIDs before calling get_pool
        result = await get_memory_stats(user_id="not-uuid", bank_id=VALID_BANK_ID)
        assert result == {"total_memories": 0}


# ===== find_similar =====


class TestFindSimilar:
    async def test_find_similar_returns_matches_above_threshold(self):
        from src.db.memories import find_similar

        fake_rows = [
            {
                "id": uuid.uuid4(),
                "content": "similar memory",
                "memory_type": "observation",
                "tags": ["test"],
                "created_at": datetime.utcnow(),
                "similarity": 0.92,
            },
        ]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=fake_rows)

        with _patch_pool(mock_pool):
            results = await find_similar(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                embedding=FAKE_EMBEDDING,
                threshold=0.85,
                limit=5,
            )

        assert len(results) == 1
        assert results[0]["similarity"] == 0.92
        assert results[0]["content"] == "similar memory"

    async def test_find_similar_returns_empty_for_no_matches(self):
        from src.db.memories import find_similar

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            results = await find_similar(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                embedding=FAKE_EMBEDDING,
                threshold=0.99,
            )

        assert results == []

    async def test_find_similar_returns_empty_for_invalid_uuid(self):
        from src.db.memories import find_similar

        # find_similar validates UUIDs before calling get_pool
        results = await find_similar(
            user_id="bad-uuid",
            bank_id=VALID_BANK_ID,
            embedding=FAKE_EMBEDDING,
        )

        assert results == []

    async def test_find_similar_excludes_archived(self):
        from src.db.memories import find_similar

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            await find_similar(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                embedding=FAKE_EMBEDDING,
            )

        call_sql = mock_pool.fetch.call_args.args[0]
        assert "archived_at IS NULL" in call_sql


# ===== batch_create_memories =====


class TestBatchCreateMemories:
    async def test_batch_creates_multiple_memories(self):
        from src.db.memories import batch_create_memories

        id1, id2 = uuid.uuid4(), uuid.uuid4()
        pool, conn = _make_transactional_pool()
        conn.fetchrow = AsyncMock(side_effect=[{"id": id1}, {"id": id2}])

        items = [
            ("memory one", FAKE_EMBEDDING, {"key": "val"}, "observation", ["tag1"], "mcp"),
            ("memory two", FAKE_EMBEDDING, None, "task", None, "api"),
        ]

        with _patch_pool(pool):
            result = await batch_create_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                items=items,
            )

        assert len(result) == 2
        assert str(id1) in result
        assert str(id2) in result
        assert conn.fetchrow.call_count == 2

    async def test_batch_respects_memory_limit(self):
        from src.db.memories import batch_create_memories

        pool, conn = _make_transactional_pool()
        # Limit check returns count at capacity — adding 2 items would exceed limit of 100
        conn.fetchrow = AsyncMock(return_value={"memory_count": 99})

        items = [
            ("memory one", FAKE_EMBEDDING, None, "observation", None, "mcp"),
            ("memory two", FAKE_EMBEDDING, None, "observation", None, "mcp"),
        ]

        with _patch_pool(pool):
            result = await batch_create_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                items=items,
                memory_limit=100,
            )

        assert result == []

    async def test_batch_returns_empty_for_no_items(self):
        from src.db.memories import batch_create_memories

        # Empty items list returns early without touching the pool
        result = await batch_create_memories(
            user_id=VALID_USER_ID,
            bank_id=VALID_BANK_ID,
            items=[],
        )

        assert result == []

    async def test_batch_returns_empty_for_invalid_uuid(self):
        from src.db.memories import batch_create_memories

        items = [
            ("memory", FAKE_EMBEDDING, None, "observation", None, "mcp"),
        ]

        # batch_create_memories validates UUIDs before calling get_pool
        result = await batch_create_memories(
            user_id="bad-uuid",
            bank_id=VALID_BANK_ID,
            items=items,
        )

        assert result == []


# ===== _update_access_counts =====


class TestUpdateAccessCounts:
    async def test_updates_access_counts_for_memory_ids(self):
        from src.db.memories import _update_access_counts

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value="UPDATE 3")

        memory_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

        await _update_access_counts(mock_pool, memory_ids)

        mock_pool.execute.assert_called_once()
        call_sql = mock_pool.execute.call_args.args[0]
        assert "access_count" in call_sql
        assert "last_accessed_at" in call_sql
        assert mock_pool.execute.call_args.args[1] == memory_ids

    async def test_logs_warning_on_failure(self):
        from src.db.memories import _update_access_counts

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(side_effect=Exception("connection lost"))

        # Should not raise — errors are caught and logged
        await _update_access_counts(mock_pool, [uuid.uuid4()])
