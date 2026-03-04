"""Shared fixtures for mcp-brain tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Environment stub — must be set BEFORE any src.config import
# ---------------------------------------------------------------------------

_ENV = {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_ANON_KEY": "test-anon-key",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "SUPABASE_DB_URL": "postgresql://test:test@localhost:5432/test",
    "OPENAI_API_KEY": "test-openai-key",
}


@pytest.fixture(autouse=True)
def _patch_env(monkeypatch):
    """Ensure required env vars are present for every test."""
    for key, value in _ENV.items():
        monkeypatch.setenv(key, value)


# ---------------------------------------------------------------------------
# Common test data
# ---------------------------------------------------------------------------

TEST_USER_ID = str(uuid.uuid4())
TEST_BANK_ID = str(uuid.uuid4())
TEST_MEMORY_ID = str(uuid.uuid4())
FAKE_EMBEDDING = [0.1] * 1536


# ---------------------------------------------------------------------------
# Mock asyncpg pool
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_pool():
    """Return a (pool, conn) tuple of AsyncMock objects.

    The pool exposes .fetchrow, .fetch, .execute directly (for code that
    calls pool.fetchrow) and also works with `async with pool.acquire()`.
    """
    pool = AsyncMock()
    conn = AsyncMock()

    # Support `async with pool.acquire() as conn:`
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    return pool, conn


# ---------------------------------------------------------------------------
# Mock OpenAI client
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_openai_embedding():
    """Patch the OpenAI client to return a fake 1536-dim embedding."""
    embedding_obj = MagicMock()
    embedding_obj.embedding = FAKE_EMBEDDING

    response = MagicMock()
    response.data = [embedding_obj]

    mock_client = AsyncMock()
    mock_client.embeddings.create = AsyncMock(return_value=response)

    with patch("src.embeddings._get_client", return_value=mock_client):
        yield mock_client


# ---------------------------------------------------------------------------
# Mock JWT payload
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_jwt_payload():
    """Valid decoded JWT payload."""
    return {
        "sub": TEST_USER_ID,
        "aud": "authenticated",
        "iss": "https://test.supabase.co/auth/v1",
        "exp": 9999999999,
        "email": "test@example.com",
        "role": "authenticated",
    }
