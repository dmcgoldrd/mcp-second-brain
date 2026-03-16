"""Entry point for the MCP Brain server."""

import os

import uvicorn
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from src.config import HOST, PORT
from src.server import mcp
from src.stripe_webhook import stripe_webhook_handler

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")


def create_app():
    """Create the combined ASGI app: MCP server + Stripe webhook + static frontend."""
    app = mcp.http_app(transport="streamable-http")

    # Stripe webhook endpoint (must come before static file mount)
    app.routes.insert(0, Route("/api/stripe/webhook", stripe_webhook_handler, methods=["POST"]))

    # Mount frontend static files if the dist directory exists
    if os.path.isdir(FRONTEND_DIR):
        app.routes.append(Mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static"))

    return app


def main() -> None:
    """Start the MCP Brain server with frontend."""
    app = create_app()
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
