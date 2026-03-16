"""Memory CRUD operations against Supabase Postgres."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

import numpy as np

from src.db.connection import get_pool
from src.db.utils import parse_uuid

logger = logging.getLogger("mcp-brain")

# Prevent GC of fire-and-forget background tasks
_background_tasks: set[asyncio.Task] = set()


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
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
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
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError:
        return []

    if query_text:
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
        rows = await pool.fetch(
            """
            SELECT id, content, metadata, memory_type, tags, source, created_at,
                   1 - (embedding <=> $1) AS score
            FROM memories
            WHERE user_id = $2::uuid AND bank_id = $3::uuid
              AND embedding IS NOT NULL AND archived_at IS NULL
            ORDER BY embedding <=> $1
            LIMIT $4
            """,
            embedding_array,
            user_uuid,
            bank_uuid,
            limit,
        )

    results = [dict(row) for row in rows]

    # Track access on returned memories (true fire-and-forget — don't block response)
    if results:
        memory_ids = [row["id"] for row in rows]
        task = asyncio.create_task(_update_access_counts(pool, memory_ids))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return results


async def search_memories_at(
    user_id: str,
    bank_id: str,
    query_embedding: list[float],
    query_text: str = "",
    as_of: datetime | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search memories as they were at a specific point in time.

    If as_of is provided:
    - Include memories created before as_of
    - Exclude memories that were archived/superseded before as_of
    - This lets you query "what did I know on March 1st?"

    If as_of is None, behaves like regular search_memories.
    """
    if as_of is None:
        return await search_memories(
            user_id=user_id,
            bank_id=bank_id,
            query_embedding=query_embedding,
            query_text=query_text,
            limit=limit,
        )

    pool = await get_pool()
    embedding_array = np.array(query_embedding, dtype=np.float32)

    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError:
        return []

    rows = await pool.fetch(
        """
        SELECT id, content, metadata, memory_type, tags, source, created_at,
               1 - (embedding <=> $1) AS score
        FROM memories
        WHERE user_id = $2::uuid AND bank_id = $3::uuid
          AND embedding IS NOT NULL
          AND created_at <= $4
          AND (archived_at IS NULL OR archived_at > $4)
        ORDER BY embedding <=> $1
        LIMIT $5
        """,
        embedding_array,
        user_uuid,
        bank_uuid,
        as_of,
        limit,
    )

    results = [dict(row) for row in rows]

    # Track access on returned memories (true fire-and-forget)
    if results:
        memory_ids = [row["id"] for row in rows]
        task = asyncio.create_task(_update_access_counts(pool, memory_ids))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return results


async def _update_access_counts(pool, memory_ids: list) -> None:
    """Background task to update access counts. Errors are logged, never raised."""
    try:
        await pool.execute(
            """
            UPDATE memories
            SET access_count = access_count + 1, last_accessed_at = now()
            WHERE id = ANY($1::uuid[])
            """,
            memory_ids,
        )
    except Exception:
        logger.warning("Failed to update access counts", exc_info=True)


