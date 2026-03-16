"""MCP tool definitions for the Personal Brain."""

from __future__ import annotations

from typing import Any

from src.config import FREE_MEMORY_LIMIT, PAID_MEMORY_LIMIT
from src.db import entities as entities_db
from src.db import memories as db
from src.db.profiles import get_user_limits
from src.embeddings import generate_embedding, generate_embeddings
from src.metadata import classify_memory_type, extract_metadata
from src.ratelimit import embedding_limiter

SIMILARITY_THRESHOLD = 0.85


def _limit_error(count: int, limit: int, is_paid: bool) -> dict[str, Any]:
    """Build a memory limit reached error response."""
    return {
        "status": "error",
        "error": "memory_limit_reached",
        "message": f"You have {count}/{limit} memories. "
        + ("Upgrade your plan for more." if not is_paid else "Limit reached."),
    }


async def create_memory(
    user_id: str,
    bank_id: str,
    content: str,
    memory_type: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    source: str = "mcp",
) -> dict[str, Any]:
    """Create a new memory with automatic embedding, conflict detection, and metadata.

    Returns conflicts (similar existing memories) in the response so the MCP
    client can decide how to handle them. Does NOT auto-resolve.
    """
    # Pre-check: single query for subscription status + memory count.
    # This avoids wasting an OpenAI embedding API call when the limit is already hit.
    # The atomic check in db.create_memory (FOR UPDATE) handles race conditions.
    is_paid, count = await get_user_limits(user_id)
    memory_limit = PAID_MEMORY_LIMIT if is_paid else FREE_MEMORY_LIMIT

    if count >= memory_limit:
        return _limit_error(count, memory_limit, is_paid)

    # Embedding rate limit
    if not embedding_limiter.check(user_id):
        return {
            "status": "error",
            "error": "rate_limited",
            "message": "Embedding rate limit exceeded. Please slow down.",
        }

    # Generate embedding (reused for both conflict detection and insert)
    embedding = await generate_embedding(content)

    # On-write conflict detection: search for similar existing memories
    # Embedding-only, no LLM calls — returns info for client to decide
    similar = await db.find_similar(
        user_id=user_id,
        bank_id=bank_id,
        embedding=embedding,
        threshold=SIMILARITY_THRESHOLD,
        limit=5,
    )

    # Auto-classify if not provided
    if not memory_type:
        memory_type = classify_memory_type(content)

    # Extract and merge metadata
    auto_metadata = extract_metadata(content)
    if metadata:
        auto_metadata.update(metadata)

    # Store in database — limit check is atomic inside the transaction
    result = await db.create_memory(
        user_id=user_id,
        bank_id=bank_id,
        content=content,
        embedding=embedding,
        metadata=auto_metadata,
        memory_type=memory_type,
        tags=tags,
        source=source,
        memory_limit=memory_limit,
    )

    # Handle limit reached (returned by atomic check in DB layer)
    if "error" in result and result["error"] == "memory_limit_reached":
        return _limit_error(result.get("count", 0), memory_limit, is_paid)

    response: dict[str, Any] = {
        "status": "created",
        "memory_id": str(result.get("id", "")),
        "memory_type": memory_type,
        "tags": tags or [],
    }

    # Include conflicts if any similar memories were found
    if similar:
        response["conflicts"] = [
            {
                "memory_id": str(s["id"]),
                "content": s["content"],
                "similarity": round(float(s["similarity"]), 3),
                "memory_type": s.get("memory_type", "observation"),
                "created_at": s["created_at"].isoformat() if s.get("created_at") else None,
            }
            for s in similar
        ]

    return response


def _serialize_memory(
    row: dict[str, Any], include_score: bool = False, include_source: bool = False
) -> dict[str, Any]:
    """Serialize a memory row for MCP response."""
    result = {
        "id": str(row["id"]),
        "content": row["content"],
        "memory_type": row.get("memory_type", "observation"),
        "tags": row.get("tags", []),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }
    if include_score:
        result["score"] = float(row.get("score", 0))
    if include_source:
        result["source"] = row.get("source", "mcp")
    return result


