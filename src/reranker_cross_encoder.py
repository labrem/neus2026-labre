"""
Cross-Encoder Reranker for OpenMath Symbol Filtering.

Phase 8d: Cross-Encoder Reranking (The Judge)

Filters and ranks Phase 8c candidates using a cross-encoder model
to eliminate irrelevant "domain overreach" symbols.

The reranker scores each (problem, symbol) pair for relevance and
applies an enhanced threshold rule: max(top_k, scores_above_threshold).
This ensures at least top_k candidates are always kept.

Supports three backends:
- "cross-encoder": sentence-transformers CrossEncoder (recommended for local)
- "vllm": Qwen3-Reranker via vLLM pooling server (high accuracy + throughput)
- "ollama": Ollama LLM-based scoring (legacy)

Recommended models:
- mixedbread-ai/mxbai-rerank-large-v1 (cross-encoder, best general accuracy)
- Qwen/Qwen3-Reranker-0.6B (vllm, optimized for reranking tasks)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

# Optional sentence-transformers import
try:
    from sentence_transformers import CrossEncoder
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

# Optional transformers import for Qwen3
try:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_BACKEND = "cross-encoder"  # "cross-encoder", "qwen3", or "ollama"
DEFAULT_CROSS_ENCODER_MODEL = "mixedbread-ai/mxbai-rerank-large-v1"
DEFAULT_QWEN3_MODEL = "Qwen/Qwen3-Reranker-0.6B"
DEFAULT_OLLAMA_MODEL = "gemma2:2b"
DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/v1").rstrip("/v1")
DEFAULT_VLLM_RERANKER_MODEL = "Qwen/Qwen3-Reranker-0.6B"
DEFAULT_VLLM_RERANKER_URL = os.getenv("VLLM_RERANKER_URL", "http://localhost:9001")
DEFAULT_THRESHOLD = 0.15  # Threshold for cross-encoder models
DEFAULT_MIN_KEEP = 3  # Minimum candidates to always keep (top_k)
DEFAULT_MAX_TOKENS = 50  # For Ollama backend
DEFAULT_TEMPERATURE = 0.0  # For Ollama backend

# System prompt for Ollama backend
SYSTEM_PROMPT = """You are a mathematical relevance scorer. Your task is to rate how relevant a mathematical definition is to solving a given problem.

Score from 0.0 (completely irrelevant) to 1.0 (highly relevant).

Respond with ONLY a JSON object containing a "score" field with a number.

