"""Bank CRUD operations against Supabase Postgres."""

from __future__ import annotations

import uuid
from typing import Any

from src.db.connection import get_pool


async def get_user_banks(user_id: str) -> list[dict[str, Any]]:
    """Get all banks for a user."""
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return []

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, slug, is_default, created_at
        FROM banks
        WHERE user_id = $1::uuid
        ORDER BY is_default DESC, created_at ASC
        """,
        user_uuid,
    )
    return [dict(row) for row in rows]


async def get_bank_by_slug(user_id: str, slug: str) -> dict[str, Any] | None:
    """Get a specific bank by user_id and slug."""
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return None

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, slug, is_default, created_at
        FROM banks
        WHERE user_id = $1::uuid AND slug = $2
        """,
        user_uuid,
        slug,
    )
    return dict(row) if row else None


async def get_default_bank(user_id: str) -> dict[str, Any] | None:
    """Get the user's default bank."""
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return None

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, slug, is_default, created_at
        FROM banks
        WHERE user_id = $1::uuid AND is_default = true
        """,
        user_uuid,
    )
    return dict(row) if row else None


async def count_user_banks(user_id: str) -> int:
    """Count the number of banks for a user."""
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return 0

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM banks WHERE user_id = $1::uuid",
        user_uuid,
    )
    return row["cnt"] if row else 0


async def create_bank(user_id: str, name: str, slug: str, max_banks: int = 10) -> dict[str, Any]:
    """Create a new bank for a user.

    Args:
        max_banks: Maximum number of banks allowed for this user.
                   Caller resolves this based on subscription status.

    Uses a transaction with row lock to prevent TOCTOU race (N-03).
    The DB also has a trigger (migration 004) as defense-in-depth (N-02).
    """
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return {"error": "Invalid user ID format"}

    pool = await get_pool()
    bank_uuid = uuid.uuid4()

    async with pool.acquire() as conn, conn.transaction():
        # N-03: Atomic limit check — lock the user's profile row
        row = await conn.fetchrow(
            "SELECT id FROM profiles WHERE id = $1::uuid FOR UPDATE",
            user_uuid,
        )

        # Count banks while holding the lock
        count_row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM banks WHERE user_id = $1::uuid",
            user_uuid,
        )
        current_count = count_row["cnt"] if count_row else 0

        if current_count >= max_banks:
            return {"error": f"Bank limit reached ({max_banks} banks maximum)"}

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO banks (id, user_id, name, slug, is_default)
                VALUES ($1, $2::uuid, $3, $4, false)
                RETURNING id, name, slug, is_default, created_at
                """,
                bank_uuid,
                user_uuid,
                name,
                slug,
            )
        except Exception as e:
            err_msg = str(e)
            if "unique" in err_msg.lower() or "duplicate" in err_msg.lower():
                return {"error": "Bank slug already exists"}
            raise

    return dict(row) if row else {}
