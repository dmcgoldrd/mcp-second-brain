"""Tests for src.consolidation_endpoint — memory consolidation HTTP handler."""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import TEST_BANK_ID, TEST_USER_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    body: bytes | None = None,
    service_key: str = "",
) -> MagicMock:
    """Build a mock Starlette Request with optional body and service key header."""
    request = MagicMock()
    request.body = AsyncMock(return_value=body or b"")
    headers = {}
    if service_key:
        headers["X-Service-Key"] = service_key
    request.headers = headers
    return request


def _install_fake_consolidation_module(
    consolidate_user: AsyncMock | None = None,
    consolidate_all: AsyncMock | None = None,
):
    """Install a fake ``src.consolidation`` module so the deferred import works.

    The consolidation_endpoint does ``from src.consolidation import ...`` inside
    the handler.  We inject a synthetic module into ``sys.modules`` so those
    imports resolve without the real module existing.
    """
    mod = types.ModuleType("src.consolidation")
    mod.consolidate_user = consolidate_user or AsyncMock(return_value={})
    mod.consolidate_all_active_users = consolidate_all or AsyncMock(return_value={})
    sys.modules["src.consolidation"] = mod
    return mod


# ===========================================================================
# Auth
# ===========================================================================


class TestConsolidationAuth:
    async def test_rejects_missing_service_key(self):
        from src.consolidation_endpoint import consolidation_handler

        request = _make_request(service_key="")

        with patch(
            "src.consolidation_endpoint.SUPABASE_SERVICE_ROLE_KEY",
            "test-service-role-key",
        ):
            resp = await consolidation_handler(request)

        assert resp.status_code == 401
        body = json.loads(resp.body)
        assert "unauthorized" in body["error"].lower()

    async def test_rejects_wrong_service_key(self):
        from src.consolidation_endpoint import consolidation_handler

        request = _make_request(service_key="wrong-key-entirely")

        with patch(
            "src.consolidation_endpoint.SUPABASE_SERVICE_ROLE_KEY",
            "test-service-role-key",
        ):
            resp = await consolidation_handler(request)

        assert resp.status_code == 401
        body = json.loads(resp.body)
        assert "unauthorized" in body["error"].lower()

    async def test_accepts_valid_service_key(self):
        from src.consolidation_endpoint import consolidation_handler

        request = _make_request(service_key="test-service-role-key")
        mock_all = AsyncMock(return_value={"consolidated": 0})
        _install_fake_consolidation_module(consolidate_all=mock_all)

        try:
            with patch(
                "src.consolidation_endpoint.SUPABASE_SERVICE_ROLE_KEY",
                "test-service-role-key",
            ):
                resp = await consolidation_handler(request)
        finally:
            sys.modules.pop("src.consolidation", None)

        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["status"] == "ok"
        mock_all.assert_called_once()


# ===========================================================================
# Behavior
# ===========================================================================


class TestConsolidationBehavior:
    async def test_consolidates_specific_user_when_body_provided(self):
        from src.consolidation_endpoint import consolidation_handler

        payload = {"user_id": TEST_USER_ID, "bank_id": TEST_BANK_ID}
        request = _make_request(
            body=json.dumps(payload).encode(),
            service_key="test-service-role-key",
        )
        mock_user = AsyncMock(return_value={"memories_consolidated": 5})
        _install_fake_consolidation_module(consolidate_user=mock_user)

        try:
            with patch(
                "src.consolidation_endpoint.SUPABASE_SERVICE_ROLE_KEY",
                "test-service-role-key",
            ):
                resp = await consolidation_handler(request)
        finally:
            sys.modules.pop("src.consolidation", None)

        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["status"] == "ok"
        assert body["summary"]["memories_consolidated"] == 5

        mock_user.assert_called_once_with(TEST_USER_ID, TEST_BANK_ID)

    async def test_consolidates_all_users_when_no_body(self):
        from src.consolidation_endpoint import consolidation_handler

        request = _make_request(
            body=b"",
            service_key="test-service-role-key",
        )
        mock_all = AsyncMock(return_value={"users_processed": 10})
        _install_fake_consolidation_module(consolidate_all=mock_all)

        try:
            with patch(
                "src.consolidation_endpoint.SUPABASE_SERVICE_ROLE_KEY",
                "test-service-role-key",
            ):
                resp = await consolidation_handler(request)
        finally:
            sys.modules.pop("src.consolidation", None)

        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["status"] == "ok"
        assert body["summary"]["users_processed"] == 10

        mock_all.assert_called_once()

    async def test_returns_500_on_consolidation_failure(self):
        from src.consolidation_endpoint import consolidation_handler

        request = _make_request(
            body=b"",
            service_key="test-service-role-key",
        )
        mock_all = AsyncMock(side_effect=RuntimeError("Pipeline exploded"))
        _install_fake_consolidation_module(consolidate_all=mock_all)

        try:
            with patch(
                "src.consolidation_endpoint.SUPABASE_SERVICE_ROLE_KEY",
                "test-service-role-key",
            ):
                resp = await consolidation_handler(request)
        finally:
            sys.modules.pop("src.consolidation", None)

        assert resp.status_code == 500
        body = json.loads(resp.body)
        assert "failed" in body["error"].lower()
