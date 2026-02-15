"""
Query Parser for Mathematical Concept Extraction.

Phase 8b: Zero-Shot Input Parsing (The Denoiser)

Transforms natural language math problem statements from MATH 500 into
a clean list of mathematical keywords and discrete LaTeX operators using
an LLM (qwen2-math:7b via Ollama).

The parser acts as a "denoiser" that removes narrative context and extracts
only the mathematical concepts needed for retrieval.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_MODEL = "qwen2-math:7b"
DEFAULT_OLLAMA_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/v1").rstrip("/v1")
DEFAULT_MAX_TOKENS = 200  # Limit tokens to prevent solving (100 was too low, causing truncation)
DEFAULT_TEMPERATURE = 0.0  # Deterministic output


# System prompt for mathematical concept extraction
SYSTEM_PROMPT = """You are a mathematical entity extractor. Extract the core mathematical concepts from a problem WITHOUT solving it.

IMPORTANT: Return ONLY a JSON object with a "concepts" key containing an array of strings.

Extract these types of concepts:
- Operations: addition, subtraction, multiplication, division, integration, differentiation
- Functions: gcd, lcm, sin, cos, log, factorial, determinant
- Objects: integer, polynomial, matrix, set, sequence, function
- Domains: algebra, calculus, number theory, combinatorics, geometry

Example 1:
Problem: "Find the greatest common divisor of 48 and 18."
Response: {"concepts": ["greatest common divisor", "gcd", "integer", "divisibility", "number theory"]}

Example 2:
Problem: "Evaluate the integral of x^2 from 0 to 1."
Response: {"concepts": ["definite integral", "integration", "polynomial", "calculus"]}

Example 3:
Problem: "Find the derivative of f(x) = e^(x^2)."
Response: {"concepts": ["derivative", "differentiation", "exponential", "chain rule", "calculus"]}

Example 4:
Problem: "Solve x^2 - 5x + 6 = 0."
Response: {"concepts": ["quadratic equation", "roots", "factoring", "algebra"]}

Example 5:
Problem: "How many ways can 5 people be arranged in a line?"
Response: {"concepts": ["permutation", "factorial", "arrangement", "combinatorics"]}

