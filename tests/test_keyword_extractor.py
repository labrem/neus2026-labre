"""Unit tests for keyword extractor."""

import pytest
from pathlib import Path


@pytest.fixture
def extractor():
    """Create extractor instance."""
    from src.keyword_extractor import KeywordExtractor
    project_root = Path(__file__).parent.parent
    index_path = project_root / "data" / "index.json"
    return KeywordExtractor(index_path=index_path if index_path.exists() else None)


def test_extract_gcd_problem(extractor):
    """Test extraction from GCD problem."""
    problem = "Find the greatest common divisor of 48 and 18."
    result = extractor.extract(problem)

    assert "greatest common divisor" in result.phrases
    assert len(result.all_terms()) > 0


def test_extract_operators(extractor):
    """Test operator extraction."""
    problem = "Calculate 2 + 3 * 4 - 1"
    result = extractor.extract(problem)

    assert "+" in result.operators
    assert "*" in result.operators
    assert "-" in result.operators


def test_extract_functions(extractor):
    """Test function name extraction."""
    problem = "Calculate sin(x) + cos(x)"
    result = extractor.extract(problem)

    assert "sin" in result.functions
    assert "cos" in result.functions


def test_extract_derivative(extractor):
    """Test calculus term extraction."""
    problem = "Find the derivative of x^2"
    result = extractor.extract(problem)

    assert "derivative" in result.keywords or "derivative" in result.functions


def test_unicode_operators(extractor):
    """Test Unicode operator handling."""
    problem = "Is π ≤ 4?"
    result = extractor.extract(problem)

    # Should detect Unicode operators
    assert "π" in result.operators or "pi" in result.keywords
    assert "≤" in result.operators or "<=" in result.operators


def test_asymptote_code_stripped(extractor):
    """Test that Asymptote [asy]...[/asy] blocks are stripped before extraction."""
    problem = """The volume of the cylinder shown is $45\\pi$ cubic cm. What is the height in centimeters of the cylinder? [asy]
size(120);
draw(shift(2.2,0)*yscale(0.3)*Circle((0,0), 1.2));
draw((1,0)--(1,-2));
draw((3.4,0)--(3.4,-2));
draw((1,-2)..(2.2,-2.36)..(3.4,-2));
label("$h$",midpoint((3.4,0)--(3.4,-2)),E);
draw (((2.2,0)--(3.4,0)));
label("$r=3$",midpoint((2.2,0)--(3.4,0)),N);
[/asy]"""
    result = extractor.extract(problem)

    # Should NOT include Asymptote code artifacts
    assert "size" not in result.keywords, "Asymptote 'size' should be stripped"
    assert "e" not in result.keywords, "Asymptote direction 'E' should be stripped"

    # Should include actual math terms from the problem
    assert "volume" in result.keywords
    assert "pi" in result.keywords or "π" in result.operators
