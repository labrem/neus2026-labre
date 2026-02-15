"""
BM25 Lexical Retriever for OpenMath Symbols.

Phase 8c: Hybrid Retrieval (Recall Layer)

Provides standalone BM25 retrieval using rank_bm25.BM25Okapi.
Extracted from hybrid_retriever.py to enable modular composition.

Features:
- Uses normalized fields from Phase 8a when available
- Stopword filtering for clean BM25 matching
- Query expansion with math synonyms
- Non-mathematical CD filtering
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


# Non-mathematical Content Dictionaries to exclude from retrieval
# These are metadata CDs that pollute search results
NON_MATHEMATICAL_CDS = {
    "meta",        # CD metadata (CDName, CDVersion, etc.)
    "metagrp",     # CDGroup metadata
    "metasig",     # Signature metadata
    "error",       # Error handling
    "scscp1",      # SCSCP protocol
    "scscp2",      # SCSCP protocol
    "altenc",      # Encoding alternatives
    "mathmlattr",  # MathML attributes
    "sts",         # Type system (internal)
    "mathmltypes", # MathML types (internal)
}


# Stopwords for BM25 tokenization
# Query-side stopwords (common in math problem statements) that should not
# contribute to BM25 matching. Without filtering, words like "find", "calculate",
# "value" match against noisy index entries, diluting relevance scores.
BM25_STOP_WORDS = {
    # Query-side stopwords (common in math problem statements)
    "find", "calculate", "compute", "solve", "determine", "evaluate",
    "what", "which", "how", "many", "much", "value", "answer",
    "the", "a", "an", "of", "to", "in", "for", "is", "are", "on",
    "that", "by", "this", "with", "and", "or", "if", "then",
    "given", "let", "show", "prove", "express", "simplify",
    # Additional noise words
    "it", "its", "be", "been", "being", "has", "have", "had",
    "do", "does", "did", "will", "would", "could", "should",
    "can", "may", "might", "must", "shall",
    # Quantifiers that don't discriminate
    "all", "each", "every", "some", "any", "no", "not",
    "number", "numbers", "total", "result",
}


# Curated math synonyms mapping common phrases to OpenMath symbol names
# These are hand-crafted to ensure high precision (no noise from index.json)
# Format: "phrase" -> "symbol_name" (symbol_name is looked up in KB to get full IDs)
MATH_SYNONYMS = {
    # Arithmetic
    "greatest common divisor": "gcd",
    "highest common factor": "gcd",
    "hcf": "gcd",
    "least common multiple": "lcm",
    "lowest common multiple": "lcm",
    "absolute value": "abs",
    "modulo": "remainder",
    "mod": "remainder",
    # Trigonometry
    "sine": "sin",
    "cosine": "cos",
    "tangent": "tan",
    "cotangent": "cot",
    "secant": "sec",
    "cosecant": "csc",
    "inverse sine": "arcsin",
    "inverse cosine": "arccos",
    "inverse tangent": "arctan",
    # Logarithms/Exponentials
    "logarithm": "log",
    "natural logarithm": "ln",
    "natural log": "ln",
    "exponential": "exp",
    "e^x": "exp",
    "e to the": "exp",
    # Combinatorics
    "binomial coefficient": "binomial",
    "combination": "binomial",
    "choose": "binomial",
    "ncr": "binomial",
    "n choose k": "binomial",
    "permutation": "permutation",
    "factorial": "factorial",
    "n!": "factorial",
    # Geometry
    "circumference": "circle",
    "diameter": "circle",
    "perimeter": "plus",  # Perimeter is sum of sides
    # Constants
    "pi": "pi",
    "euler": "e",
    "infinity": "infinity",
    # Relations
    "equals": "eq",
    "equal to": "eq",
    "less than": "lt",
    "greater than": "gt",
    "less than or equal": "leq",
    "greater than or equal": "geq",
    "not equal": "neq",
    # Calculus
    "derivative": "diff",
    "differentiate": "diff",
    "integral": "int",
    "integrate": "int",
    "definite integral": "defint",
    # Algebra
    "square root": "root",
    "sqrt": "root",
    "cube root": "root",
    "power": "power",
    "exponent": "power",
    "raised to": "power",
}


@dataclass
class BM25RetrievalResult:
    """Result of BM25 symbol retrieval."""

    query: str
    symbol_ids: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)

    def get_top_k(self, k: int = 10) -> list[tuple[str, float]]:
        """Get top-k symbol IDs with scores."""
        sorted_items = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_items[:k]


class BM25Retriever:
    """
    BM25 Lexical Retriever for OpenMath symbols.

    Uses rank_bm25.BM25Okapi for lexical matching against
    normalized OpenMath Description Cards.

    Example:
        >>> retriever = BM25Retriever(Path("data/openmath.json"))
        >>> result = retriever.retrieve("greatest common divisor", top_k=10)
        >>> print(result.symbol_ids)
        ['arith1:gcd', 'polynomial3:gcd', ...]
    """

    def __init__(
        self,
        kb_path: Path,
        use_normalized_fields: bool = True,
        filter_non_math: bool = True,
    ):
        """
        Initialize BM25 retriever.

        Args:
            kb_path: Path to openmath.json knowledge base
            use_normalized_fields: Use Phase 8a normalized fields for indexing
            filter_non_math: Filter non-mathematical CDs
        """
        self.kb_path = kb_path
        self.use_normalized_fields = use_normalized_fields
        self.filter_non_math = filter_non_math

        # Load knowledge base
        with open(kb_path) as f:
            self.kb = json.load(f)

        self.symbols = self._load_and_filter_symbols()
        self.symbol_ids = [s["id"] for s in self.symbols]

        logger.info(f"BM25Retriever: Loaded {len(self.symbols)} symbols")

        # Build symbol name index for query expansion
        self.symbol_name_index = self._build_symbol_name_index()

        # Build BM25 index
        self.bm25_corpus: list[list[str]] = []
        self.bm25: BM25Okapi | None = None
        self._build_bm25_index()

    def _load_and_filter_symbols(self) -> list[dict[str, Any]]:
        """Load symbols from KB, optionally filtering non-mathematical ones."""
        all_symbols = list(self.kb.get("symbols", {}).values())

        if not self.filter_non_math:
            return all_symbols

        filtered = []
        for symbol in all_symbols:
            cd = symbol.get("cd", "")
            if cd not in NON_MATHEMATICAL_CDS:
                filtered.append(symbol)

        excluded_count = len(all_symbols) - len(filtered)
        if excluded_count > 0:
            logger.info(f"Filtered {excluded_count} non-mathematical symbols")

        return filtered

    def _build_symbol_name_index(self) -> dict[str, list[str]]:
        """
        Build mapping from symbol names to their full IDs.

        This creates a clean lookup table from OpenMath symbol names (e.g., "gcd", "sin")
        to their full symbol IDs (e.g., ["arith1:gcd", "poly:gcd"]).

        Returns:
            Dict mapping symbol_name -> list of symbol_ids
        """
        name_to_ids: dict[str, list[str]] = {}

        for symbol in self.symbols:
            sym_id = symbol.get("id", "")
            if ":" in sym_id:
                name = sym_id.split(":")[1].lower()
                if name not in name_to_ids:
                    name_to_ids[name] = []
                name_to_ids[name].append(sym_id)

        logger.debug(f"Built symbol name index with {len(name_to_ids)} unique names")
        return name_to_ids

    def _get_description_card(self, symbol: dict) -> str:
        """
        Get concatenated text for BM25 indexing.

        Uses normalized fields from Phase 8a when available,
        falling back to original fields if not present.

        Args:
            symbol: Symbol dictionary from KB

        Returns:
            Concatenated text for indexing
        """
        parts = [symbol.get("name", "")]

        if self.use_normalized_fields:
            # Use normalized fields if available (Phase 8a output)
            if desc := symbol.get("description_normalized"):
                parts.append(desc)
            elif desc := symbol.get("description"):
                parts.append(desc)

            if props := symbol.get("cmp_properties_normalized"):
                if isinstance(props, list):
                    parts.extend(props)
                else:
                    parts.append(str(props))
            elif props := symbol.get("cmp_properties"):
                if isinstance(props, list):
                    parts.extend(props)
                else:
                    parts.append(str(props))

            if examples := symbol.get("examples_normalized"):
                if isinstance(examples, list):
                    parts.extend(examples)
                else:
                    parts.append(str(examples))
            elif examples := symbol.get("examples"):
                if isinstance(examples, list):
                    parts.extend(examples)
                else:
                    parts.append(str(examples))
        else:
            # Fallback to original fields only
            if desc := symbol.get("description"):
                parts.append(desc)
            if props := symbol.get("cmp_properties"):
                if isinstance(props, list):
                    parts.extend(props)
                else:
                    parts.append(str(props))

        return " ".join(parts)

    def _build_bm25_index(self) -> None:
        """Build BM25 index from symbol Description Cards."""
        logger.info("Building BM25 index...")

        corpus = []
        for symbol in self.symbols:
            text = self._get_description_card(symbol)
            tokens = self._tokenize(text)
            corpus.append(tokens)

        self.bm25_corpus = corpus

        # Handle empty corpus gracefully
        if corpus:
            self.bm25 = BM25Okapi(corpus)
            logger.info(f"BM25 index built with {len(corpus)} documents")
        else:
            self.bm25 = None
            logger.warning("No symbols to index for BM25")

    def _tokenize(self, text: str) -> list[str]:
        """
        Tokenize text for BM25 with stopword removal.

        Args:
            text: Text to tokenize

        Returns:
            List of lowercase tokens with stopwords removed
        """
        # Remove punctuation and split on whitespace
        text = re.sub(r'[^\w\s]', ' ', text)
        tokens = [t.lower() for t in text.split() if t]
        # Filter stopwords for cleaner BM25 matching
        return [t for t in tokens if t not in BM25_STOP_WORDS]

    def _expand_query(self, query: str) -> str:
        """
        Expand query with OpenMath symbol names for better BM25 matching.

        Uses two clean sources:
        1. MATH_SYNONYMS: Hand-curated phrase->symbol_name mappings
        2. Symbol names: Auto-generated from KB

        Args:
            query: The original query text

        Returns:
            Expanded query with symbol names appended
        """
        expanded_terms: set[str] = set()
        query_lower = query.lower()

        # Check curated synonyms first (phrase -> symbol_name)
        for phrase, symbol_name in MATH_SYNONYMS.items():
            if phrase in query_lower:
                expanded_terms.add(symbol_name)

        # Check symbol names directly (for exact matches like "gcd", "sin")
        for name in self.symbol_name_index:
            # Only match whole words (avoid matching "sin" in "using")
            if re.search(rf'\b{re.escape(name)}\b', query_lower):
                expanded_terms.add(name)

        if expanded_terms:
            expansion = " ".join(expanded_terms)
            logger.debug(f"Query expanded with: {expansion}")
            return query + " " + expansion

        return query

    def get_all_scores(self, query: str, expand_query: bool = True) -> np.ndarray:
        """
        Get BM25 scores for all symbols.

        Used for RRF fusion in HybridRetriever.

        Args:
            query: Query text
            expand_query: Whether to expand query with synonyms

        Returns:
            Array of BM25 scores for all symbols (same order as self.symbol_ids)
        """
        if self.bm25 is None:
            return np.zeros(len(self.symbols))

        # Optionally expand query
        if expand_query:
            query = self._expand_query(query)

        query_tokens = self._tokenize(query)
        return self.bm25.get_scores(query_tokens)

    def retrieve(
        self,
        query: str,
        top_k: int = 50,
        expand_query: bool = True,
    ) -> BM25RetrievalResult:
        """
        Retrieve symbols using BM25.

        Args:
            query: Query text (concepts concatenated or problem text)
            top_k: Number of results to return
            expand_query: Whether to expand query with synonyms

        Returns:
            BM25RetrievalResult with symbol_ids and scores
        """
        result = BM25RetrievalResult(query=query)

        if self.bm25 is None or not self.symbols:
            logger.warning("BM25 index not available")
            return result

        # Get scores for all symbols
        scores = self.get_all_scores(query, expand_query)

        # Get top-k indices
        top_indices = np.argsort(scores)[::-1][:top_k]

        for idx in top_indices:
            symbol_id = self.symbol_ids[idx]
            score = float(scores[idx])
            if score > 0:  # Only include symbols with positive scores
                result.symbol_ids.append(symbol_id)
                result.scores[symbol_id] = score

        logger.debug(f"BM25 retrieved {len(result.symbol_ids)} symbols")
        return result

    def get_symbol(self, symbol_id: str) -> dict[str, Any] | None:
        """Get a specific symbol by ID."""
        return self.kb.get("symbols", {}).get(symbol_id)


def create_bm25_retriever(
    project_root: Path | None = None,
    use_normalized_fields: bool = True,
    **kwargs: Any,
) -> BM25Retriever:
    """
    Factory function to create a BM25 retriever with default paths.

    Args:
        project_root: Path to project root (auto-detected if None)
        use_normalized_fields: Whether to use Phase 8a normalized fields
        **kwargs: Additional arguments passed to BM25Retriever

    Returns:
        Configured BM25Retriever instance
    """
    if project_root is None:
        # Auto-detect from common locations
        possible_roots = [
            Path.cwd(),
            Path.cwd().parent,
            Path(__file__).parent.parent,
        ]
        for root in possible_roots:
            if (root / "data" / "openmath.json").exists():
                project_root = root
                break

    if project_root is None:
        raise FileNotFoundError("Could not locate project root with data/openmath.json")

    return BM25Retriever(
        kb_path=project_root / "data" / "openmath.json",
        use_normalized_fields=use_normalized_fields,
        **kwargs,
    )


# CLI interface for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BM25 Retriever for OpenMath symbols")
    parser.add_argument("query", nargs="?", help="Query to search for")
    parser.add_argument("--top-k", type=int, default=10, help="Number of results")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    retriever = create_bm25_retriever()

    if args.query:
        result = retriever.retrieve(args.query, top_k=args.top_k)
        print(f"\nQuery: {args.query}")
        print(f"Results ({len(result.symbol_ids)}):")
        for sym_id, score in result.get_top_k(args.top_k):
            print(f"  {sym_id}: {score:.4f}")
    else:
        # Demo mode
        test_queries = [
            "greatest common divisor",
            "integral sine",
            "binomial coefficient",
            "factorial",
        ]

        print("\n" + "=" * 60)
        print("BM25 Retriever Demo")
        print("=" * 60)

        for query in test_queries:
            result = retriever.retrieve(query, top_k=5)
            print(f"\nQuery: {query}")
            for sym_id, score in result.get_top_k(5):
                print(f"  {sym_id}: {score:.4f}")
