"""Consolidation conflict resolution benchmark runner.

Evaluates classification quality across multiple strategies using a
deterministic test dataset of 70 memory conflict pairs.

Usage:
    cd benchmarks
    OPENAI_API_KEY=... ANTHROPIC_API_KEY=... uv run python consolidation/run.py

Options:
    --strategies gpt4o-mini,haiku,heuristic  (default: all three + oracle)
    --output-dir consolidation/results/      (default: consolidation/results/)
    --concurrency N                          max concurrent API calls (default: 5)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Ensure benchmarks/ is on sys.path when run as `python consolidation/run.py`
_benchmarks_dir = str(Path(__file__).resolve().parent.parent)
if _benchmarks_dir not in sys.path:
    sys.path.insert(0, _benchmarks_dir)

from anthropic import AsyncAnthropic  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from consolidation.report import generate_report  # noqa: E402
from consolidation.strategies import (  # noqa: E402
    _EMBEDDING_COST,
    STRATEGIES,
    ClassificationResult,
    get_embedding_tokens_used,
    reset_embedding_cache,
)
from consolidation.test_data import CONFLICT_PAIRS  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmarks.consolidation")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class PairResult:
    """Result for a single test pair."""

    pair_id: str
    category: str
    difficulty: str
    expected: str
    predicted: str
    correct: bool
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost: float
    error: str | None = None


@dataclass
class StrategyMetrics:
    """Aggregated metrics for one strategy across all test pairs."""

    strategy: str
    description: str

    # Classification quality
    accuracy: float = 0.0
    precision: float = 0.0  # For UPDATE class
    recall: float = 0.0  # For UPDATE class
    f1: float = 0.0  # For UPDATE class

    # Confusion matrix counts
    true_positive: int = 0  # Predicted UPDATE, expected UPDATE
    false_positive: int = 0  # Predicted UPDATE, expected KEEP_BOTH
    true_negative: int = 0  # Predicted KEEP_BOTH, expected KEEP_BOTH
    false_negative: int = 0  # Predicted KEEP_BOTH, expected UPDATE

    # Latency
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    total_latency_ms: float = 0.0

    # Cost
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    cost_per_call: float = 0.0

    # Per-category accuracy
    by_category: dict[str, float] = field(default_factory=dict)

    # Error count
    errors: int = 0

    # Individual results
    pair_results: list[PairResult] = field(default_factory=list)


def _percentile(data: list[float], pct: int) -> float:
    """Compute percentile from a list of values."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (pct / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def compute_strategy_metrics(
    strategy_name: str,
    description: str,
    results: list[tuple[dict, ClassificationResult]],
) -> StrategyMetrics:
    """Compute all metrics for a strategy from its raw classification results."""
    metrics = StrategyMetrics(strategy=strategy_name, description=description)

    if not results:
        return metrics

    pair_results: list[PairResult] = []
    latencies: list[float] = []
    category_correct: dict[str, int] = defaultdict(int)
    category_total: dict[str, int] = defaultdict(int)

    for pair, result in results:
        expected = pair["expected"]
        predicted = result.label
        correct = predicted == expected

        pr = PairResult(
            pair_id=pair["id"],
            category=pair["category"],
            difficulty=pair["difficulty"],
            expected=expected,
            predicted=predicted,
            correct=correct,
            latency_ms=result.latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cost=result.cost,
            error=result.error,
        )
        pair_results.append(pr)
        latencies.append(result.latency_ms)

        # Confusion matrix (UPDATE is the positive class)
        if predicted == "UPDATE" and expected == "UPDATE":
            metrics.true_positive += 1
        elif predicted == "UPDATE" and expected == "KEEP_BOTH":
            metrics.false_positive += 1
        elif predicted == "KEEP_BOTH" and expected == "KEEP_BOTH":
            metrics.true_negative += 1
        elif predicted == "KEEP_BOTH" and expected == "UPDATE":
            metrics.false_negative += 1

        # Per-category
        category_total[pair["category"]] += 1
        if correct:
            category_correct[pair["category"]] += 1

        # Totals
        metrics.total_input_tokens += result.input_tokens
        metrics.total_output_tokens += result.output_tokens
        metrics.total_cost += result.cost

        if result.error:
            metrics.errors += 1

    # Accuracy
    total = len(results)
    metrics.accuracy = sum(1 for pr in pair_results if pr.correct) / total

    # Precision/Recall/F1 for UPDATE class
    if metrics.true_positive + metrics.false_positive > 0:
        metrics.precision = metrics.true_positive / (metrics.true_positive + metrics.false_positive)
    if metrics.true_positive + metrics.false_negative > 0:
        metrics.recall = metrics.true_positive / (metrics.true_positive + metrics.false_negative)
    if metrics.precision + metrics.recall > 0:
        metrics.f1 = 2 * metrics.precision * metrics.recall / (metrics.precision + metrics.recall)

    # Latency
    metrics.avg_latency_ms = statistics.mean(latencies)
    metrics.p50_latency_ms = _percentile(latencies, 50)
    metrics.p95_latency_ms = _percentile(latencies, 95)
    metrics.total_latency_ms = sum(latencies)

    # Cost per call
    metrics.cost_per_call = metrics.total_cost / total if total > 0 else 0.0

    # Per-category accuracy
    for cat, count in sorted(category_total.items()):
        metrics.by_category[cat] = category_correct.get(cat, 0) / count if count > 0 else 0.0

    metrics.pair_results = pair_results
    return metrics


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_strategy(
    strategy_name: str,
    pairs: list[dict],
    concurrency: int = 5,
    openai_client: AsyncOpenAI | None = None,
    anthropic_client: AsyncAnthropic | None = None,
) -> list[tuple[dict, ClassificationResult]]:
    """Run a single strategy against all test pairs."""
    classify_fn, _description = STRATEGIES[strategy_name]
    sem = asyncio.Semaphore(concurrency)
    results: list[tuple[dict, ClassificationResult]] = []

    async def classify_one(pair: dict) -> tuple[dict, ClassificationResult]:
        async with sem:
            if strategy_name == "gpt4o-mini":
                result = await classify_fn(pair, client=openai_client)
            elif strategy_name == "haiku":
                result = await classify_fn(pair, client=anthropic_client)
            elif strategy_name == "heuristic":
                result = await classify_fn(pair, client=openai_client)
            else:
                result = await classify_fn(pair)
            return pair, result

    tasks = [classify_one(p) for p in pairs]
    completed = await asyncio.gather(*tasks, return_exceptions=True)

    for item in completed:
        if isinstance(item, Exception):
            logger.error("Strategy %s failed on a pair: %s", strategy_name, item)
            # Create a dummy result for the failed pair
            results.append(
                (
                    pairs[len(results)],
                    ClassificationResult(
                        label="KEEP_BOTH",
                        strategy=strategy_name,
                        error=str(item),
                    ),
                )
            )
        else:
            results.append(item)

    return results


