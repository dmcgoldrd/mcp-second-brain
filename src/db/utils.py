"""Shared database utilities."""

from __future__ import annotations

import uuid


def parse_uuid(value: str, name: str = "id") -> uuid.UUID:
    """Parse a string to UUID, raising ValueError with context on failure."""
    try:
        return uuid.UUID(value)
    except ValueError as err:
        raise ValueError(f"Invalid {name} format") from err
