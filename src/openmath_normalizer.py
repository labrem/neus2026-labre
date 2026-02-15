"""
OpenMath Knowledge Base Normalizer.

Converts mathematical expressions in cmp_properties and examples fields
to consistent LaTeX format for improved retrieval quality.

Phase 8a: Knowledge Base Normalization (The Pre-Processor)
"""

from __future__ import annotations

import json
import logging
import re
import warnings
from pathlib import Path
from typing import Any

# Suppress SymPy deprecation warnings globally
warnings.filterwarnings("ignore", message="Using non-Expr arguments")
warnings.filterwarnings("ignore", category=DeprecationWarning)

import sympy
from sympy import (
    Abs,
    Add,
    Derivative,
    Eq,
    Function,
    Integral,
    Lambda,
    Mul,
    Pow,
    Rational,
    Symbol,
    acos,
    asin,
    atan,
    cos,
    exp,
    factorial,
    gcd,
    latex,
    lcm,
    ln,
    log,
    oo,
    pi,
    simplify,
    sin,
    sqrt,
    symbols,
    tan,
)
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

import os
import requests

logger = logging.getLogger(__name__)


# =============================================================================
# LLM-Based Normalizer (Fallback for Complex Expressions)
# =============================================================================


class LLMNormalizer:
    """
    LLM-based normalizer for complex mathematical expressions.
    Uses Ollama API to convert expressions that pattern matching cannot handle.
    """

    # Prompt template for expression normalization
    SYSTEM_PROMPT = """You convert mathematical expressions to proper LaTeX notation.
Return ONLY the complete LaTeX expression wrapped in $...$.
Convert the ENTIRE expression including quantifiers, conditions, and equations.
If the input is purely natural language with no mathematical content, return it unchanged.

CRITICAL: Always convert these patterns:
- "for all" or "for each" → \\forall
- "there exists" → \\exists
- "|" (condition separator) → \\mid
- "integers" → \\mathbb{Z}
- "divides" → \\mid (divisibility)
- "subset of" → \\subseteq
- "difference of A and B" → A \\setminus B
- "integral over [a,b]" → \\int_a^b
- "diff(lambda x: f(x))" → \\frac{d}{dx}f(x)
- "a * b" or "a*b" → a \\cdot b
- "cos 2A" → \\cos(2A)
- "sin^2 x" → \\sin^2(x)

IMPORTANT: The ENTIRE expression must be converted to LaTeX, not just part of it.
Example: "for all a,b | a + b = b + a" → "$\\forall a, b \\mid a + b = b + a$"
"""

    FEW_SHOT_EXAMPLES = [
        # Quantifier expressions (critical - must convert "for all" to \forall)
        ("for all a,b | a + b = b + a", "$\\forall a, b \\mid a + b = b + a$"),
        ("for all a,b,c | a*(b+c) = a*b + a*c", "$\\forall a, b, c \\mid a \\cdot (b + c) = a \\cdot b + a \\cdot c$"),
        (
            "for all integers a,b | gcd(a,b) divides a",
            "$\\forall a, b \\in \\mathbb{Z} \\mid \\gcd(a, b) \\mid a$",
        ),
        (
            "for all a < b < c | integral over [a,c] = integral over [a,b] + integral over [b,c]",
            "$\\forall a < b < c \\mid \\int_a^c = \\int_a^b + \\int_b^c$",
        ),
        # Simple expressions
        ("sin(x)^2 + cos(x)^2 = 1", "$\\sin^2(x) + \\cos^2(x) = 1$"),
        ("cos 2A = cos^2 A - sin^2 A", "$\\cos(2A) = \\cos^2(A) - \\sin^2(A)$"),
        ("diff(lambda y:f(y))(x) = f'(x)", "$\\frac{d}{dx}f(x) = f^{\\prime}(x)$"),
        # Set theory
        (
            "the difference of A and B is a subset of A",
            "$A \\setminus B \\subseteq A$",
        ),
        # Natural language (should be unchanged)
        (
            "This symbol represents the natural logarithm function",
            "This symbol represents the natural logarithm function",
        ),
    ]

    def __init__(
        self,
        model: str = "qwen2-math:7b",
        ollama_url: str | None = None,
        timeout: int = 30,
    ):
        """
        Initialize the LLM normalizer.

        Args:
            model: Ollama model to use for normalization
            ollama_url: Ollama API URL (default from OLLAMA_API_URL env var)
            timeout: Request timeout in seconds
        """
        self.model = model
        self.timeout = timeout

        # Get Ollama URL from env or use default
        if ollama_url is None:
            env_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434/v1")
            # Strip /v1 suffix if present - we need the base URL for /api/chat
            self.ollama_url = env_url.rstrip("/v1").rstrip("/")
        else:
            self.ollama_url = ollama_url.rstrip("/")

        self._cache: dict[str, str] = {}

    def normalize(self, expr: str) -> str:
        """
        Convert an expression to LaTeX using LLM.

        Args:
            expr: The expression to normalize

        Returns:
            LaTeX-formatted expression, or original if conversion fails
        """
        if not expr or not expr.strip():
            return expr

        expr = expr.strip()

        # Check cache
        if expr in self._cache:
            logger.debug(f"LLM cache hit: {expr[:50]}...")
            return self._cache[expr]

        try:
            # Build prompt with few-shot examples
            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
            ]

            # Add few-shot examples
            for input_ex, output_ex in self.FEW_SHOT_EXAMPLES:
                messages.append({"role": "user", "content": f"Convert: {input_ex}"})
                messages.append({"role": "assistant", "content": output_ex})

            # Add the actual query
            messages.append({"role": "user", "content": f"Convert: {expr}"})

            # Call Ollama API
            url = f"{self.ollama_url}/api/chat"
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_predict": 512,
                },
            }

            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()

            result = response.json()
            output = result.get("message", {}).get("content", "").strip()

            # Validate output
            if output and self._validate_latex(output):
                self._cache[expr] = output
                logger.debug(f"LLM normalized: {expr[:30]}... -> {output[:30]}...")
                return output
            else:
                logger.debug(f"LLM output invalid, keeping original: {expr[:50]}...")
                self._cache[expr] = expr
                return expr

        except requests.exceptions.RequestException as e:
            logger.warning(f"LLM request failed: {e}")
            return expr
        except Exception as e:
            logger.warning(f"LLM normalization error: {e}")
            return expr

    def _validate_latex(self, output: str) -> bool:
        """
        Basic validation of LaTeX output.

        Checks:
        - Balanced $ delimiters (or no $ for natural language)
        - No obviously malformed LaTeX
        """
        if not output:
            return False

        # Count $ signs
        dollar_count = output.count("$")

        # Natural language (no $) is valid
        if dollar_count == 0:
            return True

        # Must have even number of $ (balanced)
        if dollar_count % 2 != 0:
            return False

        # Check for common malformed patterns
        malformed_patterns = [
            r"\$\s*\$",  # Empty math mode
            r"\\\\\\\\",  # Excessive backslashes
        ]
        for pattern in malformed_patterns:
            if re.search(pattern, output):
                return False

        return True

    def clear_cache(self) -> None:
        """Clear the normalization cache."""
        self._cache.clear()


