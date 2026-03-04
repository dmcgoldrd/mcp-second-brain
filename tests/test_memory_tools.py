"""Tests for src.tools.memory_tools — business logic layer."""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import FAKE_EMBEDDING, TEST_BANK_ID, TEST_USER_ID

VALID_USER_ID = TEST_USER_ID
VALID_BANK_ID = TEST_BANK_ID
VALID_MEMORY_ID = str(uuid.uuid4())


def _enter_mock_deps(stack: ExitStack) -> None:
    """Enter rate limiter and subscription mocks into an ExitStack."""
    mock_limiter = MagicMock()
    mock_limiter.check.return_value = True
    stack.enter_context(patch("src.tools.memory_tools.embedding_limiter", mock_limiter))
    stack.enter_context(
        patch(
            "src.tools.memory_tools.is_subscription_active",
            new_callable=AsyncMock,
            return_value=False,
        )
    )


# ===== create_memory =====


class TestCreateMemory:
    async def test_creates_memory_with_auto_classify(self):
        from src.tools.memory_tools import create_memory

        fake_db_result = {"id": uuid.uuid4(), "content": "test"}

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embedding",
                    new_callable=AsyncMock,
                    return_value=FAKE_EMBEDDING,
                )
            )
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.create_memory",
                    new_callable=AsyncMock,
                    return_value=fake_db_result,
                )
            )

            result = await create_memory(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                content="todo: fix the bug",
            )

        assert result["status"] == "created"
        assert result["memory_type"] == "task"
        assert result["tags"] == []

    async def test_uses_provided_memory_type(self):
        from src.tools.memory_tools import create_memory

        fake_db_result = {"id": uuid.uuid4()}

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embedding",
                    new_callable=AsyncMock,
                    return_value=FAKE_EMBEDDING,
                )
            )
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.create_memory",
                    new_callable=AsyncMock,
                    return_value=fake_db_result,
                )
            )

            result = await create_memory(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                content="some content",
                memory_type="decision",
            )

        assert result["memory_type"] == "decision"

    async def test_merges_metadata(self):
        from src.tools.memory_tools import create_memory

        fake_db_result = {"id": uuid.uuid4()}
        captured_kwargs = {}

        async def capture_create(**kwargs):
            captured_kwargs.update(kwargs)
            return fake_db_result

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embedding",
                    new_callable=AsyncMock,
                    return_value=FAKE_EMBEDDING,
                )
            )
            stack.enter_context(
                patch("src.tools.memory_tools.db.create_memory", side_effect=capture_create)
            )

            await create_memory(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                content="hello world",
                metadata={"custom_key": "custom_val"},
            )

        assert "custom_key" in captured_kwargs["metadata"]
        assert "word_count" in captured_kwargs["metadata"]

    async def test_passes_tags_and_source(self):
        from src.tools.memory_tools import create_memory

        fake_db_result = {"id": uuid.uuid4()}
        captured_kwargs = {}

        async def capture_create(**kwargs):
            captured_kwargs.update(kwargs)
            return fake_db_result

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embedding",
                    new_callable=AsyncMock,
                    return_value=FAKE_EMBEDDING,
                )
            )
            stack.enter_context(
                patch("src.tools.memory_tools.db.create_memory", side_effect=capture_create)
            )

            await create_memory(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                content="test",
                tags=["python", "dev"],
                source="slack",
            )

        assert captured_kwargs["tags"] == ["python", "dev"]
        assert captured_kwargs["source"] == "slack"

    async def test_returns_memory_id_as_string(self):
        from src.tools.memory_tools import create_memory

        mem_id = uuid.uuid4()
        fake_db_result = {"id": mem_id}

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embedding",
                    new_callable=AsyncMock,
                    return_value=FAKE_EMBEDDING,
                )
            )
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.create_memory",
                    new_callable=AsyncMock,
                    return_value=fake_db_result,
                )
            )

            result = await create_memory(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, content="test"
            )

        assert result["memory_id"] == str(mem_id)

    async def test_memory_limit_reached(self):
        """F-05: Limit check now happens atomically in db.create_memory."""
        from src.tools.memory_tools import create_memory

        # db.create_memory returns limit error when count >= limit
        db_limit_error = {"error": "memory_limit_reached", "count": 1000, "limit": 1000}

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embedding",
                    new_callable=AsyncMock,
                    return_value=FAKE_EMBEDDING,
                )
            )
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.create_memory",
                    new_callable=AsyncMock,
                    return_value=db_limit_error,
                )
            )

            result = await create_memory(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, content="test"
            )

        assert result["status"] == "error"
        assert result["error"] == "memory_limit_reached"

    async def test_rate_limited(self):
        from src.tools.memory_tools import create_memory

        mock_limiter = MagicMock()
        mock_limiter.check.return_value = False

        with (
            patch("src.tools.memory_tools.embedding_limiter", mock_limiter),
            patch(
                "src.tools.memory_tools.is_subscription_active",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await create_memory(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, content="test"
            )

        assert result["status"] == "error"
        assert result["error"] == "rate_limited"


# ===== search_memories =====


class TestSearchMemories:
    async def test_returns_serialized_results(self):
        from src.tools.memory_tools import search_memories

        mock_limiter = MagicMock()
        mock_limiter.check.return_value = True
        mem_id = uuid.uuid4()
        fake_results = [
            {
                "id": mem_id,
                "content": "found it",
                "memory_type": "observation",
                "tags": ["tag1"],
                "score": 0.95,
                "created_at": datetime(2024, 6, 1, 12, 0),
            }
        ]

        with (
            patch("src.tools.memory_tools.embedding_limiter", mock_limiter),
            patch(
                "src.tools.memory_tools.generate_embedding",
                new_callable=AsyncMock,
                return_value=FAKE_EMBEDDING,
            ),
            patch(
                "src.tools.memory_tools.db.search_memories",
                new_callable=AsyncMock,
                return_value=fake_results,
            ),
        ):
            results = await search_memories(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, query="find it"
            )

        assert len(results) == 1
        assert results[0]["id"] == str(mem_id)
        assert results[0]["content"] == "found it"
        assert results[0]["score"] == 0.95
        assert results[0]["created_at"] == "2024-06-01T12:00:00"

    async def test_handles_empty_results(self):
        from src.tools.memory_tools import search_memories

        mock_limiter = MagicMock()
        mock_limiter.check.return_value = True

        with (
            patch("src.tools.memory_tools.embedding_limiter", mock_limiter),
            patch(
                "src.tools.memory_tools.generate_embedding",
                new_callable=AsyncMock,
                return_value=FAKE_EMBEDDING,
            ),
            patch(
                "src.tools.memory_tools.db.search_memories", new_callable=AsyncMock, return_value=[]
            ),
        ):
            results = await search_memories(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, query="nothing"
            )

        assert results == []

    async def test_passes_limit_to_db(self):
        from src.tools.memory_tools import search_memories

        mock_limiter = MagicMock()
        mock_limiter.check.return_value = True

        with (
            patch("src.tools.memory_tools.embedding_limiter", mock_limiter),
            patch(
                "src.tools.memory_tools.generate_embedding",
                new_callable=AsyncMock,
                return_value=FAKE_EMBEDDING,
            ),
            patch(
                "src.tools.memory_tools.db.search_memories", new_callable=AsyncMock, return_value=[]
            ) as mock_search,
        ):
            await search_memories(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, query="test", limit=5
            )

        mock_search.assert_called_once()
        assert mock_search.call_args.kwargs["limit"] == 5

    async def test_handles_missing_created_at(self):
        from src.tools.memory_tools import search_memories

        mock_limiter = MagicMock()
        mock_limiter.check.return_value = True
        fake_results = [
            {
                "id": uuid.uuid4(),
                "content": "no date",
                "memory_type": "observation",
                "tags": [],
                "score": 0.5,
            }
        ]

        with (
            patch("src.tools.memory_tools.embedding_limiter", mock_limiter),
            patch(
                "src.tools.memory_tools.generate_embedding",
                new_callable=AsyncMock,
                return_value=FAKE_EMBEDDING,
            ),
            patch(
                "src.tools.memory_tools.db.search_memories",
                new_callable=AsyncMock,
                return_value=fake_results,
            ),
        ):
            results = await search_memories(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, query="test"
            )

        assert results[0]["created_at"] is None

    async def test_defaults_missing_score_to_zero(self):
        from src.tools.memory_tools import search_memories

        mock_limiter = MagicMock()
        mock_limiter.check.return_value = True
        fake_results = [{"id": uuid.uuid4(), "content": "x", "tags": [], "created_at": None}]

        with (
            patch("src.tools.memory_tools.embedding_limiter", mock_limiter),
            patch(
                "src.tools.memory_tools.generate_embedding",
                new_callable=AsyncMock,
                return_value=FAKE_EMBEDDING,
            ),
            patch(
                "src.tools.memory_tools.db.search_memories",
                new_callable=AsyncMock,
                return_value=fake_results,
            ),
        ):
            results = await search_memories(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, query="test"
            )

        assert results[0]["score"] == 0.0

    async def test_rate_limited_returns_empty(self):
        from src.tools.memory_tools import search_memories

        mock_limiter = MagicMock()
        mock_limiter.check.return_value = False

        with patch("src.tools.memory_tools.embedding_limiter", mock_limiter):
            results = await search_memories(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, query="test"
            )

        assert results == []


# ===== list_memories =====


class TestListMemories:
    async def test_returns_serialized_list(self):
        from src.tools.memory_tools import list_memories

        mem_id = uuid.uuid4()
        fake_results = [
            {
                "id": mem_id,
                "content": "listed",
                "memory_type": "task",
                "tags": ["work"],
                "source": "mcp",
                "created_at": datetime(2024, 3, 1),
            }
        ]

        with patch(
            "src.tools.memory_tools.db.list_memories",
            new_callable=AsyncMock,
            return_value=fake_results,
        ):
            results = await list_memories(user_id=VALID_USER_ID, bank_id=VALID_BANK_ID)

        assert len(results) == 1
        assert results[0]["id"] == str(mem_id)
        assert results[0]["source"] == "mcp"

    async def test_passes_all_params(self):
        from src.tools.memory_tools import list_memories

        with patch(
            "src.tools.memory_tools.db.list_memories", new_callable=AsyncMock, return_value=[]
        ) as mock_list:
            await list_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                limit=5,
                offset=10,
                memory_type="idea",
            )

        mock_list.assert_called_once_with(
            user_id=VALID_USER_ID,
            bank_id=VALID_BANK_ID,
            limit=5,
            offset=10,
            memory_type="idea",
        )

    async def test_handles_missing_optional_fields(self):
        from src.tools.memory_tools import list_memories

        fake_results = [{"id": uuid.uuid4(), "content": "x"}]

        with patch(
            "src.tools.memory_tools.db.list_memories",
            new_callable=AsyncMock,
            return_value=fake_results,
        ):
            results = await list_memories(user_id=VALID_USER_ID, bank_id=VALID_BANK_ID)

        assert results[0]["memory_type"] == "observation"
        assert results[0]["source"] == "mcp"
        assert results[0]["created_at"] is None


# ===== delete_memory =====


class TestDeleteMemory:
    async def test_returns_deleted_status(self):
        from src.tools.memory_tools import delete_memory

        with patch(
            "src.tools.memory_tools.db.delete_memory", new_callable=AsyncMock, return_value=True
        ):
            result = await delete_memory(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, memory_id=VALID_MEMORY_ID
            )

        assert result["status"] == "deleted"
        assert result["memory_id"] == VALID_MEMORY_ID

    async def test_returns_not_found_status(self):
        from src.tools.memory_tools import delete_memory

        with patch(
            "src.tools.memory_tools.db.delete_memory", new_callable=AsyncMock, return_value=False
        ):
            result = await delete_memory(
                user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, memory_id=VALID_MEMORY_ID
            )

        assert result["status"] == "not_found"


# ===== get_stats =====


class TestGetStats:
    async def test_returns_formatted_stats(self):
        from src.tools.memory_tools import get_stats

        fake_stats = {
            "total_memories": 100,
            "type_breakdown": {"task": 50, "idea": 50},
            "oldest_memory": datetime(2024, 1, 1),
            "newest_memory": datetime(2024, 12, 31),
        }

        with patch(
            "src.tools.memory_tools.db.get_memory_stats",
            new_callable=AsyncMock,
            return_value=fake_stats,
        ):
            result = await get_stats(user_id=VALID_USER_ID, bank_id=VALID_BANK_ID)

        assert result["total_memories"] == 100
        assert result["type_breakdown"] == {"task": 50, "idea": 50}
        assert result["oldest_memory"] == "2024-01-01T00:00:00"
        assert result["newest_memory"] == "2024-12-31T00:00:00"

    async def test_handles_none_dates(self):
        from src.tools.memory_tools import get_stats

        fake_stats = {
            "total_memories": 0,
            "type_breakdown": {},
            "oldest_memory": None,
            "newest_memory": None,
        }

        with patch(
            "src.tools.memory_tools.db.get_memory_stats",
            new_callable=AsyncMock,
            return_value=fake_stats,
        ):
            result = await get_stats(user_id=VALID_USER_ID, bank_id=VALID_BANK_ID)

        assert result["oldest_memory"] is None
        assert result["newest_memory"] is None

    async def test_handles_missing_keys(self):
        from src.tools.memory_tools import get_stats

        fake_stats = {}

        with patch(
            "src.tools.memory_tools.db.get_memory_stats",
            new_callable=AsyncMock,
            return_value=fake_stats,
        ):
            result = await get_stats(user_id=VALID_USER_ID, bank_id=VALID_BANK_ID)

        assert result["total_memories"] == 0
        assert result["type_breakdown"] == {}
        assert result["oldest_memory"] is None
        assert result["newest_memory"] is None
