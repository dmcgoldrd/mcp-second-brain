"""Memory CRUD operations against Supabase Postgres."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import numpy as np

from src.db.connection import get_pool


async def create_memory(
    user_id: str,
    content: str,
    embedding: list[float],
    metadata: dict[str, Any] | None = None,
    memory_type: str = "observation",
    tags: list[str] | None = None,
    source: str = "mcp",
) -> dict[str, Any]:
    """Insert a new memory with its embedding."""
    pool = await get_pool()
    memory_id = str(uuid.uuid4())
    embedding_array = np.array(embedding, dtype=np.float32)

    row = await pool.fetchrow(
        """
        INSERT INTO memories (id, user_id, content, embedding, metadata, memory_type, tags, source)
        VALUES ($1, $2::uuid, $3, $4, $5::jsonb, $6, $7, $8)
        RETURNING id, content, metadata, memory_type, tags, source, created_at
        """,
        uuid.UUID(memory_id),
        uuid.UUID(user_id),
        content,
        embedding_array,
        metadata or {},
        memory_type,
        tags or [],
        source,
    )
    return dict(row) if row else {}


async def search_memories(
    user_id: str,
    query_embedding: list[float],
    query_text: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Hybrid search: combines semantic (vector) and full-text search via RRF."""
    pool = await get_pool()
    embedding_array = np.array(query_embedding, dtype=np.float32)

    if query_text:
        # Hybrid search using the RRF function
        rows = await pool.fetch(
            """
            SELECT id, content, metadata, memory_type, tags, source, created_at, score
            FROM hybrid_search($1, $2, $3)
            """,
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
            WHERE user_id = $2::uuid AND embedding IS NOT NULL
            ORDER BY embedding <=> $1
            LIMIT $3
            """,
            embedding_array,
            uuid.UUID(user_id),
            limit,
        )

    return [dict(row) for row in rows]


async def list_memories(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    memory_type: str | None = None,
) -> list[dict[str, Any]]:
    """List memories for a user, most recent first."""
    pool = await get_pool()

    if memory_type:
        rows = await pool.fetch(
            """
            SELECT id, content, metadata, memory_type, tags, source, created_at
            FROM memories
            WHERE user_id = $1::uuid AND memory_type = $2
            ORDER BY created_at DESC
            LIMIT $3 OFFSET $4
            """,
            uuid.UUID(user_id),
            memory_type,
            limit,
            offset,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, content, metadata, memory_type, tags, source, created_at
            FROM memories
            WHERE user_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            uuid.UUID(user_id),
            limit,
            offset,
        )

    return [dict(row) for row in rows]


async def delete_memory(user_id: str, memory_id: str) -> bool:
    """Delete a specific memory. Returns True if deleted."""
    pool = await get_pool()
    result = await pool.execute(
        """
        DELETE FROM memories
        WHERE id = $1 AND user_id = $2::uuid
        """,
        uuid.UUID(memory_id),
        uuid.UUID(user_id),
    )
    return result == "DELETE 1"


async def get_memory_stats(user_id: str) -> dict[str, Any]:
    """Get memory statistics for a user."""
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
            WHERE user_id = $1::uuid
            GROUP BY memory_type
        ) sub
        """,
        uuid.UUID(user_id),
    )
    return dict(row) if row else {"total_memories": 0}