async def search_memories(
    user_id: str,
    bank_id: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search memories using hybrid semantic + full-text search.

    Results are ranked using Reciprocal Ranked Fusion. Access counts are
    automatically incremented on returned memories.
    """
    # Embedding rate limit
    if not embedding_limiter.check(user_id):
        return []

    query_embedding = await generate_embedding(query)

    results = await db.search_memories(
        user_id=user_id,
        bank_id=bank_id,
        query_embedding=query_embedding,
        query_text=query,
        limit=limit,
    )

    return [_serialize_memory(r, include_score=True) for r in results]


async def list_memories(
    user_id: str,
    bank_id: str,
    limit: int = 20,
    offset: int = 0,
    memory_type: str | None = None,
) -> list[dict[str, Any]]:
    """List recent memories, optionally filtered by type."""
    results = await db.list_memories(
        user_id=user_id,
        bank_id=bank_id,
        limit=limit,
        offset=offset,
        memory_type=memory_type,
    )

    return [_serialize_memory(r, include_source=True) for r in results]


async def delete_memory(user_id: str, bank_id: str, memory_id: str) -> dict[str, Any]:
    """Delete a specific memory by ID."""
    deleted = await db.delete_memory(user_id=user_id, bank_id=bank_id, memory_id=memory_id)
    return {
        "status": "deleted" if deleted else "not_found",
        "memory_id": memory_id,
    }


async def get_stats(user_id: str, bank_id: str) -> dict[str, Any]:
    """Get memory statistics for the current user."""
    stats = await db.get_memory_stats(user_id=user_id, bank_id=bank_id)
    return {
        "total_memories": stats.get("total_memories", 0),
        "type_breakdown": stats.get("type_breakdown", {}),
        "oldest_memory": (
            stats["oldest_memory"].isoformat() if stats.get("oldest_memory") else None
        ),
        "newest_memory": (
            stats["newest_memory"].isoformat() if stats.get("newest_memory") else None
        ),
    }


async def get_entities(
    user_id: str,
    bank_id: str,
    query: str | None = None,
    entity_type: str | None = None,
) -> list[dict[str, Any]]:
    """List/search entities for a user+bank."""
    results = await entities_db.get_entities(
        user_id=user_id,
        bank_id=bank_id,
        query=query,
        entity_type=entity_type,
    )
    return [
        {
            "id": str(row["id"]),
            "entity_name": row["entity_name"],
            "entity_type": row["entity_type"],
            "facts": row.get("facts", []),
            "memory_ids": [str(mid) for mid in row.get("memory_ids", [])],
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        }
        for row in results
    ]


async def get_entity_memories(
    user_id: str,
    bank_id: str,
    entity_name: str,
) -> list[dict[str, Any]]:
    """Get all memories linked to a specific entity."""
    results = await entities_db.get_entity_memories(
        user_id=user_id,
        bank_id=bank_id,
        entity_name=entity_name,
    )
    return [_serialize_memory(r, include_source=True) for r in results]


async def import_memories(
    user_id: str,
    bank_id: str,
    memories: list[dict[str, Any]],
    deduplicate: bool = True,
) -> dict[str, Any]:
    """Import multiple memories at once.

    Generates embeddings in batch, optionally deduplicates against existing
    memories, and inserts non-duplicates via batch_create_memories.

    Returns {created: N, skipped: N, conflicts: [...]}.
    """
    # Pre-check: subscription status + memory count
    is_paid, count = await get_user_limits(user_id)
    memory_limit = PAID_MEMORY_LIMIT if is_paid else FREE_MEMORY_LIMIT

    if count >= memory_limit:
        return _limit_error(count, memory_limit, is_paid)

    # Embedding rate limit -- check once for the batch
    if not embedding_limiter.check(user_id):
        return {
            "status": "error",
            "error": "rate_limited",
            "message": "Embedding rate limit exceeded. Please slow down.",
        }

    # Extract contents for batch embedding
    contents = [m["content"] for m in memories]

    # Generate all embeddings in one API call
    embeddings = await generate_embeddings(contents)

    # Deduplicate if requested
    skipped = 0
    conflicts: list[dict[str, Any]] = []
    items_to_insert: list[
        tuple[str, list[float], dict[str, Any] | None, str, list[str] | None, str]
    ] = []

    for i, (memory_dict, embedding) in enumerate(zip(memories, embeddings, strict=True)):
        content = memory_dict["content"]
        memory_type = memory_dict.get("memory_type") or classify_memory_type(content)
        tags = memory_dict.get("tags")
        metadata = memory_dict.get("metadata")
        source = "import"

        if deduplicate:
            similar = await db.find_similar(
                user_id=user_id,
                bank_id=bank_id,
                embedding=embedding,
                threshold=0.90,
                limit=1,
            )
            if similar:
                skipped += 1
                conflicts.append(
                    {
                        "index": i,
                        "content_preview": content[:100],
                        "similar_memory_id": str(similar[0]["id"]),
                        "similarity": round(float(similar[0]["similarity"]), 3),
                    }
                )
                continue

        # Enrich metadata
        auto_metadata = extract_metadata(content)
        if metadata:
            auto_metadata.update(metadata)

        items_to_insert.append((content, embedding, auto_metadata, memory_type, tags, source))

    # Batch insert
    created_ids = await db.batch_create_memories(
        user_id=user_id,
        bank_id=bank_id,
        items=items_to_insert,
        memory_limit=memory_limit,
    )

    result: dict[str, Any] = {
        "status": "imported",
        "created": len(created_ids),
        "skipped": skipped,
        "memory_ids": created_ids,
    }
    if conflicts:
        result["conflicts"] = conflicts

    return result