# Global LLM normalizer instance (lazy-initialized)
_llm_normalizer: LLMNormalizer | None = None


def _get_llm_normalizer() -> LLMNormalizer:
    """Get or create the global LLM normalizer instance."""
    global _llm_normalizer
    if _llm_normalizer is None:
        _llm_normalizer = LLMNormalizer()
    return _llm_normalizer


def _llm_normalize(expr: str) -> str:
    """
    Normalize an expression using LLM fallback.

    Args:
        expr: The expression to normalize

    Returns:
        Normalized expression
    """
    return _get_llm_normalizer().normalize(expr)


def _looks_like_math_expression(text: str) -> bool:
    """
    Heuristic to determine if text contains mathematical content worth normalizing.

    Returns True if text contains:
    - Mathematical operators (=, +, -, *, /, ^, <, >)
    - Function calls (word followed by parentheses)
    - Mathematical keywords (integral, diff, for all, etc.)
    """
    if not text:
        return False

    # Mathematical operators
    if re.search(r"[=+\-*/^<>]", text):
        return True

    # Function calls: word(args)
    if re.search(r"\b\w+\s*\([^)]+\)", text):
        return True

    # Mathematical keywords
    math_keywords = [
        r"\bintegral\b",
        r"\bdiff\b",
        r"\bfor all\b",
        r"\bthere exists\b",
        r"\bsubset\b",
        r"\bdivides\b",
        r"\bgcd\b",
        r"\blcm\b",
        r"\bsin\b",
        r"\bcos\b",
        r"\btan\b",
        r"\bexp\b",
        r"\blog\b",
        r"\bsqrt\b",
    ]
    for pattern in math_keywords:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


# =============================================================================
# Comprehensive Phrase-to-LaTeX Mapping (Deterministic Conversion)
# =============================================================================

# Path to external JSON mapping file (generated by scripts/generate_latex_phrases.py)
LATEX_JSON_PATH = Path(__file__).parent.parent / "data" / "latex.json"

# Default fallback mappings if JSON file is not available
# Note: Use single backslash in raw strings: r"\forall" = literal "\forall"
DEFAULT_PHRASE_TO_LATEX = {
    # === Quantifiers ===
    "for all": r"\forall",
    "for each": r"\forall",
    "for every": r"\forall",
    "for any": r"\forall",
    "there exists": r"\exists",
    "there exist": r"\exists",
    "there is": r"\exists",
    "there are": r"\exists",
    # === Set Membership ===
    "is an element of": r"\in",
    "is a member of": r"\in",
    "belongs to": r"\in",
    "is not an element of": r"\notin",
    "is not in": r"\notin",
    # === Number Sets ===
    "integers": r"\mathbb{Z}",
    "natural numbers": r"\mathbb{N}",
    "real numbers": r"\mathbb{R}",
    "rational numbers": r"\mathbb{Q}",
    "complex numbers": r"\mathbb{C}",
    "positive integers": r"\mathbb{Z}^+",
    "negative integers": r"\mathbb{Z}^-",
    # === Set Operations ===
    "subset of": r"\subseteq",
    "proper subset of": r"\subset",
    "superset of": r"\supseteq",
    "union of": r"\cup",
    "intersection of": r"\cap",
    "the difference of": r"\setminus",
    "set difference": r"\setminus",
    "empty set": r"\emptyset",
    # === Relations ===
    "divides": r"\mid",
    "does not divide": r"\nmid",
    "is congruent to": r"\equiv",
    "is equal to": "=",
    "equals": "=",
    "is not equal to": r"\neq",
    "less than": "<",
    "greater than": ">",
    "less than or equal to": r"\leq",
    "at most": r"\leq",
    "greater than or equal to": r"\geq",
    "at least": r"\geq",
    # === Logic ===
    "if and only if": r"\Leftrightarrow",
    "iff": r"\Leftrightarrow",
    "implies": r"\Rightarrow",
    "is implied by": r"\Leftarrow",
    "such that": r"\mid",
    # === Calculus ===
    "integral of": r"\int",
    "integral over": r"\int",
    "the integral": r"\int",
    "derivative of": r"\frac{d}{dx}",
    "partial derivative": r"\partial",
    "infinity": r"\infty",
    "approaches": r"\to",
    "tends to": r"\to",
    "limit": r"\lim",
    # === Arithmetic ===
    "times": r"\cdot",
    "plus or minus": r"\pm",
    "approximately": r"\approx",
    "proportional to": r"\propto",
}