Example response: {"score": 0.85}"""


@dataclass
class RerankerResult:
    """Result of cross-encoder reranking for a single problem."""

    problem_id: str
    problem_text: str
    original_count: int  # Number of Phase 8c candidates
    reranked_symbols: list[dict] = field(default_factory=list)  # Symbols passing threshold
    all_scores: dict[str, float] = field(default_factory=dict)  # symbol_id -> score
    processing_time: float = 0.0  # Seconds
    success: bool = True
    error: Optional[str] = None

    @property
    def reranked_count(self) -> int:
        """Number of symbols passing threshold."""
        return len(self.reranked_symbols)

    @property
    def filtered_count(self) -> int:
        """Number of symbols filtered out."""
        return self.original_count - self.reranked_count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "problem_id": self.problem_id,
            "problem_text": self.problem_text[:500] + "..." if len(self.problem_text) > 500 else self.problem_text,
            "original_count": self.original_count,
            "reranked_count": self.reranked_count,
            "reranked_symbols": self.reranked_symbols,
            "processing_time": round(self.processing_time, 2),
            "success": self.success,
            "error": self.error,
        }


def apply_threshold_rule(
    candidates: list[dict],
    scores: list[float],
    threshold: float,
    min_keep: int = DEFAULT_MIN_KEEP,
) -> list[dict]:
    """
    Apply enhanced threshold rule: max(top_k, scores_above_threshold).

    This ensures:
    - At least min_keep candidates are always returned (top scores)
    - If more candidates exceed threshold, all of them are returned

    Examples:
        - scores=[0.75, 0.75, 0.61], threshold=0.7, min_keep=3 → returns all 3
        - scores=[0.9, 0.8, 0.75, 0.71, 0.65], threshold=0.7, min_keep=3 → returns 4 (all > 0.7)
        - scores=[0.5, 0.4, 0.3], threshold=0.7, min_keep=3 → returns all 3 (top_k rule)

    Args:
        candidates: List of symbol dicts
        scores: Parallel list of relevance scores
        threshold: Minimum score threshold
        min_keep: Minimum candidates to keep (default: 3)

    Returns:
        List of (candidate, score) tuples sorted by score descending
    """
    # Pair candidates with scores
    scored = list(zip(candidates, scores))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Count how many exceed threshold
    above_threshold_count = sum(1 for _, s in scored if s >= threshold)

    # Take max of min_keep and above_threshold_count
    keep_count = max(min_keep, above_threshold_count)

    # Don't keep more than we have
    keep_count = min(keep_count, len(scored))

    return scored[:keep_count]


class SentenceTransformerReranker:
    """
    Cross-encoder reranker using sentence-transformers CrossEncoder.

    Uses proper cross-encoder models (BGE, mxbai) for accurate relevance scoring.
    This is the recommended backend for better discrimination.

    Example:
        >>> reranker = SentenceTransformerReranker()
        >>> result = reranker.rerank(
        ...     problem_id="math_00000",
        ...     problem_text="Find the GCD of 48 and 18.",
        ...     candidates=[{"name": "gcd", "cd": "arith1", ...}]
        ... )
        >>> print(result.reranked_count)
        3
    """

    def __init__(
        self,
        model: str = DEFAULT_CROSS_ENCODER_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        min_keep: int = DEFAULT_MIN_KEEP,
        max_length: int = 512,
        batch_size: int = 32,
    ):
        """
        Initialize the sentence-transformers cross-encoder reranker.

        Args:
            model: HuggingFace model name (default: mxbai-rerank-large-v1)
            threshold: Minimum score to keep (default: 0.15)
            min_keep: Minimum candidates to always keep (default: 3)
            max_length: Maximum sequence length (default: 512)
            batch_size: Batch size for scoring (default: 32)
        """
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers not installed. Install with: pip install sentence-transformers"
            )

        self.model_name = model
        self.threshold = threshold
        self.min_keep = min_keep
        self.max_length = max_length
        self.batch_size = batch_size

        logger.info(f"Loading CrossEncoder model: {model}")
        self.model = CrossEncoder(model, max_length=max_length)
        logger.info(
            f"SentenceTransformerReranker initialized: model={model}, "
            f"threshold={threshold}, min_keep={min_keep}"
        )

    def score(
        self,
        problem_text: str,
        description_card: dict,
    ) -> float:
        """
        Score a single problem-symbol pair for relevance.

        Args:
            problem_text: The math problem statement
            description_card: Symbol dict with normalized fields

        Returns:
            Relevance score (raw cross-encoder output)
        """
        definition_text = self._format_description_card(description_card)
        scores = self.model.predict([[problem_text, definition_text]])
        return float(scores[0])

    def score_batch(
        self,
        problem_text: str,
        candidates: list[dict],
    ) -> list[float]:
        """
        Score multiple candidates for a single problem in batch.

        This is much faster than scoring one at a time.

        Args:
            problem_text: The math problem statement
            candidates: List of symbol dicts

        Returns:
            List of relevance scores
        """
        pairs = [
            [problem_text, self._format_description_card(c)]
            for c in candidates
        ]
        scores = self.model.predict(pairs, batch_size=self.batch_size)
        return [float(s) for s in scores]

    def rerank(
        self,
        problem_id: str,
        problem_text: str,
        candidates: list[dict],
        progress_callback: Optional[callable] = None,
    ) -> RerankerResult:
        """
        Rerank candidates for a single problem.

        Args:
            problem_id: Unique identifier for the problem
            problem_text: The math problem statement
            candidates: List of symbol dicts from Phase 8c
            progress_callback: Optional callback(current, total) for progress

        Returns:
            RerankerResult with filtered and scored symbols
        """
        result = RerankerResult(
            problem_id=problem_id,
            problem_text=problem_text,
            original_count=len(candidates),
        )

        start_time = time.time()

        try:
            # Score all candidates in batch for efficiency
            scores = self.score_batch(problem_text, candidates)

            reranked = []
            for i, (symbol, score) in enumerate(zip(candidates, scores)):
                symbol_id = f"{symbol.get('cd', '')}:{symbol.get('name', '')}"
                result.all_scores[symbol_id] = score

                if score >= self.threshold:
                    reranked.append({
                        **symbol,
                        "reranker_score": round(score, 4),
                    })

                logger.debug(
                    f"Scored {symbol_id}: {score:.4f} "
                    f"({'KEEP' if score >= self.threshold else 'FILTER'})"
                )

                # Progress callback
                if progress_callback:
                    progress_callback(i + 1, len(candidates))

            # Sort by reranker score descending
            reranked.sort(key=lambda x: x.get("reranker_score", 0), reverse=True)
            result.reranked_symbols = reranked
            result.success = True

        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.exception(f"Reranking failed for {problem_id}: {e}")

        result.processing_time = time.time() - start_time
        return result

    def rerank_batch(
        self,
        problems: dict[str, str],
        candidates_by_problem: dict[str, dict],
        progress_callback: Optional[callable] = None,
    ) -> dict[str, RerankerResult]:
        """
        Rerank candidates for multiple problems.

        Args:
            problems: {problem_id: problem_text}
            candidates_by_problem: From openmath-retrieved.json
                Format: {problem_id: {"concepts": [...], "openmath": {...}}}
            progress_callback: Optional callback(current, total) for progress

        Returns:
            {problem_id: RerankerResult}
        """
        results = {}
        total_problems = len(problems)
        processed = 0

        for problem_id, problem_text in problems.items():
            # Get candidates for this problem
            problem_data = candidates_by_problem.get(problem_id, {})
            openmath_dict = problem_data.get("openmath", {})

            # Convert dict of symbols to list
            candidates = list(openmath_dict.values())

            logger.info(
                f"Reranking {problem_id}: {len(candidates)} candidates"
            )

            result = self.rerank(
                problem_id=problem_id,
                problem_text=problem_text,
                candidates=candidates,
            )
            results[problem_id] = result

            processed += 1
            if progress_callback:
                progress_callback(processed, total_problems)

            logger.info(
                f"[{processed}/{total_problems}] {problem_id}: "
                f"{result.reranked_count}/{result.original_count} symbols kept"
            )

        return results

    def _format_description_card(self, symbol: dict) -> str:
        """
        Format a symbol as a description card for reranking.

        Args:
            symbol: Symbol dict with normalized fields

        Returns:
            Formatted description card text
        """
        parts = [
            f"Symbol: {symbol.get('cd', '')}:{symbol.get('name', '')}",
        ]

        # Add description
        desc = symbol.get("description_normalized") or symbol.get("description", "")
        if desc:
            parts.append(f"Description: {desc}")

        # Add properties (join if list)
        props = symbol.get("cmp_properties_normalized") or symbol.get("cmp_properties", [])
        if props:
            if isinstance(props, list):
                props = "; ".join(str(p) for p in props if p)
            parts.append(f"Properties: {props}")

        # Add examples (join if list)
        examples = symbol.get("examples_normalized") or symbol.get("examples", [])
        if examples:
            if isinstance(examples, list):
                examples = "; ".join(str(e) for e in examples if e)
            parts.append(f"Examples: {examples}")

        return "\n".join(parts)


class OllamaReranker:
    """
    Cross-encoder reranker using Ollama LLM-based scoring.

    Uses an LLM to score relevance between problem statements and
    mathematical symbol definitions. Less accurate than proper
    cross-encoder models but doesn't require sentence-transformers.

    Example:
        >>> reranker = OllamaReranker()
        >>> result = reranker.rerank(
        ...     problem_id="math_00000",
        ...     problem_text="Find the GCD of 48 and 18.",
        ...     candidates=[{"name": "gcd", "cd": "arith1", ...}]
        ... )
        >>> print(result.reranked_count)
        3
    """

    def __init__(
        self,
        model: str = DEFAULT_OLLAMA_MODEL,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        threshold: float = 0.7,  # Higher threshold for LLM-based scoring
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        system_prompt: str = SYSTEM_PROMPT,
        rate_limit_delay: float = 0.02,
    ):
        """
        Initialize the Ollama-based reranker.

        Args:
            model: Ollama model name (default: gemma2:2b)
            ollama_url: Base URL for Ollama API (default: from .env)
            threshold: Minimum score to keep (default: 0.7)
            max_tokens: Maximum tokens for response (default: 50)
            temperature: Sampling temperature (default: 0.0)
            system_prompt: System prompt for scoring
            rate_limit_delay: Delay between API calls in seconds
        """
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.threshold = threshold
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system_prompt = system_prompt
        self.rate_limit_delay = rate_limit_delay

        logger.info(
            f"OllamaReranker initialized: model={model}, "
            f"threshold={threshold}, url={ollama_url}"
        )

    def score(
        self,
        problem_text: str,
        description_card: dict,
    ) -> float:
        """
        Score a single problem-symbol pair for relevance.

        Args:
            problem_text: The math problem statement
            description_card: Symbol dict with normalized fields

        Returns:
            Relevance score between 0.0 and 1.0
        """
        definition_text = self._format_description_card(description_card)
        return self._call_reranker(problem_text, definition_text)

    def rerank(
        self,
        problem_id: str,
        problem_text: str,
        candidates: list[dict],
        progress_callback: Optional[callable] = None,
    ) -> RerankerResult:
        """
        Rerank candidates for a single problem.

        Args:
            problem_id: Unique identifier for the problem
            problem_text: The math problem statement
            candidates: List of symbol dicts from Phase 8c
            progress_callback: Optional callback(current, total) for progress

        Returns:
            RerankerResult with filtered and scored symbols
        """
        result = RerankerResult(
            problem_id=problem_id,
            problem_text=problem_text,
            original_count=len(candidates),
        )

        start_time = time.time()

        try:
            reranked = []
            total = len(candidates)

            for i, symbol in enumerate(candidates):
                symbol_id = f"{symbol.get('cd', '')}:{symbol.get('name', '')}"

                try:
                    card_text = self._format_description_card(symbol)
                    score = self._call_reranker(problem_text, card_text)
                    result.all_scores[symbol_id] = score

                    if score >= self.threshold:
                        reranked.append({
                            **symbol,
                            "reranker_score": score,
                        })

                    logger.debug(
                        f"Scored {symbol_id}: {score:.3f} "
                        f"({'KEEP' if score >= self.threshold else 'FILTER'})"
                    )

                except Exception as e:
                    logger.warning(f"Failed to score {symbol_id}: {e}")
                    result.all_scores[symbol_id] = 0.0

                # Progress callback
                if progress_callback:
                    progress_callback(i + 1, total)

                # Rate limiting
                if self.rate_limit_delay > 0:
                    time.sleep(self.rate_limit_delay)

            # Sort by reranker score descending
            reranked.sort(key=lambda x: x.get("reranker_score", 0), reverse=True)
            result.reranked_symbols = reranked
            result.success = True

        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.exception(f"Reranking failed for {problem_id}: {e}")

        result.processing_time = time.time() - start_time
        return result

    def rerank_batch(
        self,
        problems: dict[str, str],
        candidates_by_problem: dict[str, dict],
        progress_callback: Optional[callable] = None,
    ) -> dict[str, RerankerResult]:
        """
        Rerank candidates for multiple problems.

        Args:
            problems: {problem_id: problem_text}
            candidates_by_problem: From openmath-retrieved.json
                Format: {problem_id: {"concepts": [...], "openmath": {...}}}
            progress_callback: Optional callback(current, total) for progress

        Returns:
            {problem_id: RerankerResult}
        """
        results = {}
        total_problems = len(problems)
        processed = 0

        for problem_id, problem_text in problems.items():
            # Get candidates for this problem
            problem_data = candidates_by_problem.get(problem_id, {})
            openmath_dict = problem_data.get("openmath", {})

            # Convert dict of symbols to list
            candidates = list(openmath_dict.values())

            logger.info(
                f"Reranking {problem_id}: {len(candidates)} candidates"
            )

            result = self.rerank(
                problem_id=problem_id,
                problem_text=problem_text,
                candidates=candidates,
            )
            results[problem_id] = result

            processed += 1
            if progress_callback:
                progress_callback(processed, total_problems)

            logger.info(
                f"[{processed}/{total_problems}] {problem_id}: "
                f"{result.reranked_count}/{result.original_count} symbols kept"
            )

        return results

    def _format_description_card(self, symbol: dict) -> str:
        """
        Format a symbol as a description card for reranking.

        Args:
            symbol: Symbol dict with normalized fields

        Returns:
            Formatted description card text
        """
        parts = [
            f"Symbol: {symbol.get('cd', '')}:{symbol.get('name', '')}",
        ]

        # Add description
        desc = symbol.get("description_normalized") or symbol.get("description", "")
        if desc:
            parts.append(f"Description: {desc}")

        # Add properties (join if list)
        props = symbol.get("cmp_properties_normalized") or symbol.get("cmp_properties", [])
        if props:
            if isinstance(props, list):
                props = "; ".join(str(p) for p in props if p)
            parts.append(f"Properties: {props}")

        # Add examples (join if list)
        examples = symbol.get("examples_normalized") or symbol.get("examples", [])
        if examples:
            if isinstance(examples, list):
                examples = "; ".join(str(e) for e in examples if e)
            parts.append(f"Examples: {examples}")

        return "\n".join(parts)

    def _call_reranker(self, problem_text: str, definition_text: str) -> float:
        """
        Call Ollama API to score relevance.

        Args:
            problem_text: The math problem statement
            definition_text: Formatted symbol description

        Returns:
            Relevance score between 0.0 and 1.0
        """
        url = f"{self.ollama_url}/api/chat"

        # Concise prompt that works reliably with JSON mode
        user_prompt = f"""Rate relevance 0.0-1.0. ONLY output JSON: {{"score": number}}

