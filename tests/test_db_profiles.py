"""Tests for src.db.profiles — Profile and subscription queries."""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

from tests.conftest import TEST_USER_ID

VALID_USER_ID = TEST_USER_ID


def _patch_pool(mock_pool):
    return patch("src.db.profiles.get_pool", new_callable=AsyncMock, return_value=mock_pool)


# ===== get_profile =====


class TestGetProfile:
    async def test_returns_profile_dict(self):
        from src.db.profiles import get_profile

        fake_row = {
            "id": uuid.UUID(VALID_USER_ID),
            "subscription_status": "active",
            "memory_count": 42,
            "created_at": datetime(2024, 1, 1),
        }
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=fake_row)

        with _patch_pool(mock_pool):
            result = await get_profile(VALID_USER_ID)

        assert result["subscription_status"] == "active"
        assert result["memory_count"] == 42

    async def test_returns_none_when_not_found(self):
        from src.db.profiles import get_profile

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with _patch_pool(mock_pool):
            result = await get_profile(VALID_USER_ID)

        assert result is None


# ===== get_memory_count =====


class TestGetMemoryCount:
    async def test_returns_count(self):
        from src.db.profiles import get_memory_count

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"memory_count": 100})

        with _patch_pool(mock_pool):
            result = await get_memory_count(VALID_USER_ID)

        assert result == 100

    async def test_returns_zero_when_no_profile(self):
        from src.db.profiles import get_memory_count

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with _patch_pool(mock_pool):
            result = await get_memory_count(VALID_USER_ID)

        assert result == 0


# ===== is_subscription_active =====


class TestIsSubscriptionActive:
    async def test_returns_true_for_active(self):
        from src.db.profiles import is_subscription_active

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"subscription_status": "active"})

        with _patch_pool(mock_pool):
            result = await is_subscription_active(VALID_USER_ID)

        assert result is True

    async def test_returns_false_for_inactive(self):
        from src.db.profiles import is_subscription_active

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value={"subscription_status": "canceled"})

        with _patch_pool(mock_pool):
            result = await is_subscription_active(VALID_USER_ID)

        assert result is False

    async def test_returns_false_when_no_profile(self):
        from src.db.profiles import is_subscription_active

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        with _patch_pool(mock_pool):
            result = await is_subscription_active(VALID_USER_ID)

        assert result is False
