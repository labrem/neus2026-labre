# %%
# Cell 1: Environment Setup
"""
Transforms natural language math problem statements into clean lists of
mathematical keywords and operators using qwen2-math:7b via Ollama.

Key Steps:
1. Parse sample math problems and extract concepts
2. Test with MATH 500 benchmark problems
3. Verify JSON list output format
4. Analyze extracted concepts for relevance
5. Save results for inspection

Output Files:
    - data/math500-concepts.md (extration report)
    - data/math500-concepts.json (concepts for each problem)

Usage:
    # CLI: Run with default settings (10 problems)
    python pipeline/2a_concept_extraction.py

    # CLI: Run with more problems
    python pipeline/2a_concept_extraction.py --n-problems 50

    # CLI: Run ALL 500 problems and save to JSON
    python pipeline/2a_concept_extraction.py --all

    # CLI: Test mode only (no MATH 500)
    python pipeline/2a_concept_extraction.py --test-mode

    # Jupyter: Run cells 1-10 sequentially

Date: 2026-02-03
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

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

# --- Model Settings ---
PARSER_MODEL = "qwen2-math:7b"  # LLM for concept extraction
OLLAMA_URL = "http://localhost:11434"  # Ollama API base URL

# --- Parsing Parameters ---
MAX_TOKENS = 200  # Limit output tokens to prevent solving (100 was too low)
TEMPERATURE = 0.0  # Deterministic output

# --- Test Parameters ---
N_PROBLEMS = 10  # Number of MATH 500 problems to test
SEED = 42  # Random seed for problem sampling

# --- Test Mode ---
# Set to True to run only manual test examples (faster, for debugging)
# Set to False to also run on MATH 500 problems
TEST_MODE = False

# --- Output Configuration ---
OUTPUT_DIR = PROJECT_ROOT / ".local" / "tests"
CONCEPTS_JSON_FILE = PROJECT_ROOT / "data" / "math500-concepts.json"

# ============================================================================
# Print current configuration (only in Jupyter mode)
if _is_jupyter_mode():
    print("=" * 70)
    print("PHASE 2a: CONCEPT EXTRACTION")
    print("=" * 70)
    print(f"Parser model:  {PARSER_MODEL}")
    print(f"Ollama URL:    {OLLAMA_URL}")
    print(f"Max tokens:    {MAX_TOKENS}")
    print(f"Temperature:   {TEMPERATURE}")
    print(f"N problems:    {N_PROBLEMS}")
    print(f"Seed:          {SEED}")
    print(f"Test mode:     {TEST_MODE}")
    print(f"Output dir:    {OUTPUT_DIR}")
    print("=" * 70)

# %%
# Cell 3: Manual Test Problems
"""Define test problems for manual verification."""

# Test problems with expected concept types
TEST_PROBLEMS = [
    {
        "id": "test_001",
        "problem": "Find the greatest common divisor of 48 and 18.",
        "expected_concepts": ["gcd", "greatest common divisor", "integer", "divisibility"],
    },
    {
        "id": "test_002",
        "problem": "Evaluate $\\int_0^1 x^2 dx$.",
        "expected_concepts": ["integral", "integration", "definite integral", "polynomial"],
    },
    {
        "id": "test_003",
        "problem": "If $f(x) = x^2 + 3x - 5$, find $f(2)$.",
        "expected_concepts": ["function", "polynomial", "evaluation", "substitution"],
    },
    {
        "id": "test_004",
        "problem": "What is the sum of the first 100 positive integers?",
        "expected_concepts": ["sum", "arithmetic", "integers", "series"],
    },
    {
        "id": "test_005",
        "problem": "Find all values of $x$ such that $\\sin(x) = \\frac{1}{2}$ for $0 \\leq x < 2\\pi$.",
        "expected_concepts": ["sin", "sine", "trigonometry", "equation"],
    },
    {
        "id": "test_006",
        "problem": "Calculate the determinant of the matrix $\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}$.",
        "expected_concepts": ["determinant", "matrix", "linear algebra"],
    },
    {
        "id": "test_007",
        "problem": "How many ways can you arrange the letters in the word MISSISSIPPI?",
        "expected_concepts": ["permutation", "combinatorics", "arrangement", "factorial"],
    },
    {
        "id": "test_008",
        "problem": "Find the derivative of $f(x) = e^{x^2}$.",
        "expected_concepts": ["derivative", "differentiation", "exponential", "chain rule"],
    },
    {
        "id": "test_009",
        "problem": "Solve the quadratic equation $x^2 - 5x + 6 = 0$.",
        "expected_concepts": ["quadratic", "equation", "roots", "algebra", "factoring"],
    },
    {
        "id": "test_010",
        "problem": "What is the probability of rolling a sum of 7 with two fair dice?",
        "expected_concepts": ["probability", "dice", "sum", "combinatorics"],
    },
]

if _is_jupyter_mode():
    print(f"\nDefined {len(TEST_PROBLEMS)} manual test problems")

# %%
# Cell 4: Import and Initialize QueryParser (Jupyter only)
"""Import the query parser module and initialize it."""

if _is_jupyter_mode():
    from query_parser import QueryParser, ParseResult, create_query_parser

    parser = create_query_parser(
        model=PARSER_MODEL,
        ollama_url=OLLAMA_URL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )

    print(f"\nQueryParser initialized")
    print(f"  Model: {parser.model}")
    print(f"  URL: {parser.ollama_url}")
    print(f"  Max tokens: {parser.max_tokens}")

# %%
# Cell 5: Test Manual Problems (Jupyter only)
"""Test the parser on manual test problems."""

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("MANUAL TEST PROBLEMS - CONCEPT EXTRACTION")
    print(f"{'=' * 70}")

    manual_results = []

    for i, test in enumerate(TEST_PROBLEMS, 1):
        print(f"\n[{i}/{len(TEST_PROBLEMS)}] {test['id']}")
        print(f"  Problem: {test['problem'][:80]}...")

        result = parser.parse(test["problem"], test["id"])
        manual_results.append({
            "test": test,
            "result": result,
        })

        if result.success:
            print(f"  Concepts: {result.concepts}")
            # Check for expected concepts (case-insensitive partial match)
            found = []
            for expected in test["expected_concepts"]:
                for concept in result.concepts:
                    if expected.lower() in concept.lower() or concept.lower() in expected.lower():
                        found.append(expected)
                        break
            coverage = len(found) / len(test["expected_concepts"]) * 100 if test["expected_concepts"] else 0
            print(f"  Expected coverage: {coverage:.0f}% ({len(found)}/{len(test['expected_concepts'])})")
        else:
            print(f"  ERROR: {result.error}")

    # Summary
    success_count = sum(1 for r in manual_results if r["result"].success)
    print(f"\n{'=' * 70}")
    print(f"MANUAL TEST SUMMARY: {success_count}/{len(manual_results)} successful")
    print(f"{'=' * 70}")

# %%
# Cell 6: Load MATH 500 Problems (Jupyter only)
"""Load problems from the MATH 500 benchmark."""

if _is_jupyter_mode() and not TEST_MODE:
    import random
    from benchmark_loader import BenchmarkLoader

    print(f"\n{'=' * 70}")
    print("LOADING MATH 500 BENCHMARK")
    print(f"{'=' * 70}")

    loader = BenchmarkLoader()
    dataset = loader.load()

    print(f"Total problems available: {len(dataset)}")

    # Sample problems
    random.seed(SEED)
    all_problems = list(dataset.problems)
    sampled_problems = random.sample(all_problems, min(N_PROBLEMS, len(all_problems)))

    print(f"Sampled {len(sampled_problems)} problems (seed={SEED})")

    # Show problem type distribution
    type_counts = {}
    for p in sampled_problems:
        type_counts[p.problem_type] = type_counts.get(p.problem_type, 0) + 1
    print("\nProblem type distribution:")
    for ptype, count in sorted(type_counts.items()):
        print(f"  {ptype}: {count}")

# %%
# Cell 7: Parse MATH 500 Problems (Jupyter only)
"""Parse sampled MATH 500 problems for concepts."""

if _is_jupyter_mode() and not TEST_MODE:
    print(f"\n{'=' * 70}")
    print("PARSING MATH 500 PROBLEMS")
    print(f"{'=' * 70}")

    math500_results = []
    start_time = time.time()

    for i, problem in enumerate(sampled_problems, 1):
        print(f"\r[{i}/{len(sampled_problems)}] Parsing {problem.id}...", end="", flush=True)

        result = parser.parse(problem.problem, problem.id)
        math500_results.append({
            "problem": problem,
            "result": result,
        })

    elapsed = time.time() - start_time
    print(f"\n\nParsed {len(math500_results)} problems in {elapsed:.1f}s ({elapsed/len(math500_results):.2f}s/problem)")

    # Statistics
    success_count = sum(1 for r in math500_results if r["result"].success)
    avg_concepts = sum(len(r["result"].concepts) for r in math500_results) / len(math500_results) if math500_results else 0

    print(f"\nSuccess rate: {success_count}/{len(math500_results)} ({100*success_count/len(math500_results):.1f}%)")
    print(f"Average concepts per problem: {avg_concepts:.1f}")

# %%
# Cell 8: Analyze Results (Jupyter only)
"""Analyze the extracted concepts."""

if _is_jupyter_mode() and not TEST_MODE:
    print(f"\n{'=' * 70}")
    print("CONCEPT ANALYSIS")
    print(f"{'=' * 70}")

    # Collect all concepts
    all_concepts = []
    for r in math500_results:
        all_concepts.extend(r["result"].concepts)

    # Frequency analysis
    concept_freq = {}
    for c in all_concepts:
        c_lower = c.lower().strip()
        concept_freq[c_lower] = concept_freq.get(c_lower, 0) + 1

    # Top concepts
    top_concepts = sorted(concept_freq.items(), key=lambda x: -x[1])[:30]
    print("\nTop 30 most frequent concepts:")
    for i, (concept, freq) in enumerate(top_concepts, 1):
        print(f"  {i:2}. {concept}: {freq}")

    # Concepts by problem type
    print("\n\nConcepts by problem type:")
    concepts_by_type = {}
    for r in math500_results:
        ptype = r["problem"].problem_type
        if ptype not in concepts_by_type:
            concepts_by_type[ptype] = []
        concepts_by_type[ptype].extend(r["result"].concepts)

    for ptype, concepts in sorted(concepts_by_type.items()):
        freq = {}
        for c in concepts:
            c_lower = c.lower().strip()
            freq[c_lower] = freq.get(c_lower, 0) + 1
        top_3 = sorted(freq.items(), key=lambda x: -x[1])[:3]
        print(f"  {ptype}: {', '.join(f'{c}({n})' for c, n in top_3)}")

# %%
# Cell 9: Display Sample Results (Jupyter only)
"""Display detailed results for a few sample problems."""

if _is_jupyter_mode() and not TEST_MODE:
    print(f"\n{'=' * 70}")
    print("SAMPLE RESULTS (First 5 problems)")
    print(f"{'=' * 70}")

    for i, r in enumerate(math500_results[:5], 1):
        problem = r["problem"]
        result = r["result"]

        print(f"\n--- [{i}] {problem.id} ({problem.problem_type}, Level {problem.level}) ---")
        print(f"Problem: {problem.problem[:150]}...")
        print(f"Concepts: {result.concepts}")
        if result.error:
            print(f"Error: {result.error}")

# %%
# Cell 10: Save Results (Jupyter only)
"""Save results to markdown file."""

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("SAVING RESULTS")
    print(f"{'=' * 70}")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate filename
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    output_file = OUTPUT_DIR / f"phase-2a_concept_extraction_results_{timestamp}.md"

    # Build markdown content
    lines = [
        "# Phase 2a: Concept Extraction Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Model**: {PARSER_MODEL}",
        f"**Max Tokens**: {MAX_TOKENS}",
        "",
        "## Configuration",
        "",
        f"- Parser Model: `{PARSER_MODEL}`",
        f"- Ollama URL: `{OLLAMA_URL}`",
        f"- Max Tokens: {MAX_TOKENS}",
        f"- Temperature: {TEMPERATURE}",
        "",
        "## Manual Test Results",
        "",
    ]

    # Manual test results
    for r in manual_results:
        test = r["test"]
        result = r["result"]
        status = "✓" if result.success else "✗"
        lines.append(f"### {test['id']} {status}")
        lines.append("")
        lines.append(f"**Problem**: {test['problem']}")
        lines.append("")
        lines.append(f"**Extracted Concepts**: {result.concepts}")
        lines.append("")
        lines.append(f"**Expected**: {test['expected_concepts']}")
        lines.append("")
        if result.error:
            lines.append(f"**Error**: {result.error}")
            lines.append("")

    # MATH 500 results
    if not TEST_MODE and 'math500_results' in dir():
        lines.extend([
            "## MATH 500 Results",
            "",
            f"**Problems Parsed**: {len(math500_results)}",
            f"**Success Rate**: {success_count}/{len(math500_results)} ({100*success_count/len(math500_results):.1f}%)",
            f"**Average Concepts**: {avg_concepts:.1f}",
            "",
            "### Top Concepts",
            "",
        ])

        for i, (concept, freq) in enumerate(top_concepts[:20], 1):
            lines.append(f"{i}. `{concept}`: {freq}")

        lines.extend([
            "",
            "### Sample Problems",
            "",
        ])

        for r in math500_results[:10]:
            problem = r["problem"]
            result = r["result"]
            status = "✓" if result.success else "✗"
            lines.append(f"#### {problem.id} ({problem.problem_type}) {status}")
            lines.append("")
            lines.append(f"**Problem**: {problem.problem[:200]}...")
            lines.append("")
            lines.append(f"**Concepts**: {result.concepts}")
            lines.append("")

    # Write file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Results saved to: {output_file}")

    # Save to JSON file if we have MATH 500 results
    if not TEST_MODE and 'math500_results' in dir():
        concepts_data = {}
        for r in math500_results:
            problem = r["problem"]
            result = r["result"]
            concepts_data[problem.id] = {
                "level": problem.level,
                "type": problem.problem_type,
                "concepts": result.concepts if result.success else [],
            }

        # Ensure data directory exists
        CONCEPTS_JSON_FILE.parent.mkdir(parents=True, exist_ok=True)

        with open(CONCEPTS_JSON_FILE, "w", encoding="utf-8") as f:
            json.dump(concepts_data, f, indent=2, ensure_ascii=False)

        print(f"Concepts JSON saved to: {CONCEPTS_JSON_FILE}")

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("PHASE 2a COMPLETE")
    print(f"{'=' * 70}")

# %%
# Cell 11: CLI Entry Point
"""Command-line interface for running Phase 8b tests."""


def main():
    """Main CLI entry point."""
    import argparse
    import random

    arg_parser = argparse.ArgumentParser(
        description="Phase 2a: Concept Extraction"
    )
    arg_parser.add_argument(
        "--n-problems",
        type=int,
        default=N_PROBLEMS,
        help=f"Number of MATH 500 problems to test (default: {N_PROBLEMS})",
    )
    arg_parser.add_argument(
        "--model",
        default=PARSER_MODEL,
        help=f"Ollama model for parsing (default: {PARSER_MODEL})",
    )
    arg_parser.add_argument(
        "--url",
        default=OLLAMA_URL,
        help=f"Ollama API URL (default: {OLLAMA_URL})",
    )
    arg_parser.add_argument(
        "--max-tokens",
        type=int,
        default=MAX_TOKENS,
        help=f"Max output tokens (default: {MAX_TOKENS})",
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
        help="Run only manual test problems (skip MATH 500)",
    )
    arg_parser.add_argument(
        "--all",
        action="store_true",
        help="Process ALL 500 problems (overrides --n-problems)",
    )
    arg_parser.add_argument(
        "--output-json",
        default=str(CONCEPTS_JSON_FILE),
        help=f"Output JSON file path (default: {CONCEPTS_JSON_FILE})",
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
    print("PHASE 2a: CONCEPT EXTRACTION")
    print("=" * 70)
    print(f"Parser model:  {args.model}")
    print(f"Ollama URL:    {args.url}")
    print(f"Max tokens:    {args.max_tokens}")
    print(f"N problems:    {'ALL (500)' if args.all else args.n_problems}")
    print(f"Seed:          {args.seed}")
    print(f"Test mode:     {args.test_mode}")
    print(f"Output JSON:   {args.output_json}")
    print("=" * 70)

    # Import parser
    from query_parser import QueryParser, create_query_parser

    parser = create_query_parser(
        model=args.model,
        ollama_url=args.url,
        max_tokens=args.max_tokens,
        temperature=TEMPERATURE,
    )

    # Run manual tests
    print(f"\n--- Manual Test Problems ---")

    manual_results = []
    for i, test in enumerate(TEST_PROBLEMS, 1):
        print(f"\n[{i}/{len(TEST_PROBLEMS)}] {test['id']}")
        print(f"  Problem: {test['problem'][:60]}...")

        result = parser.parse(test["problem"], test["id"])
        manual_results.append({"test": test, "result": result})

        if result.success:
            print(f"  Concepts: {result.concepts[:5]}{'...' if len(result.concepts) > 5 else ''}")
        else:
            print(f"  ERROR: {result.error}")

    success_count = sum(1 for r in manual_results if r["result"].success)
    print(f"\nManual test success: {success_count}/{len(manual_results)}")

    if args.test_mode:
        print("\n[TEST MODE] Skipping MATH 500 problems")
        return

    # Run MATH 500 tests
    print(f"\n--- MATH 500 Problems ---")

    from benchmark_loader import BenchmarkLoader

    loader = BenchmarkLoader()
    dataset = loader.load()

    all_problems = list(dataset.problems)

    if args.all:
        sampled = all_problems
    else:
        random.seed(args.seed)
        sampled = random.sample(all_problems, min(args.n_problems, len(all_problems)))

    print(f"Parsing {len(sampled)} problems...")

    math500_results = []
    start_time = time.time()

    for i, problem in enumerate(sampled, 1):
        print(f"\r[{i}/{len(sampled)}] {problem.id}", end="", flush=True)
        result = parser.parse(problem.problem, problem.id)
        math500_results.append({"problem": problem, "result": result})

    elapsed = time.time() - start_time
    print(f"\n\nParsed {len(math500_results)} problems in {elapsed:.1f}s")

    # Statistics
    success_count = sum(1 for r in math500_results if r["result"].success)
    avg_concepts = sum(len(r["result"].concepts) for r in math500_results) / len(math500_results)

    print(f"Success rate: {success_count}/{len(math500_results)} ({100*success_count/len(math500_results):.1f}%)")
    print(f"Avg concepts: {avg_concepts:.1f}")

    # Concept frequency
    all_concepts = []
    for r in math500_results:
        all_concepts.extend(r["result"].concepts)

    freq = {}
    for c in all_concepts:
        c_lower = c.lower().strip()
        freq[c_lower] = freq.get(c_lower, 0) + 1

    top_concepts = sorted(freq.items(), key=lambda x: -x[1])[:15]
    print(f"\nTop 15 concepts:")
    for i, (concept, count) in enumerate(top_concepts, 1):
        print(f"  {i:2}. {concept}: {count}")

    # Save results
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    output_file = OUTPUT_DIR / f"phase-2a_concept_extraction_results_{timestamp}.md"

    lines = [
        "# Phase 2a: Concept Extraction Results",
        "",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Model**: {args.model}",
        "",
        "## Statistics",
        "",
        f"- Problems parsed: {len(math500_results)}",
        f"- Success rate: {100*success_count/len(math500_results):.1f}%",
        f"- Avg concepts: {avg_concepts:.1f}",
        "",
        "## Top Concepts",
        "",
    ]
    for i, (c, n) in enumerate(top_concepts, 1):
        lines.append(f"{i}. `{c}`: {n}")

    lines.extend(["", "## Sample Results", ""])
    for r in math500_results[:15]:
        p = r["problem"]
        res = r["result"]
        lines.append(f"### {p.id} ({p.problem_type})")
        lines.append("")
        lines.append(f"**Problem**: {p.problem[:150]}...")
        lines.append("")
        lines.append(f"**Concepts**: {res.concepts}")
        lines.append("")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nResults saved to: {output_file}")

    # Save concepts to JSON file
    concepts_data = {}
    for r in math500_results:
        p = r["problem"]
        res = r["result"]
        concepts_data[p.id] = {
            "level": p.level,
            "type": p.problem_type,
            "concepts": res.concepts if res.success else [],
        }

    json_path = Path(args.output_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(concepts_data, f, indent=2, ensure_ascii=False)

    print(f"Concepts JSON saved to: {json_path}")

    print("\n" + "=" * 70)
    print("PHASE 2a COMPLETE")
    print("=" * 70)


# Only run CLI when executed directly (not in Jupyter)
if __name__ == "__main__" and not _is_jupyter_mode():
    main()
