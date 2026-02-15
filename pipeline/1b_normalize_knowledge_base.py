# %%
# Cell 1: Environment Setup
"""
OpenMath normalizer that converts mathematical expressions
in cmp_properties and examples fields to consistent LaTeX format.

Key steps:
1. Load original OpenMath JSON (created by 1a_build_knowledge_base.py)
2. Normalize expressions to LaTeX format
3. Save normalized knowledge base

Output Files:
    - `data/openmath.json` (updated in-place)

Usage:
    # CLI: Run normalization
    python pipeline/1b_normalize_knowledge_base.py

    # CLI: Dry run (no save)
    python pipeline/1b_normalize_knowledge_base.py --dry-run

    # Jupyter: Run cells 1-9 sequentially

Date: 2026-02-03
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

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

# --- Input/Output Paths ---
KB_INPUT_PATH = PROJECT_ROOT / "data" / "openmath.json"
KB_OUTPUT_PATH = PROJECT_ROOT / "data" / "openmath.json"  # Overwrite original
OUTPUT_DIR = PROJECT_ROOT / ".local" / "tests"

# --- Test Parameters ---
# Number of sample symbols to display in detail
N_SAMPLES = 10

# Symbols to specifically test (known to have complex expressions)
TEST_SYMBOLS = [
    "calculus1:int",
    "calculus1:defint",
    "calculus1:diff",
    "arith1:gcd",
    "arith1:plus",
    "arith1:times",
    "integer1:factorial",
    "transc1:sin",
    "transc1:cos",
    "relation1:eq",
]

# --- Dry Run Mode ---
# Set to True to preview without saving
DRY_RUN = False

# --- LLM Normalization ---
# Set to True to use LLM fallback for complex expressions
USE_LLM = True
LLM_MODEL = "qwen2-math:7b"  # Ollama model for LLM normalization

# --- Test Mode ---
# Set to True to run only test examples (faster, for debugging)
# Set to False to run full normalization on all symbols
TEST_MODE = True  # Toggle this to switch between test examples and full run

# ============================================================================
# Print current configuration (only in Jupyter mode)
if _is_jupyter_mode():
    print("=" * 70)
    print("PHASE 1b: KNOWLEDGE BASE NORMALIZATION")
    print("=" * 70)
    print(f"Input path:    {KB_INPUT_PATH}")
    print(f"Output path:   {KB_OUTPUT_PATH}")
    print(f"Output dir:    {OUTPUT_DIR}")
    print(f"N samples:     {N_SAMPLES}")
    print(f"Dry run:       {DRY_RUN}")
    print(f"Use LLM:       {USE_LLM}")
    print(f"LLM model:     {LLM_MODEL}")
    print(f"Test mode:     {TEST_MODE}")
    print("=" * 70)

# %%
# Cell 3: Load Original Knowledge Base (Jupyter only)
"""Load the original knowledge base and show its current state."""

if _is_jupyter_mode():
    # Load original JSON
    with open(KB_INPUT_PATH, "r", encoding="utf-8") as f:
        original_kb = json.load(f)

    # Extract symbols
    symbols = original_kb.get("symbols", {})

    print(f"\n{'=' * 70}")
    print("ORIGINAL KNOWLEDGE BASE STATE")
    print(f"{'=' * 70}")
    print(f"Total symbols: {len(symbols)}")

    # Count symbols with cmp_properties and examples
    cmp_count = sum(1 for s in symbols.values() if s.get("cmp_properties"))
    example_count = sum(1 for s in symbols.values() if s.get("examples"))
    print(f"Symbols with cmp_properties: {cmp_count}")
    print(f"Symbols with examples: {example_count}")

# %%
# Cell 4: Show Original State of Target Symbols (Jupyter only)
"""Display the original cmp_properties and examples for target symbols."""

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("ORIGINAL STATE OF TARGET SYMBOLS")
    print(f"{'=' * 70}")

    original_data = {}
    for symbol_id in TEST_SYMBOLS:
        if symbol_id in symbols:
            symbol = symbols[symbol_id]
            original_data[symbol_id] = {
                "cmp_properties": symbol.get("cmp_properties", []).copy(),
                "examples": symbol.get("examples", []).copy(),
            }
            print(f"\n--- {symbol_id} ---")
            print(f"  Description: {symbol.get('description', 'N/A')[:80]}...")
            if symbol.get("cmp_properties"):
                print(f"  CMP Properties:")
                for i, cmp in enumerate(symbol["cmp_properties"], 1):
                    print(f"    [{i}] {cmp}")
            if symbol.get("examples"):
                print(f"  Examples:")
                for i, ex in enumerate(symbol["examples"], 1):
                    print(f"    [{i}] {ex}")
        else:
            print(f"\n--- {symbol_id} --- (NOT FOUND)")

# %%
# Cell 5: Import and Initialize Normalizer (Jupyter only)
"""Import the normalizer module and initialize it."""

if _is_jupyter_mode():
    from openmath_normalizer import (
        OpenMathNormalizer,
        normalize_cmp_property,
        normalize_example,
    )

    normalizer = OpenMathNormalizer(
        kb_path=KB_INPUT_PATH,
        use_llm_fallback=USE_LLM,
        llm_model=LLM_MODEL,
    )
    print(f"Normalizer initialized (LLM fallback: {USE_LLM}).")

# %%
# Cell 6: Test Individual Expression Normalization (Jupyter only)
"""Test the normalization functions on individual expressions."""

if _is_jupyter_mode():
    print(f"\n{'=' * 70}")
    print("INDIVIDUAL EXPRESSION NORMALIZATION TESTS")
    print(f"{'=' * 70}")

    # Test CMP property normalization - includes quantifier cases
    test_cmps = [
        # Quantifier cases (problematic)
        "for all a,b | a + b = b + a",
        "for all a,b | a * 0 = 0 and a * b = a * (b - 1) + a",
        "for all a,b,c | a*(b+c) = a*b + a*c",
        "for all integers a,b | gcd(a,b) divides a",
        # Complex expressions
        "application of integrate followed by differentiate is the identity function, that is: diff(lambda y:integral(lambda z:f(z))(y)) = f",
        "for all integers a,b | There does not exist a c such that a/c is an Integer and b/c is an Integer and c > gcd(a,b)",
        # Simple expressions
        "sin(x)^2 + cos(x)^2 = 1",
        "cos 2A = cos^2 A - sin^2 A",
    ]

    print("\n--- CMP Property Normalization ---")
    print(f"(USE_LLM = {USE_LLM})")
    for i, cmp in enumerate(test_cmps, 1):
        normalized = normalize_cmp_property(cmp, use_llm_fallback=USE_LLM)
        changed = "CHANGED" if normalized != cmp else "unchanged"
        print(f"\n[{i}] {changed}")
        print(f"  Original:   {cmp}")
        print(f"  Normalized: {normalized}")

    # Test example normalization
    test_examples = [
        "An example which represents the equation: integral(x +-> sin(x)) w.r.t. x = x +-> -cos(x)",
        "gcd(6,9) = 3 6 9 3",
        "An example to represent the definite integration of sin(x) between the points -1.0 and 1.0.",
        "factorial(5) = 120",
        "sin(pi/2) = 1",
    ]

    print("\n--- Example Normalization ---")
    print(f"(USE_LLM = {USE_LLM})")
    for i, ex in enumerate(test_examples, 1):
        normalized = normalize_example(ex, use_llm_fallback=USE_LLM)
        changed = "CHANGED" if normalized != ex else "unchanged"
        print(f"\n[{i}] {changed}")
        print(f"  Original:   {ex}")
        print(f"  Normalized: {normalized}")

    if TEST_MODE:
        print(f"\n{'=' * 70}")
        print("TEST MODE: Skipping full normalization.")
        print("Set TEST_MODE = False in Cell 2 to run full normalization.")
        print(f"{'=' * 70}")

# %%
# Cell 7: Run Full Normalization (Jupyter only)
"""Run the normalization on the entire knowledge base."""

if _is_jupyter_mode() and not TEST_MODE:
    print(f"\n{'=' * 70}")
    print("RUNNING FULL NORMALIZATION")
    print(f"{'=' * 70}")

    # Load and normalize
    normalizer.load()
    normalizer.normalize()

    # Get statistics
    stats = normalizer.get_stats()
    print("\nNormalization Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
elif _is_jupyter_mode() and TEST_MODE:
    print("\n[TEST MODE] Skipping full normalization. Set TEST_MODE = False to run.")

# %%
# Cell 8: Compare Before and After (Jupyter only)
"""Show before/after comparison for target symbols."""

if _is_jupyter_mode() and not TEST_MODE:
    print(f"\n{'=' * 70}")
    print("BEFORE/AFTER COMPARISON")
    print(f"{'=' * 70}")

    normalized_symbols = normalizer.knowledge_base.get("symbols", {})

    comparison_results = []

    for symbol_id in TEST_SYMBOLS:
        if symbol_id in normalized_symbols:
            normalized = normalized_symbols[symbol_id]
            original = original_data.get(symbol_id, {})

            print(f"\n{'=' * 50}")
            print(f"SYMBOL: {symbol_id}")
            print(f"{'=' * 50}")

            # Compare CMP properties (original vs normalized)
            orig_cmps = original.get("cmp_properties", [])
            norm_cmps = normalized.get("cmp_properties_normalized", [])

            if orig_cmps or norm_cmps:
                print("\nCMP Properties:")
                for i, (orig, norm) in enumerate(
                    zip(orig_cmps, norm_cmps), 1
                ):
                    changed = "CHANGED" if orig != norm else "unchanged"
                    print(f"\n  [{i}] {changed}")
                    print(f"  BEFORE: {orig}")
                    print(f"  AFTER:  {norm}")

                    comparison_results.append({
                        "symbol_id": symbol_id,
                        "type": "cmp_property",
                        "index": i,
                        "original": orig,
                        "normalized": norm,
                        "changed": orig != norm,
                    })

            # Compare examples (original vs normalized)
            orig_examples = original.get("examples", [])
            norm_examples = normalized.get("examples_normalized", [])

            if orig_examples or norm_examples:
                print("\nExamples:")
                for i, (orig, norm) in enumerate(
                    zip(orig_examples, norm_examples), 1
                ):
                    changed = "CHANGED" if orig != norm else "unchanged"
                    print(f"\n  [{i}] {changed}")
                    print(f"  BEFORE: {orig}")
                    print(f"  AFTER:  {norm}")

                    comparison_results.append({
                        "symbol_id": symbol_id,
                        "type": "example",
                        "index": i,
                        "original": orig,
                        "normalized": norm,
                        "changed": orig != norm,
                    })

    # Summary
    changed_count = sum(1 for r in comparison_results if r["changed"])
    total_count = len(comparison_results)
    print(f"\n{'=' * 70}")
    print(f"SUMMARY: {changed_count}/{total_count} expressions were normalized")
    print(f"{'=' * 70}")

# %%
# Cell 9: Save Results (Jupyter only)
"""Save the normalized knowledge base and generate report."""

if _is_jupyter_mode() and not TEST_MODE:
    print(f"\n{'=' * 70}")
    print("SAVING RESULTS")
    print(f"{'=' * 70}")

    # Generate timestamp
    timestamp = datetime.now().strftime("%y%m%d_%H%M")

    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate report
    report_path = OUTPUT_DIR / f"phase-1b_normalization_results_{timestamp}.md"

    llm_mode_str = f"LLM={LLM_MODEL}" if USE_LLM else "Pattern-only"
    report_content = f"""# Phase 1b: Knowledge Base Normalization Results

