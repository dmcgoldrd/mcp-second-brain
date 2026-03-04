"""Memory CRUD operations against Supabase Postgres."""

from __future__ import annotations

import json
import uuid
from typing import Any

import numpy as np

from src.db.connection import get_pool


async def create_memory(
    user_id: str,
    bank_id: str,
    content: str,
    embedding: list[float],
    metadata: dict[str, Any] | None = None,
    memory_type: str = "observation",
    tags: list[str] | None = None,
    source: str = "mcp",
    memory_limit: int | None = None,
) -> dict[str, Any]:
    """Insert a new memory with its embedding.

    If memory_limit is provided, atomically checks the user's memory_count
    against the limit before inserting (F-05: prevents TOCTOU race).
    """
    try:
        user_uuid = uuid.UUID(user_id)
        bank_uuid = uuid.UUID(bank_id)
    except ValueError:
        return {"error": "Invalid user ID or bank ID format"}

    pool = await get_pool()
    memory_uuid = uuid.uuid4()
    embedding_array = np.array(embedding, dtype=np.float32)

    async with pool.acquire() as conn, conn.transaction():
        # F-05: Atomic limit check with row lock to prevent TOCTOU race
        if memory_limit is not None:
            row = await conn.fetchrow(
                "SELECT memory_count FROM profiles WHERE id = $1::uuid FOR UPDATE",
                user_uuid,
            )
            count = row["memory_count"] if row else 0
            if count >= memory_limit:
                return {
                    "error": "memory_limit_reached",
                    "count": count,
                    "limit": memory_limit,
                }

        row = await conn.fetchrow(
            """
                INSERT INTO memories
                    (id, user_id, bank_id, content, embedding, metadata, memory_type, tags, source)
                VALUES ($1, $2::uuid, $3::uuid, $4, $5, $6::jsonb, $7, $8, $9)
                RETURNING id, content, metadata, memory_type, tags, source, created_at
                """,
            memory_uuid,
            user_uuid,
            bank_uuid,
            content,
            embedding_array,
            json.dumps(metadata or {}),
            memory_type,
            tags or [],
            source,
        )
    return dict(row) if row else {}


async def search_memories(
    user_id: str,
    bank_id: str,
    query_embedding: list[float],
    query_text: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Hybrid search: combines semantic (vector) and full-text search via RRF."""
    pool = await get_pool()
    embedding_array = np.array(query_embedding, dtype=np.float32)

    try:
        user_uuid = uuid.UUID(user_id)
        bank_uuid = uuid.UUID(bank_id)
    except ValueError:
        return []

    if query_text:
        # Hybrid search using the RRF function (with user_id and bank_id)
        rows = await pool.fetch(
            """
            SELECT id, content, metadata, memory_type, tags, source, created_at, score
            FROM hybrid_search($1, $2, $3, $4, $5)
            """,
            user_uuid,
            bank_uuid,
            query_text,
            embedding_array,
            limit,
        )
    else:
        # Pure semantic search
        rows = await pool.fetch(
            """
            SELECT id, content, metadata, memory_type, tags, source, created_at,
                   1 - (embedding <=> $1) AS score
            FROM memories
            WHERE user_id = $2::uuid AND bank_id = $3::uuid AND embedding IS NOT NULL
            ORDER BY embedding <=> $1
            LIMIT $4
            """,
            embedding_array,
            user_uuid,
            bank_uuid,
            limit,
        )

    return [dict(row) for row in rows]


async def list_memories(
    user_id: str,
    bank_id: str,
    limit: int = 20,
    offset: int = 0,
    memory_type: str | None = None,
) -> list[dict[str, Any]]:
    """List memories for a user, most recent first."""
    try:
        user_uuid = uuid.UUID(user_id)
        bank_uuid = uuid.UUID(bank_id)
    except ValueError:
        return []

    pool = await get_pool()

    if memory_type:
        rows = await pool.fetch(
            """
            SELECT id, content, metadata, memory_type, tags, source, created_at
            FROM memories
            WHERE user_id = $1::uuid AND bank_id = $2::uuid AND memory_type = $3
            ORDER BY created_at DESC
            LIMIT $4 OFFSET $5
            """,
            user_uuid,
            bank_uuid,
            memory_type,
            limit,
            offset,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, content, metadata, memory_type, tags, source, created_at
            FROM memories
            WHERE user_id = $1::uuid AND bank_id = $2::uuid
            ORDER BY created_at DESC
            LIMIT $3 OFFSET $4
            """,
            user_uuid,
            bank_uuid,
            limit,
            offset,
        )

    return [dict(row) for row in rows]


async def delete_memory(user_id: str, bank_id: str, memory_id: str) -> bool:
    """Delete a specific memory. Returns True if deleted."""
    try:
        user_uuid = uuid.UUID(user_id)
        bank_uuid = uuid.UUID(bank_id)
        memory_uuid = uuid.UUID(memory_id)
    except ValueError:
        return False

    pool = await get_pool()
    result = await pool.execute(
        """
        DELETE FROM memories
        WHERE id = $1 AND user_id = $2::uuid AND bank_id = $3::uuid
        """,
        memory_uuid,
        user_uuid,
        bank_uuid,
    )
    return result == "DELETE 1"


async def get_memory_stats(user_id: str, bank_id: str) -> dict[str, Any]:
    """Get memory statistics for a user within a specific bank."""
    try:
        user_uuid = uuid.UUID(user_id)
        bank_uuid = uuid.UUID(bank_id)
    except ValueError:
        return {"total_memories": 0}

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*) AS total_memories,
            COUNT(DISTINCT memory_type) AS type_count,
            MIN(created_at) AS oldest_memory,
            MAX(created_at) AS newest_memory,
            jsonb_object_agg(memory_type, type_count) AS type_breakdown
        FROM (
            SELECT memory_type, COUNT(*) AS type_count
            FROM memories
            WHERE user_id = $1::uuid AND bank_id = $2::uuid
            GROUP BY memory_type
        ) sub
        """,
        user_uuid,
        bank_uuid,
    )
    return dict(row) if row else {"total_memories": 0}
