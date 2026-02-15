# %%
# Cell 1: Environment Setup
"""
Combines BM25 (lexical) + Dense Embedding (semantic) retrieval with
Reciprocal Rank Fusion (RRF) to retrieve top-50 OpenMath candidates.

Key Steps:
1. Test manual queries for expected symbol retrieval
2. Load Phase 2a concepts from data/math500-concepts.json
3. Run batch retrieval on MATH 500 problems
4. Analyze retrieval statistics (RRF scores, coverage, etc.)
5. Save results to data/openmath-retrieved.json

Output Files:
    - data/openmath-retrieved.md
    - data/openmath-retrieved.json (top-50 candidates per problem)

Usage:
    # CLI: Run with default settings (10 problems)
    python pipeline/3_hybrid_retrieval.py

    # CLI: Run with more problems
    python pipeline/3_hybrid_retrieval.py --n-problems 50

    # CLI: Run ALL 500 problems and save to JSON
    python pipeline/3_hybrid_retrieval.py --all

    # CLI: Test mode only (manual queries only)
    python pipeline/3_hybrid_retrieval.py --test-mode

    # Jupyter: Run cells 1-11 sequentially

Date: 2026-02-03
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Project root detection
PROJECT_ROOT = Path.cwd()
if PROJECT_ROOT.name == "experiments":
    PROJECT_ROOT = PROJECT_ROOT.parent

# Add src to path
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# Define early: Check if running in Jupyter/interactive mode
def _is_jupyter_mode():
    """Check if running in Jupyter/IPython mode."""
    try:
        shell = get_ipython().__class__.__name__  # type: ignore
        return shell in ["ZMQInteractiveShell", "TerminalInteractiveShell"]
    except NameError:
        pass
    return "ipykernel" in sys.modules


# Only print in Jupyter mode
if _is_jupyter_mode():
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python: {sys.executable}")

# %%
# Cell 2: Configuration
# ============================================================================
# MODIFY THESE PARAMETERS TO CONFIGURE THE TEST
# ============================================================================

# --- Embedding Model Settings ---
EMBEDDING_MODEL = "qwen3-embedding:4b"  # Dense embedding model via Ollama
OLLAMA_URL = "http://localhost:11434"  # Ollama API base URL

# --- Retrieval Parameters ---
TOP_K = 50  # Number of candidates to retrieve per problem
BM25_WEIGHT = 0.5  # Weight for BM25 scores in RRF
DENSE_WEIGHT = 0.5  # Weight for dense embedding scores in RRF
RRF_K = 60  # RRF constant (standard value)

# --- Test Parameters ---
N_PROBLEMS = 10  # Number of MATH 500 problems to process
SEED = 42  # Random seed for problem sampling

# --- Test Mode ---
# Set to True to run only manual test queries (faster, for debugging)
# Set to False to also run on MATH 500 problems
TEST_MODE = False

# --- File Paths ---
KB_PATH = PROJECT_ROOT / "data" / "openmath.json"
CONCEPTS_JSON_PATH = PROJECT_ROOT / "data" / "math500-concepts.json"
OUTPUT_JSON_PATH = PROJECT_ROOT / "data" / "openmath-retrieved.json"
REPORT_DIR = PROJECT_ROOT / ".local" / "tests"

# ============================================================================
# Print current configuration (only in Jupyter mode)
if _is_jupyter_mode():
    print("=" * 70)
    print("PHASE 3: HYBRID RETRIEVAL (RECALL LAYER)")
    print("=" * 70)
    print(f"Embedding model: {EMBEDDING_MODEL}")
    print(f"Ollama URL:      {OLLAMA_URL}")
    print(f"Top K:           {TOP_K}")
    print(f"BM25 weight:     {BM25_WEIGHT}")
    print(f"Dense weight:    {DENSE_WEIGHT}")
    print(f"RRF K:           {RRF_K}")
    print(f"N problems:      {N_PROBLEMS}")
    print(f"Seed:            {SEED}")
    print(f"Test mode:       {TEST_MODE}")
    print(f"KB path:         {KB_PATH}")
    print(f"Concepts path:   {CONCEPTS_JSON_PATH}")
    print(f"Output path:     {OUTPUT_JSON_PATH}")
    print("=" * 70)

# %%
# Cell 3: Test Queries for Manual Verification
"""Define test queries with expected OpenMath symbols."""

# Test queries with expected symbols for validation
TEST_QUERIES = [
    {
        "id": "test_gcd",
        "concepts": ["greatest common divisor", "gcd", "integer", "number theory"],
        "expected_symbols": ["arith1:gcd", "integer1:factorof"],
        "description": "GCD/HCF query",
    },
    {
        "id": "test_integral",
        "concepts": ["integral", "integration", "calculus", "definite integral"],
        "expected_symbols": ["calculus1:int", "calculus1:defint"],
        "description": "Integration query",
    },
    {
        "id": "test_sine",
        "concepts": ["sine", "sin", "trigonometry", "angle"],
        "expected_symbols": ["transc1:sin", "transc1:cos"],
        "description": "Trigonometric functions",
    },
    {
        "id": "test_factorial",
        "concepts": ["factorial", "permutation", "combinatorics"],
        "expected_symbols": ["integer1:factorial", "combinat1:binomial"],
        "description": "Factorial/combinatorics",
    },
    {
        "id": "test_derivative",
        "concepts": ["derivative", "differentiation", "calculus", "chain rule"],
        "expected_symbols": ["calculus1:diff", "calculus1:partialdiff"],
        "description": "Differentiation",
    },
    {
        "id": "test_matrix",
        "concepts": ["matrix", "determinant", "linear algebra"],
        "expected_symbols": ["linalg1:determinant", "linalg1:matrix_selector"],
        "description": "Matrix operations",
    },
    {
        "id": "test_logarithm",
        "concepts": ["logarithm", "log", "natural log", "ln", "exponential"],
        "expected_symbols": ["transc1:log", "transc1:ln", "transc1:exp"],
        "description": "Logarithms/exponentials",
    },
    {
        "id": "test_binomial",
        "concepts": ["binomial coefficient", "combination", "choose", "n choose k"],
        "expected_symbols": ["combinat1:binomial"],
        "description": "Binomial coefficient",
    },
    {
        "id": "test_quadratic",
        "concepts": ["quadratic", "polynomial", "roots", "algebra", "equation"],
        "expected_symbols": ["poly:root", "relation1:eq", "arith1:power"],
        "description": "Quadratic equation",
    },
    {
        "id": "test_probability",
        "concepts": ["probability", "statistics", "random", "distribution"],
        "expected_symbols": ["s_dist1:mean", "s_data1:mean"],
        "description": "Probability/statistics",
    },
]

if _is_jupyter_mode():
    print(f"\nDefined {len(TEST_QUERIES)} test queries")

# %%
# Cell 4: Initialize HybridRetriever (Jupyter only)
"""Import and initialize the hybrid retriever."""

if _is_jupyter_mode():
    from hybrid_retriever import HybridRetriever, create_hybrid_retriever

    print(f"\n{'=' * 70}")
    print("INITIALIZING HYBRID RETRIEVER")
    print(f"{'=' * 70}")

    retriever = create_hybrid_retriever(
        project_root=PROJECT_ROOT,
        embedding_model=EMBEDDING_MODEL,
        ollama_url=OLLAMA_URL,
        rrf_k=RRF_K,
        use_normalized_fields=True,
    )

    print(f"\nHybridRetriever initialized:")
    print(f"  Embedding model: {retriever.embedding_model}")
    print(f"  BM25 weight: {BM25_WEIGHT} (used in retrieve calls)")
    print(f"  Dense weight: {DENSE_WEIGHT} (used in retrieve calls)")
    print(f"  RRF K: {retriever.rrf_k}")
    print(f"  Symbols loaded: {len(retriever.symbol_ids)}")
    print(f"  Embeddings shape: {retriever.embeddings.shape if retriever.embeddings is not None else 'None'}")

# %%
# Cell 5: Test Manual Queries (Jupyter only)
"""Test the retriever on manual test queries."""

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("MANUAL TEST QUERIES - HYBRID RETRIEVAL")
    print(f"{'=' * 70}")

    manual_results = []
    total_hits = 0
    total_expected = 0

    for i, test in enumerate(TEST_QUERIES, 1):
        print(f"\n[{i}/{len(TEST_QUERIES)}] {test['id']}: {test['description']}")
        print(f"  Concepts: {test['concepts']}")

        # Join concepts for query
        query = " ".join(test["concepts"])
        result = retriever.retrieve(query, top_k=TOP_K, bm25_weight=BM25_WEIGHT, dense_weight=DENSE_WEIGHT)

        manual_results.append({
            "test": test,
            "result": result,
        })

        # Check for expected symbols
        found_symbols = []
        for expected in test["expected_symbols"]:
            if expected in result.symbol_ids:
                found_symbols.append(expected)
                rank = result.symbol_ids.index(expected) + 1
                print(f"  ✓ Found {expected} at rank {rank}")
            else:
                print(f"  ✗ Missing {expected}")

        hits = len(found_symbols)
        expected = len(test["expected_symbols"])
        total_hits += hits
        total_expected += expected

        print(f"  Coverage: {hits}/{expected} ({100*hits/expected:.0f}%)")
        print(f"  Top-5 retrieved: {result.symbol_ids[:5]}")

    # Summary
    print(f"\n{'=' * 70}")
    print(f"MANUAL TEST SUMMARY: {total_hits}/{total_expected} expected symbols found ({100*total_hits/total_expected:.1f}%)")
    print(f"{'=' * 70}")

# %%
# Cell 6: Load Phase 2a Concepts (Jupyter only)
"""Load concepts extracted in Phase 2a from data/math500-concepts.json."""

if _is_jupyter_mode() and not TEST_MODE:
    print(f"\n{'=' * 70}")
    print("LOADING PHASE 2a CONCEPTS")
    print(f"{'=' * 70}")

    if not CONCEPTS_JSON_PATH.exists():
        print(f"ERROR: Concepts file not found: {CONCEPTS_JSON_PATH}")
        print("Please run Phase 2a first: python pipeline/2a_concept_extraction.py --all")
        concepts_data = {}
    else:
        with open(CONCEPTS_JSON_PATH, "r", encoding="utf-8") as f:
            concepts_data = json.load(f)

        print(f"Loaded concepts for {len(concepts_data)} problems")

        # Sample subset if needed
        import random
        random.seed(SEED)

        problem_ids = list(concepts_data.keys())
        if N_PROBLEMS < len(problem_ids):
            sampled_ids = random.sample(problem_ids, N_PROBLEMS)
        else:
            sampled_ids = problem_ids

        print(f"Selected {len(sampled_ids)} problems (seed={SEED})")

        # Show distribution by type
        type_counts = {}
        for pid in sampled_ids:
            ptype = concepts_data[pid].get("type", "unknown")
            type_counts[ptype] = type_counts.get(ptype, 0) + 1

        print("\nProblem type distribution:")
        for ptype, count in sorted(type_counts.items()):
            print(f"  {ptype}: {count}")

        # Show sample concepts
        print("\nSample concepts (first 3 problems):")
        for pid in sampled_ids[:3]:
            concepts = concepts_data[pid].get("concepts", [])
            print(f"  {pid}: {concepts[:5]}{'...' if len(concepts) > 5 else ''}")

# %%
# Cell 6.5: Load or Compute Concept Embeddings (Jupyter only)
"""Load cached concept embeddings or compute them if not available."""

concept_embeddings = None
concept_problem_ids = None

if _is_jupyter_mode() and not TEST_MODE and concepts_data:
    print(f"\n{'=' * 70}")
    print("LOADING/COMPUTING CONCEPT EMBEDDINGS")
    print(f"{'=' * 70}")

    # Prepare ALL concepts (not just sampled) for caching
    all_concepts_by_problem = {
        pid: concepts_data[pid].get("concepts", [])
        for pid in concepts_data.keys()
    }

    # Get cache path for current embedding model
    concept_cache_path = retriever.get_concept_embeddings_cache_path(CONCEPTS_JSON_PATH)
    print(f"Cache path: {concept_cache_path}")

    # Try to load cached embeddings
    cached = retriever.load_concept_embeddings(concept_cache_path, all_concepts_by_problem)

    if cached is not None:
        concept_embeddings, concept_problem_ids = cached
        print(f"Loaded cached embeddings: shape {concept_embeddings.shape}")
    else:
        print("Cache not found, computing concept embeddings...")

        # Progress callback
        def embed_progress(current, total):
            print(f"\r[{current}/{total}] Embedding concepts...", end="", flush=True)

        # Compute and cache
        start_time = time.time()
        concept_embeddings, concept_problem_ids = retriever.compute_concept_embeddings(
            concepts_by_problem=all_concepts_by_problem,
            cache_path=concept_cache_path,
            progress_callback=embed_progress,
        )
        elapsed = time.time() - start_time

        print(f"\n\nComputed {len(concept_problem_ids)} concept embeddings in {elapsed:.1f}s")
        print(f"Saved to: {concept_cache_path}")

# %%
# Cell 7: Run Batch Retrieval (Jupyter only)
"""Run hybrid retrieval on sampled MATH 500 problems."""

if _is_jupyter_mode() and not TEST_MODE and concepts_data:
    print(f"\n{'=' * 70}")
    print("RUNNING BATCH RETRIEVAL")
    print(f"{'=' * 70}")

    # Prepare concepts for batch retrieval
    concepts_by_problem = {
        pid: concepts_data[pid].get("concepts", [])
        for pid in sampled_ids
    }

    start_time = time.time()

    # Progress callback
    def print_progress(current, total):
        print(f"\r[{current}/{total}] Retrieving...", end="", flush=True)

    # Run batch retrieval with cached embeddings
    batch_results = retriever.retrieve_batch(
        concepts_by_problem=concepts_by_problem,
        top_k=TOP_K,
        bm25_weight=BM25_WEIGHT,
        dense_weight=DENSE_WEIGHT,
        progress_callback=print_progress,
        concept_embeddings=concept_embeddings,
        concept_problem_ids=concept_problem_ids,
    )

    elapsed = time.time() - start_time
    print(f"\n\nRetrieved candidates for {len(batch_results)} problems in {elapsed:.1f}s")
    print(f"Average time per problem: {elapsed/len(batch_results):.2f}s")

# %%
# Cell 8: Statistics Analysis (Jupyter only)
"""Analyze retrieval statistics."""

if _is_jupyter_mode() and not TEST_MODE and concepts_data and 'batch_results' in dir():
    print(f"\n{'=' * 70}")
    print("RETRIEVAL STATISTICS")
    print(f"{'=' * 70}")

    # Collect statistics
    all_symbols = []
    score_stats = []
    symbols_per_problem = []

    for pid, result in batch_results.items():
        all_symbols.extend(result.symbol_ids)
        symbols_per_problem.append(len(result.symbol_ids))
        if result.scores:
            score_stats.extend(list(result.scores.values()))

    # Symbol frequency
    symbol_freq = {}
    for sym in all_symbols:
        symbol_freq[sym] = symbol_freq.get(sym, 0) + 1

    top_symbols = sorted(symbol_freq.items(), key=lambda x: -x[1])[:20]

    print("\nTop 20 most retrieved symbols:")
    for i, (symbol, freq) in enumerate(top_symbols, 1):
        print(f"  {i:2}. {symbol}: {freq}")

    # Score statistics
    if score_stats:
        import numpy as np
        scores_arr = np.array(score_stats)
        print(f"\nRRF Score statistics:")
        print(f"  Min: {scores_arr.min():.4f}")
        print(f"  Max: {scores_arr.max():.4f}")
        print(f"  Mean: {scores_arr.mean():.4f}")
        print(f"  Std: {scores_arr.std():.4f}")

    # Coverage statistics
    print(f"\nCoverage statistics:")
    print(f"  Avg symbols per problem: {sum(symbols_per_problem)/len(symbols_per_problem):.1f}")
    print(f"  Min symbols: {min(symbols_per_problem)}")
    print(f"  Max symbols: {max(symbols_per_problem)}")
    print(f"  Total unique symbols retrieved: {len(symbol_freq)}")

    # By problem type
    print(f"\nRetrieval by problem type:")
    results_by_type = {}
    for pid, result in batch_results.items():
        ptype = concepts_data[pid].get("type", "unknown")
        if ptype not in results_by_type:
            results_by_type[ptype] = []
        results_by_type[ptype].append(len(result.symbol_ids))

    for ptype, counts in sorted(results_by_type.items()):
        avg = sum(counts) / len(counts)
        print(f"  {ptype}: avg {avg:.1f} symbols ({len(counts)} problems)")

# %%
# Cell 9: Save Results to JSON (Jupyter only)
"""Save retrieval results to data/openmath-retrieved.json."""

if _is_jupyter_mode() and not TEST_MODE and concepts_data and 'batch_results' in dir():
    print(f"\n{'=' * 70}")
    print("SAVING RESULTS")
    print(f"{'=' * 70}")

    # Build output data structure
    output_data = {}

    for pid, result in batch_results.items():
        # Get concepts for this problem
        concepts = concepts_data[pid].get("concepts", [])

        # Build OpenMath object with symbol details
        openmath_dict = {}
        for symbol_id in result.symbol_ids:
            symbol_data = retriever.get_symbol(symbol_id)
            if symbol_data:
                openmath_dict[symbol_id] = {
                    "name": symbol_data.get("name", ""),
                    "cd": symbol_data.get("cd", ""),
                    "description_normalized": symbol_data.get("description_normalized", symbol_data.get("description", "")),
                    "cmp_properties_normalized": symbol_data.get("cmp_properties_normalized", symbol_data.get("cmp_properties", [])),
                    "examples_normalized": symbol_data.get("examples_normalized", symbol_data.get("examples", [])),
                    "rrf_score": result.scores.get(symbol_id, 0.0),
                }

        output_data[pid] = {
            "concepts": concepts,
            "openmath": openmath_dict,
        }

    # Save to JSON
    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"Results saved to: {OUTPUT_JSON_PATH}")
    print(f"Total problems: {len(output_data)}")

    # Show file size
    file_size = OUTPUT_JSON_PATH.stat().st_size
    print(f"File size: {file_size / 1024 / 1024:.2f} MB")

# %%
# Cell 10: Generate Report (Jupyter only)
"""Generate markdown report for Phase 3 results."""

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("GENERATING REPORT")
    print(f"{'=' * 70}")

    # Create report directory
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate filename
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    report_file = REPORT_DIR / f"phase-3_hybrid_retrieval_{timestamp}.md"

    # Build markdown content
    lines = [
        "# Phase 3: Hybrid Retrieval Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Embedding Model**: {EMBEDDING_MODEL}",
        "",
        "## Configuration",
        "",
        f"- Embedding Model: `{EMBEDDING_MODEL}`",
        f"- Ollama URL: `{OLLAMA_URL}`",
        f"- Top K: {TOP_K}",
        f"- BM25 Weight: {BM25_WEIGHT}",
        f"- Dense Weight: {DENSE_WEIGHT}",
        f"- RRF K: {RRF_K}",
        "",
        "## Manual Test Results",
        "",
    ]

    # Manual test results
    for r in manual_results:
        test = r["test"]
        result = r["result"]
        found = [s for s in test["expected_symbols"] if s in result.symbol_ids]
        coverage = len(found) / len(test["expected_symbols"]) * 100 if test["expected_symbols"] else 0
        status = "✓" if coverage >= 50 else "✗"

        lines.append(f"### {test['id']}: {test['description']} {status}")
        lines.append("")
        lines.append(f"**Concepts**: {test['concepts']}")
        lines.append("")
        lines.append(f"**Expected**: {test['expected_symbols']}")
        lines.append("")
        lines.append(f"**Found**: {found} ({coverage:.0f}% coverage)")
        lines.append("")
        lines.append(f"**Top 10 Retrieved**: {result.symbol_ids[:10]}")
        lines.append("")

    # Summary line
    lines.append(f"**Overall Coverage**: {total_hits}/{total_expected} ({100*total_hits/total_expected:.1f}%)")
    lines.append("")

    # MATH 500 results
    if not TEST_MODE and concepts_data and 'batch_results' in dir():
        lines.extend([
            "## MATH 500 Batch Retrieval Results",
            "",
            f"**Problems Processed**: {len(batch_results)}",
            f"**Avg Symbols/Problem**: {sum(symbols_per_problem)/len(symbols_per_problem):.1f}",
            f"**Total Unique Symbols**: {len(symbol_freq)}",
            "",
            "### Top 20 Retrieved Symbols",
            "",
        ])

        for i, (symbol, freq) in enumerate(top_symbols, 1):
            lines.append(f"{i}. `{symbol}`: {freq}")

        lines.extend([
            "",
            "### Sample Results",
            "",
        ])

        # Show first 5 results
        for pid in list(batch_results.keys())[:5]:
            result = batch_results[pid]
            concepts = concepts_data[pid].get("concepts", [])
            ptype = concepts_data[pid].get("type", "unknown")
            level = concepts_data[pid].get("level", "?")

            lines.append(f"#### {pid} ({ptype}, Level {level})")
            lines.append("")
            lines.append(f"**Concepts**: {concepts}")
            lines.append("")
            lines.append(f"**Top 10 Symbols**: {result.symbol_ids[:10]}")
            lines.append("")

    # Write file
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Report saved to: {report_file}")

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("PHASE 3 COMPLETE")
    print(f"{'=' * 70}")

# %%
# Cell 11: CLI Entry Point
"""Command-line interface for running Phase 3."""


def main():
    """Main CLI entry point."""
    import argparse
    import random

    arg_parser = argparse.ArgumentParser(
        description="Phase 3: Hybrid Retrieval (Recall Layer)"
    )
    arg_parser.add_argument(
        "--n-problems",
        type=int,
        default=N_PROBLEMS,
        help=f"Number of MATH 500 problems to process (default: {N_PROBLEMS})",
    )
    arg_parser.add_argument(
        "--embedding-model",
        default=EMBEDDING_MODEL,
        help=f"Ollama embedding model (default: {EMBEDDING_MODEL})",
    )
    arg_parser.add_argument(
        "--url",
        default=OLLAMA_URL,
        help=f"Ollama API URL (default: {OLLAMA_URL})",
    )
    arg_parser.add_argument(
        "--top-k",
        type=int,
        default=TOP_K,
        help=f"Number of candidates to retrieve (default: {TOP_K})",
    )
    arg_parser.add_argument(
        "--bm25-weight",
        type=float,
        default=BM25_WEIGHT,
        help=f"BM25 weight in RRF (default: {BM25_WEIGHT})",
    )
    arg_parser.add_argument(
        "--dense-weight",
        type=float,
        default=DENSE_WEIGHT,
        help=f"Dense weight in RRF (default: {DENSE_WEIGHT})",
    )
    arg_parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help=f"Random seed (default: {SEED})",
    )
    arg_parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run only manual test queries (skip MATH 500)",
    )
    arg_parser.add_argument(
        "--all",
        action="store_true",
        help="Process ALL 500 problems (overrides --n-problems)",
    )
    arg_parser.add_argument(
        "--output-json",
        default=str(OUTPUT_JSON_PATH),
        help=f"Output JSON file path (default: {OUTPUT_JSON_PATH})",
    )
    arg_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = arg_parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Print configuration
    print("=" * 70)
    print("PHASE 3: HYBRID RETRIEVAL (RECALL LAYER)")
    print("=" * 70)
    print(f"Embedding model: {args.embedding_model}")
    print(f"Ollama URL:      {args.url}")
    print(f"Top K:           {args.top_k}")
    print(f"BM25 weight:     {args.bm25_weight}")
    print(f"Dense weight:    {args.dense_weight}")
    print(f"N problems:      {'ALL (500)' if args.all else args.n_problems}")
    print(f"Seed:            {args.seed}")
    print(f"Test mode:       {args.test_mode}")
    print(f"Output JSON:     {args.output_json}")
    print("=" * 70)

    # Import retriever
    from hybrid_retriever import create_hybrid_retriever

    print("\nInitializing HybridRetriever...")
    retriever = create_hybrid_retriever(
        project_root=PROJECT_ROOT,
        embedding_model=args.embedding_model,
        ollama_url=args.url,
        rrf_k=RRF_K,
        use_normalized_fields=True,
    )

    print(f"  Symbols loaded: {len(retriever.symbol_ids)}")
    print(f"  Embeddings shape: {retriever.embeddings.shape if retriever.embeddings is not None else 'None'}")

    # Run manual tests
    print(f"\n--- Manual Test Queries ---")

    total_hits = 0
    total_expected = 0
    manual_results = []

    for i, test in enumerate(TEST_QUERIES, 1):
        print(f"\n[{i}/{len(TEST_QUERIES)}] {test['id']}: {test['description']}")

        query = " ".join(test["concepts"])
        result = retriever.retrieve(query, top_k=args.top_k, bm25_weight=args.bm25_weight, dense_weight=args.dense_weight)
        manual_results.append({"test": test, "result": result})

        found = [s for s in test["expected_symbols"] if s in result.symbol_ids]
        hits = len(found)
        expected = len(test["expected_symbols"])
        total_hits += hits
        total_expected += expected

        print(f"  Found: {found} ({hits}/{expected})")
        print(f"  Top 5: {result.symbol_ids[:5]}")

    print(f"\nManual test coverage: {total_hits}/{total_expected} ({100*total_hits/total_expected:.1f}%)")

    if args.test_mode:
        print("\n[TEST MODE] Skipping MATH 500 problems")
        print("\n" + "=" * 70)
        print("PHASE 3 COMPLETE")
        print("=" * 70)
        return

    # Load Phase 2a concepts
    print(f"\n--- Loading Phase 2a Concepts ---")

    concepts_path = Path(CONCEPTS_JSON_PATH)
    if not concepts_path.exists():
        print(f"ERROR: Concepts file not found: {concepts_path}")
        print("Please run Phase 2a first: python pipeline/2a_concept_extraction.py --all")
        return

    with open(concepts_path, "r", encoding="utf-8") as f:
        concepts_data = json.load(f)

    print(f"Loaded concepts for {len(concepts_data)} problems")

    # Prepare ALL concepts for caching
    all_concepts_by_problem = {
        pid: concepts_data[pid].get("concepts", [])
        for pid in concepts_data.keys()
    }

    # Load or compute concept embeddings
    print(f"\n--- Loading/Computing Concept Embeddings ---")
    concept_cache_path = retriever.get_concept_embeddings_cache_path(concepts_path)
    print(f"Cache path: {concept_cache_path}")

    cached = retriever.load_concept_embeddings(concept_cache_path, all_concepts_by_problem)
    if cached is not None:
        concept_embeddings, concept_problem_ids = cached
        print(f"Loaded cached embeddings: shape {concept_embeddings.shape}")
    else:
        print("Cache not found, computing concept embeddings...")

        def embed_progress(current, total):
            print(f"\r[{current}/{total}] Embedding concepts...", end="", flush=True)

        start_time = time.time()
        concept_embeddings, concept_problem_ids = retriever.compute_concept_embeddings(
            concepts_by_problem=all_concepts_by_problem,
            cache_path=concept_cache_path,
            progress_callback=embed_progress,
        )
        elapsed = time.time() - start_time
        print(f"\n\nComputed {len(concept_problem_ids)} concept embeddings in {elapsed:.1f}s")

    # Sample problems
    problem_ids = list(concepts_data.keys())
    if args.all:
        sampled_ids = problem_ids
    else:
        random.seed(args.seed)
        sampled_ids = random.sample(problem_ids, min(args.n_problems, len(problem_ids)))

    print(f"\nProcessing {len(sampled_ids)} problems...")

    # Prepare concepts for batch retrieval
    concepts_by_problem = {
        pid: concepts_data[pid].get("concepts", [])
        for pid in sampled_ids
    }

    # Run batch retrieval with cached embeddings
    def print_progress(current, total):
        print(f"\r[{current}/{total}] Retrieving...", end="", flush=True)

    start_time = time.time()
    batch_results = retriever.retrieve_batch(
        concepts_by_problem=concepts_by_problem,
        top_k=args.top_k,
        bm25_weight=args.bm25_weight,
        dense_weight=args.dense_weight,
        progress_callback=print_progress,
        concept_embeddings=concept_embeddings,
        concept_problem_ids=concept_problem_ids,
    )
    elapsed = time.time() - start_time

    print(f"\n\nRetrieved candidates for {len(batch_results)} problems in {elapsed:.1f}s")

    # Statistics
    all_symbols = []
    symbols_per_problem = []

    for pid, result in batch_results.items():
        all_symbols.extend(result.symbol_ids)
        symbols_per_problem.append(len(result.symbol_ids))

    symbol_freq = {}
    for sym in all_symbols:
        symbol_freq[sym] = symbol_freq.get(sym, 0) + 1

    top_symbols = sorted(symbol_freq.items(), key=lambda x: -x[1])[:15]

    print(f"\nAvg symbols/problem: {sum(symbols_per_problem)/len(symbols_per_problem):.1f}")
    print(f"Total unique symbols: {len(symbol_freq)}")

    print(f"\nTop 15 retrieved symbols:")
    for i, (symbol, freq) in enumerate(top_symbols, 1):
        print(f"  {i:2}. {symbol}: {freq}")

    # Save results
    print(f"\n--- Saving Results ---")

    output_data = {}
    for pid, result in batch_results.items():
        concepts = concepts_data[pid].get("concepts", [])

        openmath_dict = {}
        for symbol_id in result.symbol_ids:
            symbol_data = retriever.get_symbol(symbol_id)
            if symbol_data:
                openmath_dict[symbol_id] = {
                    "name": symbol_data.get("name", ""),
                    "cd": symbol_data.get("cd", ""),
                    "description_normalized": symbol_data.get("description_normalized", symbol_data.get("description", "")),
                    "cmp_properties_normalized": symbol_data.get("cmp_properties_normalized", symbol_data.get("cmp_properties", [])),
                    "examples_normalized": symbol_data.get("examples_normalized", symbol_data.get("examples", [])),
                    "rrf_score": result.scores.get(symbol_id, 0.0),
                }

        output_data[pid] = {
            "concepts": concepts,
            "openmath": openmath_dict,
        }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"Results saved to: {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")

    # Save report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    report_file = REPORT_DIR / f"phase-3_hybrid_retrieval_{timestamp}.md"

    lines = [
        "# Phase 3: Hybrid Retrieval Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Embedding Model**: {args.embedding_model}",
        "",
        "## Statistics",
        "",
        f"- Problems processed: {len(batch_results)}",
        f"- Avg symbols/problem: {sum(symbols_per_problem)/len(symbols_per_problem):.1f}",
        f"- Total unique symbols: {len(symbol_freq)}",
        f"- Manual test coverage: {total_hits}/{total_expected} ({100*total_hits/total_expected:.1f}%)",
        "",
        "## Top 15 Retrieved Symbols",
        "",
    ]

    for i, (symbol, freq) in enumerate(top_symbols, 1):
        lines.append(f"{i}. `{symbol}`: {freq}")

    lines.extend(["", "## Sample Results", ""])

    for pid in list(batch_results.keys())[:10]:
        result = batch_results[pid]
        concepts = concepts_data[pid].get("concepts", [])
        ptype = concepts_data[pid].get("type", "unknown")
        level = concepts_data[pid].get("level", "?")

        lines.append(f"### {pid} ({ptype}, Level {level})")
        lines.append("")
        lines.append(f"**Concepts**: {concepts}")
        lines.append("")
        lines.append(f"**Top 10 Symbols**: {result.symbol_ids[:10]}")
        lines.append("")

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Report saved to: {report_file}")

    print("\n" + "=" * 70)
    print("PHASE 3 COMPLETE")
    print("=" * 70)


# Only run CLI when executed directly (not in Jupyter)
if __name__ == "__main__" and not _is_jupyter_mode():
    main()
