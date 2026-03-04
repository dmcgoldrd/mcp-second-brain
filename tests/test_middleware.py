"""Tests for src.auth.middleware — JWT auth middleware."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import TEST_BANK_ID, TEST_USER_ID


def _make_headers(token="valid-token", extra=None):
    headers = {"authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers


def _mock_context():
    ctx = MagicMock()
    ctx.fastmcp_context = MagicMock()
    ctx.fastmcp_context._state = {}
    return ctx


class TestJWTAuthMiddleware:
    async def test_extracts_auth_header(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock(return_value="ok")
        ctx = _mock_context()

        default_bank = {"id": uuid.UUID(TEST_BANK_ID), "name": "Default", "slug": "default"}

        with (
            patch("src.auth.middleware.get_http_headers", return_value=_make_headers()),
            patch("src.auth.middleware.validate_token", return_value={"sub": TEST_USER_ID}),
            patch("src.auth.middleware.tool_limiter") as mock_limiter,
            patch(
                "src.auth.middleware.get_default_bank",
                new_callable=AsyncMock,
                return_value=default_bank,
            ),
        ):
            mock_limiter.check.return_value = True
            await mw.on_call_tool(ctx, call_next)

        call_next.assert_called_once_with(ctx)
        assert ctx.fastmcp_context._state["user_id"] == TEST_USER_ID
        assert ctx.fastmcp_context._state["bank_id"] == TEST_BANK_ID

    async def test_rejects_missing_auth_header(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock()
        ctx = _mock_context()

        with (
            patch("src.auth.middleware.get_http_headers", return_value={}),
            pytest.raises(Exception, match="Authentication required"),
        ):
            await mw.on_call_tool(ctx, call_next)

    async def test_rejects_invalid_token(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock()
        ctx = _mock_context()

        with (
            patch("src.auth.middleware.get_http_headers", return_value=_make_headers()),
            patch("src.auth.middleware.validate_token", side_effect=Exception("bad token")),
            pytest.raises(Exception, match="Authentication failed"),
        ):
            await mw.on_call_tool(ctx, call_next)

    async def test_rejects_token_without_sub(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock()
        ctx = _mock_context()

        with (
            patch("src.auth.middleware.get_http_headers", return_value=_make_headers()),
            patch("src.auth.middleware.validate_token", return_value={"email": "test@x.com"}),
            pytest.raises(Exception, match="no user ID"),
        ):
            await mw.on_call_tool(ctx, call_next)

    async def test_rate_limit_enforced(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock()
        ctx = _mock_context()

        with (
            patch("src.auth.middleware.get_http_headers", return_value=_make_headers()),
            patch("src.auth.middleware.validate_token", return_value={"sub": TEST_USER_ID}),
            patch("src.auth.middleware.tool_limiter") as mock_limiter,
            pytest.raises(Exception, match="Rate limit exceeded"),
        ):
            mock_limiter.check.return_value = False
            await mw.on_call_tool(ctx, call_next)

    async def test_resolves_bank_from_url_header(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock(return_value="ok")
        ctx = _mock_context()
        bank_id = str(uuid.uuid4())
        bank = {"id": bank_id, "name": "Work", "slug": "work"}

        headers = _make_headers(
            extra={"x-forwarded-url": "https://brain.example.com/mcp?bank=work"}
        )

        with (
            patch("src.auth.middleware.get_http_headers", return_value=headers),
            patch("src.auth.middleware.validate_token", return_value={"sub": TEST_USER_ID}),
            patch("src.auth.middleware.tool_limiter") as mock_limiter,
            patch(
                "src.auth.middleware.get_bank_by_slug", new_callable=AsyncMock, return_value=bank
            ),
        ):
            mock_limiter.check.return_value = True
            await mw.on_call_tool(ctx, call_next)

        assert ctx.fastmcp_context._state["bank_id"] == bank_id

    async def test_resolves_bank_from_x_bank_slug_header(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock(return_value="ok")
        ctx = _mock_context()
        bank_id = str(uuid.uuid4())
        bank = {"id": bank_id, "name": "Personal", "slug": "personal"}

        headers = _make_headers(extra={"x-bank-slug": "personal"})

        with (
            patch("src.auth.middleware.get_http_headers", return_value=headers),
            patch("src.auth.middleware.validate_token", return_value={"sub": TEST_USER_ID}),
            patch("src.auth.middleware.tool_limiter") as mock_limiter,
            patch(
                "src.auth.middleware.get_bank_by_slug", new_callable=AsyncMock, return_value=bank
            ),
        ):
            mock_limiter.check.return_value = True
            await mw.on_call_tool(ctx, call_next)

        assert ctx.fastmcp_context._state["bank_id"] == bank_id

    async def test_raises_when_bank_slug_not_found(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock()
        ctx = _mock_context()

        headers = _make_headers(extra={"x-bank-slug": "nonexistent"})

        with (
            patch("src.auth.middleware.get_http_headers", return_value=headers),
            patch("src.auth.middleware.validate_token", return_value={"sub": TEST_USER_ID}),
            patch("src.auth.middleware.tool_limiter") as mock_limiter,
            patch(
                "src.auth.middleware.get_bank_by_slug", new_callable=AsyncMock, return_value=None
            ),
            pytest.raises(Exception, match="not found"),
        ):
            mock_limiter.check.return_value = True
            await mw.on_call_tool(ctx, call_next)

    async def test_uses_set_state_fallback(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock(return_value="ok")
        # Context with set_state but no fastmcp_context
        ctx = MagicMock(spec=["set_state"])
        ctx.set_state = MagicMock()

        default_bank = {"id": uuid.UUID(TEST_BANK_ID), "name": "Default", "slug": "default"}

        with (
            patch("src.auth.middleware.get_http_headers", return_value=_make_headers()),
            patch("src.auth.middleware.validate_token", return_value={"sub": TEST_USER_ID}),
            patch("src.auth.middleware.tool_limiter") as mock_limiter,
            patch(
                "src.auth.middleware.get_default_bank",
                new_callable=AsyncMock,
                return_value=default_bank,
            ),
        ):
            mock_limiter.check.return_value = True
            await mw.on_call_tool(ctx, call_next)

        ctx.set_state.assert_any_call("user_id", TEST_USER_ID)
        ctx.set_state.assert_any_call("bank_id", TEST_BANK_ID)

    async def test_raises_when_no_default_bank(self):
        from src.auth.middleware import JWTAuthMiddleware

        mw = JWTAuthMiddleware()
        call_next = AsyncMock()
        ctx = _mock_context()

        with (
            patch("src.auth.middleware.get_http_headers", return_value=_make_headers()),
            patch("src.auth.middleware.validate_token", return_value={"sub": TEST_USER_ID}),
            patch("src.auth.middleware.tool_limiter") as mock_limiter,
            patch(
                "src.auth.middleware.get_default_bank", new_callable=AsyncMock, return_value=None
            ),
            pytest.raises(Exception, match="No default bank"),
        ):
            mock_limiter.check.return_value = True
            await mw.on_call_tool(ctx, call_next)
