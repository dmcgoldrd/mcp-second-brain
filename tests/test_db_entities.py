"""Tests for src.db.entities — Entity queries + FTS."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

from tests.conftest import TEST_BANK_ID, TEST_USER_ID

VALID_USER_ID = TEST_USER_ID
VALID_BANK_ID = TEST_BANK_ID


def _patch_pool(mock_pool):
    """Return a context manager that patches get_pool to return mock_pool."""
    return patch("src.db.entities.get_pool", new_callable=AsyncMock, return_value=mock_pool)


# ===== get_entities =====


class TestGetEntities:
    async def test_get_entities_returns_all_for_user(self):
        from src.db.entities import get_entities

        fake_rows = [
            {
                "id": uuid.uuid4(),
                "entity_name": "Python",
                "entity_type": "technology",
                "facts": ["general purpose language"],
                "memory_ids": [uuid.uuid4()],
                "metadata": {},
                "created_at": datetime(2024, 6, 1),
                "updated_at": datetime(2024, 6, 2),
            },
            {
                "id": uuid.uuid4(),
                "entity_name": "Alice",
                "entity_type": "person",
                "facts": ["works at Acme"],
                "memory_ids": [uuid.uuid4()],
                "metadata": {},
                "created_at": datetime(2024, 5, 1),
                "updated_at": datetime(2024, 5, 2),
            },
        ]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=fake_rows)

        with _patch_pool(mock_pool):
            results = await get_entities(user_id=VALID_USER_ID, bank_id=VALID_BANK_ID)

        assert len(results) == 2
        assert results[0]["entity_name"] == "Python"
        assert results[1]["entity_name"] == "Alice"
        mock_pool.fetch.assert_called_once()

    async def test_get_entities_filters_by_type(self):
        from src.db.entities import get_entities

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            await get_entities(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                entity_type="person",
            )

        call_sql = mock_pool.fetch.call_args.args[0]
        assert "entity_type" in call_sql
        # entity_type value should be passed as a positional arg
        assert "person" in mock_pool.fetch.call_args.args

    async def test_get_entities_searches_by_query_fts(self):
        from src.db.entities import get_entities

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            await get_entities(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                query="Python",
            )

        call_sql = mock_pool.fetch.call_args.args[0]
        assert "plainto_tsquery" in call_sql
        assert "Python" in mock_pool.fetch.call_args.args

    async def test_get_entities_returns_empty_for_invalid_uuid(self):
        from src.db.entities import get_entities

        # Invalid UUID should short-circuit — no pool call needed
        results = await get_entities(user_id="not-a-uuid", bank_id=VALID_BANK_ID)

        assert results == []

    async def test_get_entities_filters_by_type_and_query(self):
        """Both entity_type and query provided — SQL should contain both conditions."""
        from src.db.entities import get_entities

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            await get_entities(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                query="Alice",
                entity_type="person",
            )

        call_sql = mock_pool.fetch.call_args.args[0]
        assert "plainto_tsquery" in call_sql
        assert "entity_type" in call_sql


# ===== get_entity_memories =====


class TestGetEntityMemories:
    async def test_get_entity_memories_returns_linked_memories(self):
        from src.db.entities import get_entity_memories

        fake_rows = [
            {
                "id": uuid.uuid4(),
                "content": "Alice likes Python",
                "memory_type": "observation",
                "tags": ["people"],
                "source": "mcp",
                "created_at": datetime(2024, 6, 1),
            },
        ]
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=fake_rows)

        with _patch_pool(mock_pool):
            results = await get_entity_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                entity_name="Alice",
            )

        assert len(results) == 1
        assert results[0]["content"] == "Alice likes Python"
        # Verify entity_name is passed in the query params
        assert "Alice" in mock_pool.fetch.call_args.args

    async def test_get_entity_memories_returns_empty_when_no_match(self):
        from src.db.entities import get_entity_memories

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            results = await get_entity_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                entity_name="NonExistentEntity",
            )

        assert results == []

    async def test_get_entity_memories_returns_empty_for_invalid_uuid(self):
        from src.db.entities import get_entity_memories

        results = await get_entity_memories(
            user_id="bad-uuid",
            bank_id=VALID_BANK_ID,
            entity_name="Alice",
        )

        assert results == []
