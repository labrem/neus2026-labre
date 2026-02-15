"""Unit tests for metrics calculator."""

import pytest


@pytest.fixture
def calculator():
    """Create calculator instance."""
    from src.metrics import create_metrics_calculator
    return create_metrics_calculator()


@pytest.fixture
def mock_results():
    """Create mock results for testing."""
    return [
        {"problem_id": f"test_{i}", "is_correct": i % 2 == 0,
         "level": (i % 5) + 1, "problem_type": "algebra",
         "code_extracted": True, "execution_success": True,
         "condition": "baseline"}
        for i in range(100)
    ]


def test_compute_accuracy(calculator, mock_results):
    """Test accuracy computation."""
    metrics = calculator.compute_accuracy(mock_results)

    assert metrics.total == 100
    assert metrics.correct == 50  # Every other is correct
    assert abs(metrics.accuracy - 0.5) < 0.01


def test_confidence_interval(calculator, mock_results):
    """Test confidence interval computation."""
    metrics = calculator.compute_accuracy(mock_results)

    lower, upper = metrics.confidence_interval_95
    assert lower < metrics.accuracy < upper
    assert lower > 0
    assert upper < 1


def test_by_level_breakdown(calculator, mock_results):
    """Test accuracy breakdown by level."""
    metrics = calculator.compute_accuracy(mock_results)

    assert len(metrics.by_level) == 5  # Levels 1-5
    for level, stats in metrics.by_level.items():
        assert "total" in stats
        assert "correct" in stats
        assert "accuracy" in stats


def test_compare_conditions(calculator):
    """Test condition comparison."""
    baseline = [{"is_correct": i % 3 == 0} for i in range(100)]
    improved = [{"is_correct": i % 2 == 0} for i in range(100)]

    comparison = calculator.compare_conditions(
        baseline, improved, "baseline", "improved"
    )

    assert comparison.accuracy_b > comparison.accuracy_a
    assert comparison.accuracy_diff > 0
    assert comparison.p_value is not None


def test_generate_summary(calculator, mock_results):
    """Test summary generation."""
    summary = calculator.generate_summary(mock_results, ["baseline"])

    assert "conditions" in summary
    assert "baseline" in summary["conditions"]
    assert summary["overall"]["total_evaluations"] == 100


def test_format_summary_table(calculator, mock_results):
    """Test ASCII table formatting."""
    summary = calculator.generate_summary(mock_results, ["baseline"])
    table = calculator.format_summary_table(summary)

    assert "EXPERIMENT SUMMARY" in table
    assert "baseline" in table
    assert "50.0%" in table or "50%" in table
