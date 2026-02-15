"""Unit tests for code extractor."""

import pytest


@pytest.fixture
def extractor():
    """Create extractor instance."""
    from src.code_extractor import create_code_extractor
    return create_code_extractor()


def test_extract_python_block(extractor):
    """Test extraction of Python code blocks."""
    response = '''
Here is the solution:

```python
import sympy
result = sympy.gcd(48, 18)
print(result)
```

The answer is 6.
'''
    result = extractor.extract(response)

    assert result.has_code
    assert len(result.code_blocks) == 1
    assert "sympy.gcd" in result.primary_code


def test_extract_multiple_blocks(extractor):
    """Test extraction of multiple code blocks."""
    response = '''
```python
x = 1
```

```python
y = 2
```
'''
    result = extractor.extract(response)

    assert len(result.code_blocks) == 2


def test_extract_boxed_answer(extractor):
    """Test extraction of boxed answers."""
    response = r"The answer is $\boxed{42}$."

    result = extractor.extract(response)

    assert "42" in result.boxed_answers
    assert result.primary_answer == "42"


def test_extract_double_backslash_boxed(extractor):
    """Test extraction with double backslash."""
    response = r"The answer is \\boxed{42}."

    result = extractor.extract(response)

    assert "42" in result.boxed_answers


def test_extract_natural_answer(extractor):
    """Test extraction of natural language answers."""
    response = "Therefore, the answer is 42."

    result = extractor.extract(response)

    assert "42" in result.natural_answers


def test_merge_code_blocks(extractor):
    """Test merging multiple code blocks."""
    blocks = [
        "import sympy",
        "import sympy\nresult = sympy.gcd(48, 18)",
    ]

    merged = extractor.merge_code_blocks(blocks)

    # Should deduplicate imports
    assert merged.count("import sympy") == 1


def test_no_code_no_answer(extractor):
    """Test response with no code or clear answer."""
    response = "I'm not sure how to solve this."

    result = extractor.extract(response)

    assert not result.has_code
    assert not result.has_answer


def test_skip_output_blocks(extractor):
    """Test that ```output blocks are skipped and not treated as code."""
    response = '''
Here is the solution:

```python
from sympy import symbols, Eq, solve

x = symbols('x')
solution = solve(Eq(2**3 * 3**x, 72), x)
print(solution)
```
```output
[2]
```
The value of x is 2.
'''
    result = extractor.extract(response)

    # Should extract the Python code block
    assert result.has_code
    assert len(result.code_blocks) == 1

    # The code should NOT contain the output "[2]"
    assert "[2]" not in result.primary_code
    assert "from sympy" in result.primary_code


def test_natural_answer_value_of_x(extractor):
    """Test extraction of 'the value of x is Y' pattern."""
    response = "Solving the equation, we find that the value of x is 5."

    result = extractor.extract(response)

    assert "5" in result.natural_answers


def test_natural_answer_latex_assignment(extractor):
    """Test extraction of LaTeX variable assignment '$x = Y$'."""
    response = "After simplification, we get $x = 42$."

    result = extractor.extract(response)

    assert any("42" in ans for ans in result.natural_answers)


def test_extract_polynomial_expression_answer(extractor):
    """Test extraction of polynomial expression as final answer.

    This tests the fix for math_00347 where the system extracted '-24'
    instead of '6r^2-4r-24' because the old patterns only captured numbers.
    """
    response = '''
Let me expand the expression step by step.

First, expand (2r-3)(r+4):
= 2r² + 8r - 3r - 12
= 2r² + 5r - 12

Then expand (r-1)(3r+2):
= 3r² + 2r - 3r - 2
= 3r² - r - 2

Adding them together:
= 2r² + 5r - 12 + 3r² - r - 2
= 5r² + 4r - 14

Wait, let me recalculate...

The simplified form is 6r^2-4r-24. Therefore, A=6, B=-4, and C=-24.
'''
    result = extractor.extract(response)

    # Should extract the polynomial expression, not just '-24'
    assert any("6r^2-4r-24" in ans or "6r^2 - 4r - 24" in ans
               for ans in result.natural_answers)


def test_filter_problem_statement_matches(extractor):
    """Test that matches from problem statements are filtered out.

    This tests the fix for math_00454 where '$y = 2x + 1$' was extracted
    from the quoted problem statement instead of the actual answer.
    """
    response = '''
The problem asks us to find the equation of a line.

Given the equation $y = 2x + 1$ from the problem, we need to...

After analysis, the answer is $\\boxed{y = 2x + 3}$.
'''
    result = extractor.extract(response)

    # Should prefer boxed answer
    assert result.primary_answer == "y = 2x + 3"


def test_all_candidate_answers(extractor):
    """Test that all_candidate_answers returns answers in priority order."""
    response = '''
First, the answer is 10.
After checking, the answer is 15.
Therefore, \\boxed{20}
'''
    result = extractor.extract(response)

    candidates = result.all_candidate_answers

    # Boxed should be first (highest priority)
    assert candidates[0] == "20"
    # Natural answers should follow
    assert "10" in candidates
    assert "15" in candidates


def test_boxed_expression_priority(extractor):
    """Test that boxed expressions take priority over natural language."""
    response = '''
The intermediate result is 42.
After simplification, the final answer is \\boxed{6r^2 - 4r - 24}.
'''
    result = extractor.extract(response)

    # Boxed answer should be primary
    assert result.primary_answer == "6r^2 - 4r - 24"
    # Natural answer should still be captured
    assert "42" in result.natural_answers


def test_filter_find_the_patterns(extractor):
    """Test that 'find the X' patterns are filtered as problem statements."""
    response = '''
We need to find the value of x such that 2x + 3 = 7.

Solving: 2x = 4, so x = 2.

The answer is 2.
'''
    result = extractor.extract(response)

    # Should extract '2' from "The answer is 2"
    assert "2" in result.natural_answers
    # Should NOT extract from "find the value of x"
    assert not any("value of x" in ans.lower() for ans in result.natural_answers)
