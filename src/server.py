"""MCP Brain Server -- Personal AI Memory via MCP.

A FastMCP server that provides persistent memory across all AI platforms.
Authenticates users via Supabase JWT (through FastMCP's SupabaseProvider),
stores memories in Postgres + pgvector, and exposes tools for creating,
searching, listing, and deleting memories.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.supabase import SupabaseProvider
from fastmcp.server.dependencies import CurrentAccessToken, get_http_headers

from src.config import (
    BASE_URL,
    MAX_BANK_NAME_LENGTH,
    MAX_BANK_SLUG_LENGTH,
    MAX_BANKS_FREE,
    MAX_BANKS_PAID,
    MAX_CONTENT_LENGTH,
    MAX_METADATA_LENGTH,
    MAX_QUERY_LENGTH,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    SUPABASE_URL,
    VALID_MEMORY_TYPES,
    VALID_SOURCES,
)
from src.db import banks as banks_db
from src.db.profiles import is_subscription_active
from src.ratelimit import tool_limiter
from src.tools import memory_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp-brain")

# Create the auth provider — validates Supabase JWTs and serves OAuth metadata
# Uses base SupabaseProvider which forwards Supabase's OAuth AS metadata
# (including registration_endpoint for Dynamic Client Registration)
auth_provider = SupabaseProvider(
    project_url=SUPABASE_URL,
    base_url=BASE_URL,
    algorithm="ES256",
)

# Create the MCP server with built-in auth
mcp = FastMCP(
    name="MCP Brain",
    instructions="""You are connected to the user's Personal Brain -- a persistent memory layer
that works across all AI platforms. Use these tools to store and retrieve the user's
knowledge, decisions, preferences, and ideas.

When the user shares something worth remembering, use create_memory to store it.
When the user asks about something they might have mentioned before, use search_memories.

Memory types: observation, task, idea, reference, person_note, decision, preference.

