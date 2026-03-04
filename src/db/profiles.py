"""Profile and subscription queries."""

from __future__ import annotations

import uuid
from typing import Any

from src.db.connection import get_pool


async def get_profile(user_id: str) -> dict[str, Any] | None:
    """Get a user's profile including subscription status and memory count."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, subscription_status, memory_count, created_at
        FROM profiles
        WHERE id = $1::uuid
        """,
        uuid.UUID(user_id),
    )
    return dict(row) if row else None


async def get_memory_count(user_id: str) -> int:
    """Get the current memory count for a user."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT memory_count FROM profiles WHERE id = $1::uuid",
        uuid.UUID(user_id),
    )
    return row["memory_count"] if row else 0


async def is_subscription_active(user_id: str) -> bool:
    """Check if user has an active paid subscription."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT subscription_status FROM profiles WHERE id = $1::uuid",
        uuid.UUID(user_id),
    )
    return row["subscription_status"] == "active" if row else False
