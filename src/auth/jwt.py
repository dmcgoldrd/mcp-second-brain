"""JWT validation using Supabase JWKS endpoint."""

from __future__ import annotations

import jwt
from jwt import PyJWKClient

from src.config import SUPABASE_JWKS_URL, SUPABASE_URL

_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    """Get or create the JWKS client for Supabase token validation."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(SUPABASE_JWKS_URL)
    return _jwks_client


def validate_token(token: str) -> dict:
    """Validate a Supabase JWT and return the decoded payload.

    Returns dict with at minimum: sub (user_id), email, role.
    Raises jwt.exceptions.PyJWTError on invalid tokens.
    """
    jwks_client = _get_jwks_client()
    signing_key = jwks_client.get_signing_key_from_jwt(token)

    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience="authenticated",
        issuer=f"{SUPABASE_URL}/auth/v1",
    )
    return payload


def extract_user_id(token: str) -> str:
    """Extract the user ID (sub claim) from a validated JWT."""
    payload = validate_token(token)
    return payload["sub"]
