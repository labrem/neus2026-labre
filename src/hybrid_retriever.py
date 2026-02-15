"""
Hybrid BM25 + Dense Retrieval for OpenMath Symbols.

Phase 8c: Hybrid Retrieval (Recall Layer)

Combines sparse BM25 retrieval with dense embeddings via Reciprocal Rank Fusion (RRF).
This provides better coverage than either method alone:
- BM25: Excels at exact keyword matching (critical for "gcd", "logarithm", "sin")
- Dense: Captures semantic meaning ("find the remainder" -> integer1:remainder)
- RRF: Effectively balances both signals

Changes in Phase 8c:
- Composes BM25Retriever from bm25_retriever.py
- Uses normalized fields from Phase 8a (description_normalized, etc.)
- Default embedding model changed to qwen3-embedding:0.6b
- Added retrieve_batch() for MATH 500 processing
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import requests
from dotenv import load_dotenv

from bm25_retriever import BM25Retriever, NON_MATHEMATICAL_CDS

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Defaults from environment
DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/v1")
DEFAULT_OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")
# Phase 8c: Changed default to qwen3-embedding:4b for better math understanding
DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:4b")


@dataclass
class HybridRetrievalResult:
    """Result of hybrid symbol retrieval."""

    query: str
    symbols: list[dict[str, Any]] = field(default_factory=list)
    symbol_ids: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)

    # Additional debug info
    bm25_scores: dict[str, float] = field(default_factory=dict)
    dense_scores: dict[str, float] = field(default_factory=dict)

    def get_symbol(self, symbol_id: str) -> dict[str, Any] | None:
        """Get a specific symbol by ID."""
        for sym in self.symbols:
            if sym.get("id") == symbol_id:
                return sym
        return None

    def to_output_dict(self) -> dict[str, Any]:
        """
        Convert to output format for data/openmath-retrieved.json.

        Returns dict with symbol IDs as keys and symbol data + rrf_score.
        """
        output = {}
        for symbol in self.symbols:
            sym_id = symbol["id"]
            output[sym_id] = {
                "id": sym_id,
                "name": symbol.get("name", ""),
                "description_normalized": symbol.get("description_normalized", symbol.get("description", "")),
                "cmp_properties_normalized": symbol.get("cmp_properties_normalized", symbol.get("cmp_properties", [])),
                "examples_normalized": symbol.get("examples_normalized", symbol.get("examples", [])),
                "rrf_score": self.scores.get(sym_id, 0.0),
            }
        return output


class HybridRetriever:
    """
    Combines BM25 sparse retrieval with dense embeddings via RRF.

    Phase 8c refactoring:
    - Composes BM25Retriever instead of implementing BM25 internally
    - Uses normalized fields from Phase 8a for embeddings
    - Supports batch processing for MATH 500 problems
    """

    def __init__(
        self,
        kb_path: Path,
        embeddings_cache: Path | None = None,
        ollama_url: str | None = None,
        ollama_api_key: str | None = None,
        embedding_model: str | None = None,
        rrf_k: int = 60,  # RRF constant (standard value from literature)
        filter_non_math: bool = True,  # Filter non-mathematical CDs
        use_normalized_fields: bool = True,  # Use Phase 8a normalized fields
    ):
        """
        Initialize the hybrid retriever.

        Args:
            kb_path: Path to openmath.json knowledge base
            embeddings_cache: Path to cache embeddings (.npy file)
            ollama_url: Ollama API URL (defaults to OLLAMA_API_URL env var)
            ollama_api_key: Ollama API key (defaults to OLLAMA_API_KEY env var)
            embedding_model: Embedding model name (defaults to qwen3-embedding:0.6b)
            rrf_k: RRF smoothing constant (default 60 from literature)
            filter_non_math: Whether to filter non-mathematical CDs
            use_normalized_fields: Whether to use Phase 8a normalized fields
        """
        self.kb_path = kb_path
        self.ollama_url = ollama_url or DEFAULT_OLLAMA_URL
        self.ollama_api_key = ollama_api_key or DEFAULT_OLLAMA_API_KEY
        self.embedding_model = embedding_model or DEFAULT_EMBEDDING_MODEL
        self.rrf_k = rrf_k
        self.filter_non_math = filter_non_math
        self.use_normalized_fields = use_normalized_fields

        # Determine embeddings cache path (model-specific)
        if embeddings_cache is None:
            safe_model_name = self.embedding_model.replace(":", "_").replace("/", "_")
            self.embeddings_cache = kb_path.parent / f"openmath-embeddings_{safe_model_name}.npy"
        else:
            self.embeddings_cache = embeddings_cache

        # Remove /v1 suffix for Ollama native endpoint
        self.ollama_base_url = self.ollama_url.rstrip("/")
        if self.ollama_base_url.endswith("/v1"):
            self.ollama_base_url = self.ollama_base_url[:-3]

        # Load knowledge base
        with open(kb_path) as f:
            self.kb = json.load(f)

        # Compose BM25Retriever (Phase 8c)
        self.bm25_retriever = BM25Retriever(
            kb_path=kb_path,
            use_normalized_fields=use_normalized_fields,
            filter_non_math=filter_non_math,
        )

        # Use symbols from BM25Retriever (already filtered)
        self.symbols = self.bm25_retriever.symbols
        self.symbol_ids = self.bm25_retriever.symbol_ids

        logger.info(f"HybridRetriever: {len(self.symbols)} symbols, model={self.embedding_model}")

        # Load or compute dense embeddings
        self.embeddings: np.ndarray | None = None
        self._load_or_compute_embeddings()

    def _strip_asymptote_blocks(self, text: str) -> str:
        """
        Remove Asymptote graphics code blocks from text.

        Asymptote ([asy]...[/asy]) blocks contain vector graphics code
        that pollutes both BM25 tokenization and semantic embeddings.

        Args:
            text: Text potentially containing Asymptote blocks

        Returns:
            Text with Asymptote blocks removed
        """
        return re.sub(
            r'\[asy\].*?\[/asy\]',
            ' ',
            text,
            flags=re.DOTALL | re.IGNORECASE
        )

    def _get_embedding_text(self, symbol: dict) -> str:
        """
        Get text for embedding a symbol.

        Uses normalized fields from Phase 8a when available.
        Does NOT include symbol IDs as they pollute semantic similarity.

        Args:
            symbol: Symbol dictionary from KB

        Returns:
            Text for embedding
        """
        text_parts = []

        if self.use_normalized_fields:
            # Use normalized fields from Phase 8a
            if desc := symbol.get("description_normalized"):
                text_parts.append(desc)
            elif desc := symbol.get("description"):
                text_parts.append(desc)

            if props := symbol.get("cmp_properties_normalized"):
                if isinstance(props, list):
                    text_parts.extend(props)
                else:
                    text_parts.append(str(props))
            elif props := symbol.get("cmp_properties"):
                if isinstance(props, list):
                    text_parts.extend(props)
                else:
                    text_parts.append(str(props))

            if examples := symbol.get("examples_normalized"):
                if isinstance(examples, list):
                    text_parts.extend(examples)
                else:
                    text_parts.append(str(examples))
            elif examples := symbol.get("examples"):
                if isinstance(examples, list):
                    text_parts.extend(examples)
                else:
                    text_parts.append(str(examples))
        else:
            # Original fields only
            if desc := symbol.get("description"):
                text_parts.append(desc)
            if props := symbol.get("cmp_properties"):
                if isinstance(props, list):
                    text_parts.extend(props)
                else:
                    text_parts.append(str(props))

        return " ".join(text_parts) if text_parts else symbol.get("name", "")

    def _load_or_compute_embeddings(self) -> None:
        """Load embeddings from cache or compute them."""
        # Handle empty symbols
        if not self.symbols:
            self.embeddings = np.array([], dtype=np.float32).reshape(0, 0)
            logger.warning("No symbols to embed")
            return

        if self.embeddings_cache.exists():
            try:
                # Load from .npy file
                cached_embeddings = np.load(self.embeddings_cache)

                # Verify cache matches current symbols
                if cached_embeddings.shape[0] == len(self.symbols):
                    self.embeddings = cached_embeddings
                    logger.info(f"Loaded {len(self.symbol_ids)} embeddings from cache: {self.embeddings_cache}")
                    return
                else:
                    logger.info(f"Cache size mismatch ({cached_embeddings.shape[0]} vs {len(self.symbols)}), recomputing...")
            except Exception as e:
                logger.warning(f"Failed to load embeddings cache: {e}")

        # Compute embeddings
        logger.info(f"Computing embeddings for {len(self.symbols)} symbols using {self.embedding_model}...")
        self.embeddings = self._compute_all_embeddings()

        # Save to cache
        try:
            np.save(self.embeddings_cache, self.embeddings)
            logger.info(f"Saved embeddings to cache: {self.embeddings_cache}")
        except Exception as e:
            logger.warning(f"Failed to save embeddings cache: {e}")

    def _embed(self, text: str) -> np.ndarray:
        """
        Get embedding for text from Ollama API.

        Args:
            text: Text to embed

        Returns:
            Embedding vector as numpy array
        """
        url = f"{self.ollama_base_url}/api/embed"

        headers = {"Content-Type": "application/json"}
        if self.ollama_api_key:
            headers["Authorization"] = f"Bearer {self.ollama_api_key}"

        payload = {
            "model": self.embedding_model,
            "input": text,
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            result = response.json()
            # Handle both array format (new API) and single embedding format
            embeddings = result.get("embeddings", [result.get("embedding", [])])
            return np.array(embeddings[0], dtype=np.float32)
        except requests.exceptions.RequestException as e:
            logger.error(f"Embedding request failed: {e}")
            raise

    def _compute_all_embeddings(self) -> np.ndarray:
        """
        Compute embeddings for all symbols in the knowledge base.

        Uses normalized fields from Phase 8a when available.
        Embeddings are built from pure definition text only (no symbol IDs).
        """
        embeddings = []
        total = len(self.symbols)

        for i, symbol in enumerate(self.symbols):
            text = self._get_embedding_text(symbol)

            try:
                embedding = self._embed(text)
                embeddings.append(embedding)

                if (i + 1) % 50 == 0:
                    logger.info(f"Computed {i + 1}/{total} embeddings...")

            except Exception as e:
                logger.error(f"Failed to embed symbol {symbol['id']}: {e}")
                if embeddings:
                    embeddings.append(np.zeros_like(embeddings[0]))
                else:
                    raise

            # Small delay to avoid rate limiting
            time.sleep(0.02)

        logger.info(f"Computed all {total} embeddings")
        return np.array(embeddings, dtype=np.float32)

    def retrieve(
        self,
        query: str,
        top_k: int = 50,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
        min_rrf_score: float = 0.0,
        require_sympy: bool = False,
        expand_query: bool = True,
        deduplicate: bool = True,
    ) -> HybridRetrievalResult:
        """
        Retrieve symbols using hybrid BM25 + Dense with RRF fusion.

        Args:
            query: The query text (concepts or problem text)
            top_k: Number of symbols to return (default 50 for recall layer)
            bm25_weight: Weight for BM25 in RRF (default 0.5)
            dense_weight: Weight for dense in RRF (default 0.5)
            min_rrf_score: Minimum RRF score threshold
            require_sympy: If True, only return symbols with SymPy mappings
            expand_query: If True, expand query with synonyms (default True)
            deduplicate: If True, deduplicate by symbol name (default True)

        Returns:
            HybridRetrievalResult with matched symbols ranked by RRF score
        """
        result = HybridRetrievalResult(query=query)

        # Handle empty retriever gracefully
        if not self.symbols:
            logger.warning("No symbols available for retrieval")
            return result

        if self.embeddings is None:
            raise RuntimeError("Retriever not properly initialized - no embeddings")

        # Clean query text: remove Asymptote graphics code blocks
        clean_query = self._strip_asymptote_blocks(query)

        # Get BM25 scores from composed BM25Retriever
        bm25_scores = self.bm25_retriever.get_all_scores(clean_query, expand_query=expand_query)

        # Get Dense scores (cosine similarity)
        try:
            query_embedding = self._embed(clean_query)
        except Exception as e:
            logger.error(f"Failed to embed query: {e}")
            return result

        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
        embeddings_norm = self.embeddings / (
            np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-10
        )
        dense_scores = embeddings_norm @ query_norm

        # Compute RRF scores
        # RRF formula: score = sum(weight / (k + rank + 1)) for each retriever
        bm25_ranks = np.argsort(-bm25_scores)  # Indices sorted by descending BM25 score
        dense_ranks = np.argsort(-dense_scores)  # Indices sorted by descending dense score

        rrf_scores = np.zeros(len(self.symbols))

        # BM25 contribution
        for rank, idx in enumerate(bm25_ranks):
            rrf_scores[idx] += bm25_weight / (self.rrf_k + rank + 1)

        # Dense contribution
        for rank, idx in enumerate(dense_ranks):
            rrf_scores[idx] += dense_weight / (self.rrf_k + rank + 1)

        # Sort by RRF score
        top_indices = np.argsort(-rrf_scores)

        # Build results with optional deduplication by full symbol ID (cd:name)
        seen_ids: set[str] = set()

        for idx in top_indices:
            if len(result.symbols) >= top_k:
                break

            score = float(rrf_scores[idx])
            if score < min_rrf_score:
                continue

            symbol = self.symbols[idx]

            # Check SymPy requirement
            if require_sympy and not symbol.get("sympy_function"):
                continue

            # Deduplicate by full symbol ID - keeps different CDs with same symbol name
            if deduplicate:
                symbol_id = symbol.get("id") or f"{symbol.get('cd', '')}:{symbol.get('name', '')}"
                if symbol_id in seen_ids:
                    continue
                seen_ids.add(symbol_id)

            result.symbols.append(symbol)
            result.symbol_ids.append(symbol["id"])
            result.scores[symbol["id"]] = score
            result.bm25_scores[symbol["id"]] = float(bm25_scores[idx])
            result.dense_scores[symbol["id"]] = float(dense_scores[idx])

        logger.debug(
            f"Retrieved {len(result.symbols)} symbols "
            f"(top RRF: {max(result.scores.values()) if result.scores else 0:.4f})"
        )

        return result

    def _retrieve_with_embedding(
        self,
        query: str,
        query_embedding: np.ndarray,
        top_k: int = 50,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
        min_rrf_score: float = 0.0,
        require_sympy: bool = False,
        expand_query: bool = True,
        deduplicate: bool = True,
    ) -> HybridRetrievalResult:
        """
        Retrieve symbols using a pre-computed query embedding.

        Internal method that avoids redundant embedding computation.

        Args:
            query: The query text (for BM25 and result object)
            query_embedding: Pre-computed query embedding
            top_k: Number of symbols to return
            bm25_weight: Weight for BM25 in RRF
            dense_weight: Weight for dense in RRF
            min_rrf_score: Minimum RRF score threshold
            require_sympy: If True, only return symbols with SymPy mappings
            expand_query: If True, expand query with synonyms
            deduplicate: If True, deduplicate by symbol name

        Returns:
            HybridRetrievalResult with matched symbols ranked by RRF score
        """
        result = HybridRetrievalResult(query=query)

        if not self.symbols or self.embeddings is None:
            return result

        # Clean query text for BM25
        clean_query = self._strip_asymptote_blocks(query)

        # Get BM25 scores
        bm25_scores = self.bm25_retriever.get_all_scores(clean_query, expand_query=expand_query)

        # Get Dense scores using pre-computed embedding
        query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
        embeddings_norm = self.embeddings / (
            np.linalg.norm(self.embeddings, axis=1, keepdims=True) + 1e-10
        )
        dense_scores = embeddings_norm @ query_norm

        # Compute RRF scores
        bm25_ranks = np.argsort(-bm25_scores)
        dense_ranks = np.argsort(-dense_scores)

        rrf_scores = np.zeros(len(self.symbols))

        for rank, idx in enumerate(bm25_ranks):
            rrf_scores[idx] += bm25_weight / (self.rrf_k + rank + 1)

        for rank, idx in enumerate(dense_ranks):
            rrf_scores[idx] += dense_weight / (self.rrf_k + rank + 1)

        # Sort by RRF score
        top_indices = np.argsort(-rrf_scores)

        # Build results with optional deduplication by full symbol ID
        seen_ids: set[str] = set()

        for idx in top_indices:
            if len(result.symbols) >= top_k:
                break

            score = float(rrf_scores[idx])
            if score < min_rrf_score:
                continue

            symbol = self.symbols[idx]

            if require_sympy and not symbol.get("sympy_function"):
                continue

            # Deduplicate by full symbol ID - keeps different CDs with same symbol name
            if deduplicate:
                symbol_id = symbol.get("id") or f"{symbol.get('cd', '')}:{symbol.get('name', '')}"
                if symbol_id in seen_ids:
                    continue
                seen_ids.add(symbol_id)

            result.symbols.append(symbol)
            result.symbol_ids.append(symbol["id"])
            result.scores[symbol["id"]] = score
            result.bm25_scores[symbol["id"]] = float(bm25_scores[idx])
            result.dense_scores[symbol["id"]] = float(dense_scores[idx])

        return result

    def get_concept_embeddings_cache_path(self, concepts_path: Path) -> Path:
        """
        Get the cache file path for concept embeddings.

        Args:
            concepts_path: Path to math500-concepts.json

        Returns:
            Path to cache file (e.g., data/math500-concepts-embeddings_qwen3-embedding_4b.npy)
        """
        safe_model_name = self.embedding_model.replace(":", "_").replace("/", "_")
        return concepts_path.parent / f"math500-concepts-embeddings_{safe_model_name}.npy"

    def compute_concept_embeddings(
        self,
        concepts_by_problem: dict[str, list[str]],
        cache_path: Path | None = None,
        progress_callback: callable | None = None,
    ) -> tuple[np.ndarray, list[str]]:
        """
        Compute and cache embeddings for MATH 500 concepts.

        Args:
            concepts_by_problem: {problem_id: [concepts]}
            cache_path: Path to save embeddings cache (.npy file)
            progress_callback: Optional callback(current, total) for progress

        Returns:
            Tuple of (embeddings array, problem_ids list)
            - embeddings: np.ndarray of shape (n_problems, embedding_dim)
            - problem_ids: List of problem IDs in same order as embeddings
        """
        # Sort problem IDs for deterministic ordering
        problem_ids = sorted(concepts_by_problem.keys())
        total = len(problem_ids)

        logger.info(f"Computing concept embeddings for {total} problems using {self.embedding_model}...")

        embeddings = []
        for i, problem_id in enumerate(problem_ids):
            concepts = concepts_by_problem[problem_id]
            query = " ".join(concepts)
            clean_query = self._strip_asymptote_blocks(query)

            try:
                embedding = self._embed(clean_query)
                embeddings.append(embedding)

                if progress_callback:
                    progress_callback(i + 1, total)
                elif (i + 1) % 50 == 0:
                    logger.info(f"Computed {i + 1}/{total} concept embeddings...")

            except Exception as e:
                logger.error(f"Failed to embed concepts for {problem_id}: {e}")
                if embeddings:
                    embeddings.append(np.zeros_like(embeddings[0]))
                else:
                    raise

            time.sleep(0.02)  # Rate limiting

        embeddings_array = np.array(embeddings, dtype=np.float32)
        logger.info(f"Computed all {total} concept embeddings, shape: {embeddings_array.shape}")

        # Save to cache
        if cache_path:
            try:
                np.save(cache_path, embeddings_array)
                logger.info(f"Saved concept embeddings to: {cache_path}")
            except Exception as e:
                logger.warning(f"Failed to save concept embeddings cache: {e}")

        return embeddings_array, problem_ids

    def load_concept_embeddings(
        self,
        cache_path: Path,
        concepts_by_problem: dict[str, list[str]],
    ) -> tuple[np.ndarray, list[str]] | None:
        """
        Load cached concept embeddings.

        Problem IDs are derived from sorted keys of concepts_by_problem,
        which must match the order used when embeddings were computed.

        Args:
            cache_path: Path to embeddings cache (.npy file)
            concepts_by_problem: {problem_id: [concepts]} to derive problem IDs

        Returns:
            Tuple of (embeddings array, problem_ids list) or None if not found
        """
        if not cache_path.exists():
            return None

        try:
            embeddings = np.load(cache_path)
            # Problem IDs are always sorted deterministically
            problem_ids = sorted(concepts_by_problem.keys())

            if embeddings.shape[0] != len(problem_ids):
                logger.warning(
                    f"Cache size mismatch: {embeddings.shape[0]} embeddings vs "
                    f"{len(problem_ids)} problems. Regenerate cache."
                )
                return None

            logger.info(f"Loaded {len(problem_ids)} concept embeddings from cache: {cache_path}")
            return embeddings, problem_ids

        except Exception as e:
            logger.warning(f"Failed to load concept embeddings cache: {e}")
            return None

    def retrieve_batch(
        self,
        concepts_by_problem: dict[str, list[str]],
        top_k: int = 50,
        bm25_weight: float = 0.5,
        dense_weight: float = 0.5,
        progress_callback: callable | None = None,
        concept_embeddings: np.ndarray | None = None,
        concept_problem_ids: list[str] | None = None,
    ) -> dict[str, HybridRetrievalResult]:
        """
        Batch retrieve symbols for multiple problems.

        Designed for processing MATH 500 problems with Phase 8b concepts.
        Supports pre-computed concept embeddings for faster batch processing.

        Args:
            concepts_by_problem: {problem_id: [concepts]}
            top_k: Number of results per problem (default 50)
            bm25_weight: BM25 weight in RRF
            dense_weight: Dense weight in RRF
            progress_callback: Optional callback(current, total) for progress
            concept_embeddings: Pre-computed concept embeddings (optional)
            concept_problem_ids: Problem IDs corresponding to embeddings (required if embeddings provided)

        Returns:
            {problem_id: HybridRetrievalResult}
        """
        results = {}
        total = len(concepts_by_problem)

        # Build embedding lookup if pre-computed embeddings provided
        embedding_lookup: dict[str, np.ndarray] = {}
        if concept_embeddings is not None and concept_problem_ids is not None:
            if len(concept_problem_ids) != concept_embeddings.shape[0]:
                logger.warning("Embeddings/IDs mismatch, falling back to on-the-fly computation")
            else:
                for i, pid in enumerate(concept_problem_ids):
                    embedding_lookup[pid] = concept_embeddings[i]
                logger.info(f"Using {len(embedding_lookup)} pre-computed concept embeddings")

        for i, (problem_id, concepts) in enumerate(concepts_by_problem.items()):
            query = " ".join(concepts)

            # Use pre-computed embedding if available
            if problem_id in embedding_lookup:
                result = self._retrieve_with_embedding(
                    query=query,
                    query_embedding=embedding_lookup[problem_id],
                    top_k=top_k,
                    bm25_weight=bm25_weight,
                    dense_weight=dense_weight,
                )
            else:
                result = self.retrieve(
                    query=query,
                    top_k=top_k,
                    bm25_weight=bm25_weight,
                    dense_weight=dense_weight,
                )

            results[problem_id] = result

            if progress_callback:
                progress_callback(i + 1, total)

        logger.info(f"Batch retrieval complete: {len(results)} problems processed")
        return results

    def get_symbol(self, symbol_id: str) -> dict[str, Any] | None:
        """Get a specific symbol by ID."""
        return self.kb.get("symbols", {}).get(symbol_id)


def create_hybrid_retriever(
    project_root: Path | None = None,
    embedding_model: str | None = None,
    use_normalized_fields: bool = True,
    **kwargs: Any,
) -> HybridRetriever:
    """
    Factory function to create a hybrid retriever with default paths.

    Args:
        project_root: Path to project root (auto-detected if None)
        embedding_model: Ollama embedding model name (default: qwen3-embedding:0.6b)
        use_normalized_fields: Whether to use Phase 8a normalized fields
        **kwargs: Additional arguments passed to HybridRetriever

    Returns:
        Configured HybridRetriever instance
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

    return HybridRetriever(
        kb_path=project_root / "data" / "openmath.json",
        embedding_model=embedding_model,
        use_normalized_fields=use_normalized_fields,
        **kwargs,
    )


