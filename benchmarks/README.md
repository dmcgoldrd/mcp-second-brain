# MCP Brain Benchmarks

Isolated benchmark suite for evaluating MCP Brain's memory retrieval quality against the [LoCoMo](https://snap-research.github.io/locomo/) dataset, using the same methodology as [MemoryBench](https://github.com/supermemoryai/memorybench).

## Prerequisites

- **MCP Brain server** running locally at `http://localhost:8080`
- **Test user JWT** — a Supabase access token (set `MCPBRAIN_TOKEN` env var)
- **OpenAI API key** — for the LLM judge and answer generation (set `OPENAI_API_KEY`)
- **uv** — Python package manager

## Quick Start

```bash
cd benchmarks
uv sync

# Run full benchmark (all 10 conversations, ~2000 questions)
MCPBRAIN_TOKEN=... OPENAI_API_KEY=... uv run python run.py

# Quick test run (first conversation, 50 questions)
MCPBRAIN_TOKEN=... OPENAI_API_KEY=... uv run python run.py --conversations 1 --limit 50
```

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dataset` | `locomo` | Benchmark dataset |
| `--provider` | `mcpbrain` | Memory provider backend |
| `--judge` | `gpt-4o-mini` | LLM model for judging correctness |
| `--answerer` | `gpt-4o-mini` | LLM model for generating answers |
| `--limit` | `0` (all) | Max questions to evaluate |
| `--conversations` | `0` (all) | Max conversations to process |
| `--search-limit` | `10` | Top-k memories per search |
| `--seed` | `42` | Random seed |
| `--output-dir` | `./results` | Output directory for report |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MCPBRAIN_TOKEN` | Yes | Supabase JWT for MCP Brain auth |
| `OPENAI_API_KEY` | Yes | OpenAI API key for judge + answerer |
| `MCPBRAIN_URL` | No | Server URL (default: `http://localhost:8080`) |
| `MCPBRAIN_BANK` | No | Bank slug to use (default: server's default bank) |

## How It Works

### Pipeline

```
Download LoCoMo → Reset memories → Ingest turns → Search → Answer → Judge → Report
```

1. **Download**: Fetches `locomo10.json` (10 conversations, ~300 turns each) from snap-research/locomo
2. **Reset**: Clears all memories for the benchmark user
3. **Ingest**: Each conversation turn becomes a memory via MCP `create_memory`
4. **Search**: For each question, retrieve top-k memories via MCP `search_memories`
5. **Answer**: An LLM generates an answer from the retrieved memory context
6. **Judge**: An LLM judge scores correctness (CORRECT/INCORRECT) against gold labels
7. **Report**: Generates markdown report with metrics and comparison to published baselines

### Metrics

| Metric | Description |
|--------|-------------|
| **LLM-as-Judge accuracy** | Primary metric. Percentage of questions judged correct. Comparable to Mem0's reported numbers. |
| **F1 token overlap** | Cheap deterministic metric. Token-level precision/recall against gold answer. |
| **Search latency (p50/p95)** | Time for MCP Brain to return search results. |
| **Answer latency (p50/p95)** | End-to-end time including search + LLM answer generation. |

### Question Categories (LoCoMo)

| Category | Code | Description |
|----------|------|-------------|
| Single-hop | 1 | Basic fact recall from one turn |
| Multi-hop | 2 | Requires reasoning across multiple turns |
| Temporal | 3 | Time-based reasoning (when, before/after) |
| Open-domain | 4 | Requires world knowledge + memory |
| Adversarial | 5 | Unanswerable from context (tests false recall) |

## Output

Results are written to `--output-dir` (default `./results/`):

```
results/
├── report.md        # Human-readable markdown report
├── results.json     # Machine-readable metrics
└── raw_results.json # Per-question details (for debugging)
```

## Adding Providers

To benchmark a different memory system, create a new provider in `providers/`:

```python
class MyProvider:
    async def add_memory(self, content: str, user_id: str, session_id: str) -> str: ...
    async def search(self, query: str, user_id: str, limit: int = 10) -> list[dict]: ...
    async def reset(self, user_id: str) -> None: ...
    async def close(self) -> None: ...
```

## Published Baselines (LoCoMo)

From Mem0's MemoryBench report:

| Provider | LLM-as-Judge | Search p95 |
|----------|--------------|------------|
| Mem0 | 66.9% | 1.44s |
| OpenAI Memory | 52.9% | - |
| Zep | 41.1% | - |