def _load_phrase_mappings() -> dict[str, str]:
    """
    Load phrase-to-LaTeX mappings from JSON file or use defaults.

    Returns dict mapping English phrases to LaTeX commands.
    """
    mappings = DEFAULT_PHRASE_TO_LATEX.copy()

    # Try to load from JSON file
    if LATEX_JSON_PATH.exists():
        try:
            with open(LATEX_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                json_mappings = data.get("mappings", {})
                # Merge JSON mappings (they take precedence)
                mappings.update(json_mappings)
                logger.debug(f"Loaded {len(json_mappings)} phrase mappings from {LATEX_JSON_PATH}")
        except Exception as e:
            logger.warning(f"Failed to load {LATEX_JSON_PATH}: {e}")

    return mappings


# Load phrase mappings at module load time
PHRASE_TO_LATEX = _load_phrase_mappings()

# Compile regex patterns for phrase replacement (case-insensitive, word boundaries)
# Sort by length (longest first) to avoid partial matches
PHRASE_PATTERNS = [
    (re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE), latex)
    for phrase, latex in sorted(PHRASE_TO_LATEX.items(), key=lambda x: -len(x[0]))
]


def _apply_phrase_to_latex(text: str) -> str:
    """
    Apply deterministic phrase-to-LaTeX conversions.
    Replaces common mathematical English phrases with LaTeX commands.
    """
    result = text
    for pattern, latex in PHRASE_PATTERNS:
        # Use lambda to avoid regex backreference interpretation of backslashes
        result = pattern.sub(lambda m: latex, result)
    return result


# =============================================================================
# Expression Pattern Matchers
# =============================================================================

# Pattern for OpenMath-style lambda expressions: lambda x: expr or x +-> expr
LAMBDA_PATTERN = re.compile(
    r"lambda\s+(\w+)\s*:\s*([^,\)]+(?:\([^)]*\))?)",
    re.IGNORECASE,
)

# Pattern for arrow notation: x +-> expr
ARROW_PATTERN = re.compile(r"(\w+)\s*\+->\s*([^,\)=]+)")

# Pattern for function application: func(args)
FUNC_PATTERN = re.compile(r"(\w+)\s*\(([^)]*)\)")

