"""Tests for src.tools.memory_tools.import_memories — batch import business logic."""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import FAKE_EMBEDDING, TEST_BANK_ID, TEST_USER_ID

VALID_USER_ID = TEST_USER_ID
VALID_BANK_ID = TEST_BANK_ID


def _enter_mock_deps(stack: ExitStack, memory_count: int = 0) -> None:
    """Enter rate limiter and subscription/limits mocks into an ExitStack."""
    mock_limiter = MagicMock()
    mock_limiter.check.return_value = True
    stack.enter_context(patch("src.tools.memory_tools.embedding_limiter", mock_limiter))
    stack.enter_context(
        patch(
            "src.tools.memory_tools.get_user_limits",
            new_callable=AsyncMock,
            return_value=(False, memory_count),
        )
    )


# ===== import_memories =====


class TestImportMemories:
    async def test_import_creates_memories_with_batch_embedding(self):
        from src.tools.memory_tools import import_memories

        created_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            mock_gen = stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embeddings",
                    new_callable=AsyncMock,
                    return_value=[FAKE_EMBEDDING, FAKE_EMBEDDING],
                )
            )
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.find_similar",
                    new_callable=AsyncMock,
                    return_value=[],
                )
            )
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.batch_create_memories",
                    new_callable=AsyncMock,
                    return_value=created_ids,
                )
            )

            result = await import_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                memories=[
                    {"content": "memory one"},
                    {"content": "memory two"},
                ],
            )

        assert result["status"] == "imported"
        assert result["created"] == 2
        assert result["skipped"] == 0
        assert result["memory_ids"] == created_ids
        # Batch embedding called once with both contents
        mock_gen.assert_called_once_with(["memory one", "memory two"])

    async def test_import_deduplicates_when_similar_found(self):
        from src.tools.memory_tools import import_memories

        existing_id = uuid.uuid4()
        similar_match = [
            {
                "id": existing_id,
                "content": "already exists",
                "similarity": 0.95,
            }
        ]

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embeddings",
                    new_callable=AsyncMock,
                    return_value=[FAKE_EMBEDDING],
                )
            )
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.find_similar",
                    new_callable=AsyncMock,
                    return_value=similar_match,
                )
            )
            mock_batch = stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.batch_create_memories",
                    new_callable=AsyncMock,
                    return_value=[],
                )
            )

            result = await import_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                memories=[{"content": "duplicate content"}],
                deduplicate=True,
            )

        assert result["status"] == "imported"
        assert result["created"] == 0
        assert result["skipped"] == 1
        assert len(result["conflicts"]) == 1
        assert result["conflicts"][0]["similar_memory_id"] == str(existing_id)
        assert result["conflicts"][0]["similarity"] == 0.95
        # batch_create called with empty items list
        mock_batch.assert_called_once()

    async def test_import_skips_dedup_when_disabled(self):
        from src.tools.memory_tools import import_memories

        created_ids = [str(uuid.uuid4())]

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embeddings",
                    new_callable=AsyncMock,
                    return_value=[FAKE_EMBEDDING],
                )
            )
            mock_find_similar = stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.find_similar",
                    new_callable=AsyncMock,
                    return_value=[],
                )
            )
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.batch_create_memories",
                    new_callable=AsyncMock,
                    return_value=created_ids,
                )
            )

            result = await import_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                memories=[{"content": "new content"}],
                deduplicate=False,
            )

        assert result["created"] == 1
        assert result["skipped"] == 0
        # find_similar should NOT be called when deduplicate=False
        mock_find_similar.assert_not_called()

    async def test_import_respects_memory_limit(self):
        from src.tools.memory_tools import import_memories

        with ExitStack() as stack:
            # Pre-check returns count=1000, limit=1000 -> rejects before embedding
            _enter_mock_deps(stack, memory_count=1000)

            result = await import_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                memories=[{"content": "should not be imported"}],
            )

        assert result["status"] == "error"
        assert result["error"] == "memory_limit_reached"

    async def test_import_returns_conflict_info(self):
        from src.tools.memory_tools import import_memories

        existing_id = uuid.uuid4()
        # First memory is a duplicate, second is new
        find_similar_returns = [
            # Call 1: similar found (duplicate)
            [{"id": existing_id, "content": "exists", "similarity": 0.92}],
            # Call 2: no similar (new)
            [],
        ]

        with ExitStack() as stack:
            _enter_mock_deps(stack)
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.generate_embeddings",
                    new_callable=AsyncMock,
                    return_value=[FAKE_EMBEDDING, FAKE_EMBEDDING],
                )
            )
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.find_similar",
                    new_callable=AsyncMock,
                    side_effect=find_similar_returns,
                )
            )
            new_id = str(uuid.uuid4())
            stack.enter_context(
                patch(
                    "src.tools.memory_tools.db.batch_create_memories",
                    new_callable=AsyncMock,
                    return_value=[new_id],
                )
            )

            result = await import_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                memories=[
                    {"content": "duplicate content"},
                    {"content": "new content"},
                ],
                deduplicate=True,
            )

        assert result["created"] == 1
        assert result["skipped"] == 1
        assert "conflicts" in result
        assert result["conflicts"][0]["index"] == 0
        assert result["conflicts"][0]["similar_memory_id"] == str(existing_id)
        assert result["conflicts"][0]["similarity"] == 0.92
        assert result["conflicts"][0]["content_preview"] == "duplicate content"

    async def test_import_rate_limits(self):
        from src.tools.memory_tools import import_memories

        mock_limiter = MagicMock()
        mock_limiter.check.return_value = False

        with (
            patch("src.tools.memory_tools.embedding_limiter", mock_limiter),
            patch(
                "src.tools.memory_tools.get_user_limits",
                new_callable=AsyncMock,
                return_value=(False, 0),
            ),
        ):
            result = await import_memories(
                user_id=VALID_USER_ID,
                bank_id=VALID_BANK_ID,
                memories=[{"content": "test"}],
            )

        assert result["status"] == "error"
        assert result["error"] == "rate_limited"
