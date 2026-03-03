"""MCP Brain Server — Personal AI Memory via MCP.

A FastMCP server that provides persistent memory across all AI platforms.
Authenticates users via Supabase JWT, stores memories in Postgres + pgvector,
and exposes tools for creating, searching, listing, and deleting memories.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastmcp import FastMCP

from src.auth.jwt import extract_user_id
from src.tools import memory_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-brain")

# Create the MCP server
mcp = FastMCP(
    name="MCP Brain",
    instructions="""You are connected to the user's Personal Brain — a persistent memory layer
that works across all AI platforms. Use these tools to store and retrieve the user's
knowledge, decisions, preferences, and ideas.

When the user shares something worth remembering, use create_memory to store it.
When the user asks about something they might have mentioned before, use search_memories.

Memory types: observation, task, idea, reference, person_note, decision, preference.

Always provide rich metadata when creating memories — include entities (people, places,
organizations), topics, and relevant tags to improve future retrieval.""",
)


def _get_user_id(context: Any) -> str:
    """Extract user ID from the MCP request context.

    In production with OAuth 2.1, the token comes from the Authorization header.
    FastMCP's auth middleware validates it and provides the user context.
    For development, falls back to a header-based approach.
    """
    # TODO: Integrate with FastMCP's OAuth middleware once configured.
    # For now, the token is extracted from the request headers by middleware.
    # This placeholder will be replaced with proper FastMCP auth integration.
    if hasattr(context, "user_id"):
        return context.user_id
    if hasattr(context, "request_context") and hasattr(context.request_context, "user_id"):
        return context.request_context.user_id
    raise ValueError("No authenticated user in request context")


@mcp.tool()
async def create_memory(
    content: Annotated[str, "The memory content to store. Be descriptive and specific."],
    memory_type: Annotated[
        str | None,
        "Type of memory: observation, task, idea, reference, person_note, decision, preference. "
        "If not provided, the system will auto-classify based on content.",
    ] = None,
    tags: Annotated[
        list[str] | None,
        "Tags for categorization. Examples: ['work', 'python', 'architecture']",
    ] = None,
    metadata: Annotated[
        str | None,
        "Additional metadata as JSON string. Include entities, topics, sentiment. "
        "Example: {\"entities\": [\"Alice\", \"Acme Corp\"], \"topics\": [\"hiring\", \"engineering\"]}",
    ] = None,
    source: Annotated[
        str,
        "Source of the memory: mcp, slack, manual, import",
    ] = "mcp",
    user_id: Annotated[
        str,
        "The authenticated user's ID (provided by auth middleware)",
    ] = "",
) -> str:
    """Store a new memory in your Personal Brain.

    The memory will be embedded for semantic search, auto-classified by type,
    and enriched with extracted metadata. Provide tags and structured metadata
    for better retrieval later.
    """
    parsed_metadata = None
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError:
            parsed_metadata = {"raw": metadata}

    result = await memory_tools.create_memory(
        user_id=user_id,
        content=content,
        memory_type=memory_type,
        tags=tags,
        metadata=parsed_metadata,
        source=source,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def search_memories(
    query: Annotated[
        str,
        "Natural language search query. Uses hybrid semantic + full-text search. "
        "Example: 'What did I decide about the database architecture?'",
    ],
    limit: Annotated[
        int,
        "Maximum number of results to return (1-50)",
    ] = 10,
    user_id: Annotated[
        str,
        "The authenticated user's ID (provided by auth middleware)",
    ] = "",
) -> str:
    """Search your Personal Brain for relevant memories.

    Uses hybrid search combining semantic similarity (meaning-based) and
    full-text search (keyword-based) with Reciprocal Ranked Fusion scoring.
    Returns the most relevant memories sorted by relevance score.
    """
    limit = max(1, min(50, limit))
    results = await memory_tools.search_memories(
        user_id=user_id,
        query=query,
        limit=limit,
    )
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
async def list_memories(
    limit: Annotated[int, "Number of memories to return (1-100)"] = 20,
    offset: Annotated[int, "Number of memories to skip (for pagination)"] = 0,
    memory_type: Annotated[
        str | None,
        "Filter by type: observation, task, idea, reference, person_note, decision, preference",
    ] = None,
    user_id: Annotated[
        str,
        "The authenticated user's ID (provided by auth middleware)",
    ] = "",
) -> str:
    """List recent memories from your Personal Brain.

    Returns memories in reverse chronological order. Optionally filter by type.
    """
    limit = max(1, min(100, limit))
    results = await memory_tools.list_memories(
        user_id=user_id,
        limit=limit,
        offset=offset,
        memory_type=memory_type,
    )
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
async def delete_memory(
    memory_id: Annotated[str, "The UUID of the memory to delete"],
    user_id: Annotated[
        str,
        "The authenticated user's ID (provided by auth middleware)",
    ] = "",
) -> str:
    """Delete a specific memory from your Personal Brain."""
    result = await memory_tools.delete_memory(user_id=user_id, memory_id=memory_id)
    return json.dumps(result, indent=2)


@mcp.tool()
async def brain_stats(
    user_id: Annotated[
        str,
        "The authenticated user's ID (provided by auth middleware)",
    ] = "",
) -> str:
    """Get statistics about your Personal Brain.

    Returns total memory count, breakdown by type, and date range.
    """
    stats = await memory_tools.get_stats(user_id=user_id)
    return json.dumps(stats, indent=2, default=str)
