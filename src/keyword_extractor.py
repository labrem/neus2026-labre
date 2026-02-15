"""
Keyword Extractor for Mathematical Problems.

Extracts mathematical keywords from problem statements for
retrieval of relevant OpenMath symbols.
"""

from __future__ import annotations

import json
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of keyword extraction from a problem."""

    problem: str
    keywords: list[str] = field(default_factory=list)
    operators: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)

    def all_terms(self) -> list[str]:
        """Return all extracted terms combined."""
        return self.keywords + self.operators + self.functions + self.phrases


class KeywordExtractor:
    """Extracts mathematical keywords from problem text."""

    # Mathematical function patterns
    MATH_FUNCTIONS = {
        # Trigonometric
        "sin", "cos", "tan", "cot", "sec", "csc",
        "arcsin", "arccos", "arctan", "arccot", "arcsec", "arccsc",
        "sinh", "cosh", "tanh", "coth", "sech", "csch",
        # Logarithmic/Exponential
        "log", "ln", "exp",
        # Arithmetic
        "gcd", "lcm", "mod", "abs", "sqrt",
        # Calculus
        "lim", "limit", "diff", "derivative", "integral", "integrate",
        # Other
        "floor", "ceil", "round", "factorial",
    }

    # Mathematical operators (single and multi-character)
    OPERATORS = {
        "+", "-", "*", "/", "^", "**", "=", "==",
        "!=", "<>", "<", ">", "<=", ">=",
        "!", "%",
    }

    # Unicode mathematical symbols
    UNICODE_OPERATORS = {
        "≤": "<=",
        "≥": ">=",
        "≠": "!=",
        "÷": "/",
        "×": "*",
        "−": "-",
        "π": "pi",
        "∞": "infinity",
        "√": "sqrt",
        "∫": "integral",
        "∂": "partial",
        "∑": "sum",
        "∏": "product",
        "∈": "in",
        "∉": "notin",
        "∀": "forall",
        "∃": "exists",
        "∧": "and",
        "∨": "or",
        "¬": "not",
    }

    # LaTeX math symbols -> keywords mapping
    # These convert LaTeX commands to extractable math terms
    LATEX_SYMBOLS = {
        # Rounding functions
        r"\lceil": " ceiling ",
        r"\rceil": " ceiling ",
        r"\lfloor": " floor ",
        r"\rfloor": " floor ",
        # Fractions and roots
        r"\frac": " fraction ",
        r"\sqrt": " sqrt ",
        r"\cbrt": " cbrt ",
        # Trig functions
        r"\sin": " sin ",
        r"\cos": " cos ",
        r"\tan": " tan ",
        r"\cot": " cot ",
        r"\sec": " sec ",
        r"\csc": " csc ",
        r"\arcsin": " arcsin ",
        r"\arccos": " arccos ",
        r"\arctan": " arctan ",
        r"\sinh": " sinh ",
        r"\cosh": " cosh ",
        r"\tanh": " tanh ",
        # Log/exp
        r"\ln": " ln ",
        r"\log": " log ",
        r"\exp": " exp ",
        # Summation/product
        r"\sum": " sum ",
        r"\prod": " product ",
        r"\int": " integral ",
        # Number theory
        r"\gcd": " gcd ",
        r"\lcm": " lcm ",
        r"\mod": " mod ",
        r"\bmod": " mod ",
        r"\pmod": " mod ",
        # Other
        r"\lim": " limit ",
        r"\infty": " infinity ",
        r"\pm": " plus_minus ",
        r"\mp": " minus_plus ",
        r"\cdot": " times ",
        r"\times": " times ",
        r"\div": " divide ",
        # Complex numbers
        r"\Re": " real ",
        r"\Im": " imaginary ",
        r"\bar": " conjugate ",
        r"\overline": " conjugate ",
        # Sets
        r"\in": " element_of ",
        r"\notin": " not_element_of ",
        r"\subset": " subset ",
        r"\subseteq": " subset ",
        r"\cup": " union ",
        r"\cap": " intersection ",
        r"\setminus": " set_difference ",
        r"\emptyset": " empty_set ",
        # Logic
        r"\forall": " for_all ",
        r"\exists": " exists ",
        r"\neg": " not ",
        r"\land": " and ",
        r"\lor": " or ",
        r"\implies": " implies ",
        r"\iff": " if_and_only_if ",
        # Comparison
        r"\le": " <= ",
        r"\leq": " <= ",
        r"\ge": " >= ",
        r"\geq": " >= ",
        r"\ne": " != ",
        r"\neq": " != ",
        # Absolute value and norms
        r"\abs": " absolute_value ",
        r"\lvert": " absolute_value ",
        r"\rvert": " absolute_value ",
        r"\|": " norm ",
    }

    # Multi-word mathematical phrases (order matters: longer first)
    MATH_PHRASES = [
        "greatest common divisor",
        "least common multiple",
        "lowest common multiple",
        "highest common factor",
        "absolute value",
        "square root",
        "cube root",
        "natural logarithm",
        "common logarithm",
        "partial derivative",
        "definite integral",
        "indefinite integral",
        "inverse sine",
        "inverse cosine",
        "inverse tangent",
        "hyperbolic sine",
        "hyperbolic cosine",
        "hyperbolic tangent",
        "complex conjugate",
        "real part",
        "imaginary part",
        "dot product",
        "cross product",
        "scalar product",
        "less than or equal",
        "greater than or equal",
        "not equal",
        "element of",
        "subset of",
        "union of",
        "intersection of",
        "standard deviation",
        "arithmetic mean",
        "geometric mean",
        "binomial coefficient",
        "n choose k",
        "for all",
        "there exists",
    ]

    # Single-word mathematical terms
    MATH_TERMS = {
        # Operations
        "sum", "product", "quotient", "remainder", "difference",
        "addition", "subtraction", "multiplication", "division",
        "exponent", "exponentiation", "power", "root",
        # Calculus
        "derivative", "integral", "differentiate", "integrate",
        "antiderivative", "limit", "infinity", "continuous",
        # Number theory
        "prime", "composite", "factorial", "divisor", "divisible",
        "multiple", "factor", "modulo", "modulus", "remainder",
        # Set theory
        "set", "union", "intersection", "complement", "subset",
        "element", "member", "empty", "cardinality",
        # Algebra
        "equation", "inequality", "variable", "constant",
        "coefficient", "polynomial", "quadratic", "linear",
        # Trigonometry
        "sine", "cosine", "tangent", "cotangent", "secant", "cosecant",
        "angle", "radian", "degree",
        # Geometry
        "area", "perimeter", "volume", "circumference",
        "radius", "diameter", "triangle", "circle", "square",
        # Linear algebra
        "matrix", "vector", "determinant", "transpose", "inverse",
        "eigenvalue", "eigenvector",
        # Statistics
        "mean", "median", "mode", "variance", "deviation",
        "probability", "distribution", "expected",
        # Logic (note: "and", "or", "not" handled specially - only included when
        # they appear as mathematical operators, not as English connectives)
        "implies", "equivalent", "true", "false", "forall", "exists",
        # Constants
        "pi", "euler", "infinity", "imaginary",
    }

    # Stop words to filter out - common English words that appear in math
    # problem descriptions but are not mathematical terms themselves.
    # These cause noise in retrieval because they match many symbol descriptions.
    STOP_WORDS = {
        # Articles and determiners
        "a", "an", "the", "this", "that", "these", "those",
        # Common verbs
        "is", "are", "was", "were", "be", "been", "being",
        "has", "have", "had", "do", "does", "did",
        "find", "calculate", "compute", "solve", "determine", "evaluate",
        "show", "prove", "verify", "check", "get", "give", "let",
        "takes", "express", "answer", "write", "put", "simplify",
        # Prepositions
        "of", "in", "to", "for", "with", "on", "at", "by", "from",
        "into", "through", "during", "before", "after", "above", "below",
        "between", "under", "over",
        # Conjunctions (as English connectives, not logical operators)
        "and", "or", "but", "if", "then", "when", "while", "although",
        # Pronouns
        "it", "its", "they", "their", "we", "our", "you", "your",
        "he", "she", "him", "her", "his",
        # Question words
        "what", "which", "who", "whom", "whose", "where", "how", "why",
        # Other common words
        "all", "each", "every", "both", "few", "more", "most", "other",
        "some", "such", "no", "any", "only", "own", "same", "so", "than",
        "too", "very", "just", "also", "now", "here", "there",
        "can", "will", "shall", "may", "might", "must", "should", "would", "could",
        "about", "as", "like", "using", "given", "following", "use",
        # Problem statement words that appear in index but are not math terms
        "number", "numbers", "value", "values", "form", "many", "much",
        "first", "second", "third", "last", "next", "new", "old",
        "total", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
        "positive", "negative", "real", "smallest", "largest", "greater", "smaller",
        "image", "line", "takes", "end", "cases", "begin", "text",
        "argument", "result", "object", "function", "called", "name",
        "type", "symbol", "element", "list", "apply", "return",
        # Single letters (often variables, not keywords)
        "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
        "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
        # Ambiguous terms that cause polysemy issues in retrieval
        # These words have different meanings in different math contexts
        "times",         # "45 times" (repetitions) vs multiplication
        "coordinates",   # plane coordinates vs complex number representation
        "point",         # "at this point" vs geometric point
        "direction",     # "direction" in context vs vector direction
        "turns",         # "turns 45 times" vs angular turns
        "side",          # "left side" vs polygon side
        "sides",         # sides of equation vs geometric sides
        "base",          # "base" in context vs logarithm base
        "degree",        # "degree" in polynomials vs angles vs graph theory
        "order",         # "in order" vs mathematical ordering
        "term",          # "term" in expressions vs general term
        "terms",         # "in terms of" vs polynomial terms
    }

    def __init__(self, index_path: Path | None = None):
        """
        Initialize the keyword extractor.

        Args:
            index_path: Path to index.json (optional, for dynamic terms)
        """
        self.index_data: dict[str, Any] = {}
        self.indexed_keywords: set[str] = set()

        if index_path and index_path.exists():
            self._load_index(index_path)

    def _load_index(self, index_path: Path) -> None:
        """Load the keyword index to augment extraction."""
        with open(index_path) as f:
            self.index_data = json.load(f)

        # Build set of all indexed keywords
        self.indexed_keywords = set(self.index_data.get("index", {}).keys())

        # Add aliases
        for alias in self.index_data.get("aliases", {}).keys():
            self.indexed_keywords.add(alias)

        # Add synonym phrases
        for synonym in self.index_data.get("synonyms", {}).keys():
            self.indexed_keywords.add(synonym.lower())

        logger.info(f"Loaded {len(self.indexed_keywords)} indexed keywords")

    def extract(self, problem: str) -> ExtractionResult:
        """
        Extract mathematical keywords from a problem statement.

        Args:
            problem: The mathematical problem text

        Returns:
            ExtractionResult with extracted keywords, operators, functions, and phrases
        """
        result = ExtractionResult(problem=problem)

        # Strip Asymptote graphics code blocks [asy]...[/asy]
        # These contain drawing commands that pollute keyword extraction
        cleaned_problem = self._strip_asymptote_blocks(problem)

        # Convert LaTeX math symbols to extractable keywords
        # This must happen before lowercasing since LaTeX commands are case-sensitive
        cleaned_problem = self._convert_latex_symbols(cleaned_problem)

        # Normalize text
        text = cleaned_problem.lower()

        # 1. Extract multi-word phrases first (before tokenizing)
        text, phrases = self._extract_phrases(text)
        result.phrases = phrases

        # 2. Convert Unicode operators
        for unicode_op, replacement in self.UNICODE_OPERATORS.items():
            if unicode_op in problem:
                result.operators.append(unicode_op)
                text = text.replace(unicode_op, f" {replacement} ")

        # 3. Extract operators
        for op in sorted(self.OPERATORS, key=len, reverse=True):
            if op in text:
                result.operators.append(op)

        # 4. Tokenize remaining text
        tokens = self._tokenize(text)

        # 5. Extract function names
        for token in tokens:
            if token in self.MATH_FUNCTIONS:
                result.functions.append(token)

        # 6. Extract mathematical terms (filtering out stop words)
        for token in tokens:
            # Skip stop words to reduce retrieval noise
            if token in self.STOP_WORDS:
                continue
            if token in self.MATH_TERMS:
                result.keywords.append(token)
            elif token in self.indexed_keywords:
                result.keywords.append(token)

        # 7. Remove duplicates while preserving order
        result.keywords = list(dict.fromkeys(result.keywords))
        result.operators = list(dict.fromkeys(result.operators))
        result.functions = list(dict.fromkeys(result.functions))
        result.phrases = list(dict.fromkeys(result.phrases))

        return result

    def _extract_phrases(self, text: str) -> tuple[str, list[str]]:
        """
        Extract multi-word mathematical phrases.

        Args:
            text: Lowercase problem text

        Returns:
            Tuple of (modified text with phrases replaced, list of found phrases)
        """
        found_phrases = []

        for phrase in self.MATH_PHRASES:
            if phrase in text:
                found_phrases.append(phrase)
                # Replace phrase with placeholder to avoid re-matching parts
                text = text.replace(phrase, " ")

        return text, found_phrases

    def _strip_asymptote_blocks(self, text: str) -> str:
        """
        Remove Asymptote graphics code blocks from problem text.

        Asymptote ([asy]...[/asy]) blocks contain drawing commands
        for geometric figures and pollute keyword extraction with
        irrelevant terms like 'size', 'draw', 'circle', 'label', etc.

        Args:
            text: Problem text potentially containing Asymptote blocks

        Returns:
            Text with Asymptote blocks removed
        """
        # Remove [asy]...[/asy] blocks (case-insensitive, multiline)
        return re.sub(
            r'\[asy\].*?\[/asy\]',
            ' ',
            text,
            flags=re.DOTALL | re.IGNORECASE
        )

    def _convert_latex_symbols(self, text: str) -> str:
        """
        Convert LaTeX math symbols to extractable keyword strings.

        This converts LaTeX commands like \\lceil, \\lfloor, \\sin, etc.
        to their corresponding math function names for better keyword
        extraction and retrieval.

        Args:
            text: Problem text containing LaTeX math notation

        Returns:
            Text with LaTeX symbols converted to keywords
        """
        # Sort by length (longest first) to avoid partial replacements
        for latex_cmd, keyword in sorted(
            self.LATEX_SYMBOLS.items(),
            key=lambda x: len(x[0]),
            reverse=True
        ):
            text = text.replace(latex_cmd, keyword)
        return text

    def _tokenize(self, text: str) -> list[str]:
        """
        Tokenize text into words, handling mathematical notation.

        Args:
            text: Text to tokenize

        Returns:
            List of tokens
        """
        # Split on whitespace and punctuation, keeping alphanumeric
        tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|\d+\.?\d*", text)
        return [t.lower() for t in tokens]

    def extract_all(self, problems: list[str]) -> list[ExtractionResult]:
        """
        Extract keywords from multiple problems.

        Args:
            problems: List of problem statements

        Returns:
            List of ExtractionResult objects
        """
        return [self.extract(p) for p in problems]
