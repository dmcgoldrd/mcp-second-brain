"""MCP tool definitions for the Personal Brain."""

from __future__ import annotations

from typing import Any

from src.config import FREE_MEMORY_LIMIT, PAID_MEMORY_LIMIT
from src.db import memories as db
from src.db.profiles import get_memory_count, is_subscription_active
from src.embeddings import generate_embedding
from src.metadata import classify_memory_type, extract_metadata
from src.ratelimit import embedding_limiter


async def create_memory(
    user_id: str,
    bank_id: str,
    content: str,
    memory_type: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    source: str = "mcp",
) -> dict[str, Any]:
    """Create a new memory with automatic embedding and metadata extraction.

    The content is embedded using OpenAI's text-embedding-3-small model,
    and basic metadata is extracted via heuristics. The AI client can
    provide richer metadata (entities, topics, sentiment) directly.
    """
    # Resolve memory limit for atomic DB check (F-05)
    is_paid = await is_subscription_active(user_id)
    memory_limit = PAID_MEMORY_LIMIT if is_paid else FREE_MEMORY_LIMIT

    # N-06: Pre-check count BEFORE embedding to avoid wasting OpenAI API costs.
    # This is a non-atomic preliminary check; the atomic check is in db.create_memory.
    count = await get_memory_count(user_id)
    if count >= memory_limit:
        return {
            "status": "error",
            "error": "memory_limit_reached",
            "message": f"You have {count}/{memory_limit} memories. "
            + ("Upgrade your plan for more." if not is_paid else "Limit reached."),
        }

    # Embedding rate limit
    if not embedding_limiter.check(user_id):
        return {
            "status": "error",
            "error": "rate_limited",
            "message": "Embedding rate limit exceeded. Please slow down.",
        }

    # Generate embedding
    embedding = await generate_embedding(content)

    # Auto-classify if not provided
    if not memory_type:
        memory_type = classify_memory_type(content)

    # Extract and merge metadata
    auto_metadata = extract_metadata(content)
    if metadata:
        auto_metadata.update(metadata)

    # Store in database — limit check is atomic inside the transaction (F-05)
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
        count = result.get("count", 0)
        return {
            "status": "error",
            "error": "memory_limit_reached",
            "message": f"You have {count}/{memory_limit} memories. "
            + ("Upgrade your plan for more." if not is_paid else "Limit reached."),
        }

    return {
        "status": "created",
        "memory_id": str(result.get("id", "")),
        "memory_type": memory_type,
        "tags": tags or [],
    }


async def search_memories(
    user_id: str,
    bank_id: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search memories using hybrid semantic + full-text search.

    The query is embedded and used for both vector similarity search
    and full-text search. Results are ranked using Reciprocal Ranked Fusion.
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

    # Serialize for MCP response
    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "memory_type": r.get("memory_type", "observation"),
            "tags": r.get("tags", []),
            "score": float(r.get("score", 0)),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        }
        for r in results
    ]


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

    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "memory_type": r.get("memory_type", "observation"),
            "tags": r.get("tags", []),
            "source": r.get("source", "mcp"),
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
        }
        for r in results
    ]


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