Return 4-8 relevant mathematical concepts. Do NOT solve the problem."""


@dataclass
class ParseResult:
    """Result of parsing a math problem for concepts."""

    problem_id: str
    problem_text: str
    concepts: list[str] = field(default_factory=list)
    raw_response: str = ""
    success: bool = True
    error: Optional[str] = None
    model: str = DEFAULT_MODEL
    tokens_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "problem_id": self.problem_id,
            "problem_text": self.problem_text[:200] + "..." if len(self.problem_text) > 200 else self.problem_text,
            "concepts": self.concepts,
            "raw_response": self.raw_response,
            "success": self.success,
            "error": self.error,
            "model": self.model,
            "tokens_used": self.tokens_used,
        }


class QueryParser:
    """
    Parses math problems to extract mathematical concepts using an LLM.

    Uses qwen2-math:7b via Ollama to transform wordy problem statements
    into clean lists of mathematical keywords and operators.

    Example:
        >>> parser = QueryParser()
        >>> result = parser.parse("Find the GCD of 12 and 18.")
        >>> print(result.concepts)
        ["greatest common divisor", "gcd", "integer", "arithmetic"]
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        system_prompt: str = SYSTEM_PROMPT,
    ):
        """
        Initialize the query parser.

        Args:
            model: Ollama model name (default: qwen2-math:7b)
            ollama_url: Base URL for Ollama API (default: from .env)
            max_tokens: Maximum tokens for response (default: 100)
            temperature: Sampling temperature (default: 0.0)
            system_prompt: System prompt for concept extraction
        """
        self.model = model
        self.ollama_url = ollama_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system_prompt = system_prompt

        logger.info(f"QueryParser initialized with model={model}, url={ollama_url}")

    def parse(
        self,
        problem_text: str,
        problem_id: str = "unknown",
    ) -> ParseResult:
        """
        Parse a math problem to extract mathematical concepts.

        Args:
            problem_text: The math problem statement
            problem_id: Unique identifier for the problem

        Returns:
            ParseResult containing extracted concepts
        """
        result = ParseResult(
            problem_id=problem_id,
            problem_text=problem_text,
            model=self.model,
        )

        try:
            # Construct the prompt
            user_prompt = f"Extract math concepts from: \"{problem_text}\""

            # Call Ollama API
            response = self._call_ollama(user_prompt)

            result.raw_response = response.get("message", {}).get("content", "")
            result.tokens_used = response.get("eval_count", 0)

            # Parse JSON from response
            concepts = self._extract_concepts(result.raw_response)
            result.concepts = concepts
            result.success = True

        except requests.exceptions.ConnectionError as e:
            result.success = False
            result.error = f"Connection error: Could not connect to Ollama at {self.ollama_url}. Is Ollama running?"
            logger.error(result.error)

        except requests.exceptions.Timeout as e:
            result.success = False
            result.error = f"Timeout error: Ollama request timed out"
            logger.error(result.error)

        except json.JSONDecodeError as e:
            result.success = False
            result.error = f"JSON parse error: Could not parse LLM response as JSON: {e}"
            logger.error(f"{result.error}\nRaw response: {result.raw_response}")

        except Exception as e:
            result.success = False
            result.error = f"Unexpected error: {str(e)}"
            logger.exception(result.error)

        return result

    def parse_batch(
        self,
        problems: list[tuple[str, str]],
        progress_callback: Optional[callable] = None,
    ) -> list[ParseResult]:
        """
        Parse multiple math problems.

        Args:
            problems: List of (problem_id, problem_text) tuples
            progress_callback: Optional callback(current, total) for progress

        Returns:
            List of ParseResult objects
        """
        results = []
        total = len(problems)

        for i, (problem_id, problem_text) in enumerate(problems):
            result = self.parse(problem_text, problem_id)
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total)

        return results

    def _call_ollama(self, user_prompt: str) -> dict[str, Any]:
        """
        Call the Ollama chat API.

        Args:
            user_prompt: The user's prompt

        Returns:
            Response dictionary from Ollama
        """
        url = f"{self.ollama_url}/api/chat"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",  # JSON mode
            "options": {
                "num_predict": self.max_tokens,
                "temperature": self.temperature,
            },
        }

        logger.debug(f"Calling Ollama: {url}")
        logger.debug(f"Payload: {json.dumps(payload, indent=2)[:500]}...")

        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()

        return response.json()

    def _extract_concepts(self, raw_response: str) -> list[str]:
        """
        Extract concept list from LLM response.

        Handles various response formats:
        - Direct JSON array: ["a", "b", "c"]
        - JSON object with array: {"concepts": ["a", "b", "c"]}
        - Newline-separated text (fallback)

        Args:
            raw_response: Raw text from LLM

        Returns:
            List of concept strings
        """
        if not raw_response.strip():
            return []

        # Try to parse as JSON
        try:
            data = json.loads(raw_response.strip())

            # Handle direct array
            if isinstance(data, list):
                return self._filter_concepts([str(item).strip() for item in data if item])

            # Handle object with common keys
            if isinstance(data, dict):
                for key in ["concepts", "keywords", "terms", "output", "result", "math_concepts"]:
                    if key in data and isinstance(data[key], list):
                        return self._filter_concepts([str(item).strip() for item in data[key] if item])

                # If dict has a single list value, use it
                list_values = [v for v in data.values() if isinstance(v, list)]
                if len(list_values) == 1:
                    return self._filter_concepts([str(item).strip() for item in list_values[0] if item])

        except json.JSONDecodeError:
            pass

        # Fallback: try to extract JSON array from text (handles complete arrays)
        array_match = re.search(r'\[([^\]]+)\]', raw_response)
        if array_match:
            try:
                items = json.loads(f"[{array_match.group(1)}]")
                return self._filter_concepts([str(item).strip() for item in items if item])
            except json.JSONDecodeError:
                pass

        # Fallback for truncated JSON: extract quoted strings directly
        # This handles cases like: {"concepts": ["gcd", "algebra", "poly...
        quoted_strings = re.findall(r'"([^"]{2,50})"', raw_response)
        if quoted_strings:
            # Filter out JSON keys and keep only concept-like values
            concepts = [
                s for s in quoted_strings
                if s.lower() not in ("concepts", "keywords", "terms", "output", "result", "math_concepts")
                and not s.startswith("{")
                and not s.startswith("[")
            ]
            if concepts:
                logger.debug(f"Extracted {len(concepts)} concepts from truncated JSON")
                return self._filter_concepts(concepts)

        # Last resort: split by common delimiters
        logger.warning(f"Could not parse JSON, falling back to text splitting")
        lines = raw_response.strip().split('\n')
        concepts = []
        for line in lines:
            # Clean up list markers
            cleaned = re.sub(r'^[\s\-\*\d\.]+', '', line).strip()
            if cleaned and len(cleaned) > 1:
                concepts.append(cleaned)

        return self._filter_concepts(concepts[:20])

    def _filter_concepts(self, concepts: list[str]) -> list[str]:
        """
        Filter and clean concept list.

        Removes:
        - Non-ASCII characters (e.g., Chinese)
        - Very short strings
        - Duplicates (case-insensitive)

        Args:
            concepts: Raw concept list

        Returns:
            Cleaned concept list
        """
        seen = set()
        filtered = []

        for concept in concepts:
            # Skip if contains non-ASCII (Chinese, etc.)
            if not concept.isascii():
                logger.debug(f"Skipping non-ASCII concept: {concept}")
                continue

            # Skip very short or very long
            if len(concept) < 2 or len(concept) > 50:
                continue

            # Case-insensitive dedup
            key = concept.lower().strip()
            if key not in seen:
                seen.add(key)
                filtered.append(concept.strip())

        return filtered[:15]  # Limit to 15 concepts max


