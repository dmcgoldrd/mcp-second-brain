# MCP Brain

**Your Personal AI Memory — works with Claude, ChatGPT, Gemini, Cursor, and any MCP client.**

MCP Brain is a persistent memory layer that lets your AI remember you across every platform. Store observations, decisions, ideas, tasks, and preferences — then retrieve them from any AI tool via the MCP protocol.

## How It Works

```
[Your AI Client] ←MCP Protocol→ [MCP Brain Server] ←→ [Supabase Postgres + pgvector]
```

1. You tell your AI something worth remembering
2. The AI calls `create_memory` via MCP
3. Your memory is embedded (OpenAI text-embedding-3-small) and stored
4. Later, from ANY AI client, search your memories semantically
5. Your AI has context about you that persists forever

## Stack

| Component | Technology |
|-----------|-----------|
| MCP Server | Python + [FastMCP](https://github.com/jlowin/fastmcp) |
| Database | [Supabase](https://supabase.com) Postgres + pgvector |
| Auth | Supabase Auth (OAuth 2.1 — works with all MCP clients) |
| Embeddings | OpenAI text-embedding-3-small (1536 dimensions) |
| Search | Hybrid: pgvector similarity + Postgres full-text + RRF ranking |
| Billing | Stripe ($7.99/month) |
| Package Manager | [UV](https://github.com/astral-sh/uv) (no pip) |

## MCP Tools

| Tool | Description |
|------|-------------|
| `create_memory` | Store a new memory with auto-embedding and classification |
| `search_memories` | Hybrid semantic + full-text search across your brain |
| `list_memories` | Browse recent memories, filter by type |
| `delete_memory` | Remove a specific memory |
| `brain_stats` | View your memory statistics |

## Quick Start

### Prerequisites

- Python 3.12+
- [UV](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Supabase project (free tier works)
- OpenAI API key

### Setup

```bash
# Clone and enter the project
cd ~/Projects/mcp-brain

# Install dependencies with UV
uv sync

# Copy environment template
cp .env.example .env
# Edit .env with your Supabase and OpenAI credentials

# Run database migrations
# (paste migrations/001_initial_schema.sql into Supabase SQL Editor)

# Start the server
uv run python -m src.main
```

### Connect from Claude Desktop

Add to your Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "brain": {
      "url": "http://localhost:8080/mcp",
      "transport": "streamable-http"
    }
  }
}
```

### Connect from Claude Code

```bash
claude mcp add brain --transport http http://localhost:8080/mcp
```

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Lint
uv run ruff check src/

# Format
uv run ruff format src/
```

## Architecture

See [docs/RESEARCH.md](docs/RESEARCH.md) for comprehensive market research, competitive analysis, and technical feasibility assessment.

## License

MIT
