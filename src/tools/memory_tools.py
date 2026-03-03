"""MCP tool definitions for the Personal Brain."""

from __future__ import annotations

from typing import Any

from src.db import memories as db
from src.embeddings import generate_embedding
from src.metadata import classify_memory_type, extract_metadata


async def create_memory(
    user_id: str,
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
    # Generate embedding
    embedding = await generate_embedding(content)

    # Auto-classify if not provided
    if not memory_type:
        memory_type = classify_memory_type(content)

    # Extract and merge metadata
    auto_metadata = extract_metadata(content)
    if metadata:
        auto_metadata.update(metadata)

    # Store in database
    result = await db.create_memory(
        user_id=user_id,
        content=content,
        embedding=embedding,
        metadata=auto_metadata,
        memory_type=memory_type,
        tags=tags,
        source=source,
    )

    return {
        "status": "created",
        "memory_id": str(result.get("id", "")),
        "memory_type": memory_type,
        "tags": tags or [],
    }


async def search_memories(
    user_id: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search memories using hybrid semantic + full-text search.

    The query is embedded and used for both vector similarity search
    and full-text search. Results are ranked using Reciprocal Ranked Fusion.
    """
    query_embedding = await generate_embedding(query)

    results = await db.search_memories(
        user_id=user_id,
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
    limit: int = 20,
    offset: int = 0,
    memory_type: str | None = None,
) -> list[dict[str, Any]]:
    """List recent memories, optionally filtered by type."""
    results = await db.list_memories(
        user_id=user_id,
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


async def delete_memory(user_id: str, memory_id: str) -> dict[str, Any]:
    """Delete a specific memory by ID."""
    deleted = await db.delete_memory(user_id=user_id, memory_id=memory_id)
    return {
        "status": "deleted" if deleted else "not_found",
        "memory_id": memory_id,
    }


async def get_stats(user_id: str) -> dict[str, Any]:
    """Get memory statistics for the current user."""
    stats = await db.get_memory_stats(user_id=user_id)
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
