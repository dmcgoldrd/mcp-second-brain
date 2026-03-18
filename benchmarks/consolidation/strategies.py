"""Conflict resolution strategies for benchmarking.

Implements 4 classifiers with identical interfaces:
    - gpt-4o-mini  (current production strategy)
    - haiku-4.5    (Anthropic alternative)
    - heuristic    (zero-LLM-cost, embedding-based rules)
    - oracle       (ground-truth baseline)

Each returns a ClassificationResult with the label, timing, and token usage.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

logger = logging.getLogger("benchmarks.consolidation")

# ---------------------------------------------------------------------------
# Shared prompt — identical to src/consolidation.py:_classify_conflict
# ---------------------------------------------------------------------------

_CLASSIFICATION_PROMPT_TEMPLATE = (
    "You are a memory deduplication classifier. Two memories from the same user "
    "are semantically similar. Decide if the newer one UPDATES/replaces the older "
    "one, or if they should BOTH be kept as distinct memories.\n\n"
    "Memory A (created {created_a}):\n{content_a}\n\n"
    "Memory B (created {created_b}):\n{content_b}\n\n"
    "Respond with exactly one word: UPDATE or KEEP_BOTH\n"
    "- UPDATE means the newer memory supersedes the older (e.g., a fact changed)\n"
    "- KEEP_BOTH means they are related but distinct memories worth preserving"
)

# ---------------------------------------------------------------------------
# Pricing constants (per 1M tokens, as of March 2026)
# ---------------------------------------------------------------------------

# gpt-4o-mini
_GPT4O_MINI_INPUT_COST = 0.15  # $/1M tokens
_GPT4O_MINI_OUTPUT_COST = 0.60  # $/1M tokens

# Claude Haiku 4.5
_HAIKU_INPUT_COST = 0.80  # $/1M tokens
_HAIKU_OUTPUT_COST = 4.00  # $/1M tokens

# OpenAI text-embedding-3-small
_EMBEDDING_COST = 0.02  # $/1M tokens


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class ClassificationResult:
    """Result from a single conflict classification call."""

    label: str  # "UPDATE" or "KEEP_BOTH"
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    strategy: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# Embedding cache (shared across heuristic calls within a run)
# ---------------------------------------------------------------------------

_embedding_cache: dict[str, list[float]] = {}
_embedding_tokens_used: int = 0


def reset_embedding_cache() -> None:
    """Clear the embedding cache between runs."""
    global _embedding_tokens_used
    _embedding_cache.clear()
    _embedding_tokens_used = 0


def get_embedding_tokens_used() -> int:
    """Return total tokens used for embeddings in this run."""
    return _embedding_tokens_used


async def _get_embedding(text: str, client: AsyncOpenAI) -> list[float]:
    """Get embedding for text, using cache to avoid redundant API calls."""
    global _embedding_tokens_used

    if text in _embedding_cache:
        return _embedding_cache[text]

    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    embedding = response.data[0].embedding
    tokens = response.usage.total_tokens if response.usage else 0
    _embedding_tokens_used += tokens
    _embedding_cache[text] = embedding
    return embedding


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    va = np.array(a)
    vb = np.array(b)
    dot = np.dot(va, vb)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _days_between(iso_a: str, iso_b: str) -> float:
    """Compute absolute days between two ISO timestamps."""
    dt_a = datetime.fromisoformat(iso_a.replace("Z", "+00:00"))
    dt_b = datetime.fromisoformat(iso_b.replace("Z", "+00:00"))
    return abs((dt_b - dt_a).total_seconds()) / 86400.0


def _build_prompt(pair: dict) -> str:
    """Build the classification prompt from a test pair."""
    return _CLASSIFICATION_PROMPT_TEMPLATE.format(
        created_a=pair["created_a"],
        content_a=pair["content_a"],
        created_b=pair["created_b"],
        content_b=pair["content_b"],
    )


# ---------------------------------------------------------------------------
# Strategy 1: gpt-4o-mini (current production)
# ---------------------------------------------------------------------------


async def classify_gpt4o_mini(
    pair: dict,
    client: AsyncOpenAI | None = None,
) -> ClassificationResult:
    """Classify using gpt-4o-mini — the current production strategy."""
    if client is None:
        client = AsyncOpenAI()

    prompt = _build_prompt(pair)
    start = time.perf_counter()

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
            temperature=0,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        raw = response.choices[0].message.content or ""
        answer = raw.strip().upper()
        if answer not in ("UPDATE", "KEEP_BOTH"):
            answer = "KEEP_BOTH"

        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        cost = (
            input_tokens * _GPT4O_MINI_INPUT_COST / 1_000_000
            + output_tokens * _GPT4O_MINI_OUTPUT_COST / 1_000_000
        )

        return ClassificationResult(
            label=answer,
            latency_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            strategy="gpt4o-mini",
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.warning("gpt-4o-mini classification failed: %s", exc)
        return ClassificationResult(
            label="KEEP_BOTH",
            latency_ms=elapsed_ms,
            strategy="gpt4o-mini",
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Strategy 2: Claude Haiku 4.5
# ---------------------------------------------------------------------------


async def classify_haiku(
    pair: dict,
    client: AsyncAnthropic | None = None,
) -> ClassificationResult:
    """Classify using Claude Haiku 4.5 via Anthropic API."""
    if client is None:
        client = AsyncAnthropic()

    prompt = _build_prompt(pair)
    start = time.perf_counter()

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        raw = response.content[0].text if response.content else ""
        answer = raw.strip().upper()
        if answer not in ("UPDATE", "KEEP_BOTH"):
            answer = "KEEP_BOTH"

        input_tokens = response.usage.input_tokens if response.usage else 0
        output_tokens = response.usage.output_tokens if response.usage else 0
        cost = (
            input_tokens * _HAIKU_INPUT_COST / 1_000_000
            + output_tokens * _HAIKU_OUTPUT_COST / 1_000_000
        )

        return ClassificationResult(
            label=answer,
            latency_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            strategy="haiku",
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.warning("Haiku classification failed: %s", exc)
        return ClassificationResult(
            label="KEEP_BOTH",
            latency_ms=elapsed_ms,
            strategy="haiku",
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Strategy 3: Heuristic (zero LLM cost, uses embeddings)
# ---------------------------------------------------------------------------


async def classify_heuristic(
    pair: dict,
    client: AsyncOpenAI | None = None,
) -> ClassificationResult:
    """Classify using deterministic heuristic rules + embedding similarity.

    Rules:
        1. Same memory_type + similarity > 0.92 + >30 days apart = UPDATE
        2. Same memory_type + similarity > 0.95 (near-duplicate) = UPDATE
        3. Default = KEEP_BOTH (conservative)

    Embedding cost is amortized — each unique text is embedded once per run.
    """
    if client is None:
        client = AsyncOpenAI()

    start = time.perf_counter()

    try:
        emb_a = await _get_embedding(pair["content_a"], client)
        emb_b = await _get_embedding(pair["content_b"], client)
        similarity = _cosine_similarity(emb_a, emb_b)
        days_apart = _days_between(pair["created_a"], pair["created_b"])

        elapsed_ms = (time.perf_counter() - start) * 1000

        # Rule 1: High similarity + significant time gap = likely fact update
        if (similarity > 0.92 and days_apart > 30) or similarity > 0.95:
            label = "UPDATE"
        # Rule 3: Default conservative
        else:
            label = "KEEP_BOTH"

        # Embedding cost is tracked globally, not per-call, since cached
        return ClassificationResult(
            label=label,
            latency_ms=elapsed_ms,
            strategy="heuristic",
            cost=0.0,  # Cost tracked separately via get_embedding_tokens_used()
        )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.warning("Heuristic classification failed: %s", exc)
        return ClassificationResult(
            label="KEEP_BOTH",
            latency_ms=elapsed_ms,
            strategy="heuristic",
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Strategy 4: Oracle (ground truth baseline)
# ---------------------------------------------------------------------------


async def classify_oracle(
    pair: dict,
    **_kwargs,
) -> ClassificationResult:
    """Perfect classifier that returns the ground-truth label."""
    start = time.perf_counter()
    label = pair["expected"]
    elapsed_ms = (time.perf_counter() - start) * 1000

    return ClassificationResult(
        label=label,
        latency_ms=elapsed_ms,
        strategy="oracle",
        cost=0.0,
    )


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

STRATEGIES: dict[str, tuple] = {
    "gpt4o-mini": (classify_gpt4o_mini, "gpt-4o-mini (current production)"),
    "haiku": (classify_haiku, "Claude Haiku 4.5 (Anthropic)"),
    "heuristic": (classify_heuristic, "Heuristic (embedding rules, no LLM)"),
    "oracle": (classify_oracle, "Oracle (ground truth)"),
}
