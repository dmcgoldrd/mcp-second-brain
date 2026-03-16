"""Metrics computation for benchmark results.

Aggregates per-question results into summary statistics, including:
- LLM-as-Judge accuracy (the primary metric, comparable to Mem0/MemoryBench reports)
- Token-overlap F1
- Retrieval latency percentiles (p50, p95)
- Breakdown by LoCoMo question category
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

# LoCoMo question category mapping (from the dataset's numeric codes)
CATEGORY_NAMES: dict[int, str] = {
    1: "single-hop",
    2: "multi-hop",
    3: "temporal",
    4: "open-domain",
    5: "adversarial",
}


@dataclass
class QuestionResult:
    """Result for a single benchmark question."""

    question_id: str
    question: str
    gold_answer: str
    predicted_answer: str
    category: int  # 1-5 per LoCoMo
    llm_judge_score: int  # 1 or 0
    f1_score: float
    search_latency_ms: float
    answer_latency_ms: float
    memories_retrieved: int
    tokens_used: int = 0
    conversation_id: str = ""


@dataclass
class CategoryMetrics:
    """Aggregated metrics for a single question category."""

    name: str
    count: int = 0
    correct: int = 0
    accuracy: float = 0.0
    mean_f1: float = 0.0
    mean_latency_ms: float = 0.0


@dataclass
class BenchmarkMetrics:
    """Full benchmark metrics summary."""

    # Overall
    total_questions: int = 0
    total_correct: int = 0
    llm_judge_accuracy: float = 0.0
    mean_f1: float = 0.0

    # Latency
    search_latency_p50_ms: float = 0.0
    search_latency_p95_ms: float = 0.0
    search_latency_mean_ms: float = 0.0
    answer_latency_p50_ms: float = 0.0
    answer_latency_p95_ms: float = 0.0

    # Tokens
    total_tokens: int = 0
    mean_tokens_per_query: float = 0.0

    # Retrieval
    mean_memories_retrieved: float = 0.0

    # Category breakdown
    by_category: dict[str, CategoryMetrics] = field(default_factory=dict)

    # Conversations
    total_conversations: int = 0


def compute_metrics(results: Sequence[QuestionResult]) -> BenchmarkMetrics:
    """Compute aggregate metrics from a list of per-question results.

    Args:
        results: Sequence of QuestionResult objects from the benchmark run.

    Returns:
        BenchmarkMetrics with all aggregate statistics computed.
    """
    if not results:
        return BenchmarkMetrics()

    metrics = BenchmarkMetrics()
    metrics.total_questions = len(results)
    metrics.total_correct = sum(r.llm_judge_score for r in results)
    metrics.llm_judge_accuracy = metrics.total_correct / metrics.total_questions

    # F1
    f1_scores = [r.f1_score for r in results]
    metrics.mean_f1 = statistics.mean(f1_scores)

    # Latency
    search_latencies = [r.search_latency_ms for r in results]
    answer_latencies = [r.answer_latency_ms for r in results]

    metrics.search_latency_mean_ms = statistics.mean(search_latencies)
    metrics.search_latency_p50_ms = _percentile(search_latencies, 50)
    metrics.search_latency_p95_ms = _percentile(search_latencies, 95)
    metrics.answer_latency_p50_ms = _percentile(answer_latencies, 50)
    metrics.answer_latency_p95_ms = _percentile(answer_latencies, 95)

    # Tokens
    metrics.total_tokens = sum(r.tokens_used for r in results)
    metrics.mean_tokens_per_query = metrics.total_tokens / metrics.total_questions

    # Retrieval
    metrics.mean_memories_retrieved = statistics.mean([r.memories_retrieved for r in results])

    # Conversations
    metrics.total_conversations = len({r.conversation_id for r in results})

    # Category breakdown
    category_groups: dict[int, list[QuestionResult]] = {}
    for r in results:
        category_groups.setdefault(r.category, []).append(r)

    for cat_id, cat_results in sorted(category_groups.items()):
        cat_name = CATEGORY_NAMES.get(cat_id, f"unknown-{cat_id}")
        correct = sum(r.llm_judge_score for r in cat_results)
        count = len(cat_results)
        metrics.by_category[cat_name] = CategoryMetrics(
            name=cat_name,
            count=count,
            correct=correct,
            accuracy=correct / count if count else 0.0,
            mean_f1=statistics.mean([r.f1_score for r in cat_results]),
            mean_latency_ms=statistics.mean([r.search_latency_ms for r in cat_results]),
        )

    return metrics


def _percentile(data: list[float], pct: int) -> float:
    """Compute a percentile from a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])
