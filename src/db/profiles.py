"""Profile and subscription queries."""

from __future__ import annotations

from typing import Any

from src.db.connection import get_pool
from src.db.utils import parse_uuid
from src.models import SubscriptionStatus


async def get_profile(user_id: str) -> dict[str, Any] | None:
    """Get a user's profile including subscription status and memory count."""
    try:
        user_uuid = parse_uuid(user_id, "user_id")
    except ValueError:
        return None

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, subscription_status, memory_count, created_at
        FROM profiles
        WHERE id = $1::uuid
        """,
        user_uuid,
    )
    return dict(row) if row else None


async def get_memory_count(user_id: str) -> int:
    """Get the current memory count for a user."""
    try:
        user_uuid = parse_uuid(user_id, "user_id")
    except ValueError:
        return 0

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT memory_count FROM profiles WHERE id = $1::uuid",
        user_uuid,
    )
    return row["memory_count"] if row else 0


async def is_subscription_active(user_id: str) -> bool:
    """Check if user has an active paid subscription."""
    try:
        user_uuid = parse_uuid(user_id, "user_id")
    except ValueError:
        return False

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT subscription_status FROM profiles WHERE id = $1::uuid",
        user_uuid,
    )
    return row["subscription_status"] == SubscriptionStatus.ACTIVE if row else False


async def get_user_limits(user_id: str) -> tuple[bool, int]:
    """Get subscription status and memory count in one query."""
    try:
        user_uuid = parse_uuid(user_id, "user_id")
    except ValueError:
        return False, 0

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT subscription_status, memory_count FROM profiles WHERE id = $1::uuid",
        user_uuid,
    )
    if not row:
        return False, 0
    return row["subscription_status"] == SubscriptionStatus.ACTIVE, row["memory_count"]