# Pattern for mathematical expressions in text (numbers, operators, functions)
MATH_EXPR_PATTERN = re.compile(
    r"""
    (?:
        # Function calls with arguments
        (?:sin|cos|tan|exp|log|ln|sqrt|gcd|lcm|factorial|integral|diff|
           arcsin|arccos|arctan|sinh|cosh|tanh|abs|floor|ceiling|mod|
           sum|product|limit|binomial)\s*\([^)]+\)
        |
        # Mathematical expressions with operators
        \b\d+(?:\.\d+)?(?:\s*[\+\-\*/\^]\s*\d+(?:\.\d+)?)+\b
        |
        # Variables with operators: a + b, x^2, etc.
        \b[a-zA-Z](?:\s*[\+\-\*/\^=<>]\s*[a-zA-Z0-9\(\)]+)+
        |
        # Fractions: a/b
        \b\d+\s*/\s*\d+\b
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


# =============================================================================
# OpenMath to Python/SymPy Conversion Mappings
# =============================================================================

OPENMATH_TO_SYMPY = {
    # Basic functions
    "integral": "Integral",
    "diff": "Derivative",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "exp": "exp",
    "ln": "ln",
    "log": "log",
    "sqrt": "sqrt",
    "abs": "Abs",
    "gcd": "gcd",
    "lcm": "lcm",
    "factorial": "factorial",
    "arcsin": "asin",
    "arccos": "acos",
    "arctan": "atan",
    "sinh": "sinh",
    "cosh": "cosh",
    "tanh": "tanh",
    "floor": "floor",
    "ceiling": "ceiling",
    "binomial": "binomial",
    "sum": "Sum",
    "product": "Product",
    "limit": "limit",
    # Constants
    "pi": "pi",
    "e": "E",
    "infinity": "oo",
    "NaN": "nan",
}


# =============================================================================
# Expression Normalizers
# =============================================================================


def _convert_arrow_to_lambda(text: str) -> str:
    """Convert x +-> expr notation to lambda x: expr."""
    return ARROW_PATTERN.sub(r"lambda \1: \2", text)


def _normalize_function_names(text: str) -> str:
    """Convert OpenMath function names to SymPy equivalents."""
    result = text
    for om_name, sympy_name in OPENMATH_TO_SYMPY.items():
        # Match function name followed by (
        pattern = rf"\b{om_name}\s*\("
        replacement = f"{sympy_name}("
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result


def _parse_simple_expression(expr_str: str, evaluate: bool = False) -> sympy.Basic | None:
    """
    Try to parse a simple mathematical expression into SymPy.

    Handles expressions like: a + b, sin(x), gcd(a, b), etc.
    Returns None if parsing fails.

    Args:
        expr_str: The expression to parse
        evaluate: If False, try to preserve structure without evaluating
    """
    # Suppress SymPy warnings during parsing
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _do_parse_expression(expr_str, evaluate)


def _do_parse_expression(expr_str: str, evaluate: bool = False) -> sympy.Basic | None:
    """Internal parsing function."""
    try:
        # Normalize the expression
        expr = expr_str.strip()
        expr = _convert_arrow_to_lambda(expr)
        expr = _normalize_function_names(expr)

        # Define common symbols
        local_dict = {
            "a": Symbol("a"),
            "b": Symbol("b"),
            "c": Symbol("c"),
            "d": Symbol("d"),
            "f": Function("f"),
            "g": Function("g"),
            "h": Function("h"),
            "n": Symbol("n"),
            "m": Symbol("m"),
            "k": Symbol("k"),
            "i": Symbol("i"),
            "j": Symbol("j"),
            "x": Symbol("x"),
            "y": Symbol("y"),
            "z": Symbol("z"),
            "t": Symbol("t"),
            "pi": pi,
            "e": sympy.E,
            "E": sympy.E,
            "I": sympy.I,
            "oo": oo,
            "Integral": Integral,
            "Derivative": Derivative,
            "sin": sin,
            "cos": cos,
            "tan": tan,
            "exp": exp,
            "ln": ln,
            "log": log,
            "sqrt": sqrt,
            "Abs": Abs,
            "gcd": gcd,
            "lcm": lcm,
            "factorial": factorial,
            "asin": asin,
            "acos": acos,
            "atan": atan,
        }

        # Try standard parsing with transformations
        transformations = standard_transformations + (
            implicit_multiplication_application,
            convert_xor,
        )

        parsed = parse_expr(
            expr,
            local_dict=local_dict,
            transformations=transformations,
            evaluate=evaluate,
        )
        return parsed

    except Exception:
        return None


def _expr_to_latex(expr: sympy.Basic) -> str:
    """Convert a SymPy expression to LaTeX string."""
    try:
        return latex(expr)
    except Exception:
        return str(expr)


def _wrap_latex(latex_str: str) -> str:
    """Wrap a LaTeX string in $ delimiters if not already wrapped."""
    latex_str = latex_str.strip()
    if not latex_str.startswith("$"):
        return f"${latex_str}$"
    return latex_str


# =============================================================================
# CMP Properties Normalizer
# =============================================================================


def normalize_cmp_property(cmp_text: str, use_llm_fallback: bool = False) -> str:
    """
    Normalize a CMP property string by converting mathematical expressions to LaTeX.

    Example input:
        "application of integrate followed by differentiate is the identity function,
         that is: diff(lambda y:integral(lambda z:f(z))(y)) = f"

    Example output:
        "application of integrate followed by differentiate is the identity function,
         that is: $\\frac{d}{dy}(\\int f(z) dz) = f$"

    Args:
        cmp_text: The original CMP property text
        use_llm_fallback: If True, use LLM for expressions that pattern matching cannot handle

    Returns:
        Normalized text with LaTeX expressions
    """
    if not cmp_text:
        return cmp_text

    original = cmp_text
    result = cmp_text

    # ==========================================================================
    # STRATEGY 0: Deterministic phrase-to-LaTeX conversion (FAST, NO LLM)
    # ==========================================================================
    # Apply comprehensive phrase-to-LaTeX mappings first
    result = _apply_phrase_to_latex(result)

    # If we have a quantifier expression (starts with \forall or \exists after conversion),
    # wrap the entire expression in $ delimiters and convert operators
    if result.startswith(r"\forall") or result.startswith(r"\exists"):
        # Convert remaining operators
        result = result.replace(" | ", r" \mid ")
        result = result.replace("|", r" \mid ")
        result = result.replace(" * ", r" \cdot ")
        result = result.replace("*", r" \cdot ")
        # Wrap in $ if changed
        if result != original:
            return f"${result}$"

    # Reset if phrase conversion didn't help with the overall structure
    if result == original or not result.startswith("$"):
        result = cmp_text

    # Strategy 1: Look for "that is:" or "i.e." or ":" followed by expression
    colon_patterns = [
        r"that is:\s*(.+)$",
        r"i\.e\.:\s*(.+)$",
        r":\s*([^:]+)$",
    ]

    for pattern in colon_patterns:
        match = re.search(pattern, result, re.IGNORECASE)
        if match:
            expr_part = match.group(1).strip()
            latex_expr = _convert_expression_to_latex(expr_part)
            if latex_expr and latex_expr != expr_part:
                result = result[: match.start(1)] + latex_expr + result[match.end(1) :]
                return result

    # Strategy 2: Look for equation patterns (= sign)
    if "=" in result:
        # Find the part with the equation
        parts = re.split(r"(\s*\|\s*)", result)
        normalized_parts = []
        for part in parts:
            if "=" in part:
                normalized_parts.append(_convert_expression_to_latex(part))
            else:
                normalized_parts.append(part)
        result = "".join(normalized_parts)
        if result != original:
            return result

    # Strategy 3: Look for specific mathematical patterns
    result = _convert_embedded_expressions(result)
    if result != original:
        return result

    # Strategy 4: LLM fallback for unchanged expressions (non-quantifier cases)
    if use_llm_fallback and result == original and _looks_like_math_expression(result):
        llm_result = _llm_normalize(result)
        if llm_result != result:
            return llm_result

    return result


def _convert_expression_to_latex(expr_text: str) -> str:
    """
    Convert a mathematical expression text to LaTeX.

    Handles complex OpenMath notation like:
    - diff(lambda y:integral(lambda z:f(z))(y)) = f
    - integral(x +-> sin(x))
    - gcd(a, b)
    """
    if not expr_text:
        return expr_text

    original = expr_text.strip()
    result = original

    # Handle special integral/derivative patterns
    # Pattern: diff(lambda y:integral(lambda z:f(z))(y)) = f
    integral_diff_match = re.search(
        r"diff\s*\(\s*lambda\s+(\w+)\s*:\s*integral\s*\(\s*lambda\s+(\w+)\s*:\s*(\w+)\((\w+)\)\s*\)\((\w+)\)\s*\)\s*=\s*(\w+)",
        result,
    )
    if integral_diff_match:
        y, z, f_name, inner_var, outer_var, rhs = integral_diff_match.groups()
        # This represents: d/dy (∫ f(z) dz) = f
        latex_expr = rf"\frac{{d}}{{d{y}}}(\int {f_name}({z}) \, d{z}) = {rhs}"
        return _wrap_latex(latex_expr)

    # Pattern: integral(x +-> expr) or integral(lambda x: expr)
    integral_match = re.search(
        r"integral\s*\(\s*(?:lambda\s+)?(\w+)\s*(?:\+->\s*|:\s*)([^)]+)\)",
        result,
    )
    if integral_match:
        var, expr_body = integral_match.groups()
        # Convert expr_body to LaTeX
        inner_expr = _try_parse_and_latex(expr_body)
        if inner_expr:
            latex_expr = rf"\int {inner_expr} \, d{var}"
            # Handle equation if present
            if "=" in result and result.index("=") > integral_match.end():
                eq_part = result[result.index("=") + 1 :].strip()
                rhs_latex = _try_parse_and_latex(eq_part)
                if rhs_latex:
                    return _wrap_latex(f"{latex_expr} = {rhs_latex}")
            return _wrap_latex(latex_expr)

    # Pattern: diff(expr, var) or derivative
    diff_match = re.search(r"diff\s*\(\s*([^,]+)\s*,\s*(\w+)\s*\)", result)
    if diff_match:
        expr_body, var = diff_match.groups()
        inner_expr = _try_parse_and_latex(expr_body)
        if inner_expr:
            latex_expr = rf"\frac{{d}}{{d{var}}}({inner_expr})"
            return _wrap_latex(latex_expr)

    # Pattern: simple function calls like gcd(a, b), sin(x), etc.
    func_match = re.match(
        r"^(\w+)\s*\(([^)]+)\)\s*(?:=\s*(.+))?$", result.strip()
    )
    if func_match:
        func_name, args, rhs = func_match.groups()
        parsed = _try_parse_and_latex(f"{func_name}({args})")
        if parsed:
            if rhs:
                rhs_latex = _try_parse_and_latex(rhs)
                if rhs_latex:
                    return _wrap_latex(f"{parsed} = {rhs_latex}")
            return _wrap_latex(parsed)

    # Pattern: algebraic expressions like a + b = b + a
    if "=" in result:
        parts = result.split("=")
        if len(parts) == 2:
            lhs = _try_parse_and_latex(parts[0])
            rhs = _try_parse_and_latex(parts[1])
            if lhs and rhs:
                return _wrap_latex(f"{lhs} = {rhs}")

    # Fallback: try to parse the whole thing
    parsed = _try_parse_and_latex(result)
    if parsed and parsed != result:
        return _wrap_latex(parsed)

    return original


def _try_parse_and_latex(expr_str: str, evaluate: bool = False) -> str | None:
    """
    Try to parse an expression and convert to LaTeX.

    Args:
        expr_str: The expression string to convert
        evaluate: If False (default), try to preserve structure without evaluating
    """
    if not expr_str:
        return None

    expr_str = expr_str.strip()

    # Manual conversion for common patterns (try this first to avoid evaluation)
    manual_latex = _manual_latex_conversion(expr_str)
    if manual_latex:
        return manual_latex

    # Normalize function names
    expr_str = _normalize_function_names(expr_str)
    expr_str = _convert_arrow_to_lambda(expr_str)

    # Try SymPy parsing with evaluate=False
    parsed = _parse_simple_expression(expr_str, evaluate=evaluate)
    if parsed is not None:
        try:
            return latex(parsed)
        except Exception:
            pass

    return None


def _manual_latex_conversion(expr_str: str) -> str | None:
    """
    Manual LaTeX conversion for patterns that SymPy can't handle.
    Uses pattern matching to preserve structure without evaluation.
    """
    expr = expr_str.strip()

    # Handle sin(x), cos(x), etc.
    trig_match = re.match(r"^(sin|cos|tan|sec|csc|cot)\s*\(([^)]+)\)$", expr)
    if trig_match:
        func, arg = trig_match.groups()
        # Recursively convert argument
        arg_latex = _manual_latex_conversion(arg.strip()) or arg.strip()
        return rf"\{func}({arg_latex})"

    # Handle -sin(x), -cos(x), etc.
    neg_trig_match = re.match(r"^-(sin|cos|tan|sec|csc|cot)\s*\(([^)]+)\)$", expr)
    if neg_trig_match:
        func, arg = neg_trig_match.groups()
        arg_latex = _manual_latex_conversion(arg.strip()) or arg.strip()
        return rf"-\{func}({arg_latex})"

    # Handle gcd(a, b), lcm(a, b) - preserve structure
    binary_func_match = re.match(r"^(gcd|lcm)\s*\(([^,]+),\s*([^)]+)\)$", expr)
    if binary_func_match:
        func, a, b = binary_func_match.groups()
        return rf"\operatorname{{{func}}}({a.strip()}, {b.strip()})"

    # Handle factorial: factorial(n) or n!
    factorial_match = re.match(r"^factorial\s*\(([^)]+)\)$", expr)
    if factorial_match:
        n = factorial_match.group(1).strip()
        return f"{n}!"

    # Handle sqrt
    sqrt_match = re.match(r"^sqrt\s*\(([^)]+)\)$", expr)
    if sqrt_match:
        arg = sqrt_match.group(1)
        return rf"\sqrt{{{arg}}}"

    # Handle simple fractions a/b (with letters)
    frac_match = re.match(r"^([a-zA-Z]+)\s*/\s*([a-zA-Z]+)$", expr)
    if frac_match:
        num, den = frac_match.groups()
        return rf"\frac{{{num}}}{{{den}}}"

    # Handle pi/2, pi/4 etc.
    pi_frac_match = re.match(r"^pi\s*/\s*(\d+)$", expr)
    if pi_frac_match:
        den = pi_frac_match.group(1)
        return rf"\frac{{\pi}}{{{den}}}"

    # Handle simple equations: a + b = b + a (preserve both sides)
    eq_match = re.match(r"^([^=]+)\s*=\s*([^=]+)$", expr)
    if eq_match:
        lhs, rhs = eq_match.groups()
        lhs_latex = _convert_simple_to_latex(lhs.strip())
        rhs_latex = _convert_simple_to_latex(rhs.strip())
        return f"{lhs_latex} = {rhs_latex}"

    return None


def _convert_simple_to_latex(expr: str) -> str:
    """
    Convert simple algebraic expressions to LaTeX.
    Preserves structure without evaluation.
    """
    expr = expr.strip()

    # Handle function calls recursively
    func_call_match = re.match(r"^(\w+)\s*\(([^)]*)\)$", expr)
    if func_call_match:
        func_name, args = func_call_match.groups()
        func_name_lower = func_name.lower()

        # Known functions
        if func_name_lower in {"sin", "cos", "tan", "cot", "sec", "csc"}:
            arg_latex = _convert_simple_to_latex(args.strip())
            return rf"\{func_name_lower}({arg_latex})"
        elif func_name_lower in {"gcd", "lcm"}:
            return rf"\operatorname{{{func_name_lower}}}({args})"
        elif func_name_lower == "factorial":
            return f"({args.strip()})!"
        elif func_name_lower == "sqrt":
            return rf"\sqrt{{{args.strip()}}}"
        elif func_name_lower in {"exp", "ln", "log"}:
            arg_latex = _convert_simple_to_latex(args.strip())
            if func_name_lower == "exp":
                return rf"e^{{{arg_latex}}}"
            else:
                return rf"\{func_name_lower}({arg_latex})"
        else:
            # Generic function
            return rf"\operatorname{{{func_name}}}({args})"

    # Handle power: x^2, sin(x)^2
    power_match = re.match(r"^(.+)\^(\d+)$", expr)
    if power_match:
        base, exp_val = power_match.groups()
        base_latex = _convert_simple_to_latex(base.strip())
        return rf"{base_latex}^{{{exp_val}}}"

    # Handle multiplication: a * b
    if " * " in expr:
        parts = expr.split(" * ")
        latex_parts = [_convert_simple_to_latex(p.strip()) for p in parts]
        return " \\cdot ".join(latex_parts)

    # Handle addition: a + b
    if " + " in expr:
        parts = expr.split(" + ")
        latex_parts = [_convert_simple_to_latex(p.strip()) for p in parts]
        return " + ".join(latex_parts)

    # Handle subtraction: a - b (careful with negation)
    if " - " in expr:
        parts = expr.split(" - ")
        latex_parts = [_convert_simple_to_latex(p.strip()) for p in parts]
        return " - ".join(latex_parts)

    # Handle division: a / b
    if "/" in expr:
        parts = expr.split("/")
        if len(parts) == 2:
            num = _convert_simple_to_latex(parts[0].strip())
            den = _convert_simple_to_latex(parts[1].strip())
            return rf"\frac{{{num}}}{{{den}}}"

    # Return as-is (simple variable or number)
    return expr


def _convert_embedded_expressions(text: str) -> str:
    """
    Find and convert mathematical expressions embedded in natural language text.
    """
    result = text

    # Find patterns like "a + b = b + a" or "gcd(a,b) = 1"
    math_patterns = [
        # Equations with operators
        r"\b([a-zA-Z])\s*([+\-*/^])\s*([a-zA-Z])\s*=\s*([a-zA-Z])\s*\2\s*\1\b",
        # Function calls with result
        r"\b(\w+)\(([^)]+)\)\s*=\s*(\d+|\w+)",
    ]

    for pattern in math_patterns:
        for match in re.finditer(pattern, result):
            expr = match.group(0)
            latex_expr = _try_parse_and_latex(expr)
            if latex_expr:
                result = result.replace(expr, _wrap_latex(latex_expr))

    return result


# =============================================================================
# Examples Normalizer
# =============================================================================


def normalize_example(example_text: str, use_llm_fallback: bool = False) -> str:
    """
    Normalize an example string by converting mathematical expressions to LaTeX.

    Example input:
        "An example which represents the equation: integral(x +-> sin(x)) w.r.t. x = x +-> -cos(x)"

    Example output:
        "An example which represents the equation: $\\int \\sin(x) \\, dx = -\\cos(x)$"

    Args:
        example_text: The original example text
        use_llm_fallback: If True, use LLM for expressions that pattern matching cannot handle

    Returns:
        Normalized text with LaTeX expressions
    """
    if not example_text:
        return example_text

    original = example_text
    result = example_text

    # Strategy 1: Look for "equation:" or "represents:" pattern
    colon_patterns = [
        r"equation:\s*(.+)$",
        r"represents:\s*(.+)$",
        r"example:\s*(.+)$",
    ]

    for pattern in colon_patterns:
        match = re.search(pattern, result, re.IGNORECASE)
        if match:
            expr_part = match.group(1).strip()
            # Remove trailing punctuation
            expr_part = re.sub(r"[.;,]$", "", expr_part)
            latex_expr = _convert_example_expression(expr_part)
            if latex_expr and latex_expr != expr_part:
                result = result[: match.start(1)] + latex_expr
                return result

    # Strategy 2: Look for integral/derivative patterns anywhere
    result = _convert_example_expression(result)
    if result != original:
        return result

    # Strategy 3: LLM fallback for unchanged expressions
    if use_llm_fallback and result == original and _looks_like_math_expression(result):
        llm_result = _llm_normalize(result)
        if llm_result != result:
            return llm_result

    return result


def _convert_example_expression(expr_text: str) -> str:
    """
    Convert an example expression to LaTeX.

    Handles patterns like:
    - integral(x +-> sin(x)) w.r.t. x = x +-> -cos(x)
    - gcd(6,9) = 3
    - sin(pi/2) = 1
    """
    if not expr_text:
        return expr_text

    original = expr_text
    result = original

    # Handle integral with "w.r.t." pattern
    wrt_match = re.search(
        r"integral\s*\(\s*(?:lambda\s+)?(\w+)\s*(?:\+->\s*|:\s*)([^)]+)\)\s*w\.r\.t\.\s*(\w+)\s*=\s*(.+)",
        result,
        re.IGNORECASE,
    )
    if wrt_match:
        var1, integrand, var2, antiderivative = wrt_match.groups()
        integrand_latex = _try_parse_and_latex(integrand.strip())
        antideriv_latex = _convert_lambda_result(antiderivative.strip())

        if integrand_latex or antideriv_latex:
            int_latex = integrand_latex if integrand_latex else integrand
            ad_latex = antideriv_latex if antideriv_latex else antiderivative
            latex_expr = rf"\int {int_latex} \, d{var2} = {ad_latex}"
            return _wrap_latex(latex_expr)

    # Handle simple integral pattern
    integral_match = re.search(
        r"integral\s*\(\s*(?:lambda\s+)?(\w+)\s*(?:\+->\s*|:\s*)([^)]+)\)",
        result,
        re.IGNORECASE,
    )
    if integral_match:
        var, integrand = integral_match.groups()
        integrand_latex = _try_parse_and_latex(integrand.strip())
        if integrand_latex:
            prefix = result[: integral_match.start()]
            suffix = result[integral_match.end() :]
            latex_expr = rf"\int {integrand_latex} \, d{var}"
            return prefix + _wrap_latex(latex_expr) + suffix

    # Handle function = result pattern like "gcd(6,9) = 3"
    func_eq_match = re.match(
        r"^(\w+)\s*\(([^)]+)\)\s*=\s*(\d+)(.*)$", result.strip()
    )
    if func_eq_match:
        func_name, args, val, suffix = func_eq_match.groups()
        parsed = _try_parse_and_latex(f"{func_name}({args})")
        if parsed:
            return _wrap_latex(f"{parsed} = {val}") + suffix

    # Handle expressions with numbers following (like "gcd(6,9) = 3 6 9 3")
    # This appears to be a formatting artifact - extract just the equation
    func_with_noise = re.match(
        r"^(\w+)\s*\(([^)]+)\)\s*=\s*(\d+)\s+\d+.*$", result.strip()
    )
    if func_with_noise:
        func_name, args, val = func_with_noise.groups()
        parsed = _try_parse_and_latex(f"{func_name}({args})")
        if parsed:
            return _wrap_latex(f"{parsed} = {val}")

    # Fallback: try to convert the whole expression
    latex_expr = _convert_expression_to_latex(result)
    if latex_expr != original:
        return latex_expr

    return original


def _convert_lambda_result(expr_text: str) -> str | None:
    """
    Convert lambda result notation like "x +-> -cos(x)" to LaTeX.
    """
    if not expr_text:
        return None

    # Handle arrow notation: x +-> -cos(x)
    arrow_match = re.match(r"^\s*\w+\s*\+->\s*(.+)$", expr_text)
    if arrow_match:
        result_expr = arrow_match.group(1).strip()
        return _try_parse_and_latex(result_expr)

    return _try_parse_and_latex(expr_text)


# =============================================================================
# Main Normalizer Class
# =============================================================================


class OpenMathNormalizer:
    """
    Normalizes OpenMath Knowledge Base by converting mathematical expressions
    in cmp_properties and examples fields to LaTeX format.
    """

    def __init__(
        self,
        kb_path: str | Path | None = None,
        use_llm_fallback: bool = False,
        llm_model: str = "qwen2-math:7b",
    ):
        """
        Initialize the normalizer.

        Args:
            kb_path: Path to the OpenMath JSON knowledge base.
                    Defaults to data/openmath.json in project root.
            use_llm_fallback: If True, use LLM for expressions that pattern matching cannot handle.
            llm_model: Ollama model to use for LLM normalization.
        """
        if kb_path is None:
            # Find project root
            self.project_root = Path(__file__).parent.parent
            self.kb_path = self.project_root / "data" / "openmath.json"
        else:
            self.kb_path = Path(kb_path)
            self.project_root = self.kb_path.parent.parent

        self.use_llm_fallback = use_llm_fallback
        self.llm_model = llm_model

        # Initialize LLM normalizer if needed
        if use_llm_fallback:
            global _llm_normalizer
            _llm_normalizer = LLMNormalizer(model=llm_model)

        self.knowledge_base: dict[str, Any] = {}
        self.stats = {
            "total_symbols": 0,
            "cmp_normalized": 0,
            "cmp_normalized_llm": 0,
            "cmp_unchanged": 0,
            "cmp_failed": 0,
            "examples_normalized": 0,
            "examples_normalized_llm": 0,
            "examples_unchanged": 0,
            "examples_failed": 0,
        }

    def load(self) -> None:
        """Load the knowledge base from JSON."""
        logger.info(f"Loading knowledge base from {self.kb_path}")
        with open(self.kb_path, "r", encoding="utf-8") as f:
            self.knowledge_base = json.load(f)
        logger.info(f"Loaded knowledge base with {len(self.knowledge_base.get('symbols', {}))} symbols")

    def normalize(self) -> dict[str, Any]:
        """
        Normalize all cmp_properties and examples in the knowledge base.

        Returns:
            The normalized knowledge base dictionary.
        """
        if not self.knowledge_base:
            self.load()

        symbols = self.knowledge_base.get("symbols", {})
        self.stats["total_symbols"] = len(symbols)

        logger.info(f"Normalizing {len(symbols)} symbols...")

        for symbol_id, symbol_data in symbols.items():
            self._normalize_symbol(symbol_id, symbol_data)

        logger.info(f"Normalization complete. Stats: {self.stats}")
        return self.knowledge_base

    def _normalize_symbol(self, symbol_id: str, symbol_data: dict) -> None:
        """
        Normalize a single symbol's cmp_properties and examples.

        Creates new fields with '_normalized' suffix, preserving originals:
        - description -> description_normalized
        - cmp_properties -> cmp_properties_normalized
        - examples -> examples_normalized
        """
        # Copy and normalize description
        description = symbol_data.get("description", "")
        if description:
            # For now, description is kept as-is (no normalization needed)
            # but we create the normalized field for consistency
            symbol_data["description_normalized"] = description

        # Copy and normalize cmp_properties
        cmp_props = symbol_data.get("cmp_properties", [])
        if cmp_props:
            normalized_cmps = []
            for cmp in cmp_props:
                try:
                    # First try pattern-based normalization
                    normalized = normalize_cmp_property(cmp, use_llm_fallback=False)
                    if normalized != cmp:
                        self.stats["cmp_normalized"] += 1
                        logger.debug(f"[{symbol_id}] CMP (pattern): {cmp[:50]}... -> {normalized[:50]}...")
                    elif self.use_llm_fallback:
                        # Try LLM fallback if pattern-based didn't change it
                        normalized = normalize_cmp_property(cmp, use_llm_fallback=True)
                        if normalized != cmp:
                            self.stats["cmp_normalized_llm"] += 1
                            logger.debug(f"[{symbol_id}] CMP (LLM): {cmp[:50]}... -> {normalized[:50]}...")
                        else:
                            self.stats["cmp_unchanged"] += 1
                    else:
                        self.stats["cmp_unchanged"] += 1
                    normalized_cmps.append(normalized)
                except Exception as e:
                    logger.warning(f"[{symbol_id}] Failed to normalize CMP: {cmp[:50]}... Error: {e}")
                    normalized_cmps.append(cmp)  # Keep original on failure
                    self.stats["cmp_failed"] += 1
            # Store in new field, preserving original
            symbol_data["cmp_properties_normalized"] = normalized_cmps

        # Copy and normalize examples
        examples = symbol_data.get("examples", [])
        if examples:
            normalized_examples = []
            for example in examples:
                try:
                    # First try pattern-based normalization
                    normalized = normalize_example(example, use_llm_fallback=False)
                    if normalized != example:
                        self.stats["examples_normalized"] += 1
                        logger.debug(f"[{symbol_id}] Example (pattern): {example[:50]}... -> {normalized[:50]}...")
                    elif self.use_llm_fallback:
                        # Try LLM fallback if pattern-based didn't change it
                        normalized = normalize_example(example, use_llm_fallback=True)
                        if normalized != example:
                            self.stats["examples_normalized_llm"] += 1
                            logger.debug(f"[{symbol_id}] Example (LLM): {example[:50]}... -> {normalized[:50]}...")
                        else:
                            self.stats["examples_unchanged"] += 1
                    else:
                        self.stats["examples_unchanged"] += 1
                    normalized_examples.append(normalized)
                except Exception as e:
                    logger.warning(f"[{symbol_id}] Failed to normalize example: {example[:50]}... Error: {e}")
                    normalized_examples.append(example)  # Keep original on failure
                    self.stats["examples_failed"] += 1
            # Store in new field, preserving original
            symbol_data["examples_normalized"] = normalized_examples

    def save(self, output_path: str | Path | None = None) -> Path:
        """
        Save the normalized knowledge base to JSON.

        Args:
            output_path: Output path. Defaults to overwriting the original file.

        Returns:
            Path to the saved file.
        """
        if output_path is None:
            output_path = self.kb_path
        else:
            output_path = Path(output_path)

        logger.info(f"Saving normalized knowledge base to {output_path}")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.knowledge_base, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved normalized knowledge base ({output_path.stat().st_size / 1024:.1f} KB)")
        return output_path

    def get_stats(self) -> dict:
        """Get normalization statistics."""
        return self.stats.copy()

    def get_comparison_samples(self, n: int = 5) -> list[dict]:
        """
        Get sample symbols showing original vs normalized content.

        Args:
            n: Number of samples to return.

        Returns:
            List of dictionaries with symbol info and normalization results.
        """
        samples = []
        symbols = self.knowledge_base.get("symbols", {})

        # Find symbols with cmp_properties or examples
        for symbol_id, symbol_data in symbols.items():
            if samples and len(samples) >= n:
                break

            cmp_props = symbol_data.get("cmp_properties", [])
            examples = symbol_data.get("examples", [])

            if cmp_props or examples:
                samples.append(
                    {
                        "symbol_id": symbol_id,
                        "name": symbol_data.get("name", ""),
                        "description": symbol_data.get("description", "")[:100],
                        "cmp_properties": cmp_props,
                        "examples": examples,
                    }
                )

        return samples


# =============================================================================
# CLI Entry Point
# =============================================================================


def main():
    """Main entry point for the normalizer CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Normalize OpenMath Knowledge Base - convert expressions to LaTeX"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=None,
        help="Input JSON path (default: data/openmath.json)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output JSON path (default: overwrite input)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print samples without saving",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LLM fallback for expressions that pattern matching cannot handle",
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        default="qwen2-math:7b",
        help="Ollama model for LLM normalization (default: qwen2-math:7b)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Create normalizer
    normalizer = OpenMathNormalizer(
        kb_path=args.input,
        use_llm_fallback=args.use_llm,
        llm_model=args.llm_model,
    )

    # Load and normalize
    normalizer.load()
    normalizer.normalize()

    # Show samples
    print("\n" + "=" * 70)
    print("SAMPLE NORMALIZATIONS")
    print("=" * 70)

    samples = normalizer.get_comparison_samples(n=5)
    for sample in samples:
        print(f"\n--- {sample['symbol_id']} ---")
        if sample["cmp_properties"]:
            print(f"CMP: {sample['cmp_properties']}")
        if sample["examples"]:
            print(f"Examples: {sample['examples']}")

    # Show stats
    print("\n" + "=" * 70)
    print("NORMALIZATION STATISTICS")
    print("=" * 70)
    stats = normalizer.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # Save unless dry-run
    if not args.dry_run:
        output_path = normalizer.save(args.output)
        print(f"\nSaved to: {output_path}")
    else:
        print("\n[DRY-RUN] No changes saved.")


if __name__ == "__main__":
    main()
