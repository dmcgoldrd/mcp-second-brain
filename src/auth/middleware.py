"""JWT authentication middleware for MCP Brain.

Intercepts every tool call, validates the Supabase JWT from the
Authorization header, and injects the authenticated user_id and
resolved bank_id into FastMCP context state.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware

from src.auth.jwt import validate_token
from src.db.banks import get_bank_by_slug, get_default_bank
from src.ratelimit import tool_limiter

logger = logging.getLogger("mcp-brain.auth")


class JWTAuthMiddleware(Middleware):
    """Validates Supabase JWT and enforces per-user rate limits."""

    async def on_call_tool(self, context, call_next):
        headers = get_http_headers() or {}
        auth_header = headers.get("authorization", "")

        if not auth_header.startswith("Bearer "):
            raise Exception("Authentication required: missing or invalid Authorization header")

        token = auth_header.removeprefix("Bearer ").strip()

        try:
            payload = validate_token(token)
        except Exception as e:
            logger.warning("JWT validation failed: %s", e)
            raise Exception("Authentication failed: invalid token") from e

        user_id = payload.get("sub")
        if not user_id:
            raise Exception("Authentication failed: no user ID in token")

        # Per-user rate limit
        if not tool_limiter.check(user_id):
            raise Exception("Rate limit exceeded. Please slow down.")

        # Resolve bank from URL query parameter or default
        bank_id = await self._resolve_bank_id(user_id, headers)

        # Store user_id and bank_id in context for downstream tools
        if hasattr(context, "fastmcp_context"):
            context.fastmcp_context._state = getattr(context.fastmcp_context, "_state", {})
            context.fastmcp_context._state["user_id"] = user_id
            context.fastmcp_context._state["bank_id"] = bank_id
        elif hasattr(context, "set_state"):
            context.set_state("user_id", user_id)
            context.set_state("bank_id", bank_id)

        return await call_next(context)

    async def _resolve_bank_id(self, user_id: str, headers: dict) -> str:
        """Resolve bank_id from the request URL ?bank= param or the user's default bank."""
        # Try to extract the bank slug from various header sources
        bank_slug = None

        # Check for the bank slug in common URL-carrying headers
        for header_key in ("x-forwarded-url", "referer", "x-original-url"):
            url_value = headers.get(header_key, "")
            if url_value:
                parsed = urlparse(url_value)
                params = parse_qs(parsed.query)
                if "bank" in params:
                    bank_slug = params["bank"][0]
                    break

        # Also check a direct x-bank-slug header as a simpler alternative
        if not bank_slug:
            bank_slug = headers.get("x-bank-slug", "").strip() or None

        if bank_slug:
            bank = await get_bank_by_slug(user_id, bank_slug)
            if not bank:
                raise Exception(f"Bank '{bank_slug}' not found for this user")
            return str(bank["id"])

        # Fall back to the user's default bank
        default_bank = await get_default_bank(user_id)
        if not default_bank:
            raise Exception("No default bank found. Please create a bank first.")
        return str(default_bank["id"])