Always provide rich metadata when creating memories -- include entities (people, places,
organizations), topics, and relevant tags to improve future retrieval.""",
    auth=auth_provider,
)


async def _resolve_auth(token: AccessToken) -> dict[str, str]:
    """Extract user_id from token and resolve bank_id from headers.

    The SupabaseProvider validates the JWT and provides the AccessToken.
    Bank is resolved from the x-bank-slug header or falls back to default.
    """
    user_id = token.claims.get("sub", "")
    if not user_id:
        raise ValueError("No user ID (sub claim) in access token")

    # Rate limit check
    if not tool_limiter.check(user_id):
        raise ValueError("Rate limit exceeded. Please slow down.")

    # Resolve bank from headers
    headers = get_http_headers() or {}
    bank_slug = headers.get("x-bank-slug", "").strip() or None

    if bank_slug:
        bank = await banks_db.get_bank_by_slug(user_id, bank_slug)
        if not bank:
            raise ValueError("Bank not found")
        bank_id = str(bank["id"])
    else:
        default_bank = await banks_db.get_default_bank(user_id)
        if not default_bank:
            raise ValueError("No default bank found. Please create a bank first.")
        bank_id = str(default_bank["id"])

    return {"user_id": user_id, "bank_id": bank_id}


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
        'Example: {"entities": ["Alice", "Acme Corp"], "topics": ["hiring", "engineering"]}',
    ] = None,
    source: Annotated[
        str,
        "Source of the memory: mcp, slack, manual, import",
    ] = "mcp",
    token: AccessToken = CurrentAccessToken(),
) -> str:
    """Store a new memory in your Personal Brain.

    The memory will be embedded for semantic search, auto-classified by type,
    and enriched with extracted metadata. Provide tags and structured metadata
    for better retrieval later.
    """
    auth = await _resolve_auth(token)

    # N-08: Reject empty content
    if not content or not content.strip():
        return json.dumps(
            {
                "status": "error",
                "error": "empty_content",
                "message": "Content cannot be empty.",
            }
        )

    # F-11: Check content length in bytes, not characters
    if len(content.encode("utf-8")) > MAX_CONTENT_LENGTH:
        return json.dumps(
            {
                "status": "error",
                "error": "content_too_long",
                "message": f"Content exceeds {MAX_CONTENT_LENGTH} byte limit.",
            }
        )

    # F-02: Validate memory_type
    if memory_type and memory_type not in VALID_MEMORY_TYPES:
        return json.dumps(
            {
                "status": "error",
                "error": "invalid_memory_type",
                "message": "Invalid memory type. Must be one of: "
                + ", ".join(sorted(VALID_MEMORY_TYPES)),
            }
        )

    # F-03: Validate source
    if source not in VALID_SOURCES:
        return json.dumps(
            {
                "status": "error",
                "error": "invalid_source",
                "message": f"Invalid source. Must be one of: {', '.join(sorted(VALID_SOURCES))}",
            }
        )

    # F-04: Validate tags
    if tags:
        if len(tags) > MAX_TAGS:
            return json.dumps(
                {
                    "status": "error",
                    "error": "too_many_tags",
                    "message": f"Maximum {MAX_TAGS} tags allowed.",
                }
            )
        tags = [t[:MAX_TAG_LENGTH] for t in tags]

    # F-08: Validate metadata size
    parsed_metadata = None
    if metadata:
        if len(metadata.encode("utf-8")) > MAX_METADATA_LENGTH:
            return json.dumps(
                {
                    "status": "error",
                    "error": "metadata_too_large",
                    "message": f"Metadata exceeds {MAX_METADATA_LENGTH} byte limit.",
                }
            )
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError:
            parsed_metadata = {"raw": metadata}

    result = await memory_tools.create_memory(
        user_id=auth["user_id"],
        bank_id=auth["bank_id"],
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
    token: AccessToken = CurrentAccessToken(),
) -> str:
    """Search your Personal Brain for relevant memories.

    Uses hybrid search combining semantic similarity (meaning-based) and
    full-text search (keyword-based) with Reciprocal Ranked Fusion scoring.
    Returns the most relevant memories sorted by relevance score.
    """
    auth = await _resolve_auth(token)

    # N-05: Validate query length
    if len(query.encode("utf-8")) > MAX_QUERY_LENGTH:
        return json.dumps(
            {
                "status": "error",
                "error": "query_too_long",
                "message": f"Query exceeds {MAX_QUERY_LENGTH} byte limit.",
            }
        )

    limit = max(1, min(50, limit))
    results = await memory_tools.search_memories(
        user_id=auth["user_id"],
        bank_id=auth["bank_id"],
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
    token: AccessToken = CurrentAccessToken(),
) -> str:
    """List recent memories from your Personal Brain.

    Returns memories in reverse chronological order. Optionally filter by type.
    """
    auth = await _resolve_auth(token)
    limit = max(1, min(100, limit))
    offset = max(0, offset)  # F-10: Ensure non-negative offset

    # F-02: Validate memory_type filter
    if memory_type and memory_type not in VALID_MEMORY_TYPES:
        return json.dumps(
            {
                "status": "error",
                "error": "invalid_memory_type",
                "message": "Invalid memory type. Must be one of: "
                + ", ".join(sorted(VALID_MEMORY_TYPES)),
            }
        )

    results = await memory_tools.list_memories(
        user_id=auth["user_id"],
        bank_id=auth["bank_id"],
        limit=limit,
        offset=offset,
        memory_type=memory_type,
    )
    return json.dumps(results, indent=2, default=str)


@mcp.tool()
async def delete_memory(
    memory_id: Annotated[str, "The UUID of the memory to delete"],
    token: AccessToken = CurrentAccessToken(),
) -> str:
    """Delete a specific memory from your Personal Brain."""
    auth = await _resolve_auth(token)
    result = await memory_tools.delete_memory(
        user_id=auth["user_id"],
        bank_id=auth["bank_id"],
        memory_id=memory_id,
    )
    return json.dumps(result, indent=2)


@mcp.tool()
async def brain_stats(
    token: AccessToken = CurrentAccessToken(),
) -> str:
    """Get statistics about your Personal Brain.

    Returns total memory count, breakdown by type, and date range.
    """
    auth = await _resolve_auth(token)
    stats = await memory_tools.get_stats(
        user_id=auth["user_id"],
        bank_id=auth["bank_id"],
    )
    return json.dumps(stats, indent=2, default=str)


@mcp.tool()
async def list_banks(
    token: AccessToken = CurrentAccessToken(),
) -> str:
    """List all memory banks for the current user.

    Returns each bank's name, slug, and whether it's the default.
    Use bank slugs when connecting to organize memories into separate collections.
    """
    auth = await _resolve_auth(token)
    banks = await banks_db.get_user_banks(user_id=auth["user_id"])
    return json.dumps(
        [
            {
                "id": str(b["id"]),
                "name": b["name"],
                "slug": b["slug"],
                "is_default": b["is_default"],
                "created_at": b["created_at"].isoformat() if b.get("created_at") else None,
            }
            for b in banks
        ],
        indent=2,
        default=str,
    )


@mcp.tool()
async def create_bank(
    name: Annotated[str, "Display name for the bank. Example: 'Work Projects'"],
    slug: Annotated[
        str,
        "URL-friendly identifier for the bank. Lowercase, no spaces. Example: 'work'",
    ],
    token: AccessToken = CurrentAccessToken(),
) -> str:
    """Create a new memory bank to organize memories into separate collections.

    Each bank acts as an isolated namespace for memories. Use different banks
    for different contexts (e.g., 'work', 'personal', 'research').
    """
    auth = await _resolve_auth(token)

    # N-04: Validate bank name and slug
    name = name.strip()
    slug = slug.strip().lower()
    if not name:
        return json.dumps(
            {"status": "error", "error": "invalid_name", "message": "Bank name is required."}
        )
    if len(name) > MAX_BANK_NAME_LENGTH:
        return json.dumps(
            {
                "status": "error",
                "error": "name_too_long",
                "message": f"Bank name exceeds {MAX_BANK_NAME_LENGTH} character limit.",
            }
        )
    if not slug or not re.match(r"^[a-z0-9][a-z0-9-]*$", slug):
        return json.dumps(
            {
                "status": "error",
                "error": "invalid_slug",
                "message": "Slug must be lowercase alphanumeric with hyphens.",
            }
        )
    if len(slug) > MAX_BANK_SLUG_LENGTH:
        return json.dumps(
            {
                "status": "error",
                "error": "slug_too_long",
                "message": f"Slug exceeds {MAX_BANK_SLUG_LENGTH} character limit.",
            }
        )

    # F-09: Resolve bank limit based on subscription
    is_paid = await is_subscription_active(auth["user_id"])
    max_banks = MAX_BANKS_PAID if is_paid else MAX_BANKS_FREE
    result = await banks_db.create_bank(
        user_id=auth["user_id"],
        name=name,
        slug=slug,
        max_banks=max_banks,
    )
    if "error" in result:
        return json.dumps({"status": "error", "message": result["error"]}, indent=2)
    return json.dumps(
        {
            "status": "created",
            "bank_id": str(result.get("id", "")),
            "name": result.get("name", ""),
            "slug": result.get("slug", ""),
        },
        indent=2,
    )