async def list_memories(
    user_id: str,
    bank_id: str,
    limit: int = 20,
    offset: int = 0,
    memory_type: str | None = None,
) -> list[dict[str, Any]]:
    """List memories for a user, most recent first."""
    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError:
        return []

    pool = await get_pool()

    if memory_type:
        rows = await pool.fetch(
            """
            SELECT id, content, metadata, memory_type, tags, source, created_at
            FROM memories
            WHERE user_id = $1::uuid AND bank_id = $2::uuid AND memory_type = $3
              AND archived_at IS NULL
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
              AND archived_at IS NULL
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
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
        memory_uuid = parse_uuid(memory_id, "memory_id")
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


async def find_similar(
    user_id: str,
    bank_id: str,
    embedding: list[float],
    threshold: float = 0.85,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find memories similar to the given embedding above a cosine threshold."""
    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError:
        return []

    pool = await get_pool()
    embedding_array = np.array(embedding, dtype=np.float32)

    rows = await pool.fetch(
        """
        SELECT id, content, memory_type, tags, created_at,
               1 - (embedding <=> $1) AS similarity
        FROM memories
        WHERE user_id = $2::uuid AND bank_id = $3::uuid
          AND embedding IS NOT NULL AND archived_at IS NULL
          AND 1 - (embedding <=> $1) > $4
        ORDER BY embedding <=> $1
        LIMIT $5
        """,
        embedding_array,
        user_uuid,
        bank_uuid,
        threshold,
        limit,
    )
    return [dict(row) for row in rows]


async def batch_create_memories(
    user_id: str,
    bank_id: str,
    items: list[tuple[str, list[float], dict[str, Any] | None, str, list[str] | None, str]],
    memory_limit: int | None = None,
) -> list[str]:
    """Insert multiple memories in a single transaction.

    Each item is a tuple of (content, embedding, metadata, memory_type, tags, source).
    Returns list of created memory UUIDs as strings.

    If memory_limit is provided, atomically checks the user's memory_count
    against the limit before inserting.
    """
    if not items:
        return []

    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError:
        return []

    pool = await get_pool()
    created_ids: list[str] = []

    async with pool.acquire() as conn, conn.transaction():
        # Atomic limit check if memory_limit provided
        if memory_limit is not None:
            row = await conn.fetchrow(
                "SELECT memory_count FROM profiles WHERE id = $1::uuid FOR UPDATE",
                user_uuid,
            )
            count = row["memory_count"] if row else 0
            if count + len(items) > memory_limit:
                return []  # Would exceed limit

        for content, embedding, metadata, memory_type, tags, source in items:
            memory_uuid = uuid.uuid4()
            embedding_array = np.array(embedding, dtype=np.float32)

            row = await conn.fetchrow(
                """
                INSERT INTO memories
                    (id, user_id, bank_id, content, embedding, metadata, memory_type, tags, source)
                VALUES ($1, $2::uuid, $3::uuid, $4, $5, $6::jsonb, $7, $8, $9)
                RETURNING id
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
            if row:
                created_ids.append(str(row["id"]))

    return created_ids


async def update_memory(
    user_id: str,
    bank_id: str,
    memory_id: str,
    content: str | None = None,
    embedding: list[float] | None = None,
    memory_type: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Update an existing memory. Only provided fields are changed.

    If content changes, the caller must also provide a new embedding.
    Increments version and sets updated_at = now() on any update.
    Returns the updated row dict, or None if not found.
    """
    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
        memory_uuid = parse_uuid(memory_id, "memory_id")
    except ValueError:
        return None

    # Build SET clauses dynamically — only touch fields that were provided
    set_clauses: list[str] = []
    params: list[Any] = []
    param_idx = 4  # $1=memory_id, $2=user_id, $3=bank_id

    if content is not None:
        set_clauses.append(f"content = ${param_idx}")
        params.append(content)
        param_idx += 1

    if embedding is not None:
        embedding_array = np.array(embedding, dtype=np.float32)
        set_clauses.append(f"embedding = ${param_idx}")
        params.append(embedding_array)
        param_idx += 1

    if memory_type is not None:
        set_clauses.append(f"memory_type = ${param_idx}")
        params.append(memory_type)
        param_idx += 1

    if tags is not None:
        set_clauses.append(f"tags = ${param_idx}")
        params.append(tags)
        param_idx += 1

    if metadata is not None:
        set_clauses.append(f"metadata = ${param_idx}::jsonb")
        params.append(json.dumps(metadata))
        param_idx += 1

    if not set_clauses:
        return None

    # Always bump version and updated_at
    set_clauses.append("version = version + 1")
    set_clauses.append("updated_at = now()")

    set_sql = ", ".join(set_clauses)
    query = f"""
        UPDATE memories
        SET {set_sql}
        WHERE id = $1 AND user_id = $2::uuid AND bank_id = $3::uuid
          AND archived_at IS NULL
        RETURNING id, content, metadata, memory_type, tags, source, version, created_at, updated_at
    """

    pool = await get_pool()
    row = await pool.fetchrow(query, memory_uuid, user_uuid, bank_uuid, *params)
    return dict(row) if row else None


async def get_memory_stats(user_id: str, bank_id: str) -> dict[str, Any]:
    """Get memory statistics for a user within a specific bank."""

    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError:
        return {"total_memories": 0}

    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            SUM(sub.type_count)::integer AS total_memories,
            MIN(sub.min_created) AS oldest_memory,
            MAX(sub.max_created) AS newest_memory,
            jsonb_object_agg(sub.memory_type, sub.type_count) AS type_breakdown
        FROM (
            SELECT memory_type, COUNT(*) AS type_count,
                   MIN(created_at) AS min_created, MAX(created_at) AS max_created
            FROM memories
            WHERE user_id = $1::uuid AND bank_id = $2::uuid
              AND archived_at IS NULL
            GROUP BY memory_type
        ) sub
        """,
        user_uuid,
        bank_uuid,
    )
    return dict(row) if row else {"total_memories": 0}
