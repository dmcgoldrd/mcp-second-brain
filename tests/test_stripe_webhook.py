"""Tests for src.stripe_webhook — Stripe webhook handler."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import stripe

from tests.conftest import TEST_USER_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(body: bytes = b"{}", sig: str = "sig_valid") -> MagicMock:
    """Build a mock Starlette Request with the given body and signature."""
    request = MagicMock()
    request.body = AsyncMock(return_value=body)
    request.headers = {"stripe-signature": sig} if sig else {}
    return request


def _stripe_event(event_type: str, data_object: dict) -> dict:
    """Return a dict shaped like a Stripe Event."""
    return {
        "id": "evt_test_123",
        "type": event_type,
        "data": {"object": data_object},
    }


def _mock_pool_and_conn():
    """Create pool + connection mocks for ``async with pool.acquire() as conn, conn.transaction():``

    The source code does:
        pool = await get_pool()            # get_pool is an async function
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(...)

    ``pool.acquire()`` must return an async context manager (not a coroutine).
    ``conn.transaction()`` must also return an async context manager.
    """
    conn = AsyncMock()

    # conn.transaction() -> async context manager
    @asynccontextmanager
    async def _txn_ctx():
        yield None

    conn.transaction = _txn_ctx

    # pool.acquire() -> async context manager yielding conn
    pool = MagicMock()

    @asynccontextmanager
    async def _acquire_ctx():
        yield conn

    pool.acquire = _acquire_ctx

    return pool, conn


# ===========================================================================
# Signature Verification
# ===========================================================================


class TestSignatureVerification:
    async def test_rejects_invalid_signature(self):
        from src.stripe_webhook import stripe_webhook_handler

        request = _make_request(body=b'{"type":"test"}', sig="sig_bad")

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                side_effect=stripe.SignatureVerificationError("bad sig", "sig_bad"),
            ),
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 400
        body = json.loads(resp.body)
        assert "signature" in body["error"].lower()

    async def test_rejects_missing_signature(self):
        from src.stripe_webhook import stripe_webhook_handler

        request = _make_request(body=b'{"type":"test"}', sig="")

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                side_effect=stripe.SignatureVerificationError("no sig", ""),
            ),
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 400

    async def test_rejects_when_secret_not_configured(self):
        from src.stripe_webhook import stripe_webhook_handler

        request = _make_request()

        with patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", ""):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 500
        body = json.loads(resp.body)
        assert "not configured" in body["error"].lower()


# ===========================================================================
# checkout.session.completed
# ===========================================================================


class TestCheckoutCompleted:
    async def test_checkout_completed_creates_subscription(self):
        from src.stripe_webhook import stripe_webhook_handler

        session_data = {
            "client_reference_id": TEST_USER_ID,
            "customer": "cus_abc123",
            "subscription": "sub_abc123",
        }
        event = _stripe_event("checkout.session.completed", session_data)
        request = _make_request(body=json.dumps(session_data).encode())
        pool, conn = _mock_pool_and_conn()

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                return_value=event,
            ),
            patch(
                "src.stripe_webhook.get_pool",
                new_callable=AsyncMock,
                return_value=pool,
            ),
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 200

        # Verify the subscription INSERT was called
        execute_calls = conn.execute.call_args_list
        assert len(execute_calls) == 2  # profile UPDATE + subscription INSERT

        sub_insert_sql = execute_calls[1][0][0]
        assert "INSERT INTO subscriptions" in sub_insert_sql
        assert execute_calls[1][0][1] == TEST_USER_ID
        assert execute_calls[1][0][2] == "sub_abc123"
        assert execute_calls[1][0][3] == "cus_abc123"

    async def test_checkout_completed_updates_profile_status(self):
        from src.stripe_webhook import stripe_webhook_handler

        session_data = {
            "client_reference_id": TEST_USER_ID,
            "customer": "cus_abc123",
            "subscription": "sub_abc123",
        }
        event = _stripe_event("checkout.session.completed", session_data)
        request = _make_request()
        pool, conn = _mock_pool_and_conn()

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                return_value=event,
            ),
            patch(
                "src.stripe_webhook.get_pool",
                new_callable=AsyncMock,
                return_value=pool,
            ),
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 200

        # First execute call should be the profile UPDATE
        profile_update_sql = conn.execute.call_args_list[0][0][0]
        assert "UPDATE profiles" in profile_update_sql
        assert "subscription_status" in profile_update_sql
        assert conn.execute.call_args_list[0][0][1] == "cus_abc123"
        assert conn.execute.call_args_list[0][0][2] == TEST_USER_ID

    async def test_checkout_completed_skips_missing_user_id(self):
        from src.stripe_webhook import stripe_webhook_handler

        # Session without client_reference_id
        session_data = {
            "customer": "cus_abc123",
            "subscription": "sub_abc123",
        }
        event = _stripe_event("checkout.session.completed", session_data)
        request = _make_request()

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                return_value=event,
            ),
            patch("src.stripe_webhook.get_pool", new_callable=AsyncMock) as mock_get_pool,
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 200
        # get_pool should never be called since we bail early
        mock_get_pool.assert_not_called()


# ===========================================================================
# customer.subscription.updated
# ===========================================================================


class TestSubscriptionUpdated:
    async def test_subscription_updated_changes_status(self):
        from src.stripe_webhook import stripe_webhook_handler

        sub_data = {
            "id": "sub_xyz",
            "status": "past_due",
            "customer": "cus_abc123",
        }
        event = _stripe_event("customer.subscription.updated", sub_data)
        request = _make_request()
        pool, conn = _mock_pool_and_conn()

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                return_value=event,
            ),
            patch(
                "src.stripe_webhook.get_pool",
                new_callable=AsyncMock,
                return_value=pool,
            ),
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 200

        # Verify subscription update
        sub_update_sql = conn.execute.call_args_list[0][0][0]
        assert "UPDATE subscriptions" in sub_update_sql
        assert conn.execute.call_args_list[0][0][1] == "past_due"
        assert conn.execute.call_args_list[0][0][2] == "sub_xyz"

        # Verify profile status update (status != "active" so uses raw status)
        profile_update_sql = conn.execute.call_args_list[1][0][0]
        assert "UPDATE profiles" in profile_update_sql
        assert conn.execute.call_args_list[1][0][1] == "past_due"
        assert conn.execute.call_args_list[1][0][2] == "cus_abc123"

    async def test_subscription_updated_uses_transaction(self):
        from src.stripe_webhook import stripe_webhook_handler

        sub_data = {
            "id": "sub_xyz",
            "status": "active",
            "customer": "cus_abc123",
        }
        event = _stripe_event("customer.subscription.updated", sub_data)
        request = _make_request()
        pool, conn = _mock_pool_and_conn()

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                return_value=event,
            ),
            patch(
                "src.stripe_webhook.get_pool",
                new_callable=AsyncMock,
                return_value=pool,
            ),
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 200

        # Verify conn.execute was called — proves the transaction block was entered.
        # (We can't assert on pool.acquire since it's a plain function, but if
        # execute was called the full `async with pool.acquire() as conn, conn.transaction():`
        # chain must have succeeded.)
        assert conn.execute.call_count >= 1


# ===========================================================================
# customer.subscription.deleted
# ===========================================================================


class TestSubscriptionDeleted:
    async def test_subscription_deleted_marks_canceled(self):
        from src.stripe_webhook import stripe_webhook_handler

        sub_data = {
            "id": "sub_xyz",
            "customer": "cus_abc123",
        }
        event = _stripe_event("customer.subscription.deleted", sub_data)
        request = _make_request()
        pool, conn = _mock_pool_and_conn()

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                return_value=event,
            ),
            patch(
                "src.stripe_webhook.get_pool",
                new_callable=AsyncMock,
                return_value=pool,
            ),
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 200

        # Verify subscription marked canceled
        sub_sql = conn.execute.call_args_list[0][0][0]
        assert "UPDATE subscriptions" in sub_sql
        assert "'canceled'" in sub_sql
        assert conn.execute.call_args_list[0][0][1] == "sub_xyz"

        # Verify profile marked canceled
        profile_sql = conn.execute.call_args_list[1][0][0]
        assert "UPDATE profiles" in profile_sql
        assert conn.execute.call_args_list[1][0][1] == "canceled"
        assert conn.execute.call_args_list[1][0][2] == "cus_abc123"


# ===========================================================================
# invoice.payment_failed
# ===========================================================================


class TestPaymentFailed:
    async def test_payment_failed_marks_past_due(self):
        from src.stripe_webhook import stripe_webhook_handler

        invoice_data = {
            "customer": "cus_abc123",
        }
        event = _stripe_event("invoice.payment_failed", invoice_data)
        request = _make_request()
        pool, conn = _mock_pool_and_conn()

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                return_value=event,
            ),
            patch(
                "src.stripe_webhook.get_pool",
                new_callable=AsyncMock,
                return_value=pool,
            ),
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 200

        # Verify profile marked past_due
        profile_sql = conn.execute.call_args_list[0][0][0]
        assert "UPDATE profiles" in profile_sql
        assert conn.execute.call_args_list[0][0][1] == "past_due"
        assert conn.execute.call_args_list[0][0][2] == "cus_abc123"


# ===========================================================================
# Error Handling
# ===========================================================================


class TestErrorHandling:
    async def test_handler_catches_sub_handler_errors(self):
        from src.stripe_webhook import stripe_webhook_handler

        session_data = {
            "client_reference_id": TEST_USER_ID,
            "customer": "cus_abc123",
            "subscription": "sub_abc123",
        }
        event = _stripe_event("checkout.session.completed", session_data)
        request = _make_request()

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                return_value=event,
            ),
            patch(
                "src.stripe_webhook.get_pool",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB connection failed"),
            ),
        ):
            resp = await stripe_webhook_handler(request)

        # Should return 500, not raise unhandled
        assert resp.status_code == 500
        body = json.loads(resp.body)
        assert "failed" in body["error"].lower()

    async def test_unhandled_event_type_returns_ok(self):
        from src.stripe_webhook import stripe_webhook_handler

        event = _stripe_event("some.unknown.event", {"id": "obj_123"})
        request = _make_request()

        with (
            patch("src.stripe_webhook.STRIPE_WEBHOOK_SECRET", "whsec_test"),
            patch(
                "src.stripe_webhook.stripe.Webhook.construct_event",
                return_value=event,
            ),
        ):
            resp = await stripe_webhook_handler(request)

        assert resp.status_code == 200
        body = json.loads(resp.body)
        assert body["status"] == "ok"