Problem: {problem_text}

Definition: {definition_text}"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "num_predict": self.max_tokens,
                "temperature": self.temperature,
            },
        }

        logger.debug(f"Calling Ollama reranker: {url}")

        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()

        result = response.json()
        content = result.get("message", {}).get("content", "{}")

        return self._extract_score(content)

    def _extract_score(self, raw_response: str) -> float:
        """
        Extract score from LLM response.

        Handles various response formats:
        - {"score": 0.85}
        - {"relevance": 0.85}
        - Just a number: 0.85
        - Percentage: 85%

        Args:
            raw_response: Raw text from LLM

        Returns:
            Score clamped to [0.0, 1.0]
        """
        if not raw_response.strip():
            return 0.0

        # Try JSON parsing
        try:
            data = json.loads(raw_response.strip())
            if isinstance(data, dict):
                # Try common score keys
                for key in ["score", "relevance", "rating", "value"]:
                    if key in data:
                        score = float(data[key])
                        return max(0.0, min(1.0, score))
            elif isinstance(data, (int, float)):
                score = float(data)
                return max(0.0, min(1.0, score))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # Try to extract number from text
        number_match = re.search(r'(\d+\.?\d*)', raw_response)
        if number_match:
            try:
                score = float(number_match.group(1))
                # Handle percentage (e.g., 85 -> 0.85)
                if score > 1.0:
                    score = score / 100.0
                return max(0.0, min(1.0, score))
            except ValueError:
                pass

        logger.warning(f"Could not extract score from: {raw_response[:100]}")
        return 0.0


