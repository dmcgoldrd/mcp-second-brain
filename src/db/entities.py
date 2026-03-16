"""Entity queries against Supabase Postgres."""

from __future__ import annotations

import logging
from typing import Any

from src.db.connection import get_pool
from src.db.utils import parse_uuid

logger = logging.getLogger("mcp-brain")


async def get_entities(
    user_id: str,
    bank_id: str,
    query: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search/list entities for a user+bank.

    If query is provided, uses full-text search on entity_name.
    If entity_type is provided, filters by type.
    Returns list of entity dicts with facts and related memory_ids.
    """
    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError:
        return []

    pool = await get_pool()
    limit = max(1, min(100, limit))

    conditions = [
        "user_id = $1::uuid",
        "bank_id = $2::uuid",
    ]
    params: list[Any] = [user_uuid, bank_uuid]
    param_idx = 3

    if query:
        conditions.append(
            f"to_tsvector('english', entity_name) @@ plainto_tsquery('english', ${param_idx})"
        )
        params.append(query)
        param_idx += 1

    if entity_type:
        conditions.append(f"entity_type = ${param_idx}")
        params.append(entity_type)
        param_idx += 1

    conditions.append("TRUE")  # always-true tail for cleaner SQL
    where = " AND ".join(conditions[:-1])  # drop the trailing TRUE

    params.append(limit)

    sql = f"""
        SELECT id, entity_name, entity_type, facts, memory_ids, metadata, created_at, updated_at
        FROM memory_entities
        WHERE {where}
        ORDER BY updated_at DESC
        LIMIT ${param_idx}
    """

    rows = await pool.fetch(sql, *params)
    return [dict(row) for row in rows]


async def get_entity_memories(
    user_id: str,
    bank_id: str,
    entity_name: str,
) -> list[dict[str, Any]]:
    """Get all memories linked to a specific entity.

    Joins memory_entities with memories on memory_ids array overlap.
    """
    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError:
        return []

    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT m.id, m.content, m.memory_type, m.tags, m.source, m.created_at
        FROM memory_entities e
        JOIN memories m ON m.id = ANY(e.memory_ids)
        WHERE e.user_id = $1::uuid
          AND e.bank_id = $2::uuid
          AND e.entity_name = $3
          AND m.archived_at IS NULL
        ORDER BY m.created_at DESC
        """,
        user_uuid,
        bank_uuid,
        entity_name,
    )
    return [dict(row) for row in rows]
