#!/usr/bin/env python3
"""
Computes and caches embeddings for MATH 500 problem concepts using the
specified embedding model via Ollama. Requires data/math500-concepts.json
from Phase 2a.

Usage:
    python pipeline/2b_generate_concept_embeddings.py
    python pipeline/2b_generate_concept_embeddings.py --model qwen3-embedding:4b
    python pipeline/2b_generate_concept_embeddings.py --force

Output:
    data/math500-concepts-embeddings_<MODEL>.npy
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_MODEL = "qwen3-embedding:4b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"


def get_cache_path(data_dir: Path, model: str) -> Path:
    """Get cache file path for the embedding model."""
    safe_model = model.replace(":", "_").replace("/", "_")
    return data_dir / f"math500-concepts-embeddings_{safe_model}.npy"


def embed_text(text: str, model: str, ollama_url: str) -> np.ndarray:
    """Embed text using Ollama API."""
    response = requests.post(
        f"{ollama_url}/api/embed",
        json={"model": model, "input": text},
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return np.array(data["embeddings"][0], dtype=np.float32)


def main():
    parser = argparse.ArgumentParser(
        description="Generate MATH 500 concept embeddings",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--model", "-m",
        default=DEFAULT_MODEL,
        help=f"Embedding model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_OLLAMA_URL,
        help=f"Ollama API URL (default: {DEFAULT_OLLAMA_URL})",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Force regeneration even if cache exists",
    )
    parser.add_argument(
        "--concepts-file",
        type=Path,
        help="Path to concepts JSON (default: data/math500-concepts.json)",
    )

    args = parser.parse_args()

    # Paths
    project_root = Path(__file__).parent.parent
    concepts_path = args.concepts_file or (project_root / "data" / "math500-concepts.json")
    cache_path = get_cache_path(project_root / "data", args.model)

    # Check if cache exists
    if cache_path.exists() and not args.force:
        logger.info(f"Cache already exists: {cache_path}")
        logger.info("Use --force to regenerate")

        # Show info about existing cache
        embeddings = np.load(cache_path)
        logger.info(f"  Shape: {embeddings.shape}")
        logger.info(f"  Size: {cache_path.stat().st_size / 1024 / 1024:.1f} MB")
        return 0

    # Check concepts file exists
    if not concepts_path.exists():
        logger.error(f"Concepts file not found: {concepts_path}")
        logger.error("Run Phase 2a first: python pipeline/2a_concept_extraction.py --all")
        return 1

    # Load concepts
    logger.info(f"Loading concepts from {concepts_path}...")
    with open(concepts_path) as f:
        concepts_data = json.load(f)

    # Sort problem IDs for deterministic ordering
    problem_ids = sorted(concepts_data.keys())
    logger.info(f"Loaded concepts for {len(problem_ids)} problems")

    # Test Ollama connectivity
    logger.info(f"Testing connection to {args.url}...")
    try:
        test_response = requests.get(f"{args.url}/api/tags", timeout=5)
        test_response.raise_for_status()
    except Exception as e:
        logger.error(f"Cannot connect to Ollama: {e}")
        logger.error("Make sure Ollama is running: ollama serve")
        return 1

    # Compute embeddings
    logger.info(f"Computing embeddings with {args.model}...")
    embeddings = []
    start_time = time.time()

    for i, problem_id in enumerate(problem_ids):
        concepts = concepts_data[problem_id].get("concepts", [])
        query = " ".join(concepts)

        try:
            embedding = embed_text(query, args.model, args.url)
            embeddings.append(embedding)

            if (i + 1) % 50 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                remaining = (len(problem_ids) - i - 1) / rate
                logger.info(
                    f"[{i + 1}/{len(problem_ids)}] "
                    f"{rate:.1f} problems/s, ~{remaining:.0f}s remaining"
                )
        except Exception as e:
            logger.error(f"Failed to embed {problem_id}: {e}")
            # Use zero vector as fallback
            if embeddings:
                embeddings.append(np.zeros_like(embeddings[0]))
            else:
                raise

        time.sleep(0.02)  # Rate limiting

    elapsed = time.time() - start_time
    logger.info(f"Computed {len(embeddings)} embeddings in {elapsed:.1f}s")

    # Save embeddings
    embeddings_array = np.array(embeddings, dtype=np.float32)
    np.save(cache_path, embeddings_array)

    logger.info(f"Saved embeddings to: {cache_path}")
    logger.info(f"  Shape: {embeddings_array.shape}")
    logger.info(f"  Size: {cache_path.stat().st_size / 1024 / 1024:.1f} MB")

    # Print usage hint
    logger.info("")
    logger.info("To use these embeddings in HybridRetriever:")
    logger.info("  embeddings = np.load(cache_path)")
    logger.info("  problem_ids = sorted(concepts_data.keys())")

    return 0


if __name__ == "__main__":
    sys.exit(main())
