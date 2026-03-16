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

    where = " AND ".join(conditions)

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


async def get_related_entities(
    user_id: str,
    bank_id: str,
    entity_name: str,
    max_hops: int = 2,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Find entities related to the given entity through shared memories.

    Hop 1: Entities that share memories with the target entity
    Hop 2: Entities that share memories with hop-1 entities

    Uses recursive CTE for multi-hop traversal within Postgres.
    """
    try:
        user_uuid = parse_uuid(user_id, "user_id")
        bank_uuid = parse_uuid(bank_id, "bank_id")
    except ValueError:
        return []

    # Cap max_hops at 3 to prevent runaway recursion
    max_hops = max(1, min(3, max_hops))
    limit = max(1, min(100, limit))

    pool = await get_pool()

    rows = await pool.fetch(
        """
        WITH RECURSIVE entity_graph AS (
            -- Base: find the starting entity
            SELECT e.id, e.entity_name, e.entity_type, e.memory_ids, 0 AS hop
            FROM memory_entities e
            WHERE e.user_id = $1::uuid AND e.bank_id = $2::uuid
              AND e.entity_name = $3

            UNION

            -- Recursive: find entities sharing memories with current level
            SELECT DISTINCT e2.id, e2.entity_name, e2.entity_type, e2.memory_ids, eg.hop + 1
            FROM entity_graph eg
            JOIN memory_entities e2
              ON e2.user_id = $1::uuid
              AND e2.bank_id = $2::uuid
              AND e2.memory_ids && eg.memory_ids
              AND e2.id != eg.id
            WHERE eg.hop < $4
        )
        SELECT id, entity_name, entity_type, memory_ids, MIN(hop) AS hop
        FROM entity_graph
        GROUP BY id, entity_name, entity_type, memory_ids
        ORDER BY MIN(hop), entity_name
        LIMIT $5
        """,
        user_uuid,
        bank_uuid,
        entity_name,
        max_hops,
        limit,
    )
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
