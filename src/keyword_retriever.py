"""
OpenMath Symbol Retriever.

Retrieves relevant OpenMath symbols based on extracted keywords
from mathematical problems.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Defaults from environment or fallback
DEFAULT_MAX_SYMBOLS = int(os.getenv("RETRIEVER_MAX_SYMBOLS", "10"))
DEFAULT_MIN_SCORE = int(os.getenv("RETRIEVER_MIN_SCORE", "1"))
DEFAULT_REQUIRE_SYMPY = os.getenv("RETRIEVER_REQUIRE_SYMPY", "true").lower() == "true"


@dataclass
class RetrievalResult:
    """Result of symbol retrieval."""

    query_terms: list[str]
    symbols: list[dict[str, Any]] = field(default_factory=list)
    symbol_ids: list[str] = field(default_factory=list)
    scores: dict[str, int] = field(default_factory=dict)

    def get_symbol(self, symbol_id: str) -> dict[str, Any] | None:
        """Get a specific symbol by ID."""
        for sym in self.symbols:
            if sym.get("id") == symbol_id:
                return sym
        return None


class OpenMathRetriever:
    """Retrieves OpenMath symbols based on keywords."""

    def __init__(
        self,
        kb_path: Path,
        index_path: Path,
    ):
        """
        Initialize the retriever.

        Args:
            kb_path: Path to openmath.json knowledge base
            index_path: Path to index.json keyword index
        """
        self.kb_path = kb_path
        self.index_path = index_path

        self.knowledge_base: dict[str, Any] = {}
        self.index: dict[str, list[str]] = {}
        self.aliases: dict[str, list[str]] = {}
        self.synonyms: dict[str, list[str]] = {}

        self._load_data()

    def _load_data(self) -> None:
        """Load knowledge base and index."""
        # Load knowledge base
        with open(self.kb_path) as f:
            self.knowledge_base = json.load(f)

        # Load index
        with open(self.index_path) as f:
            index_data = json.load(f)

        self.index = index_data.get("index", {})
        self.aliases = index_data.get("aliases", {})
        self.synonyms = index_data.get("synonyms", {})

        logger.info(
            f"Loaded KB with {len(self.knowledge_base.get('symbols', {}))} symbols, "
            f"index with {len(self.index)} keywords"
        )

    def retrieve(
        self,
        terms: list[str],
        max_symbols: int | None = None,
        min_score: int | None = None,
        require_sympy: bool | None = None,
    ) -> RetrievalResult:
        """
        Retrieve relevant OpenMath symbols for given terms.

        Args:
            terms: List of keywords/terms to search for
            max_symbols: Maximum number of symbols to return.
                         If None, uses RETRIEVER_MAX_SYMBOLS from .env (default: 10)
            min_score: Minimum match score (number of matching terms).
                       If None, uses RETRIEVER_MIN_SCORE from .env (default: 1)
            require_sympy: If True, only return symbols with SymPy mappings
                          (executable symbols). If None, uses RETRIEVER_REQUIRE_SYMPY
                          from .env (default: true)

        Returns:
            RetrievalResult with matched symbols ranked by relevance
        """
        # Apply defaults from environment
        if max_symbols is None:
            max_symbols = DEFAULT_MAX_SYMBOLS
        if min_score is None:
            min_score = DEFAULT_MIN_SCORE
        if require_sympy is None:
            require_sympy = DEFAULT_REQUIRE_SYMPY
        result = RetrievalResult(query_terms=terms)

        # Count matches per symbol
        symbol_matches: Counter[str] = Counter()
        symbols_dict = self.knowledge_base.get("symbols", {})

        for term in terms:
            term_lower = term.lower()
            matched_symbols = self._resolve_term(term_lower)

            for symbol_id in matched_symbols:
                # Pre-filter by SymPy requirement
                if require_sympy:
                    symbol = symbols_dict.get(symbol_id, {})
                    if not symbol.get("sympy_function"):
                        continue
                symbol_matches[symbol_id] += 1

        # Filter by minimum score and sort by match count
        scored_symbols = [
            (sid, score) for sid, score in symbol_matches.items()
            if score >= min_score
        ]
        scored_symbols.sort(key=lambda x: (-x[1], x[0]))  # Score desc, then alphabetical

        # Limit results
        top_symbols = scored_symbols[:max_symbols]

        # Build result
        for symbol_id, score in top_symbols:
            if symbol_id in symbols_dict:
                result.symbols.append(symbols_dict[symbol_id])
                result.symbol_ids.append(symbol_id)
                result.scores[symbol_id] = score

        logger.debug(
            f"Retrieved {len(result.symbols)} symbols for {len(terms)} terms"
        )

        return result

    def _resolve_term(self, term: str) -> list[str]:
        """
        Resolve a term to symbol IDs, handling aliases and synonyms.

        Args:
            term: Lowercase search term

        Returns:
            List of matching symbol IDs
        """
        matched_symbols: list[str] = []

        # 1. Direct index lookup
        if term in self.index:
            matched_symbols.extend(self.index[term])

        # 2. Alias lookup (e.g., "+" → ["arith1:plus"])
        if term in self.aliases:
            matched_symbols.extend(self.aliases[term])

        # 3. Synonym expansion (e.g., "sine" → ["sin"] → lookup "sin")
        if term in self.synonyms:
            for target in self.synonyms[term]:
                if target in self.index:
                    matched_symbols.extend(self.index[target])
                # Also try direct CD:name format
                for cd_name in ["arith1", "relation1", "transc1", "logic1",
                               "set1", "integer1", "calculus1", "nums1"]:
                    potential_id = f"{cd_name}:{target}"
                    if potential_id in self.knowledge_base.get("symbols", {}):
                        matched_symbols.append(potential_id)

        # Remove duplicates while preserving order
        return list(dict.fromkeys(matched_symbols))

    def get_symbol(self, symbol_id: str) -> dict[str, Any] | None:
        """
        Get a specific symbol by ID.

        Args:
            symbol_id: Symbol ID (e.g., "arith1:gcd")

        Returns:
            Symbol dict or None if not found
        """
        return self.knowledge_base.get("symbols", {}).get(symbol_id)

    def get_all_symbols_for_cd(self, cd_name: str) -> list[dict[str, Any]]:
        """
        Get all symbols from a specific Content Dictionary.

        Args:
            cd_name: Content Dictionary name (e.g., "arith1")

        Returns:
            List of symbol dicts
        """
        symbols = []
        for symbol_id, symbol_data in self.knowledge_base.get("symbols", {}).items():
            if symbol_data.get("cd") == cd_name:
                symbols.append(symbol_data)
        return symbols


def create_retriever(project_root: Path | None = None) -> OpenMathRetriever:
    """
    Factory function to create a retriever with default paths.

    Args:
        project_root: Path to project root (auto-detected if None)

    Returns:
        Configured OpenMathRetriever instance
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

    return OpenMathRetriever(
        kb_path=project_root / "data" / "openmath.json",
        index_path=project_root / "data" / "index.json",
    )
