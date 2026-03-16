"""Shared database utilities."""

from __future__ import annotations

import json
import uuid


def parse_uuid(value: str, name: str = "id") -> uuid.UUID:
    """Parse a string to UUID, raising ValueError with context on failure."""
    try:
        return uuid.UUID(value)
    except ValueError as err:
        raise ValueError(f"Invalid {name} format") from err


def parse_uuids(**kwargs: str) -> dict[str, uuid.UUID]:
    """Parse multiple named UUID strings. Returns dict of name -> UUID."""
    return {name: parse_uuid(value, name) for name, value in kwargs.items()}


def error_response(error_code: str, message: str, **extra) -> str:
    """Build a standardized JSON error response string."""
    return json.dumps({"status": "error", "error": error_code, "message": message, **extra})
