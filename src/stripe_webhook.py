"""Stripe webhook handler for subscription management."""

from __future__ import annotations

import logging

import stripe
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from src.db.connection import get_pool

logger = logging.getLogger("mcp-brain")

stripe.api_key = STRIPE_SECRET_KEY


async def stripe_webhook_handler(request: Request) -> JSONResponse:
    """Handle Stripe webhook events for subscription lifecycle."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    if not STRIPE_WEBHOOK_SECRET:
        logger.error("STRIPE_WEBHOOK_SECRET not configured")
        return JSONResponse({"error": "Webhook not configured"}, status_code=500)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        logger.warning("Invalid Stripe webhook payload")
        return JSONResponse({"error": "Invalid payload"}, status_code=400)
    except stripe.SignatureVerificationError:
        logger.warning("Invalid Stripe webhook signature")
        return JSONResponse({"error": "Invalid signature"}, status_code=400)

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        await _handle_checkout_completed(data)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data)
    else:
        logger.info("Unhandled Stripe event: %s", event_type)

    return JSONResponse({"status": "ok"})


async def _handle_checkout_completed(session: dict) -> None:
    """Handle successful checkout — create subscription and activate user."""
    user_id = session.get("client_reference_id")
    customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    if not user_id or not subscription_id:
        logger.warning("Checkout session missing user_id or subscription_id")
        return

    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        # Update profile with Stripe customer ID and active status
        await conn.execute(
            """
            UPDATE profiles
            SET stripe_customer_id = $1, subscription_status = 'active', updated_at = now()
            WHERE id = $2::uuid
            """,
            customer_id,
            user_id,
        )
        # Upsert subscription record
        await conn.execute(
            """
            INSERT INTO subscriptions (user_id, stripe_subscription_id, stripe_customer_id, status)
            VALUES ($1::uuid, $2, $3, 'active')
            ON CONFLICT (stripe_subscription_id)
            DO UPDATE SET status = 'active', updated_at = now()
            """,
            user_id,
            subscription_id,
            customer_id,
        )

    logger.info("Checkout completed for user %s", user_id)


async def _handle_subscription_updated(subscription: dict) -> None:
    """Handle subscription status changes (active, past_due, etc.)."""
    sub_id = subscription.get("id")
    status = subscription.get("status", "")
    customer_id = subscription.get("customer")

    pool = await get_pool()
    await pool.execute(
        """
        UPDATE subscriptions SET status = $1, updated_at = now()
        WHERE stripe_subscription_id = $2
        """,
        status,
        sub_id,
    )
    # Also update profile status
    if customer_id:
        profile_status = "active" if status == "active" else status
        await pool.execute(
            """
            UPDATE profiles SET subscription_status = $1, updated_at = now()
            WHERE stripe_customer_id = $2
            """,
            profile_status,
            customer_id,
        )

    logger.info("Subscription %s updated to %s", sub_id, status)


async def _handle_subscription_deleted(subscription: dict) -> None:
    """Handle subscription cancellation."""
    sub_id = subscription.get("id")
    customer_id = subscription.get("customer")

    pool = await get_pool()
    await pool.execute(
        """
        UPDATE subscriptions SET status = 'canceled', updated_at = now()
        WHERE stripe_subscription_id = $1
        """,
        sub_id,
    )
    if customer_id:
        await pool.execute(
            """
            UPDATE profiles SET subscription_status = 'canceled', updated_at = now()
            WHERE stripe_customer_id = $1
            """,
            customer_id,
        )

    logger.info("Subscription %s canceled", sub_id)


async def _handle_payment_failed(invoice: dict) -> None:
    """Handle failed payment — mark as past_due."""
    customer_id = invoice.get("customer")
    if not customer_id:
        return

    pool = await get_pool()
    await pool.execute(
        """
        UPDATE profiles SET subscription_status = 'past_due', updated_at = now()
        WHERE stripe_customer_id = $1
        """,
        customer_id,
    )

    logger.info("Payment failed for customer %s", customer_id)
