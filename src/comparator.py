"""
Answer Comparator for Mathematical Expressions.

Compares LLM-generated answers against ground truth using
symbolic computation for mathematical equivalence.
"""

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from typing import Any
from fractions import Fraction

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Default tolerance from environment or fallback
DEFAULT_TOLERANCE = float(os.getenv("COMPARATOR_TOLERANCE", "1e-9"))

# Try to import sympy for symbolic comparison
try:
    import sympy
    from sympy import sympify, simplify, Eq, N
    from sympy.parsing.latex import parse_latex
    SYMPY_AVAILABLE = True
except ImportError:
    SYMPY_AVAILABLE = False
    logger.warning("SymPy not available, falling back to string comparison")


@dataclass
class ComparisonResult:
    """Result of comparing two answers."""

    predicted: str
    ground_truth: str
    is_equivalent: bool
    comparison_method: str
    normalized_predicted: str = ""
    normalized_ground_truth: str = ""
    error_message: str = ""


class AnswerComparator:
    """Compares mathematical answers for equivalence."""

    # LaTeX to Python symbol mappings
    # Note: Nested patterns (frac, sqrt) handled specially via iteration
    LATEX_REPLACEMENTS = [
        (r'\\pi', 'pi'),
        (r'\\infty', 'oo'),
        (r'\\cdot', '*'),
        (r'\\times', '*'),
        (r'\\div', '/'),
        (r'\\pm', '+-'),
        (r'\\le', '<='),
        (r'\\ge', '>='),
        (r'\\ne', '!='),
        (r'\\neq', '!='),
        (r'\^', '**'),
        (r'\\left', ''),
        (r'\\right', ''),
        (r'\\[,;\s]+', ' '),
    ]

    # Patterns that need iterative application for nested structures
    NESTED_LATEX_PATTERNS = [
        # Match \frac with balanced braces (handles nesting via iteration)
        (r'\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}', r'((\1)/(\2))'),
        # Match \sqrt with balanced braces
        (r'\\sqrt\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}', r'sqrt(\1)'),
        # Match \sqrt[n]{x} with balanced braces
        (r'\\sqrt\[(\d+)\]\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}', r'((\2))**(1/(\1))'),
    ]

    # Final cleanup patterns (applied last)
    FINAL_CLEANUP_PATTERNS = [
        (r'\{', '('),
        (r'\}', ')'),
    ]

    def __init__(self, tolerance: float = 1e-9):
        """
        Initialize the comparator.

        Args:
            tolerance: Numerical tolerance for floating point comparison
        """
        self.tolerance = tolerance

    def compare(
        self,
        predicted: str | Any,
        ground_truth: str | Any,
    ) -> ComparisonResult:
        """
        Compare predicted answer against ground truth.

        Args:
            predicted: The LLM-generated answer
            ground_truth: The correct answer from benchmark

        Returns:
            ComparisonResult with equivalence determination
        """
        # Convert to strings if needed
        pred_str = str(predicted).strip() if predicted is not None else ""
        truth_str = str(ground_truth).strip() if ground_truth is not None else ""

        result = ComparisonResult(
            predicted=pred_str,
            ground_truth=truth_str,
            is_equivalent=False,
            comparison_method="none",
        )

        if not pred_str or not truth_str:
            result.error_message = "Empty answer"
            return result

        # Try comparison methods in order of reliability
        methods = [
            ("exact_match", self._exact_match),
            ("numeric", self._numeric_compare),
            ("fraction", self._fraction_compare),
            ("set_compare", self._set_compare),  # For unordered multi-value answers
            ("symbolic", self._symbolic_compare),
            ("normalized_string", self._normalized_string_compare),
        ]

        for method_name, method_func in methods:
            try:
                is_equivalent, normalized_pred, normalized_truth = method_func(
                    pred_str, truth_str
                )
                if is_equivalent:
                    result.is_equivalent = True
                    result.comparison_method = method_name
                    result.normalized_predicted = normalized_pred
                    result.normalized_ground_truth = normalized_truth
                    logger.debug(f"Match found using {method_name}")
                    return result
            except Exception as e:
                logger.debug(f"Method {method_name} failed: {e}")
                continue

        result.comparison_method = "no_match"
        return result

    def _exact_match(
        self, predicted: str, ground_truth: str
    ) -> tuple[bool, str, str]:
        """
        Check for exact string match.

        Returns:
            Tuple of (is_equivalent, normalized_predicted, normalized_ground_truth)
        """
        return (predicted == ground_truth, predicted, ground_truth)

    def _numeric_compare(
        self, predicted: str, ground_truth: str
    ) -> tuple[bool, str, str]:
        """
        Compare as floating point numbers.

        Returns:
            Tuple of (is_equivalent, normalized_predicted, normalized_ground_truth)
        """
        pred_num = self._parse_number(predicted)
        truth_num = self._parse_number(ground_truth)

        if pred_num is None or truth_num is None:
            return (False, "", "")

        # Check if close enough
        if abs(pred_num - truth_num) <= self.tolerance:
            return (True, str(pred_num), str(truth_num))

        # Also check relative tolerance for large numbers
        if truth_num != 0:
            rel_diff = abs((pred_num - truth_num) / truth_num)
            if rel_diff <= self.tolerance:
                return (True, str(pred_num), str(truth_num))

        return (False, str(pred_num), str(truth_num))

    def _fraction_compare(
        self, predicted: str, ground_truth: str
    ) -> tuple[bool, str, str]:
        """
        Compare as fractions.

        Returns:
            Tuple of (is_equivalent, normalized_predicted, normalized_ground_truth)
        """
        pred_frac = self._parse_fraction(predicted)
        truth_frac = self._parse_fraction(ground_truth)

        if pred_frac is None or truth_frac is None:
            return (False, "", "")

        is_equal = pred_frac == truth_frac
        return (is_equal, str(pred_frac), str(truth_frac))

    def _set_compare(
        self, predicted: str, ground_truth: str
    ) -> tuple[bool, str, str]:
        """
        Compare as unordered sets of values.

        Handles multi-value answers like polynomial roots where order doesn't matter.
        Examples: "-2, 2" vs "2, -2", "{1, 2, 3}" vs "{3, 2, 1}"

        Returns:
            Tuple of (is_equivalent, normalized_predicted, normalized_ground_truth)
        """
        # Check if this looks like a multi-value answer
        separators = [',', ';', ' and ']

        pred_values = None
        truth_values = None

        for sep in separators:
            if sep in predicted and sep in ground_truth:
                pred_values = [v.strip() for v in predicted.split(sep)]
                truth_values = [v.strip() for v in ground_truth.split(sep)]
                break
            elif sep in predicted or sep in ground_truth:
                # Try this separator for whichever has it
                if sep in predicted:
                    pred_values = [v.strip() for v in predicted.split(sep)]
                if sep in ground_truth:
                    truth_values = [v.strip() for v in ground_truth.split(sep)]

        # If no multi-value pattern detected, not applicable
        if pred_values is None and truth_values is None:
            return (False, "", "")

        # Handle single vs multi value case
        if pred_values is None:
            pred_values = [predicted.strip()]
        if truth_values is None:
            truth_values = [ground_truth.strip()]

        # Clean up values (remove braces, brackets, etc.)
        def clean_value(v: str) -> str:
            v = v.strip()
            v = re.sub(r'^[\[\{\(]+|[\]\}\)]+$', '', v)  # Remove enclosing brackets
            v = re.sub(r'^\$+|\$+$', '', v)  # Remove LaTeX delimiters
            v = v.strip()
            return v

        pred_values = [clean_value(v) for v in pred_values if clean_value(v)]
        truth_values = [clean_value(v) for v in truth_values if clean_value(v)]

        # Must have same number of values
        if len(pred_values) != len(truth_values):
            return (False, "", "")

        # Try to match each predicted value to a truth value
        # Using numeric/symbolic comparison for each element
        matched_truth = [False] * len(truth_values)

        for pred_val in pred_values:
            found_match = False
            for i, truth_val in enumerate(truth_values):
                if matched_truth[i]:
                    continue

                # Try various comparison methods for individual values
                # Exact match
                if pred_val == truth_val:
                    matched_truth[i] = True
                    found_match = True
                    break

                # Numeric comparison
                pred_num = self._parse_number(pred_val)
                truth_num = self._parse_number(truth_val)
                if pred_num is not None and truth_num is not None:
                    if abs(pred_num - truth_num) <= self.tolerance:
                        matched_truth[i] = True
                        found_match = True
                        break

                # Symbolic comparison with improved parsing
                if SYMPY_AVAILABLE:
                    pred_sym = None
                    truth_sym = None

                    # Try our LaTeX conversion first
                    try:
                        pred_expr = self._latex_to_sympy_string(pred_val)
                        pred_sym = sympify(pred_expr)
                    except Exception:
                        pass

                    try:
                        truth_expr = self._latex_to_sympy_string(truth_val)
                        truth_sym = sympify(truth_expr)
                    except Exception:
                        pass

                    # Fallback to parse_latex for complex LaTeX
                    if pred_sym is None:
                        pred_sym = self._try_parse_latex(pred_val)
                    if truth_sym is None:
                        truth_sym = self._try_parse_latex(truth_val)

                    if pred_sym is not None and truth_sym is not None:
                        try:
                            # Try simplification
                            diff = simplify(pred_sym - truth_sym)
                            if diff == 0:
                                matched_truth[i] = True
                                found_match = True
                                break

                            # Try expand + simplify
                            diff_expanded = simplify(sympy.expand(pred_sym) - sympy.expand(truth_sym))
                            if diff_expanded == 0:
                                matched_truth[i] = True
                                found_match = True
                                break

                            # Try numerical evaluation
                            pred_val_num = complex(N(pred_sym))
                            truth_val_num = complex(N(truth_sym))
                            if abs(pred_val_num - truth_val_num) <= self.tolerance:
                                matched_truth[i] = True
                                found_match = True
                                break
                        except Exception:
                            pass

            if not found_match:
                return (False, "", "")

        # All values matched
        pred_sorted = sorted(pred_values)
        truth_sorted = sorted(truth_values)
        return (True, ", ".join(pred_sorted), ", ".join(truth_sorted))

    def _symbolic_compare(
        self, predicted: str, ground_truth: str
    ) -> tuple[bool, str, str]:
        """
        Compare using SymPy symbolic computation.

        Uses multiple strategies:
        1. Convert LaTeX to SymPy string and sympify
        2. Fallback to parse_latex for complex expressions
        3. Numerical evaluation for verification

        Returns:
            Tuple of (is_equivalent, normalized_predicted, normalized_ground_truth)
        """
        if not SYMPY_AVAILABLE:
            return (False, "", "")

        pred_sym = None
        truth_sym = None

        # Strategy 1: Use our LaTeX-to-SymPy string conversion
        pred_expr = self._latex_to_sympy_string(predicted)
        truth_expr = self._latex_to_sympy_string(ground_truth)

        try:
            pred_sym = sympify(pred_expr)
            truth_sym = sympify(truth_expr)
        except Exception as e:
            logger.debug(f"sympify failed for converted strings: {e}")

        # Strategy 2: Fallback to parse_latex if sympify failed
        if pred_sym is None:
            pred_sym = self._try_parse_latex(predicted)
        if truth_sym is None:
            truth_sym = self._try_parse_latex(ground_truth)

        if pred_sym is None or truth_sym is None:
            return (False, pred_expr, truth_expr)

        try:
            # Try simplification
            diff = simplify(pred_sym - truth_sym)
            if diff == 0:
                return (True, str(pred_sym), str(truth_sym))

            # Try expand then simplify (catches more algebraic equivalences)
            diff_expanded = simplify(sympy.expand(pred_sym) - sympy.expand(truth_sym))
            if diff_expanded == 0:
                return (True, str(pred_sym), str(truth_sym))

            # Try trigsimp for trigonometric expressions
            try:
                diff_trig = sympy.trigsimp(pred_sym - truth_sym)
                if diff_trig == 0:
                    return (True, str(pred_sym), str(truth_sym))
            except Exception:
                pass

            # Try numerical evaluation
            pred_val = complex(N(pred_sym))
            truth_val = complex(N(truth_sym))

            if abs(pred_val - truth_val) <= self.tolerance:
                return (True, str(pred_sym), str(truth_sym))

        except Exception as e:
            logger.debug(f"Symbolic comparison failed: {e}")

        return (False, str(pred_sym) if pred_sym else pred_expr,
                str(truth_sym) if truth_sym else truth_expr)

    def _normalized_string_compare(
        self, predicted: str, ground_truth: str
    ) -> tuple[bool, str, str]:
        """
        Compare normalized string representations.

        Returns:
            Tuple of (is_equivalent, normalized_predicted, normalized_ground_truth)
        """
        pred_norm = self._normalize_string(predicted)
        truth_norm = self._normalize_string(ground_truth)

        return (pred_norm == truth_norm, pred_norm, truth_norm)

    def _parse_number(self, s: str) -> float | None:
        """
        Parse a string as a number.

        Args:
            s: String to parse

        Returns:
            Float value or None if not parseable
        """
        # Clean the string
        s = self._normalize_string(s)

        # Try direct conversion
        try:
            return float(s)
        except ValueError:
            pass

        # Try fraction notation (a/b)
        match = re.match(r'^(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)$', s)
        if match:
            try:
                return float(match.group(1)) / float(match.group(2))
            except (ValueError, ZeroDivisionError):
                pass

        # Try evaluating simple expressions
        try:
            # Only allow safe characters
            if re.match(r'^[\d\.\+\-\*/\(\)\s]+$', s):
                return float(eval(s))
        except Exception:
            pass

        return None

    def _parse_fraction(self, s: str) -> Fraction | None:
        """
        Parse a string as a fraction.

        Args:
            s: String to parse

        Returns:
            Fraction or None if not parseable
        """
        s = self._normalize_string(s)

        # Try direct Fraction parsing
        try:
            return Fraction(s).limit_denominator(10000)
        except ValueError:
            pass

        # Try \\frac{a}{b} notation
        match = re.search(r'\\frac\{(\d+)\}\{(\d+)\}', s)
        if match:
            try:
                return Fraction(int(match.group(1)), int(match.group(2)))
            except (ValueError, ZeroDivisionError):
                pass

        # Try a/b notation
        match = re.match(r'^(-?\d+)\s*/\s*(-?\d+)$', s)
        if match:
            try:
                return Fraction(int(match.group(1)), int(match.group(2)))
            except (ValueError, ZeroDivisionError):
                pass

        # Try converting float to fraction
        try:
            return Fraction(float(s)).limit_denominator(10000)
        except ValueError:
            pass

        return None

    def _latex_to_sympy_string(self, s: str) -> str:
        """
        Convert LaTeX notation to SymPy-parseable string.

        Handles nested LaTeX expressions by iteratively applying
        transformations until no more matches are found.

        Args:
            s: String potentially containing LaTeX

        Returns:
            Cleaned string for sympify
        """
        result = s

        # Remove $ signs first
        result = result.replace('$', '')

        # Apply simple replacements
        for pattern, replacement in self.LATEX_REPLACEMENTS:
            result = re.sub(pattern, replacement, result)

        # Apply nested patterns iteratively (handles \frac{\frac{1}{2}}{3} etc.)
        # Keep applying until no more changes occur
        max_iterations = 10  # Prevent infinite loops
        for _ in range(max_iterations):
            changed = False
            for pattern, replacement in self.NESTED_LATEX_PATTERNS:
                new_result = re.sub(pattern, replacement, result)
                if new_result != result:
                    changed = True
                    result = new_result
            if not changed:
                break

        # Final cleanup: remaining braces become parentheses
        for pattern, replacement in self.FINAL_CLEANUP_PATTERNS:
            result = re.sub(pattern, replacement, result)

        # Clean whitespace
        result = ' '.join(result.split())

        return result

    def _try_parse_latex(self, s: str) -> Any | None:
        """
        Try to parse a string using SymPy's LaTeX parser.

        This is more robust for complex expressions but slower.

        Args:
            s: String containing LaTeX

        Returns:
            SymPy expression or None if parsing failed
        """
        if not SYMPY_AVAILABLE:
            return None

        try:
            # Clean the string for parse_latex
            cleaned = s.replace('$', '').strip()
            if not cleaned:
                return None
            return parse_latex(cleaned)
        except Exception as e:
            logger.debug(f"parse_latex failed: {e}")
            return None

    def _normalize_string(self, s: str) -> str:
        """
        Normalize a string for comparison.

        Args:
            s: String to normalize

        Returns:
            Normalized string
        """
        # Remove LaTeX delimiters
        s = re.sub(r'\$+', '', s)

        # Remove backslashes
        s = s.replace('\\', '')

        # Remove whitespace
        s = ''.join(s.split())

        # Convert to lowercase
        s = s.lower()

        return s


def create_comparator(tolerance: float | None = None) -> AnswerComparator:
    """
    Factory function to create an answer comparator.

    Args:
        tolerance: Numerical tolerance for floating point comparison.
                   If None, uses COMPARATOR_TOLERANCE from .env (default: 1e-9)

    Returns:
        Configured AnswerComparator instance
    """
    if tolerance is None:
        tolerance = DEFAULT_TOLERANCE
    return AnswerComparator(tolerance=tolerance)
