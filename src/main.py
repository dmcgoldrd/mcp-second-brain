"""Entry point for the MCP Brain server."""

from src.config import HOST, PORT
from src.server import mcp


def main() -> None:
    """Start the MCP Brain server using Streamable HTTP transport."""
    mcp.run(transport="streamable-http", host=HOST, port=PORT)


if __name__ == "__main__":
    main()