def create_query_parser(
    model: str = DEFAULT_MODEL,
    ollama_url: Optional[str] = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
) -> QueryParser:
    """
    Factory function to create a QueryParser instance.

    Args:
        model: Ollama model name
        ollama_url: Ollama API URL (defaults to .env setting)
        max_tokens: Maximum response tokens
        temperature: Sampling temperature

    Returns:
        Configured QueryParser instance
    """
    if ollama_url is None:
        ollama_url = DEFAULT_OLLAMA_URL

    return QueryParser(
        model=model,
        ollama_url=ollama_url,
        max_tokens=max_tokens,
        temperature=temperature,
    )


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract mathematical concepts from problem statements")
    parser.add_argument("problem", nargs="?", help="Math problem text to parse")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--url", default=DEFAULT_OLLAMA_URL, help="Ollama API URL")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    qp = QueryParser(model=args.model, ollama_url=args.url)

    if args.problem:
        result = qp.parse(args.problem)
        print(f"\nProblem: {args.problem}")
        print(f"Concepts: {result.concepts}")
        if result.error:
            print(f"Error: {result.error}")
    else:
        # Demo mode
        test_problems = [
            "Find the greatest common divisor of 48 and 18.",
            "Evaluate $\\int_0^1 x^2 dx$.",
            "If $f(x) = x^2 + 3x - 5$, find $f(2)$.",
            "What is the sum of the first 100 positive integers?",
        ]

        print("\n" + "=" * 60)
        print("Query Parser Demo - Mathematical Concept Extraction")
        print("=" * 60)

        for problem in test_problems:
            result = qp.parse(problem)
            print(f"\nProblem: {problem}")
            print(f"Concepts: {result.concepts}")
            if result.error:
                print(f"Error: {result.error}")