# CLI interface for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hybrid BM25 + Dense Retriever for OpenMath")
    parser.add_argument("query", nargs="?", help="Query to search for")
    parser.add_argument("--top-k", type=int, default=10, help="Number of results")
    parser.add_argument("--model", default=None, help="Embedding model")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    retriever = create_hybrid_retriever(embedding_model=args.model)

    if args.query:
        result = retriever.retrieve(args.query, top_k=args.top_k)
        print(f"\nQuery: {args.query}")
        print(f"Results ({len(result.symbols)}):")
        for sym_id in result.symbol_ids[:args.top_k]:
            score = result.scores[sym_id]
            bm25 = result.bm25_scores.get(sym_id, 0)
            dense = result.dense_scores.get(sym_id, 0)
            print(f"  {sym_id}: RRF={score:.4f} (BM25={bm25:.2f}, Dense={dense:.4f})")
    else:
        # Demo mode
        test_queries = [
            "greatest common divisor integer",
            "integral sine calculus",
            "binomial coefficient combinatorics",
            "factorial permutation",
        ]

        print("\n" + "=" * 60)
        print("Hybrid Retriever Demo")
        print(f"Model: {retriever.embedding_model}")
        print("=" * 60)

        for query in test_queries:
            result = retriever.retrieve(query, top_k=5)
            print(f"\nQuery: {query}")
            for sym_id in result.symbol_ids[:5]:
                score = result.scores[sym_id]
                print(f"  {sym_id}: {score:.4f}")