async def run_benchmark(args: argparse.Namespace) -> None:
    """Run the full consolidation benchmark."""
    strategy_names = [s.strip() for s in args.strategies.split(",")]

    # Validate strategy names
    for name in strategy_names:
        if name not in STRATEGIES:
            logger.error("Unknown strategy: %s (available: %s)", name, list(STRATEGIES.keys()))
            sys.exit(1)

    logger.info("=" * 60)
    logger.info("CONSOLIDATION CONFLICT RESOLUTION BENCHMARK")
    logger.info("=" * 60)
    logger.info("Test pairs: %d", len(CONFLICT_PAIRS))
    logger.info("Strategies: %s", ", ".join(strategy_names))
    logger.info("Concurrency: %d", args.concurrency)
    logger.info("")

    # Initialize API clients
    openai_client = (
        AsyncOpenAI() if any(s in strategy_names for s in ("gpt4o-mini", "heuristic")) else None
    )
    anthropic_client = AsyncAnthropic() if "haiku" in strategy_names else None

    all_metrics: list[StrategyMetrics] = []
    run_start = time.perf_counter()

    for strategy_name in strategy_names:
        _, description = STRATEGIES[strategy_name]
        logger.info("--- Running: %s (%s) ---", strategy_name, description)

        # Reset embedding cache for heuristic strategy
        if strategy_name == "heuristic":
            reset_embedding_cache()

        strategy_start = time.perf_counter()
        results = await run_strategy(
            strategy_name=strategy_name,
            pairs=CONFLICT_PAIRS,
            concurrency=args.concurrency,
            openai_client=openai_client,
            anthropic_client=anthropic_client,
        )
        strategy_elapsed = (time.perf_counter() - strategy_start) * 1000

        # For heuristic, add embedding cost to total
        metrics = compute_strategy_metrics(strategy_name, description, results)
        if strategy_name == "heuristic":
            embedding_tokens = get_embedding_tokens_used()
            embedding_cost = embedding_tokens * _EMBEDDING_COST / 1_000_000
            metrics.total_cost += embedding_cost
            metrics.total_input_tokens += embedding_tokens
            metrics.cost_per_call = metrics.total_cost / len(CONFLICT_PAIRS)
            logger.info(
                "  Embedding tokens used: %d (cost: $%.6f)",
                embedding_tokens,
                embedding_cost,
            )

        all_metrics.append(metrics)

        logger.info("  Accuracy: %.1f%%", metrics.accuracy * 100)
        logger.info(
            "  Precision: %.1f%% | Recall: %.1f%% | F1: %.3f",
            metrics.precision * 100,
            metrics.recall * 100,
            metrics.f1,
        )
        logger.info(
            "  Avg latency: %.0fms | Total: %.0fms",
            metrics.avg_latency_ms,
            strategy_elapsed,
        )
        logger.info("  Total cost: $%.6f", metrics.total_cost)
        if metrics.errors > 0:
            logger.warning("  Errors: %d", metrics.errors)
        logger.info("")

    total_elapsed = (time.perf_counter() - run_start) * 1000

    # Close clients
    if openai_client:
        await openai_client.close()
    if anthropic_client:
        await anthropic_client.close()

    # Generate report
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    generate_report(all_metrics, output_dir)

    # Save raw results JSON
    raw_results = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_pairs": len(CONFLICT_PAIRS),
        "total_elapsed_ms": total_elapsed,
        "strategies": {},
    }
    for m in all_metrics:
        raw_results["strategies"][m.strategy] = {
            "accuracy": m.accuracy,
            "precision": m.precision,
            "recall": m.recall,
            "f1": m.f1,
            "confusion_matrix": {
                "true_positive": m.true_positive,
                "false_positive": m.false_positive,
                "true_negative": m.true_negative,
                "false_negative": m.false_negative,
            },
            "avg_latency_ms": m.avg_latency_ms,
            "p50_latency_ms": m.p50_latency_ms,
            "p95_latency_ms": m.p95_latency_ms,
            "total_cost": m.total_cost,
            "cost_per_call": m.cost_per_call,
            "total_input_tokens": m.total_input_tokens,
            "total_output_tokens": m.total_output_tokens,
            "errors": m.errors,
            "by_category": m.by_category,
            "pair_results": [
                {
                    "pair_id": pr.pair_id,
                    "category": pr.category,
                    "expected": pr.expected,
                    "predicted": pr.predicted,
                    "correct": pr.correct,
                    "latency_ms": pr.latency_ms,
                    "cost": pr.cost,
                }
                for pr in m.pair_results
            ],
        }

    raw_path = output_dir / "raw_results.json"
    raw_path.write_text(json.dumps(raw_results, indent=2))

    # Print summary
    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETE")
    print("=" * 60)
    print(f"Test pairs:     {len(CONFLICT_PAIRS)}")
    print(f"Strategies:     {len(all_metrics)}")
    print(f"Total time:     {total_elapsed / 1000:.1f}s")
    print()
    print(f"{'Strategy':<16} {'Accuracy':>10} {'F1':>8} {'Avg ms':>10} {'Cost':>12}")
    print("-" * 60)
    for m in all_metrics:
        print(
            f"{m.strategy:<16} {m.accuracy * 100:>9.1f}% {m.f1:>8.3f} "
            f"{m.avg_latency_ms:>9.0f} ${m.total_cost:>10.6f}"
        )
    print()
    print(f"Report: {output_dir / 'report.md'}")
    print(f"Raw:    {raw_path}")
    print("=" * 60)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Consolidation conflict resolution benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--strategies",
        default="gpt4o-mini,haiku,heuristic,oracle",
        help="Comma-separated strategy names (default: all)",
    )
    parser.add_argument(
        "--output-dir",
        default="consolidation/results",
        help="Output directory for report (default: consolidation/results/)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Max concurrent API calls (default: 5)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run_benchmark(args))