**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Input**: {KB_INPUT_PATH}
**Output**: {KB_OUTPUT_PATH}
**Mode**: {llm_mode_str}

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total symbols | {stats['total_symbols']} |
| CMP normalized (pattern) | {stats['cmp_normalized']} |
| CMP normalized (LLM) | {stats.get('cmp_normalized_llm', 0)} |
| CMP unchanged | {stats['cmp_unchanged']} |
| CMP failed | {stats['cmp_failed']} |
| Examples normalized (pattern) | {stats['examples_normalized']} |
| Examples normalized (LLM) | {stats.get('examples_normalized_llm', 0)} |
| Examples unchanged | {stats['examples_unchanged']} |
| Examples failed | {stats['examples_failed']} |

## Target Symbol Comparisons

"""

    # Add comparison details
    for symbol_id in TEST_SYMBOLS:
        symbol_results = [r for r in comparison_results if r["symbol_id"] == symbol_id]
        if symbol_results:
            report_content += f"\n### {symbol_id}\n\n"
            for result in symbol_results:
                status = "NORMALIZED" if result["changed"] else "unchanged"
                report_content += f"**{result['type'].upper()} [{result['index']}]** - {status}\n\n"
                report_content += f"- Original: `{result['original'][:100]}{'...' if len(result['original']) > 100 else ''}`\n"
                report_content += f"- Normalized: `{result['normalized'][:100]}{'...' if len(result['normalized']) > 100 else ''}`\n\n"

    # Write report
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"Report saved to: {report_path}")

    # Save normalized knowledge base (unless dry run)
    if not DRY_RUN:
        output_path = normalizer.save(KB_OUTPUT_PATH)
        print(f"Normalized KB saved to: {output_path}")
    else:
        print("[DRY-RUN] Knowledge base NOT saved.")

    print(f"\n{'=' * 70}")
    print("PHASE 1b COMPLETE")
    print(f"{'=' * 70}")

# %%
# Cell 10: CLI Entry Point


def main():
    """Main function for CLI execution."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Phase 1b: Knowledge Base Normalization"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without saving changes",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Input JSON path (default: data/openmath.json)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path (default: overwrite input)",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Use LLM fallback for complex expressions",
    )
    parser.add_argument(
        "--llm-model",
        type=str,
        default="qwen2-math:7b",
        help="Ollama model for LLM normalization (default: qwen2-math:7b)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run only test examples (skip full normalization)",
    )

    args = parser.parse_args()

    # Configure paths
    input_path = Path(args.input) if args.input else KB_INPUT_PATH
    output_path = Path(args.output) if args.output else KB_OUTPUT_PATH
    dry_run = args.dry_run
    use_llm = args.use_llm
    llm_model = args.llm_model
    test_mode = args.test_mode

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Print configuration
    print("=" * 70)
    print("PHASE 1b: KNOWLEDGE BASE NORMALIZATION")
    print("=" * 70)
    print(f"Input path:    {input_path}")
    print(f"Output path:   {output_path}")
    print(f"Dry run:       {dry_run}")
    print(f"Use LLM:       {use_llm}")
    print(f"LLM model:     {llm_model}")
    print(f"Test mode:     {test_mode}")
    print("=" * 70)

    # Import normalizer
    from openmath_normalizer import (
        OpenMathNormalizer,
        normalize_cmp_property,
        normalize_example,
    )

    # Load original data to preserve for comparison
    with open(input_path, "r", encoding="utf-8") as f:
        original_kb = json.load(f)
    symbols = original_kb.get("symbols", {})
    print(f"\nLoaded {len(symbols)} symbols")

    # Save original data for target symbols
    original_data = {}
    for symbol_id in TEST_SYMBOLS:
        if symbol_id in symbols:
            symbol = symbols[symbol_id]
            original_data[symbol_id] = {
                "cmp_properties": symbol.get("cmp_properties", []).copy(),
                "examples": symbol.get("examples", []).copy(),
            }

    # Test individual expressions
    print("\n--- Testing Individual Expressions ---")
    print(f"(USE_LLM = {use_llm})")

    test_cmps = [
        # Quantifier cases (problematic)
        "for all a,b | a + b = b + a",
        "for all a,b | a * 0 = 0 and a * b = a * (b - 1) + a",
        "for all a,b,c | a*(b+c) = a*b + a*c",
        "for all integers a,b | gcd(a,b) divides a",
        # Complex expressions
        "application of integrate followed by differentiate is the identity function, that is: diff(lambda y:integral(lambda z:f(z))(y)) = f",
        # Simple expressions
        "sin(x)^2 + cos(x)^2 = 1",
        "cos 2A = cos^2 A - sin^2 A",
    ]

    for i, cmp in enumerate(test_cmps, 1):
        normalized = normalize_cmp_property(cmp, use_llm_fallback=use_llm)
        changed = "CHANGED" if normalized != cmp else "unchanged"
        print(f"\n[{i}] {changed}")
        print(f"  Original:   {cmp}")
        print(f"  Normalized: {normalized}")

    if test_mode:
        print("\n" + "=" * 70)
        print("TEST MODE: Skipping full normalization.")
        print("Remove --test-mode flag to run full normalization.")
        print("=" * 70)
        return

    # Run full normalization
    print("\n--- Running Full Normalization ---")
    normalizer = OpenMathNormalizer(
        kb_path=input_path,
        use_llm_fallback=use_llm,
        llm_model=llm_model,
    )
    normalizer.load()
    normalizer.normalize()

    stats = normalizer.get_stats()
    print("\nStatistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # Compare before/after
    print("\n--- Before/After Comparison ---")
    normalized_symbols = normalizer.knowledge_base.get("symbols", {})
    comparison_results = []

    for symbol_id in TEST_SYMBOLS[:5]:  # Limit output for CLI
        if symbol_id in normalized_symbols:
            normalized = normalized_symbols[symbol_id]
            original = original_data.get(symbol_id, {})

            print(f"\n{symbol_id}:")

            # Compare CMP properties (original vs normalized)
            orig_cmps = original.get("cmp_properties", [])
            norm_cmps = normalized.get("cmp_properties_normalized", [])

            for i, (orig, norm) in enumerate(zip(orig_cmps, norm_cmps), 1):
                changed = "CHANGED" if orig != norm else "unchanged"
                print(f"  CMP [{i}] {changed}")
                if changed == "CHANGED":
                    print(f"    Before: {orig[:60]}...")
                    print(f"    After:  {norm[:60]}...")

                comparison_results.append({
                    "symbol_id": symbol_id,
                    "type": "cmp_property",
                    "index": i,
                    "original": orig,
                    "normalized": norm,
                    "changed": orig != norm,
                })

    # Save results
    timestamp = datetime.now().strftime("%y%m%d_%H%M")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"phase-1b_normalization_results_{timestamp}.md"

    # Generate report
    llm_mode = f"LLM={llm_model}" if use_llm else "Pattern-only"
    report_content = f"""# Phase 1b: Knowledge Base Normalization Results

**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Mode**: {'DRY-RUN' if dry_run else 'PRODUCTION'} ({llm_mode})

## Statistics

| Metric | Value |
|--------|-------|
| Total symbols | {stats['total_symbols']} |
| CMP normalized (pattern) | {stats['cmp_normalized']} |
| CMP normalized (LLM) | {stats.get('cmp_normalized_llm', 0)} |
| CMP unchanged | {stats['cmp_unchanged']} |
| Examples normalized (pattern) | {stats['examples_normalized']} |
| Examples normalized (LLM) | {stats.get('examples_normalized_llm', 0)} |
| Examples unchanged | {stats['examples_unchanged']} |

## Sample Comparisons

"""

    for result in comparison_results:
        if result["changed"]:
            report_content += f"### {result['symbol_id']} - {result['type']} [{result['index']}]\n\n"
            report_content += f"**Original**: {result['original']}\n\n"
            report_content += f"**Normalized**: {result['normalized']}\n\n"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"\nReport saved to: {report_path}")

    # Save KB
    if not dry_run:
        output_path = normalizer.save(output_path)
        print(f"Normalized KB saved to: {output_path}")
    else:
        print("[DRY-RUN] Knowledge base NOT saved.")

    print("\n" + "=" * 70)
    print("PHASE 1b COMPLETE")
    print("=" * 70)


# Only run CLI when executed directly (not in Jupyter)
if __name__ == "__main__" and not _is_jupyter_mode():
    main()
