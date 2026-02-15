#!/usr/bin/env python3
"""
Computes and caches embeddings for all OpenMath symbols using the specified
embedding model via Ollama. Requires data/openmath.json from Phase 1b.

Usage:
    python pipeline/1c_generate_knowledge_base_embeddings.py
    python pipeline/1c_generate_knowledge_base_embeddings.py --model qwen3-embedding:4b
    python pipeline/1c_generate_knowledge_base_embeddings.py --force

Output:
    data/openmath-embeddings_<MODEL>.npy
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

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_MODEL = "qwen3-embedding:4b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"

# Non-mathematical CDs to exclude
NON_MATHEMATICAL_CDS = {
    "meta", "metagrp", "metasig", "error", "scscp1", "scscp2",
    "altenc", "mathmlattr", "sts", "mathmltypes",
}


def get_cache_path(data_dir: Path, model: str) -> Path:
    """Get cache file path for the embedding model."""
    safe_model = model.replace(":", "_").replace("/", "_")
    return data_dir / f"openmath-embeddings_{safe_model}.npy"


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


def get_embedding_text(symbol: dict, use_normalized: bool = True) -> str:
    """Get text to embed for a symbol."""
    parts = [symbol.get("name", "")]

    if use_normalized:
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
    else:
        if desc := symbol.get("description"):
            parts.append(desc)
        if props := symbol.get("cmp_properties"):
            if isinstance(props, list):
                parts.extend(props)
            else:
                parts.append(str(props))

    return " ".join(parts)


def load_symbols(kb_path: Path, filter_non_math: bool = True) -> list[dict]:
    """Load symbols from knowledge base."""
    with open(kb_path) as f:
        kb = json.load(f)

    symbols = list(kb.get("symbols", {}).values())

    if filter_non_math:
        symbols = [s for s in symbols if s.get("cd", "") not in NON_MATHEMATICAL_CDS]

    return symbols


def main():
    parser = argparse.ArgumentParser(
        description="Generate OpenMath symbol embeddings",
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
        "--include-non-math",
        action="store_true",
        help="Include non-mathematical CDs (meta, error, etc.)",
    )

    args = parser.parse_args()

    # Paths
    project_root = Path(__file__).parent.parent
    kb_path = project_root / "data" / "openmath.json"
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

    # Check KB exists
    if not kb_path.exists():
        logger.error(f"Knowledge base not found: {kb_path}")
        return 1

    # Load symbols
    logger.info(f"Loading symbols from {kb_path}...")
    symbols = load_symbols(kb_path, filter_non_math=not args.include_non_math)
    logger.info(f"Loaded {len(symbols)} symbols")

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

    for i, symbol in enumerate(symbols):
        text = get_embedding_text(symbol)

        try:
            embedding = embed_text(text, args.model, args.url)
            embeddings.append(embedding)

            if (i + 1) % 100 == 0:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                remaining = (len(symbols) - i - 1) / rate
                logger.info(
                    f"[{i + 1}/{len(symbols)}] "
                    f"{rate:.1f} symbols/s, ~{remaining:.0f}s remaining"
                )
        except Exception as e:
            logger.error(f"Failed to embed {symbol.get('id', 'unknown')}: {e}")
            # Use zero vector as fallback
            if embeddings:
                embeddings.append(np.zeros_like(embeddings[0]))
            else:
                raise

        time.sleep(0.01)  # Rate limiting

    elapsed = time.time() - start_time
    logger.info(f"Computed {len(embeddings)} embeddings in {elapsed:.1f}s")

    # Save embeddings
    embeddings_array = np.array(embeddings, dtype=np.float32)
    np.save(cache_path, embeddings_array)

    logger.info(f"Saved embeddings to: {cache_path}")
    logger.info(f"  Shape: {embeddings_array.shape}")
    logger.info(f"  Size: {cache_path.stat().st_size / 1024 / 1024:.1f} MB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
