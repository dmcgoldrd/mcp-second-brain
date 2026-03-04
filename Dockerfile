# Stage 1: Build frontend
FROM node:22-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/package.json frontend/bun.lock* ./
RUN npm install
COPY frontend/ .
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
RUN npm run build

# Stage 2: Python server
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

# Copy frontend build output
COPY --from=frontend-builder /frontend/dist /app/frontend/dist

# Expose MCP server port
EXPOSE 8080

# Run the MCP server
CMD ["uv", "run", "python", "-m", "src.main"]
