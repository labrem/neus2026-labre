# %%
# Cell 1: Environment Setup
"""
Filters and ranks Phase 3 candidates using a cross-encoder model
to eliminate irrelevant "domain overreach" symbols.

Supported Backends:
- vllm: Qwen3-Reranker-0.6B via vLLM pooling server (recommended)

Key Steps:
1. Test manual problem-symbol pairs for relevance scoring
2. Load Phase 3 candidates from data/openmath-retrieved.json
3. Load MATH 500 problem statements via BenchmarkLoader
4. Run batch reranking with threshold filtering
5. Analyze reranking statistics (score distributions, filtering rates)
6. Save results to data/openmath-reranked.json

Output Files:
    - .local/tests/phase-4_cross_encoder_reranking_<timestamp>.md
    - data/openmath-reranked.json (filtered candidates per problem)

Usage:
    # CLI: Run with vLLM backend (default, recommended)
    python pipeline/4_cross_encoder_reranking.py --backend vllm

    # CLI: Run with Ollama backend
    python pipeline/4_cross_encoder_reranking.py --backend ollama

    # CLI: Run with more problems
    python pipeline/4_cross_encoder_reranking.py --n-problems 50

    # CLI: Run ALL 500 problems (full run)
    python pipeline/4_cross_encoder_reranking.py --all

    # CLI: Test mode only (manual queries only)
    python pipeline/4_cross_encoder_reranking.py --test-mode

    # Jupyter: Run cells 1-12 sequentially

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

# --- Backend Selection ---
# "vllm"   - Qwen3-Reranker via vLLM pooling server (recommended, accurate)
#            Requires: ./scripts/start_vllm_server.sh --model Qwen/Qwen3-Reranker-0.6B --runner pooling --port 9001 --hf-overrides '{"architectures":["Qwen3ForSequenceClassification"],"classifier_from_token":["no","yes"],"is_original_qwen3_reranker":true}'
# "ollama" - gemma2:2b via Ollama (legacy, slower but no server setup)
# "cross-encoder" - sentence-transformers CrossEncoder (local, fast)
BACKEND = "vllm"  # Options: "vllm", "ollama", "cross-encoder"

# --- Reranker Model Settings ---
# For vLLM backend:
VLLM_RERANKER_MODEL = "Qwen/Qwen3-Reranker-0.6B"
VLLM_RERANKER_URL = "http://localhost:9001"

# For Ollama backend (legacy):
# Note: Original spec was dengcao/qwen3-reranker:0.6b, but it has a reasoning mode
# that prevents simple score output. gemma2:2b provides reliable JSON-mode scoring.
OLLAMA_MODEL = "gemma2:2b"
OLLAMA_URL = "http://localhost:11434"

# For cross-encoder backend:
CROSS_ENCODER_MODEL = "mixedbread-ai/mxbai-rerank-large-v1"

# --- Reranking Parameters ---
# Threshold varies by backend:
#   vllm/cross-encoder: 0.15 (models output calibrated scores)
#   ollama: 0.7 (LLM-based scoring, different scale)
THRESHOLD = 0.15 if BACKEND in ("vllm", "cross-encoder") else 0.7
MIN_KEEP = 3  # Minimum candidates to always keep (regardless of threshold)
MAX_TOKENS = 50  # For Ollama backend only
TEMPERATURE = 0.0  # For Ollama backend only

# --- Test Parameters ---
N_PROBLEMS = 10  # Number of MATH 500 problems to process
SEED = 42  # Random seed for problem sampling

# --- Test Mode ---
# Set to True to run only manual test queries (faster, for debugging)
# Set to False to also run on MATH 500 problems
TEST_MODE = False

# --- File Paths ---
RETRIEVED_JSON_PATH = PROJECT_ROOT / "data" / "openmath-retrieved.json"
OUTPUT_JSON_PATH = PROJECT_ROOT / "data" / "openmath-reranked.json"
REPORT_DIR = PROJECT_ROOT / ".local" / "tests"

# ============================================================================
# Print current configuration (only in Jupyter mode)
if _is_jupyter_mode():
    print("=" * 70)
    print("PHASE 4: CROSS-ENCODER RERANKING (THE JUDGE)")
    print("=" * 70)
    print(f"Backend:        {BACKEND}")
    if BACKEND == "vllm":
        print(f"Model:          {VLLM_RERANKER_MODEL}")
        print(f"URL:            {VLLM_RERANKER_URL}")
    elif BACKEND == "ollama":
        print(f"Model:          {OLLAMA_MODEL}")
        print(f"URL:            {OLLAMA_URL}")
    else:
        print(f"Model:          {CROSS_ENCODER_MODEL}")
    print(f"Threshold:      {THRESHOLD}")
    print(f"Min keep:       {MIN_KEEP}")
    print(f"N problems:     {N_PROBLEMS}")
    print(f"Seed:           {SEED}")
    print(f"Test mode:      {TEST_MODE}")
    print(f"Retrieved path: {RETRIEVED_JSON_PATH}")
    print(f"Output path:    {OUTPUT_JSON_PATH}")
    print("=" * 70)

# %%
# Cell 3: Manual Test Cases
"""Define test cases with expected relevance behavior."""

# Test cases for manual verification of relevance scoring
# Each case has a problem and symbol(s) with expected behavior
TEST_CASES = [
    # High relevance expected
    {
        "id": "test_gcd_high",
        "problem": "Find the greatest common divisor of 48 and 18.",
        "symbol": {
            "name": "gcd",
            "cd": "arith1",
            "description_normalized": "The gcd function returns the greatest common divisor of two integers.",
            "cmp_properties_normalized": ["$\\gcd(a,b) = \\gcd(b, a \\mod b)$"],
            "examples_normalized": ["$\\gcd(6, 9) = 3$"],
        },
        "expected": "high",  # Should score >= threshold
        "description": "GCD symbol for GCD problem (high relevance)",
    },
    # Low relevance expected (domain overreach)
    {
        "id": "test_gcd_low",
        "problem": "Find the greatest common divisor of 48 and 18.",
        "symbol": {
            "name": "sin",
            "cd": "transc1",
            "description_normalized": "The sin function returns the sine of its argument.",
            "cmp_properties_normalized": ["$\\sin^2(x) + \\cos^2(x) = 1$"],
            "examples_normalized": ["$\\sin(\\pi) = 0$"],
        },
        "expected": "low",  # Should score < threshold
        "description": "Sin function for GCD problem (domain overreach)",
    },
    # High relevance expected
    {
        "id": "test_integral_high",
        "problem": "Evaluate the integral of x^2 from 0 to 1.",
        "symbol": {
            "name": "defint",
            "cd": "calculus1",
            "description_normalized": "The definite integral from a to b of a function.",
            "cmp_properties_normalized": ["$\\int_a^b f(x) dx = F(b) - F(a)$"],
            "examples_normalized": ["$\\int_0^1 x^2 dx = \\frac{1}{3}$"],
        },
        "expected": "high",
        "description": "Definite integral for integration problem (high relevance)",
    },
    # Low relevance expected
    {
        "id": "test_integral_low",
        "problem": "Evaluate the integral of x^2 from 0 to 1.",
        "symbol": {
            "name": "gcd",
            "cd": "arith1",
            "description_normalized": "The gcd function returns the greatest common divisor of two integers.",
            "cmp_properties_normalized": ["$\\gcd(a,b) = \\gcd(b, a \\mod b)$"],
            "examples_normalized": [],
        },
        "expected": "low",
        "description": "GCD for integration problem (domain overreach)",
    },
    # High relevance expected
    {
        "id": "test_binomial_high",
        "problem": "How many ways can you choose 3 items from a set of 10?",
        "symbol": {
            "name": "binomial",
            "cd": "combinat1",
            "description_normalized": "The binomial coefficient (n choose k).",
            "cmp_properties_normalized": ["$\\binom{n}{k} = \\frac{n!}{k!(n-k)!}$"],
            "examples_normalized": ["$\\binom{10}{3} = 120$"],
        },
        "expected": "high",
        "description": "Binomial coefficient for combination problem (high relevance)",
    },
    # Medium relevance (borderline)
    {
        "id": "test_factorial_medium",
        "problem": "How many ways can you choose 3 items from a set of 10?",
        "symbol": {
            "name": "factorial",
            "cd": "integer1",
            "description_normalized": "The factorial of a non-negative integer n.",
            "cmp_properties_normalized": ["$n! = n \\cdot (n-1)!$"],
            "examples_normalized": ["$5! = 120$"],
        },
        "expected": "medium",  # Related but not primary
        "description": "Factorial for combination problem (related)",
    },
]

if _is_jupyter_mode():
    print(f"\nDefined {len(TEST_CASES)} test cases")

# %%
# Cell 4: Initialize Reranker (Jupyter only)
"""Import and initialize the reranker based on selected backend."""

if _is_jupyter_mode():
    from reranker_cross_encoder import create_reranker, check_vllm_reranker_health

    print(f"\n{'=' * 70}")
    print(f"INITIALIZING RERANKER (backend={BACKEND})")
    print(f"{'=' * 70}")

    # Check vLLM server health if using vllm backend
    if BACKEND == "vllm":
        health = check_vllm_reranker_health(VLLM_RERANKER_URL)
        if not health["healthy"]:
            print(f"\n⚠️  WARNING: vLLM server not healthy!")
            print(f"   URL: {health['url']}")
            print(f"   Error: {health['error']}")
            print(f"\n   Start the server with:")
            print(f"   ./scripts/start_vllm_server.sh --model Qwen/Qwen3-Reranker-0.6B --runner pooling --port 9001 \\")
            print(f"     --hf-overrides '{{\"architectures\":[\"Qwen3ForSequenceClassification\"],\"classifier_from_token\":[\"no\",\"yes\"],\"is_original_qwen3_reranker\":true}}'")
        else:
            print(f"✓ vLLM server healthy at {health['url']}")

    # Create reranker based on backend
    if BACKEND == "vllm":
        reranker = create_reranker(
            backend="vllm",
            model=VLLM_RERANKER_MODEL,
            vllm_url=VLLM_RERANKER_URL,
            threshold=THRESHOLD,
            min_keep=MIN_KEEP,
        )
    elif BACKEND == "ollama":
        reranker = create_reranker(
            backend="ollama",
            model=OLLAMA_MODEL,
            ollama_url=OLLAMA_URL,
            threshold=THRESHOLD,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
        )
    else:  # cross-encoder
        reranker = create_reranker(
            backend="cross-encoder",
            model=CROSS_ENCODER_MODEL,
            threshold=THRESHOLD,
            min_keep=MIN_KEEP,
        )

    print(f"\nReranker initialized:")
    print(f"  Backend: {BACKEND}")
    print(f"  Model: {reranker.model}")
    print(f"  Threshold: {reranker.threshold}")

# %%
# Cell 5: Test Manual Cases (Jupyter only)
"""Test the reranker on manual test cases."""

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("MANUAL TEST CASES - RELEVANCE SCORING")
    print(f"{'=' * 70}")

    manual_results = []
    correct_predictions = 0
    total_predictions = 0

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] {tc['id']}: {tc['description']}")
        print(f"  Problem: {tc['problem'][:60]}...")

        symbol = tc["symbol"]
        symbol_id = f"{symbol['cd']}:{symbol['name']}"
        print(f"  Symbol: {symbol_id}")

        # Score the pair
        score = reranker.score(tc["problem"], symbol)
        verdict = "KEEP" if score >= THRESHOLD else "FILTER"

        # Check prediction
        expected = tc["expected"]
        if expected == "high" and score >= THRESHOLD:
            prediction = "✓ CORRECT"
            correct_predictions += 1
        elif expected == "low" and score < THRESHOLD:
            prediction = "✓ CORRECT"
            correct_predictions += 1
        elif expected == "medium":
            prediction = "~ BORDERLINE"
            # Don't count medium cases in accuracy
            total_predictions -= 1
        else:
            prediction = "✗ WRONG"

        total_predictions += 1

        manual_results.append({
            "test_case": tc,
            "score": score,
            "verdict": verdict,
            "expected": expected,
            "prediction": prediction,
        })

        print(f"  Score: {score:.3f} → {verdict} ({prediction})")

    # Summary
    accuracy = correct_predictions / total_predictions * 100 if total_predictions > 0 else 0
    print(f"\n{'=' * 70}")
    print(f"MANUAL TEST SUMMARY: {correct_predictions}/{total_predictions} correct ({accuracy:.0f}%)")
    print(f"{'=' * 70}")

# %%
# Cell 6: Load Phase 3 Retrieved Candidates (Jupyter only)
"""Load candidates retrieved in Phase 3 from data/openmath-retrieved.json."""

if _is_jupyter_mode() and not TEST_MODE:
    print(f"\n{'=' * 70}")
    print("LOADING PHASE 3 CANDIDATES")
    print(f"{'=' * 70}")

    if not RETRIEVED_JSON_PATH.exists():
        print(f"ERROR: Retrieved file not found: {RETRIEVED_JSON_PATH}")
        print("Please run Phase 3 first: python pipeline/3_hybrid_retrieval.py --all")
        retrieved_data = {}
    else:
        with open(RETRIEVED_JSON_PATH, "r", encoding="utf-8") as f:
            retrieved_data = json.load(f)

        print(f"Loaded candidates for {len(retrieved_data)} problems")

        # Sample subset if needed
        import random
        random.seed(SEED)

        problem_ids = list(retrieved_data.keys())
        if N_PROBLEMS < len(problem_ids):
            sampled_ids = random.sample(problem_ids, N_PROBLEMS)
        else:
            sampled_ids = problem_ids

        print(f"Selected {len(sampled_ids)} problems (seed={SEED})")

        # Show candidate counts
        total_candidates = sum(
            len(retrieved_data[pid].get("openmath", {}))
            for pid in sampled_ids
        )
        avg_candidates = total_candidates / len(sampled_ids) if sampled_ids else 0

        print(f"Total candidates to rerank: {total_candidates}")
        print(f"Average candidates per problem: {avg_candidates:.1f}")

        # Show sample
        print("\nSample problems:")
        for pid in sampled_ids[:3]:
            openmath = retrieved_data[pid].get("openmath", {})
            concepts = retrieved_data[pid].get("concepts", [])
            print(f"  {pid}: {len(openmath)} candidates, concepts: {concepts[:3]}...")

# %%
# Cell 7: Load MATH 500 Problem Statements (Jupyter only)
"""Load MATH 500 problem statements via BenchmarkLoader."""

if _is_jupyter_mode() and not TEST_MODE and retrieved_data:
    print(f"\n{'=' * 70}")
    print("LOADING MATH 500 PROBLEM STATEMENTS")
    print(f"{'=' * 70}")

    from benchmark_loader import BenchmarkLoader

    loader = BenchmarkLoader(project_root=PROJECT_ROOT)
    dataset = loader.load()

    print(f"Loaded {len(dataset)} problems")

    # Build problem_id -> problem_text mapping
    problems_dict = {}
    for problem in dataset:
        if problem.id in sampled_ids:
            problems_dict[problem.id] = problem.problem

    print(f"Mapped {len(problems_dict)} problem statements for selected problems")

    # Show sample
    print("\nSample problem statements:")
    for pid in list(problems_dict.keys())[:2]:
        text = problems_dict[pid]
        print(f"  {pid}: {text[:100]}...")

# %%
# Cell 8: Run Batch Reranking (Jupyter only)
"""Run cross-encoder reranking on sampled problems."""

if _is_jupyter_mode() and not TEST_MODE and retrieved_data and problems_dict:
    print(f"\n{'=' * 70}")
    print("RUNNING BATCH RERANKING")
    print(f"{'=' * 70}")

    start_time = time.time()

    # Progress callback
    def print_progress(current, total):
        print(f"\r[{current}/{total}] Reranking problems...", end="", flush=True)

    # Build candidates subset
    candidates_subset = {pid: retrieved_data[pid] for pid in sampled_ids}

    # Run batch reranking
    batch_results = reranker.rerank_batch(
        problems=problems_dict,
        candidates_by_problem=candidates_subset,
        progress_callback=print_progress,
    )

    elapsed = time.time() - start_time
    print(f"\n\nReranked {len(batch_results)} problems in {elapsed:.1f}s")
    print(f"Average time per problem: {elapsed/len(batch_results):.2f}s")

# %%
# Cell 9: Statistics Analysis (Jupyter only)
"""Analyze reranking statistics."""

if _is_jupyter_mode() and not TEST_MODE and retrieved_data and 'batch_results' in dir():
    print(f"\n{'=' * 70}")
    print("RERANKING STATISTICS")
    print(f"{'=' * 70}")

    # Collect statistics
    all_scores = []
    original_counts = []
    reranked_counts = []
    filtered_counts = []

    for pid, result in batch_results.items():
        all_scores.extend(result.all_scores.values())
        original_counts.append(result.original_count)
        reranked_counts.append(result.reranked_count)
        filtered_counts.append(result.filtered_count)

    # Score statistics
    import numpy as np
    scores_arr = np.array(all_scores) if all_scores else np.array([0.0])

    print(f"\nScore Statistics:")
    print(f"  Total pairs scored: {len(all_scores)}")
    print(f"  Min score: {scores_arr.min():.3f}")
    print(f"  Max score: {scores_arr.max():.3f}")
    print(f"  Mean score: {scores_arr.mean():.3f}")
    print(f"  Std score: {scores_arr.std():.3f}")
    print(f"  Median score: {np.median(scores_arr):.3f}")

    # Score distribution
    print(f"\nScore Distribution:")
    for low, high in [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0)]:
        count = ((scores_arr >= low) & (scores_arr < high)).sum()
        pct = count / len(scores_arr) * 100 if len(scores_arr) > 0 else 0
        print(f"  [{low:.1f}, {high:.1f}): {count} ({pct:.1f}%)")

    # Filtering statistics
    total_original = sum(original_counts)
    total_reranked = sum(reranked_counts)
    total_filtered = sum(filtered_counts)
    filter_rate = total_filtered / total_original * 100 if total_original > 0 else 0

    print(f"\nFiltering Statistics:")
    print(f"  Original candidates: {total_original}")
    print(f"  Kept after reranking: {total_reranked} ({100 - filter_rate:.1f}%)")
    print(f"  Filtered out: {total_filtered} ({filter_rate:.1f}%)")

    # Per-problem statistics
    print(f"\nPer-Problem Statistics:")
    print(f"  Avg original: {np.mean(original_counts):.1f}")
    print(f"  Avg reranked: {np.mean(reranked_counts):.1f}")
    print(f"  Min reranked: {min(reranked_counts)}")
    print(f"  Max reranked: {max(reranked_counts)}")

    # Problems with zero results
    zero_results = sum(1 for c in reranked_counts if c == 0)
    print(f"  Problems with 0 symbols kept: {zero_results}")

# %%
# Cell 10: Save Results to JSON (Jupyter only)
"""Save reranking results to data/openmath-reranked.json."""

if _is_jupyter_mode() and not TEST_MODE and retrieved_data and 'batch_results' in dir():
    print(f"\n{'=' * 70}")
    print("SAVING RESULTS")
    print(f"{'=' * 70}")

    # Build output data structure
    output_data = {}

    for pid, result in batch_results.items():
        output_data[pid] = {
            "problem_text": result.problem_text[:500] + "..." if len(result.problem_text) > 500 else result.problem_text,
            "original_count": result.original_count,
            "reranked_count": result.reranked_count,
            "reranked_symbols": result.reranked_symbols,
        }

    # Save to JSON
    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"Results saved to: {OUTPUT_JSON_PATH}")
    print(f"Total problems: {len(output_data)}")

    # Show file size
    file_size = OUTPUT_JSON_PATH.stat().st_size
    print(f"File size: {file_size / 1024:.2f} KB")

# %%
# Cell 11: Generate Report (Jupyter only)
"""Generate markdown report for Phase 4 results."""

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("GENERATING REPORT")
    print(f"{'=' * 70}")

    # Create report directory
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate filename
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    report_file = REPORT_DIR / f"phase-4_cross_encoder_reranking_{timestamp}.md"

    # Build markdown content
    lines = [
        "# Phase 4: Cross-Encoder Reranking Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Reranker Model**: {RERANKER_MODEL}",
        f"**Threshold**: {THRESHOLD}",
        "",
        "## Configuration",
        "",
        f"- Reranker Model: `{RERANKER_MODEL}`",
        f"- Ollama URL: `{OLLAMA_URL}`",
        f"- Threshold: {THRESHOLD}",
        f"- Max Tokens: {MAX_TOKENS}",
        f"- Temperature: {TEMPERATURE}",
        "",
        "## Manual Test Results",
        "",
    ]

    # Manual test results
    for r in manual_results:
        tc = r["test_case"]
        symbol = tc["symbol"]
        symbol_id = f"{symbol['cd']}:{symbol['name']}"

        lines.append(f"### {tc['id']}: {tc['description']}")
        lines.append("")
        lines.append(f"**Problem**: {tc['problem'][:100]}...")
        lines.append("")
        lines.append(f"**Symbol**: `{symbol_id}`")
        lines.append("")
        lines.append(f"**Score**: {r['score']:.3f} → {r['verdict']} ({r['prediction']})")
        lines.append("")
        lines.append(f"**Expected**: {tc['expected']}")
        lines.append("")

    # Summary line
    lines.append(f"**Accuracy**: {correct_predictions}/{total_predictions} ({accuracy:.0f}%)")
    lines.append("")

    # MATH 500 results
    if not TEST_MODE and retrieved_data and 'batch_results' in dir():
        lines.extend([
            "## MATH 500 Batch Reranking Results",
            "",
            f"**Problems Processed**: {len(batch_results)}",
            f"**Total Pairs Scored**: {len(all_scores)}",
            "",
            "### Score Statistics",
            "",
            f"- Min: {scores_arr.min():.3f}",
            f"- Max: {scores_arr.max():.3f}",
            f"- Mean: {scores_arr.mean():.3f}",
            f"- Std: {scores_arr.std():.3f}",
            f"- Median: {np.median(scores_arr):.3f}",
            "",
            "### Filtering Statistics",
            "",
            f"- Original candidates: {total_original}",
            f"- Kept after reranking: {total_reranked} ({100 - filter_rate:.1f}%)",
            f"- Filtered out: {total_filtered} ({filter_rate:.1f}%)",
            f"- Avg reranked per problem: {np.mean(reranked_counts):.1f}",
            "",
            "### Sample Results",
            "",
        ])

        # Show first 5 results
        for pid in list(batch_results.keys())[:5]:
            result = batch_results[pid]

            lines.append(f"#### {pid}")
            lines.append("")
            lines.append(f"**Problem**: {result.problem_text[:100]}...")
            lines.append("")
            lines.append(f"**Original**: {result.original_count} → **Reranked**: {result.reranked_count}")
            lines.append("")

            if result.reranked_symbols:
                lines.append("**Top 5 Symbols**:")
                for sym in result.reranked_symbols[:5]:
                    sym_id = f"{sym.get('cd', '')}:{sym.get('name', '')}"
                    score = sym.get("reranker_score", 0)
                    lines.append(f"- `{sym_id}`: {score:.3f}")
            else:
                lines.append("**No symbols passed threshold**")

            lines.append("")

    # Write file
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Report saved to: {report_file}")

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("PHASE 4 COMPLETE")
    print(f"{'=' * 70}")

# %%
# Cell 12: CLI Entry Point
"""Command-line interface for running Phase 4."""


def main():
    """Main CLI entry point."""
    import argparse
    import random

    arg_parser = argparse.ArgumentParser(
        description="Phase 4: Cross-Encoder Reranking (The Judge)"
    )
    arg_parser.add_argument(
        "--n-problems",
        type=int,
        default=N_PROBLEMS,
        help=f"Number of MATH 500 problems to process (default: {N_PROBLEMS})",
    )
    arg_parser.add_argument(
        "--backend",
        default=BACKEND,
        choices=["vllm", "ollama", "cross-encoder"],
        help=f"Reranker backend (default: {BACKEND})",
    )
    arg_parser.add_argument(
        "--model",
        help="Model name (auto-selected based on backend if not provided)",
    )
    arg_parser.add_argument(
        "--url",
        help="API URL (for vllm/ollama backends)",
    )
    arg_parser.add_argument(
        "--threshold",
        type=float,
        help="Score threshold (default: 0.15 for vllm/cross-encoder, 0.7 for ollama)",
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

    # Determine model and URL based on backend
    backend = args.backend
    if args.model:
        model = args.model
    elif backend == "vllm":
        model = VLLM_RERANKER_MODEL
    elif backend == "ollama":
        model = OLLAMA_MODEL
    else:
        model = CROSS_ENCODER_MODEL

    if args.url:
        url = args.url
    elif backend == "vllm":
        url = VLLM_RERANKER_URL
    else:
        url = OLLAMA_URL

    if args.threshold is not None:
        threshold = args.threshold
    elif backend in ("vllm", "cross-encoder"):
        threshold = 0.15
    else:
        threshold = 0.7

    # Print configuration
    print("=" * 70)
    print("PHASE 4: CROSS-ENCODER RERANKING (THE JUDGE)")
    print("=" * 70)
    print(f"Backend:        {backend}")
    print(f"Model:          {model}")
    if backend in ("vllm", "ollama"):
        print(f"URL:            {url}")
    print(f"Threshold:      {threshold}")
    print(f"Min keep:       {MIN_KEEP}")
    print(f"N problems:     {'ALL (500)' if args.all else args.n_problems}")
    print(f"Seed:           {args.seed}")
    print(f"Test mode:      {args.test_mode}")
    print(f"Output JSON:    {args.output_json}")
    print("=" * 70)

    # Import reranker
    from reranker_cross_encoder import create_reranker, check_vllm_reranker_health

    # Check vLLM server health if using vllm backend
    if backend == "vllm":
        health = check_vllm_reranker_health(url)
        if not health["healthy"]:
            print(f"\n⚠️  WARNING: vLLM server not healthy at {url}")
            print(f"   Error: {health['error']}")
            print(f"\n   Start the server with:")
            print(f"   ./scripts/start_vllm_server.sh --model Qwen/Qwen3-Reranker-0.6B --runner pooling --port 9001 \\")
            print(f"     --hf-overrides '{{\"architectures\":[\"Qwen3ForSequenceClassification\"],\"classifier_from_token\":[\"no\",\"yes\"],\"is_original_qwen3_reranker\":true}}'")
            import sys
            sys.exit(1)
        print(f"\n✓ vLLM server healthy at {url}")

    print(f"\nInitializing reranker (backend={backend})...")

    # Create reranker based on backend
    kwargs = {"threshold": threshold}
    if backend == "vllm":
        kwargs["vllm_url"] = url
        kwargs["min_keep"] = MIN_KEEP
    elif backend == "ollama":
        kwargs["ollama_url"] = url
        kwargs["max_tokens"] = MAX_TOKENS
        kwargs["temperature"] = TEMPERATURE
    else:  # cross-encoder
        kwargs["min_keep"] = MIN_KEEP

    reranker = create_reranker(backend=backend, model=model, **kwargs)

    print(f"  Backend: {backend}")
    print(f"  Model: {reranker.model}")
    print(f"  Threshold: {reranker.threshold}")

    # Run manual tests
    print(f"\n--- Manual Test Cases ---")

    correct_predictions = 0
    total_predictions = 0
    manual_results = []

    for i, tc in enumerate(TEST_CASES, 1):
        print(f"\n[{i}/{len(TEST_CASES)}] {tc['id']}: {tc['description']}")

        symbol = tc["symbol"]
        score = reranker.score(tc["problem"], symbol)
        verdict = "KEEP" if score >= threshold else "FILTER"

        expected = tc["expected"]
        if expected == "high" and score >= threshold:
            prediction = "✓"
            correct_predictions += 1
        elif expected == "low" and score < threshold:
            prediction = "✓"
            correct_predictions += 1
        elif expected == "medium":
            prediction = "~"
            total_predictions -= 1
        else:
            prediction = "✗"

        total_predictions += 1

        manual_results.append({
            "test_case": tc,
            "score": score,
            "verdict": verdict,
            "expected": expected,
            "prediction": prediction,
        })

        print(f"  Score: {score:.3f} → {verdict} ({prediction})")

    accuracy = correct_predictions / total_predictions * 100 if total_predictions > 0 else 0
    print(f"\nManual test accuracy: {correct_predictions}/{total_predictions} ({accuracy:.0f}%)")

    if args.test_mode:
        print("\n[TEST MODE] Skipping MATH 500 problems")
        print("\n" + "=" * 70)
        print("PHASE 4 COMPLETE")
        print("=" * 70)
        return

    # Load Phase 3 retrieved candidates
    print(f"\n--- Loading Phase 3 Candidates ---")

    retrieved_path = Path(RETRIEVED_JSON_PATH)
    if not retrieved_path.exists():
        print(f"ERROR: Retrieved file not found: {retrieved_path}")
        print("Please run Phase 3 first: python pipeline/3_hybrid_retrieval.py --all")
        return

    with open(retrieved_path, "r", encoding="utf-8") as f:
        retrieved_data = json.load(f)

    print(f"Loaded candidates for {len(retrieved_data)} problems")

    # Sample problems
    problem_ids = list(retrieved_data.keys())
    if args.all:
        sampled_ids = problem_ids
    else:
        random.seed(args.seed)
        sampled_ids = random.sample(problem_ids, min(args.n_problems, len(problem_ids)))

    print(f"Selected {len(sampled_ids)} problems")

    # Load MATH 500 problem statements
    print(f"\n--- Loading MATH 500 Problem Statements ---")

    from benchmark_loader import BenchmarkLoader

    loader = BenchmarkLoader(project_root=PROJECT_ROOT)
    dataset = loader.load()

    # Build problem_id -> problem_text mapping
    problems_dict = {}
    for problem in dataset:
        if problem.id in sampled_ids:
            problems_dict[problem.id] = problem.problem

    print(f"Mapped {len(problems_dict)} problem statements")

    # Run batch reranking
    print(f"\n--- Running Batch Reranking ---")

    def print_progress(current, total):
        print(f"\r[{current}/{total}] Reranking problems...", end="", flush=True)

    candidates_subset = {pid: retrieved_data[pid] for pid in sampled_ids}

    start_time = time.time()
    batch_results = reranker.rerank_batch(
        problems=problems_dict,
        candidates_by_problem=candidates_subset,
        progress_callback=print_progress,
    )
    elapsed = time.time() - start_time

    print(f"\n\nReranked {len(batch_results)} problems in {elapsed:.1f}s")

    # Statistics
    import numpy as np

    all_scores = []
    original_counts = []
    reranked_counts = []

    for pid, result in batch_results.items():
        all_scores.extend(result.all_scores.values())
        original_counts.append(result.original_count)
        reranked_counts.append(result.reranked_count)

    scores_arr = np.array(all_scores) if all_scores else np.array([0.0])

    total_original = sum(original_counts)
    total_reranked = sum(reranked_counts)
    filter_rate = (total_original - total_reranked) / total_original * 100 if total_original > 0 else 0

    print(f"\nScore statistics:")
    print(f"  Mean: {scores_arr.mean():.3f}, Std: {scores_arr.std():.3f}")
    print(f"  Min: {scores_arr.min():.3f}, Max: {scores_arr.max():.3f}")

    print(f"\nFiltering statistics:")
    print(f"  Original: {total_original} → Reranked: {total_reranked} ({100 - filter_rate:.1f}% kept)")
    print(f"  Avg per problem: {np.mean(reranked_counts):.1f}")

    # Save results
    print(f"\n--- Saving Results ---")

    output_data = {}
    for pid, result in batch_results.items():
        output_data[pid] = {
            "problem_text": result.problem_text[:500] + "..." if len(result.problem_text) > 500 else result.problem_text,
            "original_count": result.original_count,
            "reranked_count": result.reranked_count,
            "reranked_symbols": result.reranked_symbols,
        }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"Results saved to: {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024:.2f} KB")

    # Save report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    report_file = REPORT_DIR / f"phase-4_cross_encoder_reranking_{timestamp}.md"

    lines = [
        "# Phase 4: Cross-Encoder Reranking Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Backend**: {backend}",
        f"**Model**: {model}",
        f"**Threshold**: {threshold}",
        "",
        "## Statistics",
        "",
        f"- Problems processed: {len(batch_results)}",
        f"- Total pairs scored: {len(all_scores)}",
        f"- Score mean: {scores_arr.mean():.3f}",
        f"- Original candidates: {total_original}",
        f"- Kept after reranking: {total_reranked} ({100 - filter_rate:.1f}%)",
        f"- Avg per problem: {np.mean(reranked_counts):.1f}",
        f"- Manual test accuracy: {correct_predictions}/{total_predictions} ({accuracy:.0f}%)",
        "",
        "## Sample Results",
        "",
    ]

    for pid in list(batch_results.keys())[:10]:
        result = batch_results[pid]
        lines.append(f"### {pid}")
        lines.append("")
        lines.append(f"**Original**: {result.original_count} → **Reranked**: {result.reranked_count}")
        lines.append("")
        if result.reranked_symbols:
            for sym in result.reranked_symbols[:3]:
                sym_id = f"{sym.get('cd', '')}:{sym.get('name', '')}"
                score = sym.get("reranker_score", 0)
                lines.append(f"- `{sym_id}`: {score:.3f}")
        lines.append("")

    with open(report_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Report saved to: {report_file}")

    print("\n" + "=" * 70)
    print("PHASE 4 COMPLETE")
    print("=" * 70)


# Only run CLI when executed directly (not in Jupyter)
if __name__ == "__main__" and not _is_jupyter_mode():
    main()
