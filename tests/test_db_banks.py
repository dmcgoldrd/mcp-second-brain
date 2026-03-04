"""Tests for src.db.banks — Bank CRUD operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

from tests.conftest import TEST_USER_ID

VALID_USER_ID = TEST_USER_ID


def _patch_pool(mock_pool):
    return patch("src.db.banks.get_pool", new_callable=AsyncMock, return_value=mock_pool)


# ===== get_user_banks =====


class TestGetUserBanks:
    async def test_returns_list_of_banks(self):
        from src.db.banks import get_user_banks

        fake_rows = [
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
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=fake_rows)

        with _patch_pool(mock_pool):
            result = await get_user_banks(VALID_USER_ID)

        assert len(result) == 2
        assert result[0]["name"] == "Default"
        assert result[1]["slug"] == "work"

    async def test_returns_empty_for_invalid_uuid(self):
        from src.db.banks import get_user_banks

        result = await get_user_banks("not-a-uuid")
        assert result == []

    async def test_returns_empty_when_no_banks(self):
        from src.db.banks import get_user_banks

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        with _patch_pool(mock_pool):
            result = await get_user_banks(VALID_USER_ID)

        assert result == []


# ===== get_bank_by_slug =====


class TestGetBankBySlug:
    async def test_returns_bank(self):
        from src.db.banks import get_bank_by_slug

        fake_row = {
            "id": uuid.uuid4(),
            "name": "Work",
            "slug": "work",
            "is_default": False,
            "created_at": datetime(2024, 6, 1),
        }
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=fake_row)

        with _patch_pool(mock_pool):
            result = await get_bank_by_slug(VALID_USER_ID, "work")

        assert result["slug"] == "work"

    async def test_returns_none_when_not_found(self):
        from src.db.banks import get_bank_by_slug

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with _patch_pool(mock_pool):
            result = await get_bank_by_slug(VALID_USER_ID, "nonexistent")

        assert result is None

    async def test_returns_none_for_invalid_uuid(self):
        from src.db.banks import get_bank_by_slug

        result = await get_bank_by_slug("bad-uuid", "work")
        assert result is None


# ===== get_default_bank =====


class TestGetDefaultBank:
    async def test_returns_default_bank(self):
        from src.db.banks import get_default_bank

        fake_row = {
            "id": uuid.uuid4(),
            "name": "Default",
            "slug": "default",
            "is_default": True,
            "created_at": datetime(2024, 1, 1),
        }
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=fake_row)

        with _patch_pool(mock_pool):
            result = await get_default_bank(VALID_USER_ID)

        assert result["is_default"] is True

    async def test_returns_none_when_no_default(self):
        from src.db.banks import get_default_bank

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with _patch_pool(mock_pool):
            result = await get_default_bank(VALID_USER_ID)

        assert result is None

    async def test_returns_none_for_invalid_uuid(self):
        from src.db.banks import get_default_bank

        result = await get_default_bank("bad-uuid")
        assert result is None


# ===== create_bank =====


class TestCreateBank:
    async def test_creates_and_returns_bank(self):
        from src.db.banks import create_bank

        fake_row = {
            "id": uuid.uuid4(),
            "name": "Research",
            "slug": "research",
            "is_default": False,
            "created_at": datetime.utcnow(),
        }
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=fake_row)

        with _patch_pool(mock_pool):
            result = await create_bank(VALID_USER_ID, "Research", "research")

        assert result["name"] == "Research"
        assert result["slug"] == "research"
        assert result["is_default"] is False

    async def test_returns_error_for_invalid_uuid(self):
        from src.db.banks import create_bank

        result = await create_bank("bad-uuid", "Test", "test")
        assert "error" in result

    async def test_returns_empty_when_no_row(self):
        from src.db.banks import create_bank

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with _patch_pool(mock_pool):
            result = await create_bank(VALID_USER_ID, "Test", "test")

        assert result == {}
