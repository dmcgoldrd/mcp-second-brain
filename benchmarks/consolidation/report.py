"""Report generation for consolidation conflict resolution benchmark.

Produces a markdown report comparing strategies with:
- Summary comparison table (accuracy, precision, recall, F1, latency, cost)
- Per-category breakdown
- Confusion matrices for each strategy
- Cost projections at scale
- Misclassification details
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from consolidation.run import StrategyMetrics


def generate_report(
    all_metrics: list[StrategyMetrics],
    output_dir: Path,
) -> str:
    """Generate the full benchmark report as markdown.

    Args:
        all_metrics: List of StrategyMetrics, one per evaluated strategy.
        output_dir: Directory to write report.md.

    Returns:
        The markdown report string.
    """
    now = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    sections = [
        _header(now, all_metrics),
        _summary_table(all_metrics),
        _category_breakdown(all_metrics),
        _confusion_matrices(all_metrics),
        _cost_projection(all_metrics),
        _misclassifications(all_metrics),
        _methodology(),
    ]

    report = "\n\n".join(sections)

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.md"
    report_path.write_text(report)

    return report


def _header(timestamp: str, all_metrics: list[StrategyMetrics]) -> str:
    """Report header with run metadata."""
    total_pairs = sum(
        len(m.pair_results)
        for m in all_metrics[:1]  # All strategies run same pairs
    )
    strategies = ", ".join(m.strategy for m in all_metrics)

    return "\n".join(
        [
            "# Consolidation Strategy Benchmark",
            "",
            f"**Date:** {timestamp}",
            f"**Test Pairs:** {total_pairs}",
            f"**Strategies:** {strategies}",
            "",
            "Evaluates conflict resolution quality for memory consolidation across",
            "LLM-based and heuristic strategies. The task: given two semantically",
            "similar memories, classify as UPDATE (newer supersedes) or KEEP_BOTH",
            "(distinct memories worth preserving).",
        ]
    )


def _summary_table(all_metrics: list[StrategyMetrics]) -> str:
    """Main comparison table."""
    lines = [
        "## Summary",
        "",
        "| Strategy | Accuracy | Precision | Recall | F1 | Avg Latency | Cost/call | Total Cost |",
        "|----------|----------|-----------|--------|-----|-------------|-----------|------------|",
    ]

    for m in all_metrics:
        latency = (
            f"{m.avg_latency_ms:.0f}ms"
            if m.avg_latency_ms < 1000
            else f"{m.avg_latency_ms / 1000:.2f}s"
        )
        lines.append(
            f"| {m.strategy} | {m.accuracy * 100:.1f}% | {m.precision * 100:.1f}% "
            f"| {m.recall * 100:.1f}% | {m.f1:.3f} | {latency} "
            f"| ${m.cost_per_call:.6f} | ${m.total_cost:.4f} |"
        )

    return "\n".join(lines)


def _category_breakdown(all_metrics: list[StrategyMetrics]) -> str:
    """Per-category accuracy breakdown."""
    # Collect all categories across strategies
    all_categories: list[str] = []
    for m in all_metrics:
        for cat in m.by_category:
            if cat not in all_categories:
                all_categories.append(cat)
    all_categories.sort()

    header_cols = " | ".join(m.strategy for m in all_metrics)
    separator = " | ".join("---" for _ in all_metrics)

    lines = [
        "## Accuracy by Category",
        "",
        f"| Category | {header_cols} |",
        f"|----------|{separator}|",
    ]

    for cat in all_categories:
        cols = []
        for m in all_metrics:
            acc = m.by_category.get(cat, 0.0)
            cols.append(f"{acc * 100:.1f}%")
        lines.append(f"| {cat} | {' | '.join(cols)} |")

    return "\n".join(lines)


def _confusion_matrices(all_metrics: list[StrategyMetrics]) -> str:
    """Confusion matrix for each strategy."""
    lines = ["## Confusion Matrices", ""]

    for m in all_metrics:
        total = m.true_positive + m.false_positive + m.true_negative + m.false_negative
        if total == 0:
            continue

        lines.extend(
            [
                f"### {m.strategy} ({m.description})",
                "",
                "| | Predicted UPDATE | Predicted KEEP_BOTH |",
                "|---|---|---|",
                f"| **Actual UPDATE** | {m.true_positive} (TP) | {m.false_negative} (FN) |",
                f"| **Actual KEEP_BOTH** | {m.false_positive} (FP) | {m.true_negative} (TN) |",
                "",
            ]
        )

    return "\n".join(lines)


def _cost_projection(all_metrics: list[StrategyMetrics]) -> str:
    """Cost projection at different user scales."""
    # From docs/cost-analysis.md: ~5 conflict pairs per user per night
    conflicts_per_user_per_night = 5
    days_per_month = 30

    lines = [
        "## Cost Projection at Scale",
        "",
        "Assumes ~5 conflict classification calls per user per night (from cost-analysis.md).",
        "",
        "| Users | " + " | ".join(f"{m.strategy}/mo" for m in all_metrics) + " |",
        "|-------|" + "|".join("---" for _ in all_metrics) + "|",
    ]

    user_counts = [10, 100, 1_000, 10_000, 100_000]

    for users in user_counts:
        cols = []
        for m in all_metrics:
            monthly_calls = users * conflicts_per_user_per_night * days_per_month
            monthly_cost = monthly_calls * m.cost_per_call
            if monthly_cost < 0.01:
                cols.append("$0.00")
            elif monthly_cost < 1.0 or monthly_cost < 100:
                cols.append(f"${monthly_cost:.2f}")
            else:
                cols.append(f"${monthly_cost:,.0f}")
        lines.append(f"| {users:,} | {' | '.join(cols)} |")

    return "\n".join(lines)


def _misclassifications(all_metrics: list[StrategyMetrics]) -> str:
    """Show which pairs each strategy got wrong (for debugging)."""
    lines = ["## Misclassifications", ""]

    for m in all_metrics:
        wrong = [pr for pr in m.pair_results if not pr.correct]
        if not wrong:
            lines.extend(
                [
                    f"### {m.strategy}",
                    "",
                    "No misclassifications (perfect accuracy).",
                    "",
                ]
            )
            continue

        lines.extend(
            [
                f"### {m.strategy} ({len(wrong)} errors)",
                "",
                "| Pair ID | Category | Expected | Predicted | Difficulty |",
                "|---------|----------|----------|-----------|------------|",
            ]
        )

        for pr in wrong:
            lines.append(
                f"| {pr.pair_id} | {pr.category} | {pr.expected} "
                f"| {pr.predicted} | {pr.difficulty} |"
            )

        lines.append("")

    return "\n".join(lines)


def _methodology() -> str:
    """Methodology section."""
    return "\n".join(
        [
            "## Methodology",
            "",
            "1. **Test dataset:** 70 handcrafted memory conflict pairs across 5 categories",
            "   (fact_update, additive, temporal, near_dup, edge_case) with ground-truth labels.",
            "2. **LLM strategies** (gpt-4o-mini, haiku-4.5) use the same prompt template as",
            "   `src/consolidation.py:_classify_conflict` for fair comparison.",
            "3. **Heuristic strategy** computes cosine similarity via OpenAI embeddings",
            "   (text-embedding-3-small) and applies deterministic threshold rules.",
            "4. **Oracle strategy** returns ground-truth labels as a perfect-accuracy baseline.",
            "5. **Metrics:** Accuracy (overall correctness), Precision/Recall/F1 (for the UPDATE",
            "   class specifically), latency, and cost per classification call.",
            "6. **Cost projections** extrapolate from per-call costs assuming ~5 conflict pairs",
            "   per user per night, consistent with the analysis in docs/cost-analysis.md.",
            "",
            "---",
            "",
            "*Generated by benchmarks/consolidation/run.py*",
        ]
    )
