"""Report generation — produces a markdown benchmark report from computed metrics.

Outputs a structured table comparing MCP Brain results against published baselines
(Mem0, OpenAI Memory) and includes per-category breakdown.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from metrics import BenchmarkMetrics


# Published baselines from Mem0's MemoryBench report (LoCoMo subset)
BASELINES = {
    "Mem0 (reported)": {"llm_judge_accuracy": 0.669, "search_latency_p95_ms": 1440},
    "OpenAI Memory (reported)": {"llm_judge_accuracy": 0.529, "search_latency_p95_ms": None},
    "Zep (reported)": {"llm_judge_accuracy": 0.411, "search_latency_p95_ms": None},
}


def generate_report(
    metrics: BenchmarkMetrics,
    run_params: dict,
    output_dir: Path | None = None,
) -> str:
    """Generate a markdown report from benchmark metrics.

    Args:
        metrics: Computed BenchmarkMetrics from the run.
        run_params: Dict of run parameters (dataset, provider, judge model, seed, etc.)
        output_dir: If provided, writes report.md and results.json to this directory.

    Returns:
        The markdown report as a string.
    """
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# MCP Brain Benchmark Results",
        "",
        f"**Date:** {now}",
        f"**Dataset:** {run_params.get('dataset', 'locomo')}",
        f"**Provider:** {run_params.get('provider', 'mcpbrain')}",
        f"**Judge Model:** {run_params.get('judge_model', 'gpt-4o-mini')}",
        f"**Questions Evaluated:** {metrics.total_questions}",
        f"**Conversations:** {metrics.total_conversations}",
        f"**Seed:** {run_params.get('seed', 42)}",
        "",
        "---",
        "",
        "## Summary",
        "",
        _summary_table(metrics),
        "",
        "## Latency",
        "",
        _latency_table(metrics),
        "",
        "## Breakdown by Question Type",
        "",
        _category_table(metrics),
        "",
        "## Retrieval Statistics",
        "",
        f"- **Mean memories retrieved per query:** {metrics.mean_memories_retrieved:.1f}",
        f"- **Mean tokens per query:** {metrics.mean_tokens_per_query:.0f}",
        f"- **Total tokens used:** {metrics.total_tokens:,}",
        "",
        "---",
        "",
        "## Methodology",
        "",
        "1. For each conversation in the LoCoMo dataset, all turns are ingested as individual "
        "memories via the MCP `create_memory` tool.",
        "2. For each evaluation question, we search the memory store and retrieve the top-k "
        "relevant memories.",
        "3. An LLM (answerer) generates an answer from the retrieved context.",
        "4. An LLM judge (gpt-4o-mini) compares the answer to the gold-standard label and "
        "returns CORRECT or INCORRECT.",
        "5. Token-overlap F1 is computed as a cheap secondary metric.",
        "",
        "This methodology mirrors MemoryBench (supermemoryai/memorybench) for comparability.",
        "",
        "## Run Parameters",
        "",
        "```json",
        json.dumps(run_params, indent=2, default=str),
        "```",
        "",
    ]

    report = "\n".join(lines)

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

        report_path = output_dir / "report.md"
        report_path.write_text(report)

        results_path = output_dir / "results.json"
        results_path.write_text(
            json.dumps(
                {
                    "run_params": run_params,
                    "metrics": {
                        "llm_judge_accuracy": metrics.llm_judge_accuracy,
                        "mean_f1": metrics.mean_f1,
                        "total_questions": metrics.total_questions,
                        "total_correct": metrics.total_correct,
                        "search_latency_p50_ms": metrics.search_latency_p50_ms,
                        "search_latency_p95_ms": metrics.search_latency_p95_ms,
                        "answer_latency_p50_ms": metrics.answer_latency_p50_ms,
                        "answer_latency_p95_ms": metrics.answer_latency_p95_ms,
                        "total_tokens": metrics.total_tokens,
                        "by_category": {
                            name: {
                                "count": cat.count,
                                "correct": cat.correct,
                                "accuracy": cat.accuracy,
                            }
                            for name, cat in metrics.by_category.items()
                        },
                    },
                    "timestamp": now,
                },
                indent=2,
            )
        )

    return report


def _summary_table(metrics: BenchmarkMetrics) -> str:
    """Build the main comparison table."""
    rows = [
        "| Metric | MCP Brain | Mem0 (reported) | OpenAI Memory (reported) | Zep (reported) |",
        "|--------|-----------|-----------------|--------------------------|----------------|",
    ]

    def _pct(v: float | None) -> str:
        return f"{v * 100:.1f}%" if v is not None else "-"

    def _ms(v: float | None) -> str:
        if v is None:
            return "-"
        return f"{v:.0f}ms" if v < 1000 else f"{v / 1000:.2f}s"

    rows.append(
        f"| LLM-as-Judge | {_pct(metrics.llm_judge_accuracy)} "
        f"| {_pct(BASELINES['Mem0 (reported)']['llm_judge_accuracy'])} "
        f"| {_pct(BASELINES['OpenAI Memory (reported)']['llm_judge_accuracy'])} "
        f"| {_pct(BASELINES['Zep (reported)']['llm_judge_accuracy'])} |"
    )
    rows.append(f"| F1 (token overlap) | {metrics.mean_f1:.3f} | - | - | - |")
    rows.append(
        f"| Search Latency (p95) | {_ms(metrics.search_latency_p95_ms)} "
        f"| {_ms(BASELINES['Mem0 (reported)']['search_latency_p95_ms'])} "
        f"| - | - |"
    )

    return "\n".join(rows)


def _latency_table(metrics: BenchmarkMetrics) -> str:
    """Build the latency breakdown table."""

    def _ms(v: float) -> str:
        return f"{v:.0f}ms" if v < 1000 else f"{v / 1000:.2f}s"

    return "\n".join(
        [
            "| Metric | Value |",
            "|--------|-------|",
            f"| Search p50 | {_ms(metrics.search_latency_p50_ms)} |",
            f"| Search p95 | {_ms(metrics.search_latency_p95_ms)} |",
            f"| Search mean | {_ms(metrics.search_latency_mean_ms)} |",
            f"| Answer (search + LLM) p50 | {_ms(metrics.answer_latency_p50_ms)} |",
            f"| Answer (search + LLM) p95 | {_ms(metrics.answer_latency_p95_ms)} |",
        ]
    )


def _category_table(metrics: BenchmarkMetrics) -> str:
    """Build the per-category breakdown table."""
    rows = [
        "| Type | Accuracy | F1 | Count | Mean Latency |",
        "|------|----------|----|-------|--------------|",
    ]

    for name, cat in sorted(metrics.by_category.items(), key=lambda x: x[0]):
        latency = (
            f"{cat.mean_latency_ms:.0f}ms"
            if cat.mean_latency_ms < 1000
            else f"{cat.mean_latency_ms / 1000:.2f}s"
        )
        rows.append(
            f"| {name} | {cat.accuracy * 100:.1f}% | {cat.mean_f1:.3f} | {cat.count} | {latency} |"
        )

    return "\n".join(rows)
