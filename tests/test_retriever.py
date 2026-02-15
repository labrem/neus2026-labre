"""Unit tests for OpenMath retriever."""

import pytest
from pathlib import Path


@pytest.fixture
def retriever():
    """Create retriever instance."""
    from src.retriever import create_retriever
    project_root = Path(__file__).parent.parent
    return create_retriever(project_root)


def test_retrieve_gcd(retriever):
    """Test retrieval for GCD terms."""
    terms = ["gcd", "greatest", "common", "divisor"]
    result = retriever.retrieve(terms, max_symbols=5)

    assert len(result.symbols) > 0
    assert "arith1:gcd" in result.symbol_ids


def test_retrieve_trigonometric(retriever):
    """Test retrieval for trig functions."""
    terms = ["sin", "cos", "sine", "cosine"]
    result = retriever.retrieve(terms, max_symbols=5)

    symbol_ids = result.symbol_ids
    assert any("sin" in sid for sid in symbol_ids) or any("transc1" in sid for sid in symbol_ids)


def test_retrieve_with_alias(retriever):
    """Test retrieval with operator alias."""
    terms = ["+", "plus", "addition"]
    result = retriever.retrieve(terms, max_symbols=3)

    assert "arith1:plus" in result.symbol_ids


def test_retrieve_scoring(retriever):
    """Test that symbols are scored by match count."""
    terms = ["gcd", "greatest", "common", "divisor"]
    result = retriever.retrieve(terms)

    if "arith1:gcd" in result.scores:
        assert result.scores["arith1:gcd"] >= 1


def test_get_symbol(retriever):
    """Test direct symbol retrieval."""
    symbol = retriever.get_symbol("arith1:gcd")

    assert symbol is not None
    assert symbol["name"] == "gcd"
    assert symbol["cd"] == "arith1"
