#!/usr/bin/env python3
"""
This script runs MATH 500 experiments with OpenMath symbols filtered by reranker_score
threshold BEFORE inference. Only problems with at least one symbol above the threshold
are included.

Key Features:
- --threshold argument for filtering OpenMath symbols
- Only processes problems with qualifying symbols
- Baseline condition uses the same filtered problem set for fair comparison
- Filename convention: experiment_<MODEL>_<CONDITION>_<MODE>_<THRESHOLD>_<TIMESTAMP>.md

Usage:
    # Dry run (preview config without running)
    python pipeline/5_run_experiment.py \
        --model "gemma2:9b" --condition openmath --threshold 0.3 --dry-run

    # Test mode (2 problems)
    python pipeline/5_run_experiment.py \
        --model "gemma2:9b" --condition openmath --threshold 0.3 --test-mode

    # Full run at threshold 0.3
    python pipeline/5_run_experiment.py \
        --model "johnnyboy/qwen2.5-math-7b:latest" --condition openmath \
        --mode greedy --threshold 0.3 --n-problems 500
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

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
sys.path.insert(0, str(PROJECT_ROOT / "experiments"))

# Import filter from run_threshold_filter
from run_threshold_filter import (
    MODEL_NAME_MAP,
    filter_by_threshold,
    get_problem_ids_at_threshold,
    load_reranked_data,
    normalize_model_name,
)

# Default paths
DEFAULT_RERANKED = PROJECT_ROOT / "data/openmath-reranked.json"
OUTPUT_DIR = PROJECT_ROOT / "results"

# Supported models
SUPPORTED_MODELS = [
    "johnnyboy/qwen2.5-math-7b:latest",
    "gemma2:2b",
    "gemma2:9b",
]

# Model configuration for prompting
MODEL_CONFIG = {
    "johnnyboy/qwen2.5-math-7b:latest": {
        "uses_system_prompt": True,
        "strategy": "minimalist_cot",
        "trigger": "Please reason step by step, and put your final answer within \\boxed{}.",
    },
    "gemma2:2b": {
        "uses_system_prompt": True,
        "strategy": "system2_reflection",
    },
    "gemma2:9b": {
        "uses_system_prompt": True,
        "strategy": "system2_reflection",
    },
}

SYSTEM2_PROMPT = """You are an expert mathematician. Your goal is to solve challenging mathematical problems correctly.
Follow this strict process:
1. BREAKDOWN: Identify the core question and variables.
2. PLAN: Outline the steps to solve the problem.
3. SOLVE: Execute the steps carefully, showing all work.
4. VERIFY: Double-check your logic and calculations.
5. FORMAT: Put the final answer inside \\boxed{}."""


@dataclass
class ExperimentResult:
    """Result for a single problem."""

    problem_id: str
    level: int
    problem_type: str
    problem_text: str
    ground_truth: str
    condition: str
    mode: str
    model: str
    threshold: float
    response: str
    predicted_answer: str
    is_correct: bool
    comparison_method: str
    attempts: int
    elapsed_time: float
    system_prompt: str = ""
    user_prompt: str = ""
    openmath_symbols: list = None

    def __post_init__(self):
        if self.openmath_symbols is None:
            self.openmath_symbols = []


def build_prompt(
    model: str,
    problem: str,
    openmath_context: str = "",
) -> dict[str, str]:
    """Build model-specific prompt."""
    config = MODEL_CONFIG.get(model, {"uses_system_prompt": True, "strategy": "system2_reflection"})
    strategy = config.get("strategy", "system2_reflection")
    uses_system = config.get("uses_system_prompt", True)

    if strategy == "minimalist_cot":
        trigger = config.get("trigger", "Please reason step by step, and put your final answer within \\boxed{}.")

        if uses_system:
            system = openmath_context if openmath_context else ""
            user = f"{problem}\n\n{trigger}"
        else:
            user_parts = []
            if openmath_context:
                user_parts.append(openmath_context)
            user_parts.append(problem)
            user_parts.append(f"\n{trigger}")
            system = ""
            user = "\n\n".join(user_parts)
    else:
        system_parts = []
        if openmath_context:
            system_parts.append(openmath_context)
        system_parts.append(SYSTEM2_PROMPT)
        system = "\n\n".join(system_parts)
        user = f"Problem: {problem}"

    return {"system": system, "user": user}


def format_openmath_context(
    problem_id: str,
    filtered_data: dict[str, Any],
    top_k: int = 20,
) -> str:
    """Format OpenMath symbols for prompt injection."""
    if problem_id not in filtered_data:
        return ""

    symbols = filtered_data[problem_id].get("reranked_symbols", [])
    if not symbols:
        return ""

    lines = ["## Relevant Mathematical Definitions and Properties", ""]

    for sym in symbols[:top_k]:
        cd_name = f"{sym.get('cd', '')}:{sym.get('name', '')}"
        lines.append(f"### {cd_name}")

        desc = sym.get("description_normalized", "")
        if desc:
            desc = " ".join(desc.split())
            lines.append(f"**Description:** {desc}")

        props = sym.get("cmp_properties_normalized", [])
        if props:
            lines.append("**Properties:**")
            for prop in props[:3]:
                lines.append(f"  - {prop}")

        examples = sym.get("examples_normalized", [])
        if examples and examples[0]:
            lines.append(f"**Example:** {examples[0]}")

        lines.append("")

    return "\n".join(lines)


def call_ollama(
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.0,
    max_tokens: int = 4096,
    base_url: str = "http://localhost:11434",
    timeout: int = 180,
    max_retries: int = 3,
) -> tuple[str, float]:
    """Call Ollama API with retry logic."""
    url = f"{base_url}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "num_ctx": 4096,
        },
    }

    for attempt in range(max_retries):
        try:
            start_time = time.time()
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            elapsed = time.time() - start_time

            result = response.json()
            content = result.get("message", {}).get("content", "")
            return content, elapsed

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                logger.warning(f"Ollama API error (attempt {attempt + 1}): {e}")
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Ollama API failed after {max_retries} attempts: {e}")
                raise

    return "", 0.0


def main():
    """Main CLI entry point."""
    # Default values
    default_model = "johnnyboy/qwen2.5-math-7b:latest"
    default_ollama_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434/v1")
    if default_ollama_url.endswith("/v1"):
        default_ollama_url = default_ollama_url[:-3]

    parser = argparse.ArgumentParser(
        description="Phase 5: Threshold-Based Experiment Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline/5_run_experiment.py --threshold 0.3 --dry-run
  python pipeline/5_run_experiment.py --threshold 0.3 --test-mode
  python pipeline/5_run_experiment.py --threshold 0.5 --condition openmath
        """,
    )
    parser.add_argument(
        "--model",
        default=default_model,
        help=f"Ollama model name (default: {default_model})",
    )
    parser.add_argument(
        "--condition",
        default="openmath",
        choices=["baseline", "openmath"],
        help="Experimental condition (default: openmath)",
    )
    parser.add_argument(
        "--mode",
        default="greedy",
        choices=["greedy", "best-of-n"],
        help="Inference mode (default: greedy)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Minimum reranker_score threshold (default: 0.0)",
    )
    parser.add_argument(
        "--n-problems",
        type=int,
        default=500,
        help="Max problems to run (default: 500, may be fewer after filtering)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=5,
        help="Max attempts for best-of-n mode (default: 5)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Maximum generation tokens (default: 4096)",
    )
    parser.add_argument(
        "--top-k-symbols",
        type=int,
        default=20,
        help="Max OpenMath symbols to include (default: 20)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.6,
        help="Temperature for best-of-n mode (default: 0.6)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    parser.add_argument(
        "--ollama-url",
        default=None,
        help=f"Ollama API base URL (default: {default_ollama_url})",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--reranked",
        type=Path,
        default=DEFAULT_RERANKED,
        help=f"Path to reranked JSON (default: {DEFAULT_RERANKED})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print config without running experiment",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Run only 2 problems for quick testing",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Parse arguments
    model = args.model
    condition = args.condition
    mode = args.mode
    threshold = args.threshold
    n_problems = 2 if args.test_mode else min(args.n_problems, 500)
    max_attempts = args.max_attempts
    max_tokens = args.max_tokens
    top_k_symbols = args.top_k_symbols
    temperature = args.temperature
    seed = args.seed
    output_dir = Path(args.output_dir)
    ollama_url = args.ollama_url if args.ollama_url else default_ollama_url
    if ollama_url.endswith("/v1"):
        ollama_url = ollama_url[:-3]

    # Get clean model name for filenames
    model_clean = normalize_model_name(model)

    # Print configuration
    print("=" * 70)
    print("PHASE 5: THRESHOLD-BASED EXPERIMENT RUNNER")
    print("=" * 70)
    print(f"Model:          {model} ({model_clean})")
    print(f"Condition:      {condition}")
    print(f"Mode:           {mode}")
    print(f"Threshold:      {threshold}")
    print(f"N problems:     {n_problems} (max)")
    print(f"Seed:           {seed}")
    print(f"Max tokens:     {max_tokens}")
    print(f"Max attempts:   {max_attempts}")
    print(f"Temperature:    {temperature} (best-of-n only)")
    print(f"Top K symbols:  {top_k_symbols}")
    print(f"Ollama URL:     {ollama_url}")
    print(f"Output dir:     {output_dir}")
    print(f"Reranked file:  {args.reranked}")
    if args.test_mode:
        print("TEST MODE:      Yes (2 problems)")
    print("=" * 70)

    if args.dry_run:
        print("\nDRY RUN - No experiment will be executed")
        print(f"\nOutput filename would be:")
        ts = datetime.now().strftime("%y%m%d_%H%M")
        fname = f"experiment_{model_clean}_{condition}_{mode}_{threshold}_{ts}.md"
        print(f"  {output_dir / fname}")
        return

    # Load benchmark data
    from benchmark_loader import BenchmarkLoader
    from code_extractor import create_code_extractor
    from comparator import create_comparator

    print("\nLoading MATH 500 benchmark...")
    loader = BenchmarkLoader(project_root=PROJECT_ROOT)
    dataset = loader.load()
    print(f"Loaded {len(dataset)} problems")

    # Load and filter OpenMath data
    if not args.reranked.exists():
        print(f"ERROR: Reranked file not found: {args.reranked}")
        sys.exit(1)

    print(f"\nLoading OpenMath reranked data from {args.reranked}...")
    reranked_data = load_reranked_data(args.reranked)
    print(f"Loaded data for {len(reranked_data)} problems")

    # Filter by threshold
    filtered_data = filter_by_threshold(reranked_data, threshold)
    valid_problem_ids = set(filtered_data.keys())
    print(f"Problems with symbols at threshold >= {threshold}: {len(valid_problem_ids)}")

    # Get problems that pass threshold filter
    all_problems = {p.id: p for p in dataset}
    filtered_problems = {pid: all_problems[pid] for pid in valid_problem_ids if pid in all_problems}
    print(f"Problems available after filtering: {len(filtered_problems)}")

    # Sample problems
    random.seed(seed)
    problem_ids = list(filtered_problems.keys())
    if len(problem_ids) > n_problems:
        problem_ids = random.sample(problem_ids, n_problems)
    problems = {pid: filtered_problems[pid] for pid in problem_ids}
    print(f"Selected {len(problems)} problems (seed={seed})")

    if len(problems) == 0:
        print("\nERROR: No problems available at this threshold!")
        print("Try a lower threshold value.")
        sys.exit(1)

    # Initialize components
    extractor = create_code_extractor()
    comparator = create_comparator()
    print("\nComponents initialized")

    # Run experiment
    print("\n" + "-" * 70)
    print("RUNNING EXPERIMENT")
    print("-" * 70)

    results: list[ExperimentResult] = []
    exp_start = time.time()

    for i, pid in enumerate(sorted(problems.keys()), 1):
        prob = problems[pid]
        print(f"\r[{i}/{len(problems)}] {pid}...", end="", flush=True)

        # Build context (only for openmath condition)
        ctx = ""
        syms: list[str] = []
        if condition == "openmath" and pid in filtered_data:
            ctx = format_openmath_context(pid, filtered_data, top_k_symbols)
            syms = [
                f"{s.get('cd', '')}:{s.get('name', '')}"
                for s in filtered_data[pid].get("reranked_symbols", [])[:top_k_symbols]
            ]

        # Build prompt
        pmt = build_prompt(model, prob.problem, ctx)

        try:
            if mode == "greedy":
                messages = []
                if pmt["system"]:
                    messages.append({"role": "system", "content": pmt["system"]})
                messages.append({"role": "user", "content": pmt["user"]})

                resp, elapsed = call_ollama(model, messages, 0.0, max_tokens, ollama_url)
                att = 1

                ext = extractor.extract(resp)
                pred = ext.primary_answer or ""
                correct = False
                cmp_method = "no_answer"

                if pred:
                    cmp_res = comparator.compare(pred, prob.answer)
                    correct = cmp_res.is_equivalent
                    cmp_method = cmp_res.comparison_method

            else:
                # Best-of-N mode
                messages = []
                if pmt["system"]:
                    messages.append({"role": "system", "content": pmt["system"]})
                messages.append({"role": "user", "content": pmt["user"]})

                total_time = 0.0
                resp = ""
                correct = False
                att = max_attempts

                for attempt in range(1, max_attempts + 1):
                    resp, elapsed = call_ollama(model, messages, temperature, max_tokens, ollama_url)
                    total_time += elapsed
                    ext = extractor.extract(resp)
                    pred = ext.primary_answer or ""
                    if pred:
                        cmp_res = comparator.compare(pred, prob.answer)
                        if cmp_res.is_equivalent:
                            correct = True
                            att = attempt
                            break

                elapsed = total_time
                ext = extractor.extract(resp)
                pred = ext.primary_answer or ""
                cmp_method = "best_of_n"

        except Exception as e:
            logger.error(f"Error processing {pid}: {e}")
            resp, pred, correct, cmp_method, elapsed, att = f"ERROR: {e}", "", False, "error", 0.0, 1

        results.append(ExperimentResult(
            problem_id=pid,
            level=prob.level,
            problem_type=prob.problem_type,
            problem_text=prob.problem,
            ground_truth=prob.answer,
            condition=condition,
            mode=mode,
            model=model,
            threshold=threshold,
            response=resp,
            predicted_answer=pred,
            is_correct=correct,
            comparison_method=cmp_method,
            attempts=att,
            elapsed_time=elapsed,
            system_prompt=pmt["system"],
            user_prompt=pmt["user"],
            openmath_symbols=syms,
        ))

    exp_elapsed = time.time() - exp_start
    print(f"\n\nCompleted in {exp_elapsed:.1f}s")

    # Statistics
    corr = sum(1 for r in results if r.is_correct)
    tot = len(results)
    acc = corr / tot * 100 if tot > 0 else 0
    avg_att = sum(r.attempts for r in results) / tot if tot > 0 else 0

    print(f"\nOverall: {corr}/{tot} ({acc:.1f}%)")
    print(f"Avg attempts: {avg_att:.2f}")

    # By level
    by_lv: dict[int, dict[str, int]] = {}
    for r in results:
        by_lv.setdefault(r.level, {"c": 0, "t": 0})
        by_lv[r.level]["t"] += 1
        if r.is_correct:
            by_lv[r.level]["c"] += 1

    print("\nBy Level:")
    for lv in sorted(by_lv.keys()):
        lv_acc = by_lv[lv]["c"] / by_lv[lv]["t"] * 100 if by_lv[lv]["t"] > 0 else 0
        print(f"  Level {lv}: {by_lv[lv]['c']}/{by_lv[lv]['t']} ({lv_acc:.1f}%)")

    # By type
    by_tp: dict[str, dict[str, int]] = {}
    for r in results:
        by_tp.setdefault(r.problem_type, {"c": 0, "t": 0})
        by_tp[r.problem_type]["t"] += 1
        if r.is_correct:
            by_tp[r.problem_type]["c"] += 1

    print("\nBy Type:")
    for tp in sorted(by_tp.keys()):
        tp_acc = by_tp[tp]["c"] / by_tp[tp]["t"] * 100 if by_tp[tp]["t"] > 0 else 0
        print(f"  {tp}: {by_tp[tp]['c']}/{by_tp[tp]['t']} ({tp_acc:.1f}%)")

    # Save results
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%y%m%d_%H%M")
    fname = f"experiment_{model_clean}_{condition}_{mode}_{threshold}_{ts}.md"
    out_path = output_dir / fname

    lines = [
        "# OpenMath Ontology Mathematical Problem Solving Experiment",
        "",
        f"**Condition**: {condition}",
        f"**Mode**: {mode}",
        f"**Model**: {model}",
        f"**Threshold**: {threshold}",
        f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Configuration",
        "",
        f"- Number of problems: {tot} (filtered by threshold >= {threshold})",
        f"- Max tokens: {max_tokens}",
        f"- Max attempts: {max_attempts}",
        f"- Temperature: {temperature} (best-of-n only)",
        f"- Top K symbols: {top_k_symbols}",
        f"- Seed: {seed}",
        f"- Ollama URL: {ollama_url}",
        "",
        "---",
        "",
        "## Summary",
        "",
        f"**Overall Accuracy**: {corr}/{tot} ({acc:.1f}%)",
        f"**Average Number of Attempts**: {avg_att:.2f}",
        "",
        "### By Level",
    ]

    for lv in sorted(by_lv.keys()):
        lv_acc = by_lv[lv]["c"] / by_lv[lv]["t"] * 100 if by_lv[lv]["t"] > 0 else 0
        lines.append(f"- Level {lv}: {by_lv[lv]['c']}/{by_lv[lv]['t']} ({lv_acc:.1f}%)")

    lines.extend(["", "### By Problem Type"])
    for tp in sorted(by_tp.keys()):
        tp_acc = by_tp[tp]["c"] / by_tp[tp]["t"] * 100 if by_tp[tp]["t"] > 0 else 0
        lines.append(f"- {tp}: {by_tp[tp]['c']}/{by_tp[tp]['t']} ({tp_acc:.1f}%)")

    lines.extend(["", "---", "", "# Detailed Results", ""])

    for r in results:
        lines.extend([
            f"## Problem {r.problem_id}",
            f"  Level: {r.level}",
            f"  Type: {r.problem_type}",
            f"  Problem Statement: {r.problem_text}",
            f"  Ground Truth: {r.ground_truth}",
            "",
            f"## Response {r.problem_id}",
            f"  Attempt: {r.attempts}",
            f"  Answer: {r.predicted_answer}",
            f"  Is Correct: {r.is_correct}",
        ])
        if r.openmath_symbols:
            lines.append(f"  OpenMath Symbols: {r.openmath_symbols}")
        lines.extend([
            "",
            "--- System Prompt ---",
            r.system_prompt if r.system_prompt else "(empty)",
            "--- End System Prompt ---",
            "",
            "--- User Prompt ---",
            r.user_prompt,
            "--- End User Prompt ---",
            "",
            "--- LLM Response ---",
            r.response,
            "--- End LLM Response ---",
            "",
            "-" * 56,
            "",
        ])

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nResults saved to: {out_path}")
    print(f"File size: {out_path.stat().st_size / 1024:.2f} KB")

    print("\n" + "=" * 70)
    print("EXPERIMENT COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
