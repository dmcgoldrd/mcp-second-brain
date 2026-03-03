FROM python:3.12-slim

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for caching
COPY pyproject.toml uv.lock* ./

# Install dependencies using UV
RUN uv sync --frozen --no-dev

# Copy source code
COPY src/ src/

# Expose MCP server port
EXPOSE 8080

# Run the MCP server
CMD ["uv", "run", "python", "-m", "src.main"]
