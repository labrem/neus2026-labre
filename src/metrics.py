"""
Evaluation Metrics for Experiment Results.

Computes accuracy metrics, statistical tests, and generates
analysis summaries.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AccuracyMetrics:
    """Accuracy metrics for a set of results."""

    total: int = 0
    correct: int = 0
    accuracy: float = 0.0
    confidence_interval_95: tuple[float, float] = (0.0, 0.0)

    # Breakdown by level
    by_level: dict[int, dict[str, Any]] = field(default_factory=dict)

    # Breakdown by type
    by_type: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Execution statistics
    code_extracted_count: int = 0
    execution_success_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.correct,
            "accuracy": self.accuracy,
            "confidence_interval_95": list(self.confidence_interval_95),
            "by_level": self.by_level,
            "by_type": self.by_type,
            "code_extracted_count": self.code_extracted_count,
            "execution_success_count": self.execution_success_count,
        }


@dataclass
class ComparisonMetrics:
    """Comparison between two experimental conditions."""

    condition_a: str
    condition_b: str
    accuracy_a: float
    accuracy_b: float
    accuracy_diff: float
    p_value: float | None = None
    is_significant: bool = False
    effect_size: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_a": self.condition_a,
            "condition_b": self.condition_b,
            "accuracy_a": self.accuracy_a,
            "accuracy_b": self.accuracy_b,
            "accuracy_diff": self.accuracy_diff,
            "p_value": self.p_value,
            "is_significant": self.is_significant,
            "effect_size": self.effect_size,
        }


class MetricsCalculator:
    """Calculates evaluation metrics from experiment results."""

    def __init__(self, significance_level: float = 0.05):
        """
        Initialize metrics calculator.

        Args:
            significance_level: Alpha for significance testing
        """
        self.significance_level = significance_level

    def compute_accuracy(
        self,
        results: list[dict[str, Any]],
    ) -> AccuracyMetrics:
        """
        Compute accuracy metrics for a set of results.

        Args:
            results: List of result dictionaries

        Returns:
            AccuracyMetrics with overall and breakdown statistics
        """
        if not results:
            return AccuracyMetrics()

        metrics = AccuracyMetrics()
        metrics.total = len(results)
        metrics.correct = sum(1 for r in results if r.get("is_correct", False))
        metrics.accuracy = metrics.correct / metrics.total if metrics.total > 0 else 0.0

        # Compute 95% confidence interval (Wilson score interval)
        metrics.confidence_interval_95 = self._wilson_interval(
            metrics.correct, metrics.total
        )

        # Breakdown by level
        level_groups: dict[int, list[dict]] = defaultdict(list)
        for r in results:
            level = r.get("level", 0)
            level_groups[level].append(r)

        for level, group in level_groups.items():
            correct = sum(1 for r in group if r.get("is_correct", False))
            total = len(group)
            metrics.by_level[level] = {
                "total": total,
                "correct": correct,
                "accuracy": correct / total if total > 0 else 0.0,
            }

        # Breakdown by type
        type_groups: dict[str, list[dict]] = defaultdict(list)
        for r in results:
            ptype = r.get("problem_type", "unknown")
            type_groups[ptype].append(r)

        for ptype, group in type_groups.items():
            correct = sum(1 for r in group if r.get("is_correct", False))
            total = len(group)
            metrics.by_type[ptype] = {
                "total": total,
                "correct": correct,
                "accuracy": correct / total if total > 0 else 0.0,
            }

        # Execution statistics
        metrics.code_extracted_count = sum(
            1 for r in results if r.get("code_extracted", False)
        )
        metrics.execution_success_count = sum(
            1 for r in results if r.get("execution_success", False)
        )

        return metrics

    def compare_conditions(
        self,
        results_a: list[dict[str, Any]],
        results_b: list[dict[str, Any]],
        condition_a: str,
        condition_b: str,
    ) -> ComparisonMetrics:
        """
        Compare accuracy between two conditions with significance testing.

        Args:
            results_a: Results for condition A
            results_b: Results for condition B
            condition_a: Name of condition A
            condition_b: Name of condition B

        Returns:
            ComparisonMetrics with statistical comparison
        """
        metrics_a = self.compute_accuracy(results_a)
        metrics_b = self.compute_accuracy(results_b)

        comparison = ComparisonMetrics(
            condition_a=condition_a,
            condition_b=condition_b,
            accuracy_a=metrics_a.accuracy,
            accuracy_b=metrics_b.accuracy,
            accuracy_diff=metrics_b.accuracy - metrics_a.accuracy,
        )

        # Perform chi-square test for significance
        if metrics_a.total > 0 and metrics_b.total > 0:
            p_value = self._chi_square_test(
                metrics_a.correct, metrics_a.total,
                metrics_b.correct, metrics_b.total,
            )
            comparison.p_value = p_value
            comparison.is_significant = p_value < self.significance_level

            # Effect size (Cohen's h)
            comparison.effect_size = self._cohens_h(
                metrics_a.accuracy, metrics_b.accuracy
            )

        return comparison

    def generate_summary(
        self,
        all_results: list[dict[str, Any]],
        conditions: list[str],
    ) -> dict[str, Any]:
        """
        Generate comprehensive summary of experiment results.

        Args:
            all_results: All results across conditions
            conditions: List of condition names

        Returns:
            Summary dictionary with metrics for all conditions
        """
        summary = {
            "conditions": {},
            "comparisons": [],
            "overall": {
                "total_problems": 0,
                "total_evaluations": len(all_results),
            },
        }

        # Group by condition
        condition_results: dict[str, list[dict]] = defaultdict(list)
        for r in all_results:
            condition = r.get("condition", "unknown")
            condition_results[condition].append(r)

        # Compute metrics per condition
        for condition in conditions:
            results = condition_results.get(condition, [])
            metrics = self.compute_accuracy(results)
            summary["conditions"][condition] = metrics.to_dict()

        # Compute problems count (from any condition)
        if condition_results:
            first_condition = list(condition_results.values())[0]
            summary["overall"]["total_problems"] = len(first_condition)

        # Pairwise comparisons (each condition vs baseline)
        if "baseline" in condition_results:
            baseline_results = condition_results["baseline"]
            for condition in conditions:
                if condition == "baseline":
                    continue
                cond_results = condition_results.get(condition, [])
                if cond_results:
                    comparison = self.compare_conditions(
                        baseline_results, cond_results,
                        "baseline", condition,
                    )
                    summary["comparisons"].append(comparison.to_dict())

        return summary

    def _wilson_interval(
        self,
        successes: int,
        total: int,
        z: float = 1.96,  # 95% confidence
    ) -> tuple[float, float]:
        """
        Compute Wilson score confidence interval.

        Args:
            successes: Number of successes
            total: Total trials
            z: Z-score for confidence level

        Returns:
            Tuple of (lower, upper) bounds
        """
        if total == 0:
            return (0.0, 0.0)

        p = successes / total
        denominator = 1 + z**2 / total
        center = (p + z**2 / (2 * total)) / denominator
        spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denominator

        lower = max(0.0, center - spread)
        upper = min(1.0, center + spread)

        return (lower, upper)

    def _chi_square_test(
        self,
        successes_a: int,
        total_a: int,
        successes_b: int,
        total_b: int,
    ) -> float:
        """
        Perform chi-square test for two proportions.

        Args:
            successes_a: Successes in group A
            total_a: Total in group A
            successes_b: Successes in group B
            total_b: Total in group B

        Returns:
            p-value (approximate)
        """
        # Pooled proportion
        p_pooled = (successes_a + successes_b) / (total_a + total_b)
        q_pooled = 1 - p_pooled

        if p_pooled == 0 or q_pooled == 0:
            return 1.0

        # Standard error
        se = math.sqrt(p_pooled * q_pooled * (1/total_a + 1/total_b))

        if se == 0:
            return 1.0

        # Z-statistic
        p_a = successes_a / total_a
        p_b = successes_b / total_b
        z = (p_b - p_a) / se

        # Approximate p-value (two-tailed)
        # Using error function approximation
        p_value = 2 * (1 - self._normal_cdf(abs(z)))

        return p_value

    def _normal_cdf(self, x: float) -> float:
        """
        Approximate standard normal CDF.

        Args:
            x: Value to evaluate

        Returns:
            Cumulative probability
        """
        # Approximation using error function
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def _cohens_h(self, p1: float, p2: float) -> float:
        """
        Compute Cohen's h effect size for proportions.

        Args:
            p1: First proportion
            p2: Second proportion

        Returns:
            Effect size (Cohen's h)
        """
        phi1 = 2 * math.asin(math.sqrt(p1))
        phi2 = 2 * math.asin(math.sqrt(p2))
        return abs(phi2 - phi1)

    def format_summary_table(self, summary: dict[str, Any]) -> str:
        """
        Format summary as ASCII table for display.

        Args:
            summary: Summary dictionary from generate_summary()

        Returns:
            Formatted table string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("EXPERIMENT SUMMARY")
        lines.append("=" * 70)

        # Overall stats
        lines.append(f"Total Problems: {summary['overall']['total_problems']}")
        lines.append(f"Total Evaluations: {summary['overall']['total_evaluations']}")
        lines.append("")

        # Condition results table
        lines.append("-" * 70)
        lines.append(f"{'Condition':<20} {'Correct':>10} {'Total':>10} {'Accuracy':>12} {'95% CI':>15}")
        lines.append("-" * 70)

        for condition, metrics in summary["conditions"].items():
            ci = metrics["confidence_interval_95"]
            ci_str = f"[{ci[0]:.1%}, {ci[1]:.1%}]"
            lines.append(
                f"{condition:<20} {metrics['correct']:>10} {metrics['total']:>10} "
                f"{metrics['accuracy']:>11.1%} {ci_str:>15}"
            )

        lines.append("-" * 70)
        lines.append("")

        # Comparisons
        if summary["comparisons"]:
            lines.append("Comparisons vs Baseline:")
            lines.append("-" * 70)
            lines.append(f"{'Condition':<20} {'Diff':>10} {'p-value':>12} {'Significant':>12}")
            lines.append("-" * 70)

            for comp in summary["comparisons"]:
                sig_str = "Yes *" if comp["is_significant"] else "No"
                p_str = f"{comp['p_value']:.4f}" if comp['p_value'] else "N/A"
                lines.append(
                    f"{comp['condition_b']:<20} {comp['accuracy_diff']:>+9.1%} "
                    f"{p_str:>12} {sig_str:>12}"
                )

            lines.append("-" * 70)

        lines.append("=" * 70)

        return "\n".join(lines)


def create_metrics_calculator(
    significance_level: float = 0.05,
) -> MetricsCalculator:
    """
    Factory function to create a metrics calculator.

    Args:
        significance_level: Alpha for significance testing

    Returns:
        Configured MetricsCalculator instance
    """
    return MetricsCalculator(significance_level=significance_level)
