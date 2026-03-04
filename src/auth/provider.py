"""MCP Brain auth provider using FastMCP's SupabaseProvider.

Extends SupabaseProvider to fix the /.well-known/oauth-authorization-server
metadata endpoint — Supabase returns 404 for this URL when the OAuth 2.1
server feature isn't enabled. We construct the metadata from Supabase's
OIDC discovery endpoint instead.
"""

from __future__ import annotations

import logging
import time

import httpx
from fastmcp.server.auth.providers.supabase import SupabaseProvider
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger("mcp-brain")

# F-14: OIDC metadata cache (5-minute TTL)
_OIDC_CACHE_TTL = 300  # seconds
_oidc_cache: dict[str, object] = {}
_oidc_cache_expires: float = 0.0


class MCPBrainAuthProvider(SupabaseProvider):
    """Supabase auth provider with fixed OAuth AS metadata.

    Supabase serves OIDC config at /.well-known/openid-configuration but
    may not serve OAuth AS metadata at /.well-known/oauth-authorization-server
    (requires the OAuth 2.1 Server beta to be enabled). This subclass
    fetches OIDC config and transforms it to OAuth AS metadata format so
    MCP clients can discover authorization endpoints.
    """

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """Get OAuth routes with fixed authorization server metadata."""
        # Get the standard protected resource routes from parent
        # but skip SupabaseProvider's broken forwarding route
        from fastmcp.server.auth import RemoteAuthProvider

        routes = RemoteAuthProvider.get_routes(self, mcp_path)

        oidc_url = f"{self.project_url}/{self.auth_route}/.well-known/openid-configuration"

        async def oauth_authorization_server_metadata(request):
            """Serve OAuth AS metadata constructed from Supabase's OIDC config."""
            global _oidc_cache, _oidc_cache_expires

            try:
                now = time.monotonic()

                # F-14: Return cached response if valid
                if _oidc_cache and now < _oidc_cache_expires:
                    return JSONResponse(_oidc_cache)

                async with httpx.AsyncClient() as client:
                    response = await client.get(oidc_url)
                    response.raise_for_status()
                    oidc = response.json()

                # Transform OIDC config to OAuth AS metadata (RFC 8414)
                metadata = {
                    "issuer": oidc.get("issuer"),
                    "authorization_endpoint": oidc.get("authorization_endpoint"),
                    "token_endpoint": oidc.get("token_endpoint"),
                    "jwks_uri": oidc.get("jwks_uri"),
                    "scopes_supported": oidc.get("scopes_supported", []),
                    "response_types_supported": oidc.get("response_types_supported", ["code"]),
                    "grant_types_supported": oidc.get(
                        "grant_types_supported",
                        ["authorization_code", "refresh_token"],
                    ),
                    "token_endpoint_auth_methods_supported": oidc.get(
                        "token_endpoint_auth_methods_supported", ["none"]
                    ),
                    "code_challenge_methods_supported": oidc.get(
                        "code_challenge_methods_supported", ["S256"]
                    ),
                }

                # F-14: Cache the response
                _oidc_cache = metadata
                _oidc_cache_expires = now + _OIDC_CACHE_TTL

                return JSONResponse(metadata)
            except Exception:
                # F-07: Don't leak exception details to clients
                logger.exception("Failed to fetch OIDC metadata from %s", oidc_url)
                return JSONResponse(
                    {
                        "error": "server_error",
                        "error_description": "Failed to fetch authorization server metadata",
                    },
                    status_code=500,
                )

        routes.append(
            Route(
                "/.well-known/oauth-authorization-server",
                endpoint=oauth_authorization_server_metadata,
                methods=["GET", "OPTIONS"],
            )
        )

        return routes
