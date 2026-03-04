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
        assert call_args.args[6] == {}

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
