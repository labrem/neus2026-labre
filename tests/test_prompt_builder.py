"""Unit tests for prompt builder."""

import pytest
from pathlib import Path


@pytest.fixture
def builder():
    """Create builder instance."""
    from src.prompt_builder import create_prompt_builder
    project_root = Path(__file__).parent.parent
    return create_prompt_builder(project_root)


@pytest.fixture
def sample_symbols():
    """Sample symbols for testing."""
    return [
        {
            "id": "arith1:gcd",
            "cd": "arith1",
            "name": "gcd",
            "description": "Greatest common divisor function.",
            "type_signature": "nassoc(SemiGroup) -> SemiGroup",
            "cmp_properties": ["gcd(a,b) = gcd(b,a)"],
            "sympy_function": "sympy.gcd",
        }
    ]


def test_available_conditions(builder):
    """Test that all conditions are available."""
    conditions = builder.get_available_conditions()

    assert "baseline" in conditions
    assert "definitions" in conditions
    assert "with_fmp" in conditions
    assert "full_system" in conditions


def test_build_baseline(builder, sample_symbols):
    """Test baseline prompt building."""
    problem = "Find the GCD of 48 and 18."
    prompt = builder.build(problem, sample_symbols, condition="baseline")

    assert prompt.problem == problem
    assert prompt.condition == "baseline"
    assert problem in prompt.user_prompt
    # Baseline should NOT include OpenMath context
    assert "arith1:gcd" not in prompt.system_prompt


def test_build_definitions(builder, sample_symbols):
    """Test definitions-only prompt building."""
    problem = "Find the GCD of 48 and 18."
    prompt = builder.build(problem, sample_symbols, condition="definitions")

    assert "arith1:gcd" in prompt.system_prompt
    assert "Description" in prompt.system_prompt
    # Should NOT include type or properties
    assert "Type:" not in prompt.system_prompt


def test_build_with_fmp(builder, sample_symbols):
    """Test with_fmp prompt building."""
    problem = "Find the GCD of 48 and 18."
    prompt = builder.build(problem, sample_symbols, condition="with_fmp")

    assert "arith1:gcd" in prompt.system_prompt
    assert "Type:" in prompt.system_prompt
    assert "Properties:" in prompt.system_prompt


def test_build_full_system(builder, sample_symbols):
    """Test full system prompt building."""
    problem = "Find the GCD of 48 and 18."
    prompt = builder.build(problem, sample_symbols, condition="full_system")

    assert "arith1:gcd" in prompt.system_prompt
    assert "SymPy" in prompt.system_prompt
    assert "sympy.gcd" in prompt.system_prompt


def test_to_messages(builder, sample_symbols):
    """Test conversion to message format."""
    prompt = builder.build("Test problem", sample_symbols, "baseline")
    messages = prompt.to_messages()

    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"


def test_invalid_condition(builder, sample_symbols):
    """Test handling of invalid condition."""
    with pytest.raises(ValueError):
        builder.build("Test", sample_symbols, condition="invalid_condition")
