"""MCP Brain provider — communicates with a running MCP Brain server via Streamable HTTP.

Uses the MCP JSON-RPC protocol to call tools (create_memory, search_memories, delete_memory)
on a live MCP Brain instance. Authenticates with a Supabase JWT.
"""

from __future__ import annotations

import json
import logging
import os
import uuid

import httpx

logger = logging.getLogger("benchmarks.provider.mcpbrain")

# MCP JSON-RPC constants
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-03-26"


class MCPBrainProvider:
    """Benchmark provider that talks to MCP Brain via the MCP Streamable HTTP transport.

    Each method sends a JSON-RPC request to the /mcp/ endpoint, following the
    MCP protocol: initialize handshake, then tools/call for each operation.

    Configuration:
        MCPBRAIN_URL   — server URL (default: http://localhost:8080)
        MCPBRAIN_TOKEN — Supabase JWT for authentication
        MCPBRAIN_BANK  — optional bank slug (default: uses server default bank)
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        bank_slug: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("MCPBRAIN_URL", "http://localhost:8080")
        ).rstrip("/")
        self.mcp_url = f"{self.base_url}/mcp"
        self.token = token or os.environ["MCPBRAIN_TOKEN"]
        self.bank_slug = bank_slug or os.environ.get("MCPBRAIN_BANK")
        self.timeout = timeout
        self._session_id: str | None = None
        self._initialized = False
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "mcpbrain"

    # -- lifecycle ---------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if self.bank_slug:
                headers["x-bank-slug"] = self.bank_slug
            self._client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def _ensure_initialized(self) -> None:
        """Send MCP initialize + initialized notification if not already done."""
        if self._initialized:
            return

        client = await self._get_client()

        # 1. Send initialize request
        init_payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": str(uuid.uuid4()),
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-brain-benchmark", "version": "0.1.0"},
            },
        }

        resp = await client.post(self.mcp_url, json=init_payload)
        resp.raise_for_status()

        # Extract session ID from response headers (Mcp-Session-Id)
        self._session_id = resp.headers.get("mcp-session-id")
        if self._session_id:
            client.headers["mcp-session-id"] = self._session_id

        # 2. Send initialized notification (no id = notification)
        notif_payload = {
            "jsonrpc": JSONRPC_VERSION,
            "method": "notifications/initialized",
        }
        await client.post(self.mcp_url, json=notif_payload)

        self._initialized = True
        logger.info("MCP session initialized (session_id=%s)", self._session_id)

    def _parse_sse_response(self, text: str) -> dict:
        """Parse an SSE response to extract the JSON-RPC message."""
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
        # Fallback: try parsing the whole response as JSON
        return json.loads(text)

    async def _call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Send a tools/call JSON-RPC request and return the parsed result."""
        await self._ensure_initialized()
        client = await self._get_client()

        payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": str(uuid.uuid4()),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        resp = await client.post(self.mcp_url, json=payload)
        resp.raise_for_status()

        # Response may be SSE (text/event-stream) or plain JSON
        content_type = resp.headers.get("content-type", "")
        if "event-stream" in content_type:
            body = self._parse_sse_response(resp.text)
        else:
            body = resp.json()

        # Handle JSON-RPC error
        if "error" in body:
            raise RuntimeError(f"MCP tool error: {body['error']}")

        # Extract text content from MCP result
        result = body.get("result", {})
        content_list = result.get("content", [])
        for item in content_list:
            if item.get("type") == "text":
                try:
                    return json.loads(item["text"])
                except (json.JSONDecodeError, KeyError):
                    return {"raw": item.get("text", "")}

        return result

    # -- provider interface ------------------------------------------------------

    async def add_memory(self, content: str, user_id: str, session_id: str) -> str:
        """Ingest a single memory into MCP Brain.

        Args:
            content: The memory text to store.
            user_id: Logical user ID (for benchmark tracking; auth comes from JWT).
            session_id: Conversation session identifier (stored as metadata).

        Returns:
            The memory ID from the server response.
        """
        result = await self._call_tool(
            "create_memory",
            {
                "content": content,
                "source": "import",
                "metadata": json.dumps(
                    {
                        "benchmark_user": user_id,
                        "benchmark_session": session_id,
                    }
                ),
            },
        )
        return result.get("memory_id", result.get("id", ""))

    async def search(self, query: str, user_id: str, limit: int = 10) -> list[dict]:
        """Search memories by semantic + full-text query.

        Args:
            query: Natural language search query.
            user_id: Logical user ID (auth comes from JWT).
            limit: Maximum results to return.

        Returns:
            List of memory dicts with content and metadata.
        """
        result = await self._call_tool(
            "search_memories",
            {"query": query, "limit": limit},
        )

        # search_memories returns {"memories": [...]} or a list directly
        if isinstance(result, list):
            return result
        return result.get("memories", result.get("results", []))

    async def reset(self, user_id: str) -> None:
        """Clear all memories for the benchmark user.

        Since MCP Brain doesn't expose a bulk-delete tool, we list all memories
        and delete them individually. This is only used for benchmark setup.
        """
        logger.info("Resetting memories for benchmark user %s", user_id)
        offset = 0
        deleted = 0

        while True:
            result = await self._call_tool(
                "list_memories",
                {"limit": 100, "offset": offset},
            )

            memories = []
            if isinstance(result, list):
                memories = result
            elif isinstance(result, dict):
                memories = result.get("memories", [])

            if not memories:
                break

            for mem in memories:
                mem_id = mem.get("id", mem.get("memory_id", ""))
                if mem_id:
                    await self._call_tool("delete_memory", {"memory_id": mem_id})
                    deleted += 1

            # If we got fewer than 100, we've reached the end
            if len(memories) < 100:
                break
            # Don't increment offset — we just deleted them, so the next page is at 0

        logger.info("Deleted %d memories", deleted)

    async def close(self) -> None:
        """Clean up the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._initialized = False
            self._session_id = None
