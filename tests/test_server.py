"""Tests for src.server — MCP tool definitions."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_BANK_ID, TEST_USER_ID

VALID_USER_ID = TEST_USER_ID
VALID_BANK_ID = TEST_BANK_ID

AUTH_CONTEXT = {"user_id": VALID_USER_ID, "bank_id": VALID_BANK_ID}


def _mock_token():
    """Create a mock AccessToken with sub claim."""
    token = MagicMock()
    token.claims = {"sub": VALID_USER_ID}
    token.scopes = []
    return token


# ===== _resolve_auth =====


class TestResolveAuth:
    async def test_extracts_user_id_from_token(self):
        from src.server import _resolve_auth

        token = _mock_token()
        with (
            patch("src.server.tool_limiter") as mock_limiter,
            patch("src.server.get_http_headers", return_value={}),
            patch(
                "src.server.banks_db.get_default_bank",
                new_callable=AsyncMock,
                return_value={"id": VALID_BANK_ID},
            ),
        ):
            mock_limiter.check.return_value = True
            result = await _resolve_auth(token)
        assert result["user_id"] == VALID_USER_ID
        assert result["bank_id"] == VALID_BANK_ID

    async def test_raises_when_no_sub_claim(self):
        from src.server import _resolve_auth

        token = MagicMock()
        token.claims = {}
        with pytest.raises(ValueError, match="No user ID"):
            await _resolve_auth(token)

    async def test_raises_when_rate_limited(self):
        from src.server import _resolve_auth

        token = _mock_token()
        with patch("src.server.tool_limiter") as mock_limiter:
            mock_limiter.check.return_value = False
            with pytest.raises(ValueError, match="Rate limit"):
                await _resolve_auth(token)

    async def test_resolves_bank_by_slug(self):
        from src.server import _resolve_auth

        token = _mock_token()
        bank_id = str(uuid.uuid4())
        with (
            patch("src.server.tool_limiter") as mock_limiter,
            patch("src.server.get_http_headers", return_value={"x-bank-slug": "work"}),
            patch(
                "src.server.banks_db.get_bank_by_slug",
                new_callable=AsyncMock,
                return_value={"id": bank_id},
            ),
        ):
            mock_limiter.check.return_value = True
            result = await _resolve_auth(token)
        assert result["bank_id"] == bank_id

    async def test_raises_when_bank_not_found(self):
        from src.server import _resolve_auth

        token = _mock_token()
        with (
            patch("src.server.tool_limiter") as mock_limiter,
            patch("src.server.get_http_headers", return_value={"x-bank-slug": "nonexistent"}),
            patch(
                "src.server.banks_db.get_bank_by_slug", new_callable=AsyncMock, return_value=None
            ),
        ):
            mock_limiter.check.return_value = True
            with pytest.raises(ValueError, match="not found"):
                await _resolve_auth(token)

    async def test_raises_when_no_default_bank(self):
        from src.server import _resolve_auth

        token = _mock_token()
        with (
            patch("src.server.tool_limiter") as mock_limiter,
            patch("src.server.get_http_headers", return_value={}),
            patch(
                "src.server.banks_db.get_default_bank", new_callable=AsyncMock, return_value=None
            ),
        ):
            mock_limiter.check.return_value = True
            with pytest.raises(ValueError, match="No default bank"):
                await _resolve_auth(token)


# ===== create_memory tool =====


class TestCreateMemoryTool:
    async def test_basic_create(self):
        from src.server import create_memory

        fake_result = {
            "status": "created",
            "memory_id": "abc123",
            "memory_type": "observation",
            "tags": [],
        }

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.create_memory",
                new_callable=AsyncMock,
                return_value=fake_result,
            ),
        ):
            result_str = await create_memory(content="test memory", token=_mock_token())

        result = json.loads(result_str)
        assert result["status"] == "created"

    async def test_with_json_metadata(self):
        from src.server import create_memory

        fake_result = {
            "status": "created",
            "memory_id": "abc",
            "memory_type": "observation",
            "tags": [],
        }

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.create_memory",
                new_callable=AsyncMock,
                return_value=fake_result,
            ) as mock_create,
        ):
            await create_memory(
                content="test", metadata='{"entities": ["Alice"]}', token=_mock_token()
            )

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["metadata"] == {"entities": ["Alice"]}

    async def test_with_invalid_json_metadata(self):
        from src.server import create_memory

        fake_result = {
            "status": "created",
            "memory_id": "abc",
            "memory_type": "observation",
            "tags": [],
        }

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.create_memory",
                new_callable=AsyncMock,
                return_value=fake_result,
            ) as mock_create,
        ):
            await create_memory(content="test", metadata="not json at all", token=_mock_token())

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["metadata"] == {"raw": "not json at all"}

    async def test_with_none_metadata(self):
        from src.server import create_memory

        fake_result = {
            "status": "created",
            "memory_id": "abc",
            "memory_type": "observation",
            "tags": [],
        }

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.create_memory",
                new_callable=AsyncMock,
                return_value=fake_result,
            ) as mock_create,
        ):
            await create_memory(content="test", metadata=None, token=_mock_token())

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["metadata"] is None

    async def test_passes_all_params(self):
        from src.server import create_memory

        fake_result = {
            "status": "created",
            "memory_id": "abc",
            "memory_type": "task",
            "tags": ["dev"],
        }

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.create_memory",
                new_callable=AsyncMock,
                return_value=fake_result,
            ) as mock_create,
        ):
            await create_memory(
                content="test content",
                memory_type="task",
                tags=["dev"],
                source="slack",
                token=_mock_token(),
            )

        mock_create.assert_called_once_with(
            user_id=VALID_USER_ID,
            bank_id=VALID_BANK_ID,
            content="test content",
            memory_type="task",
            tags=["dev"],
            metadata=None,
            source="slack",
        )

    async def test_content_too_long(self):
        from src.server import create_memory

        with patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT):
            result_str = await create_memory(content="x" * 100_000, token=_mock_token())

        result = json.loads(result_str)
        assert result["status"] == "error"
        assert result["error"] == "content_too_long"


# ===== search_memories tool =====


class TestSearchMemoriesTool:
    async def test_basic_search(self):
        from src.server import search_memories

        fake_results = [{"id": "abc", "content": "found", "score": 0.9}]

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.search_memories",
                new_callable=AsyncMock,
                return_value=fake_results,
            ),
        ):
            result_str = await search_memories(query="find this", token=_mock_token())

        results = json.loads(result_str)
        assert len(results) == 1
        assert results[0]["content"] == "found"

    async def test_clamps_limit(self):
        from src.server import search_memories

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.search_memories", new_callable=AsyncMock, return_value=[]
            ) as mock_search,
        ):
            await search_memories(query="test", limit=100, token=_mock_token())
            assert mock_search.call_args.kwargs["limit"] == 50

            mock_search.reset_mock()

            await search_memories(query="test", limit=0, token=_mock_token())
            assert mock_search.call_args.kwargs["limit"] == 1


# ===== list_memories tool =====


class TestListMemoriesTool:
    async def test_basic_list(self):
        from src.server import list_memories

        fake_results = [{"id": "abc", "content": "listed"}]

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.list_memories",
                new_callable=AsyncMock,
                return_value=fake_results,
            ),
        ):
            result_str = await list_memories(token=_mock_token())

        results = json.loads(result_str)
        assert len(results) == 1

    async def test_clamps_limit(self):
        from src.server import list_memories

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.list_memories", new_callable=AsyncMock, return_value=[]
            ) as mock_list,
        ):
            await list_memories(limit=200, token=_mock_token())
            assert mock_list.call_args.kwargs["limit"] == 100

            mock_list.reset_mock()

            await list_memories(limit=-5, token=_mock_token())
            assert mock_list.call_args.kwargs["limit"] == 1

    async def test_passes_all_params(self):
        from src.server import list_memories

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.list_memories", new_callable=AsyncMock, return_value=[]
            ) as mock_list,
        ):
            await list_memories(limit=10, offset=5, memory_type="idea", token=_mock_token())

        mock_list.assert_called_once_with(
            user_id=VALID_USER_ID,
            bank_id=VALID_BANK_ID,
            limit=10,
            offset=5,
            memory_type="idea",
        )


# ===== delete_memory tool =====


class TestDeleteMemoryTool:
    async def test_delete_returns_json(self):
        from src.server import delete_memory

        fake_result = {"status": "deleted", "memory_id": "abc"}

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.delete_memory",
                new_callable=AsyncMock,
                return_value=fake_result,
            ),
        ):
            result_str = await delete_memory(memory_id="abc", token=_mock_token())

        result = json.loads(result_str)
        assert result["status"] == "deleted"

    async def test_passes_user_bank_and_memory_id(self):
        from src.server import delete_memory

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.delete_memory", new_callable=AsyncMock, return_value={}
            ) as mock_del,
        ):
            await delete_memory(memory_id="mem-123", token=_mock_token())

        mock_del.assert_called_once_with(
            user_id=VALID_USER_ID, bank_id=VALID_BANK_ID, memory_id="mem-123"
        )


# ===== brain_stats tool =====


class TestBrainStatsTool:
    async def test_returns_json_stats(self):
        from src.server import brain_stats

        fake_stats = {"total_memories": 42, "type_breakdown": {"task": 20}}

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.get_stats", new_callable=AsyncMock, return_value=fake_stats
            ),
        ):
            result_str = await brain_stats(token=_mock_token())

        result = json.loads(result_str)
        assert result["total_memories"] == 42

    async def test_passes_user_and_bank_id(self):
        from src.server import brain_stats

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.memory_tools.get_stats", new_callable=AsyncMock, return_value={}
            ) as mock_stats,
        ):
            await brain_stats(token=_mock_token())

        mock_stats.assert_called_once_with(user_id=VALID_USER_ID, bank_id=VALID_BANK_ID)


# ===== list_banks tool =====


class TestListBanksTool:
    async def test_returns_banks_list(self):
        from datetime import datetime

        from src.server import list_banks

        fake_banks = [
            {
                "id": uuid.uuid4(),
                "name": "Default",
                "slug": "default",
                "is_default": True,
                "created_at": datetime(2024, 1, 1),
            },
            {
                "id": uuid.uuid4(),
                "name": "Work",
                "slug": "work",
                "is_default": False,
                "created_at": datetime(2024, 6, 1),
            },
        ]

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch(
                "src.server.banks_db.get_user_banks",
                new_callable=AsyncMock,
                return_value=fake_banks,
            ),
        ):
            result_str = await list_banks(token=_mock_token())

        results = json.loads(result_str)
        assert len(results) == 2
        assert results[0]["name"] == "Default"
        assert results[0]["is_default"] is True
        assert results[1]["slug"] == "work"


# ===== create_bank tool =====


class TestCreateBankTool:
    async def test_creates_bank(self):
        from src.server import create_bank

        fake_result = {"id": uuid.uuid4(), "name": "Work", "slug": "work"}

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch("src.server.is_subscription_active", new_callable=AsyncMock, return_value=False),
            patch(
                "src.server.banks_db.create_bank", new_callable=AsyncMock, return_value=fake_result
            ),
        ):
            result_str = await create_bank(name="Work", slug="work", token=_mock_token())

        result = json.loads(result_str)
        assert result["status"] == "created"
        assert result["name"] == "Work"
        assert result["slug"] == "work"

    async def test_returns_error_on_duplicate(self):
        from src.server import create_bank

        fake_result = {"error": "Bank slug 'work' already exists"}

        with (
            patch("src.server._resolve_auth", new_callable=AsyncMock, return_value=AUTH_CONTEXT),
            patch("src.server.is_subscription_active", new_callable=AsyncMock, return_value=False),
            patch(
                "src.server.banks_db.create_bank", new_callable=AsyncMock, return_value=fake_result
            ),
        ):
            result_str = await create_bank(name="Work", slug="work", token=_mock_token())

        result = json.loads(result_str)
        assert result["status"] == "error"
