"""Unit tests for answer comparator."""

import pytest


@pytest.fixture
def comparator():
    """Create comparator instance."""
    from src.comparator import create_comparator
    return create_comparator()


def test_exact_match(comparator):
    """Test exact string match."""
    result = comparator.compare("42", "42")

    assert result.is_equivalent
    assert result.comparison_method == "exact_match"


def test_numeric_integer(comparator):
    """Test integer comparison."""
    result = comparator.compare("6", "6.0")

    assert result.is_equivalent


def test_numeric_float(comparator):
    """Test float comparison with tolerance."""
    result = comparator.compare("6.0000001", "6")

    assert result.is_equivalent


def test_fraction_decimal(comparator):
    """Test fraction to decimal comparison."""
    result = comparator.compare("3/4", "0.75")

    assert result.is_equivalent


def test_fraction_latex(comparator):
    """Test LaTeX fraction parsing."""
    result = comparator.compare(r"\frac{1}{2}", "0.5")

    assert result.is_equivalent


def test_symbolic_sqrt(comparator):
    """Test symbolic square root comparison."""
    result = comparator.compare("2*sqrt(3)", "sqrt(12)")

    assert result.is_equivalent


def test_not_equal(comparator):
    """Test non-equivalent values."""
    result = comparator.compare("7", "6")

    assert not result.is_equivalent


def test_empty_answer(comparator):
    """Test handling of empty answers."""
    result = comparator.compare("", "42")

    assert not result.is_equivalent
    assert "Empty" in result.error_message


def test_latex_cleanup(comparator):
    """Test LaTeX notation cleanup."""
    # \cdot should become *
    result = comparator.compare(r"2 \cdot 3", "6")

    assert result.is_equivalent


def test_negative_numbers(comparator):
    """Test negative number comparison."""
    result = comparator.compare("-5", "-5.0")

    assert result.is_equivalent


def test_pi_comparison(comparator):
    """Test symbolic pi comparison with numerical approximation."""
    result = comparator.compare("pi", "3.14159265359")

    # pi ≈ 3.14159265358979..., so 3.14159265359 is within tolerance
    assert result.is_equivalent
    assert result.comparison_method == "symbolic"


def test_set_comparison_unordered(comparator):
    """Test that unordered multi-value answers match."""
    result = comparator.compare("-2, 2", "2, -2")

    assert result.is_equivalent
    assert result.comparison_method == "set_compare"


def test_set_comparison_with_brackets(comparator):
    """Test set comparison with brackets."""
    result = comparator.compare("{1, 2, 3}", "{3, 2, 1}")

    assert result.is_equivalent
    assert result.comparison_method == "set_compare"


# === Tests for nested LaTeX expressions ===

def test_nested_fraction(comparator):
    """Test nested fraction parsing: \\frac{\\frac{1}{2}}{3} = 1/6."""
    result = comparator.compare(r"\frac{\frac{1}{2}}{3}", "1/6")

    assert result.is_equivalent


def test_nested_sqrt_in_fraction(comparator):
    """Test sqrt nested in fraction: \\frac{1}{\\sqrt{2}} = sqrt(2)/2."""
    result = comparator.compare(r"\frac{1}{\sqrt{2}}", "sqrt(2)/2")

    assert result.is_equivalent


def test_fraction_in_sqrt(comparator):
    """Test fraction nested in sqrt: \\sqrt{\\frac{1}{4}} = 1/2."""
    result = comparator.compare(r"\sqrt{\frac{1}{4}}", "0.5")

    assert result.is_equivalent


def test_deeply_nested_expression(comparator):
    """Test deeply nested expression: \\frac{1}{\\frac{1}{\\frac{1}{2}}} = 1/2."""
    result = comparator.compare(r"\frac{1}{\frac{1}{\frac{1}{2}}}", "0.5")

    assert result.is_equivalent


# === Tests for complex set expressions ===

def test_set_with_sqrt(comparator):
    """Test set comparison with sqrt elements."""
    result = comparator.compare("sqrt(2), sqrt(3)", "sqrt(3), sqrt(2)")

    assert result.is_equivalent
    assert result.comparison_method == "set_compare"


def test_set_with_fractions(comparator):
    """Test set comparison with fraction elements."""
    result = comparator.compare(r"\frac{1}{2}, \frac{1}{3}", r"\frac{1}{3}, \frac{1}{2}")

    assert result.is_equivalent
    assert result.comparison_method == "set_compare"


def test_set_with_negative_sqrt(comparator):
    """Test set comparison: {-sqrt(2), sqrt(2)} in any order."""
    result = comparator.compare("-sqrt(2), sqrt(2)", "sqrt(2), -sqrt(2)")

    assert result.is_equivalent
    assert result.comparison_method == "set_compare"


def test_complex_nested_in_set(comparator):
    """Test set with nested fractions."""
    result = comparator.compare(
        r"\frac{1}{\sqrt{2}}, -\frac{1}{\sqrt{2}}",
        r"-\frac{1}{\sqrt{2}}, \frac{1}{\sqrt{2}}"
    )

    assert result.is_equivalent
    assert result.comparison_method == "set_compare"


# === Additional edge case tests ===

def test_equivalent_sqrt_forms(comparator):
    """Test that sqrt(8) = 2*sqrt(2)."""
    result = comparator.compare("sqrt(8)", "2*sqrt(2)")

    assert result.is_equivalent


def test_nth_root(comparator):
    """Test nth root: \\sqrt[3]{8} = 2."""
    result = comparator.compare(r"\sqrt[3]{8}", "2")

    assert result.is_equivalent
