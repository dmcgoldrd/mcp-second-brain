"""HTTP endpoint for triggering memory consolidation.

Called by Railway cron (or any external scheduler) to run the nightly
consolidation pipeline.  Authenticates via X-Service-Key header using
the SUPABASE_SERVICE_ROLE_KEY (constant-time comparison).
"""

from __future__ import annotations

import hmac
import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.config import SUPABASE_SERVICE_ROLE_KEY

logger = logging.getLogger("mcp-brain")


async def consolidation_handler(request: Request) -> JSONResponse:
    """Handle POST /api/consolidate — trigger memory consolidation.

    Auth: X-Service-Key header must match SUPABASE_SERVICE_ROLE_KEY.

    Body (optional JSON):
        {"user_id": "uuid", "bank_id": "uuid"}  — consolidate a specific user/bank
        Empty or missing body — consolidate all active users.

    Returns:
        200 with summary on success, 401 on bad auth, 500 on error.
    """
    # --- Auth ---
    service_key = request.headers.get("X-Service-Key", "")

    if not SUPABASE_SERVICE_ROLE_KEY:
        logger.error("SUPABASE_SERVICE_ROLE_KEY not configured")
        return JSONResponse({"error": "Consolidation not configured"}, status_code=500)

    if not hmac.compare_digest(service_key, SUPABASE_SERVICE_ROLE_KEY):
        logger.warning("Consolidation endpoint: invalid service key")
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # --- Parse optional body ---
    user_id: str | None = None
    bank_id: str | None = None

    body = await request.body()
    if body:
        try:
            payload = json.loads(body)
            user_id = payload.get("user_id")
            bank_id = payload.get("bank_id")
        except (json.JSONDecodeError, AttributeError):
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    # --- Run consolidation ---
    try:
        # src.consolidation is built by WS-1; import deferred so the
        # server can still start before that module lands.
        from src.consolidation import consolidate_all_active_users, consolidate_user

        if user_id:
            logger.info("Consolidation triggered for user=%s bank=%s", user_id, bank_id)
            result = await consolidate_user(user_id, bank_id)
        else:
            logger.info("Consolidation triggered for all active users")
            result = await consolidate_all_active_users()

        return JSONResponse({"status": "ok", "summary": result})

    except Exception:
        logger.exception("Consolidation failed")
        return JSONResponse({"error": "Consolidation failed"}, status_code=500)
