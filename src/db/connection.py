"""Database connection pool using asyncpg with pgvector support."""

import logging

import asyncpg
from pgvector.asyncpg import register_vector

from src.config import SUPABASE_DB_URL

logger = logging.getLogger("mcp-brain")

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            SUPABASE_DB_URL,
            min_size=2,
            max_size=10,
            init=_init_connection,
        )
    return _pool


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Initialize each connection with pgvector support."""
    await register_vector(conn)


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