class VLLMReranker:
    """
    Cross-encoder reranker using vLLM pooling server.

    Uses Qwen3-Reranker-0.6B via vLLM's /score endpoint for accurate
    relevance scoring. This backend provides native cross-encoder support
    with high throughput through continuous batching.

    Requires vLLM server running with pooling runner:
        ./scripts/start_vllm_server.sh --model Qwen/Qwen3-Reranker-0.6B --runner pooling --port 9001

    Example:
        >>> reranker = VLLMReranker()
        >>> result = reranker.rerank(
        ...     problem_id="math_00000",
        ...     problem_text="Find the GCD of 48 and 18.",
        ...     candidates=[{"name": "gcd", "cd": "arith1", ...}]
        ... )
        >>> print(result.reranked_count)
        5
    """

    # Qwen3-Reranker prompt templates
    PROMPT_PREFIX = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
    PROMPT_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    INSTRUCTION = "Given a math problem, retrieve relevant mathematical definitions and properties that would help solve it"

    def __init__(
        self,
        vllm_url: str | None = None,
        model: str = DEFAULT_VLLM_RERANKER_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        min_keep: int = DEFAULT_MIN_KEEP,
        timeout: int = 60,
    ):
        """
        Initialize the vLLM-based reranker.

        Args:
            vllm_url: Base URL for vLLM reranker server (default: from .env)
            model: Model name for API calls (default: Qwen/Qwen3-Reranker-0.6B)
            threshold: Minimum score to keep (default: 0.15)
            min_keep: Minimum candidates to always keep (default: 3)
            timeout: Request timeout in seconds (default: 60)
        """
        self.vllm_url = (vllm_url or DEFAULT_VLLM_RERANKER_URL).rstrip("/")
        self.model = model
        self.threshold = threshold
        self.min_keep = min_keep
        self.timeout = timeout

        logger.info(
            f"VLLMReranker initialized: url={self.vllm_url}, "
            f"model={model}, threshold={threshold}, min_keep={min_keep}"
        )

    def _format_query(self, problem_text: str) -> str:
        """Format problem as Qwen3-Reranker query."""
        return (
            f"{self.PROMPT_PREFIX}"
            f"<Instruct>: {self.INSTRUCTION}\n"
            f"<Query>: {problem_text}\n"
        )

    def _format_document(self, symbol: dict) -> str:
        """Format symbol as Qwen3-Reranker document."""
        card = self._format_description_card(symbol)
        return f"<Document>: {card}{self.PROMPT_SUFFIX}"

    def _format_description_card(self, symbol: dict) -> str:
        """
        Format a symbol as a description card for reranking.

        Args:
            symbol: Symbol dict with normalized fields

        Returns:
            Formatted description card text
        """
        parts = [
            f"Symbol: {symbol.get('cd', '')}:{symbol.get('name', '')}",
        ]

        # Add description
        desc = symbol.get("description_normalized") or symbol.get("description", "")
        if desc:
            parts.append(f"Description: {desc}")

        # Add properties (join if list)
        props = symbol.get("cmp_properties_normalized") or symbol.get("cmp_properties", [])
        if props:
            if isinstance(props, list):
                props = "; ".join(str(p) for p in props if p)
            parts.append(f"Properties: {props}")

        # Add examples (join if list)
        examples = symbol.get("examples_normalized") or symbol.get("examples", [])
        if examples:
            if isinstance(examples, list):
                examples = "; ".join(str(e) for e in examples if e)
            parts.append(f"Examples: {examples}")

        return "\n".join(parts)

    def score(
        self,
        problem_text: str,
        description_card: dict,
    ) -> float:
        """
        Score a single problem-symbol pair for relevance.

        Args:
            problem_text: The math problem statement
            description_card: Symbol dict with normalized fields

        Returns:
            Relevance score between 0.0 and 1.0
        """
        query = self._format_query(problem_text)
        document = self._format_document(description_card)

        url = f"{self.vllm_url}/score"
        payload = {
            "model": self.model,
            "text_1": query,
            "text_2": document,
        }

        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()

            # Extract score from response
            # vLLM /score returns: {"data": [{"index": 0, "score": 0.85}]}
            data = result.get("data", [])
            if data and len(data) > 0:
                return float(data[0].get("score", 0.0))
            return 0.0

        except requests.RequestException as e:
            logger.error(f"vLLM score request failed: {e}")
            return 0.0

    def score_batch(
        self,
        problem_text: str,
        candidates: list[dict],
    ) -> list[float]:
        """
        Score multiple candidates for a single problem.

        Makes individual /score calls for each candidate.
        vLLM's continuous batching handles concurrent requests efficiently.

        Args:
            problem_text: The math problem statement
            candidates: List of symbol dicts

        Returns:
            List of relevance scores
        """
        scores = []
        for candidate in candidates:
            score = self.score(problem_text, candidate)
            scores.append(score)
        return scores

    def rerank(
        self,
        problem_id: str,
        problem_text: str,
        candidates: list[dict],
        progress_callback: Optional[callable] = None,
    ) -> RerankerResult:
        """
        Rerank candidates for a single problem.

        Args:
            problem_id: Unique identifier for the problem
            problem_text: The math problem statement
            candidates: List of symbol dicts from Phase 8c
            progress_callback: Optional callback(current, total) for progress

        Returns:
            RerankerResult with filtered and scored symbols
        """
        result = RerankerResult(
            problem_id=problem_id,
            problem_text=problem_text,
            original_count=len(candidates),
        )

        start_time = time.time()

        try:
            # Score all candidates
            scores = []
            for i, candidate in enumerate(candidates):
                score = self.score(problem_text, candidate)
                scores.append(score)

                symbol_id = f"{candidate.get('cd', '')}:{candidate.get('name', '')}"
                result.all_scores[symbol_id] = score

                logger.debug(f"Scored {symbol_id}: {score:.4f}")

                if progress_callback:
                    progress_callback(i + 1, len(candidates))

            # Apply threshold rule: max(min_keep, above_threshold_count)
            scored_candidates = apply_threshold_rule(
                candidates, scores, self.threshold, self.min_keep
            )

            # Build reranked list
            reranked = []
            for symbol, score in scored_candidates:
                reranked.append({
                    **symbol,
                    "reranker_score": round(score, 4),
                })

            result.reranked_symbols = reranked
            result.success = True

        except Exception as e:
            result.success = False
            result.error = str(e)
            logger.exception(f"Reranking failed for {problem_id}: {e}")

        result.processing_time = time.time() - start_time
        return result

    def rerank_batch(
        self,
        problems: dict[str, str],
        candidates_by_problem: dict[str, dict],
        progress_callback: Optional[callable] = None,
    ) -> dict[str, RerankerResult]:
        """
        Rerank candidates for multiple problems.

        Args:
            problems: {problem_id: problem_text}
            candidates_by_problem: From openmath-retrieved.json
                Format: {problem_id: {"concepts": [...], "openmath": {...}}}
            progress_callback: Optional callback(current, total) for progress

        Returns:
            {problem_id: RerankerResult}
        """
        results = {}
        total_problems = len(problems)
        processed = 0

        for problem_id, problem_text in problems.items():
            # Get candidates for this problem
            problem_data = candidates_by_problem.get(problem_id, {})
            openmath_dict = problem_data.get("openmath", {})

            # Convert dict of symbols to list
            candidates = list(openmath_dict.values())

            logger.info(
                f"Reranking {problem_id}: {len(candidates)} candidates"
            )

            result = self.rerank(
                problem_id=problem_id,
                problem_text=problem_text,
                candidates=candidates,
            )
            results[problem_id] = result

            processed += 1
            if progress_callback:
                progress_callback(processed, total_problems)

            logger.info(
                f"[{processed}/{total_problems}] {problem_id}: "
                f"{result.reranked_count}/{result.original_count} symbols kept"
            )

        return results


def check_vllm_reranker_health(url: str | None = None) -> dict:
    """
    Check if vLLM reranker server is healthy.

    Args:
        url: vLLM server URL (default: from .env)

    Returns:
        {"healthy": bool, "model": str | None, "error": str | None}
    """
    url = (url or DEFAULT_VLLM_RERANKER_URL).rstrip("/")

    try:
        response = requests.get(f"{url}/health", timeout=5)
        if response.status_code == 200:
            return {
                "healthy": True,
                "model": DEFAULT_VLLM_RERANKER_MODEL,
                "url": url,
                "error": None,
            }
        else:
            return {
                "healthy": False,
                "model": None,
                "url": url,
                "error": f"Status {response.status_code}",
            }
    except requests.RequestException as e:
        return {
            "healthy": False,
            "model": None,
            "url": url,
            "error": str(e),
        }


# Alias for backwards compatibility
CrossEncoderReranker = OllamaReranker


def create_reranker(
    backend: str = DEFAULT_BACKEND,
    model: Optional[str] = None,
    threshold: Optional[float] = None,
    **kwargs,
) -> SentenceTransformerReranker | OllamaReranker | VLLMReranker:
    """
    Factory function to create a reranker instance.

    Args:
        backend: "cross-encoder" (recommended), "vllm", or "ollama"
        model: Model name (auto-selected if not provided)
        threshold: Minimum score threshold
        **kwargs: Additional backend-specific arguments
            - For vllm: vllm_url, min_keep, timeout
            - For ollama: ollama_url, max_tokens, temperature
            - For cross-encoder: max_length, batch_size, min_keep

    Returns:
        Configured reranker instance

    Example:
        >>> # Recommended: Use cross-encoder backend
        >>> reranker = create_reranker(backend="cross-encoder")

        >>> # Use vLLM backend (requires vLLM server with pooling runner)
        >>> reranker = create_reranker(backend="vllm")

        >>> # Use Ollama backend
        >>> reranker = create_reranker(backend="ollama", model="gemma2:2b")
    """
    if backend == "cross-encoder":
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "sentence-transformers not installed. Install with: pip install sentence-transformers\n"
                "Or use backend='ollama' or backend='vllm' instead."
            )
        return SentenceTransformerReranker(
            model=model or DEFAULT_CROSS_ENCODER_MODEL,
            threshold=threshold if threshold is not None else DEFAULT_THRESHOLD,
            **kwargs,
        )
    elif backend == "vllm":
        return VLLMReranker(
            model=model or DEFAULT_VLLM_RERANKER_MODEL,
            threshold=threshold if threshold is not None else DEFAULT_THRESHOLD,
            **kwargs,
        )
    elif backend == "ollama":
        return OllamaReranker(
            model=model or DEFAULT_OLLAMA_MODEL,
            threshold=threshold if threshold is not None else 0.7,
            **kwargs,
        )
    else:
        raise ValueError(f"Unknown backend: {backend}. Use 'cross-encoder', 'vllm', or 'ollama'.")


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Rerank OpenMath symbol candidates for relevance"
    )
    parser.add_argument(
        "problem",
        nargs="?",
        help="Math problem text to test"
    )
    parser.add_argument(
        "--backend",
        default=DEFAULT_BACKEND,
        choices=["cross-encoder", "vllm", "ollama"],
        help=f"Reranker backend (default: {DEFAULT_BACKEND})"
    )
    parser.add_argument(
        "--model",
        help="Model name (auto-selected based on backend if not provided)"
    )
    parser.add_argument(
        "--url",
        help="API URL (for ollama/vllm backends)"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        help="Score threshold (default: 0.15 for cross-encoder/vllm, 0.7 for ollama)"
    )
    parser.add_argument(
        "--check-health",
        action="store_true",
        help="Check vLLM reranker server health and exit"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Health check mode
    if args.check_health:
        health = check_vllm_reranker_health(args.url)
        print("\nvLLM Reranker Health Check")
        print("=" * 40)
        print(f"URL: {health['url']}")
        print(f"Healthy: {health['healthy']}")
        if health['healthy']:
            print(f"Model: {health['model']}")
        else:
            print(f"Error: {health['error']}")
        print("=" * 40)
        import sys
        sys.exit(0 if health['healthy'] else 1)

    # Create reranker
    kwargs = {}
    if args.backend == "ollama" and args.url:
        kwargs["ollama_url"] = args.url
    elif args.backend == "vllm" and args.url:
        kwargs["vllm_url"] = args.url

    reranker = create_reranker(
        backend=args.backend,
        model=args.model,
        threshold=args.threshold,
        **kwargs,
    )

    # Demo mode with test cases
    test_cases = [
        {
            "problem": "Find the greatest common divisor of 48 and 18.",
            "symbol": {
                "name": "gcd",
                "cd": "arith1",
                "description_normalized": "The gcd function returns the greatest common divisor of two integers.",
                "cmp_properties_normalized": ["$\\gcd(a,b) = \\gcd(b, a \\mod b)$"],
            },
            "expected": "KEEP",
        },
        {
            "problem": "Find the greatest common divisor of 48 and 18.",
            "symbol": {
                "name": "sin",
                "cd": "transc1",
                "description_normalized": "The sin function returns the sine of its argument.",
                "cmp_properties_normalized": ["$\\sin^2(x) + \\cos^2(x) = 1$"],
            },
            "expected": "FILTER",
        },
        {
            "problem": "Evaluate the integral of x^2 from 0 to 1.",
            "symbol": {
                "name": "int",
                "cd": "calculus1",
                "description_normalized": "The int symbol represents indefinite integration.",
                "cmp_properties_normalized": ["$\\frac{d}{dx}\\int f(x)dx = f(x)$"],
            },
            "expected": "KEEP",
        },
        {
            "problem": "Calculate |(1-i)^8|",
            "symbol": {
                "name": "abs",
                "cd": "arith1",
                "description_normalized": "The abs function returns the absolute value of a number.",
            },
            "expected": "KEEP",
        },
        {
            "problem": "Calculate |(1-i)^8|",
            "symbol": {
                "name": "gcd",
                "cd": "arith1",
                "description_normalized": "The gcd function returns the greatest common divisor of two integers.",
            },
            "expected": "FILTER",
        },
    ]

    backend_name = args.backend
    if args.model:
        model_name = args.model
    elif backend_name == "cross-encoder":
        model_name = DEFAULT_CROSS_ENCODER_MODEL
    elif backend_name == "vllm":
        model_name = DEFAULT_VLLM_RERANKER_MODEL
    else:
        model_name = DEFAULT_OLLAMA_MODEL

    if args.threshold is not None:
        threshold = args.threshold
    elif backend_name in ("cross-encoder", "vllm"):
        threshold = DEFAULT_THRESHOLD
    else:
        threshold = 0.7

    print("\n" + "=" * 70)
    print("Cross-Encoder Reranker Demo - Relevance Scoring")
    print(f"Backend: {backend_name}")
    print(f"Model: {model_name}")
    print(f"Threshold: {threshold}")
    print("=" * 70)

    correct = 0
    total = len(test_cases)

    for tc in test_cases:
        problem = tc["problem"]
        symbol = tc["symbol"]
        expected = tc["expected"]
        symbol_id = f"{symbol['cd']}:{symbol['name']}"

        score = reranker.score(problem, symbol)
        verdict = "KEEP" if score >= threshold else "FILTER"
        match = "✓" if verdict == expected else "✗"
        if verdict == expected:
            correct += 1

        print(f"\nProblem: {problem}")
        print(f"Symbol: {symbol_id}")
        print(f"Score: {score:.4f} → {verdict} {match} (expected: {expected})")

    print("\n" + "=" * 70)
    print(f"Accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
    print("=" * 70)
