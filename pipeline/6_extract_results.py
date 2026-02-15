#!/usr/bin/env python3
"""
Extract Results

This script directly extracts structured results from baseline/openmath experiment file pairs.

Usage:
    python pipeline/6_extract_results.py \\
        --config configs/results/extract_results.yaml

    # Override output
    python pipeline/6_extract_results.py \\
        --config configs/results/extract_results.yaml \\
        --output results/my_results.csv
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_RERANKED = PROJECT_ROOT / "data/openmath-reranked.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results"

# Model name mapping for CSV output (Ollama name -> clean name)
MODEL_NAME_MAP = {
    "johnnyboy/qwen2.5-math-7b:latest": "qwen2.5-math-7b",
    "gemma2:9b": "gemma2-9b",
    "gemma2:2b": "gemma2-2b",
}

# Problem types and levels
PROBLEM_TYPES = [
    "algebra",
    "counting_&_probability",
    "geometry",
    "intermediate_algebra",
    "number_theory",
    "prealgebra",
    "precalculus",
]
LEVELS = [1, 2, 3, 4, 5]

# CSV field names
CSV_FIELDNAMES = [
    "model",
    "problems",
    "correct",
    "attempts",
    "condition",
    "mode",
    "level",
    "type",
    "threshold",
]


@dataclass
class ProblemResult:
    """Parsed result for a single problem from experiment markdown."""

    problem_id: str
    level: int
    problem_type: str
    is_correct: bool
    attempts: int = 1


@dataclass
class ExperimentMetadata:
    """Metadata extracted from experiment markdown header."""

    condition: str
    mode: str
    model: str
    date: str
    n_problems: int
    max_tokens: int
    max_attempts: int
    temperature: float
    top_k_symbols: int
    seed: int


@dataclass
class ThresholdStats:
    """Statistics for a given threshold."""

    threshold: float
    n_problems: int
    baseline_correct: int
    openmath_correct: int
    baseline_accuracy: float
    openmath_accuracy: float
    delta: float
    by_level: dict = field(default_factory=dict)
    by_type: dict = field(default_factory=dict)
    avg_attempts_baseline: float = 1.0
    avg_attempts_openmath: float = 1.0


def normalize_model_name(model: str) -> str:
    """Normalize model name from Ollama format to clean format."""
    # Direct lookup
    if model in MODEL_NAME_MAP:
        return MODEL_NAME_MAP[model]

    # Try partial matching
    for ollama_name, clean_name in MODEL_NAME_MAP.items():
        if ollama_name in model or model in ollama_name:
            return clean_name

    # Fallback: clean up the model name
    clean = model.replace("/", "-").replace(":", "-").replace("_", "-")
    return clean.lower()


def load_reranked_data(path: Path) -> dict:
    """Load the openmath-reranked.json file."""
    with open(path) as f:
        return json.load(f)


def get_max_score_per_problem(reranked_data: dict) -> dict[str, float]:
    """
    Get the maximum reranker_score for each problem.

    Returns:
        Dict mapping problem_id -> max reranker_score across all symbols
    """
    max_scores = {}
    for problem_id, data in reranked_data.items():
        if data.get("reranked_symbols"):
            max_score = max(s["reranker_score"] for s in data["reranked_symbols"])
        else:
            max_score = 0.0
        max_scores[problem_id] = max_score
    return max_scores


def filter_problems_by_threshold(
    max_scores: dict[str, float], threshold: float
) -> set[str]:
    """
    Get set of problem IDs where max reranker_score >= threshold.

    Args:
        max_scores: Dict mapping problem_id -> max reranker_score
        threshold: Minimum score threshold

    Returns:
        Set of problem IDs meeting the threshold
    """
    return {pid for pid, score in max_scores.items() if score >= threshold}


def parse_experiment_results(
    md_path: Path,
) -> tuple[ExperimentMetadata, dict[str, ProblemResult]]:
    """
    Parse experiment markdown file to extract results.

    Args:
        md_path: Path to experiment markdown file

    Returns:
        Tuple of (metadata, results_dict)
        where results_dict maps problem_id -> ProblemResult
    """
    content = md_path.read_text()

    # Extract metadata from header
    condition_match = re.search(r"\*\*Condition\*\*:\s*(\w+)", content)
    mode_match = re.search(r"\*\*Mode\*\*:\s*(\S+)", content)
    model_match = re.search(r"\*\*Model\*\*:\s*(.+?)$", content, re.MULTILINE)
    date_match = re.search(r"\*\*Date\*\*:\s*(.+?)$", content, re.MULTILINE)
    n_problems_match = re.search(r"Number of problems:\s*(\d+)", content)
    max_tokens_match = re.search(r"Max tokens:\s*(\d+)", content)
    max_attempts_match = re.search(r"Max attempts:\s*(\d+)", content)
    temp_match = re.search(r"Temperature:\s*([\d.]+)", content)
    top_k_match = re.search(r"Top K symbols:\s*(\d+)", content)
    seed_match = re.search(r"Seed:\s*(\d+)", content)

    metadata = ExperimentMetadata(
        condition=condition_match.group(1) if condition_match else "unknown",
        mode=mode_match.group(1) if mode_match else "unknown",
        model=model_match.group(1).strip() if model_match else "unknown",
        date=date_match.group(1).strip() if date_match else "unknown",
        n_problems=int(n_problems_match.group(1)) if n_problems_match else 0,
        max_tokens=int(max_tokens_match.group(1)) if max_tokens_match else 0,
        max_attempts=int(max_attempts_match.group(1)) if max_attempts_match else 0,
        temperature=float(temp_match.group(1)) if temp_match else 0.0,
        top_k_symbols=int(top_k_match.group(1)) if top_k_match else 0,
        seed=int(seed_match.group(1)) if seed_match else 0,
    )

    # Parse individual problem results
    # Pattern: ## Problem math_XXXXX followed by metadata lines
    problem_pattern = re.compile(
        r"## Problem (math_\d+)\s*\n" r"\s*Level:\s*(\d+)\s*\n" r"\s*Type:\s*(\S+)\s*\n",
        re.MULTILINE,
    )

    # Pattern: ## Response math_XXXXX followed by result lines
    response_pattern = re.compile(
        r"## Response (math_\d+)\s*\n"
        r"\s*Attempt:\s*(\d+)\s*\n"
        r"\s*Answer:.*?\n"
        r"\s*Is Correct:\s*(True|False)",
        re.MULTILINE | re.DOTALL,
    )

    # Extract problem metadata
    problem_meta = {}
    for match in problem_pattern.finditer(content):
        problem_id = match.group(1)
        problem_meta[problem_id] = {
            "level": int(match.group(2)),
            "type": match.group(3),
        }

    # Extract response results
    results = {}
    for match in response_pattern.finditer(content):
        problem_id = match.group(1)
        if problem_id in problem_meta:
            results[problem_id] = ProblemResult(
                problem_id=problem_id,
                level=problem_meta[problem_id]["level"],
                problem_type=problem_meta[problem_id]["type"],
                is_correct=match.group(3) == "True",
                attempts=int(match.group(2)),
            )

    return metadata, results


def compute_threshold_stats(
    threshold: float,
    filtered_problems: set[str],
    baseline_results: dict[str, ProblemResult],
    openmath_results: dict[str, ProblemResult],
) -> ThresholdStats:
    """
    Compute statistics for problems meeting the threshold.

    Args:
        threshold: The score threshold used
        filtered_problems: Set of problem IDs meeting threshold
        baseline_results: Results from baseline experiment
        openmath_results: Results from openmath experiment

    Returns:
        ThresholdStats with computed metrics
    """
    # Filter results to only those problems
    baseline_filtered = {
        pid: r for pid, r in baseline_results.items() if pid in filtered_problems
    }
    openmath_filtered = {
        pid: r for pid, r in openmath_results.items() if pid in filtered_problems
    }

    # Compute overall stats
    n_problems = len(filtered_problems)
    baseline_correct = sum(1 for r in baseline_filtered.values() if r.is_correct)
    openmath_correct = sum(1 for r in openmath_filtered.values() if r.is_correct)

    baseline_accuracy = (baseline_correct / n_problems * 100) if n_problems > 0 else 0.0
    openmath_accuracy = (openmath_correct / n_problems * 100) if n_problems > 0 else 0.0
    delta = openmath_accuracy - baseline_accuracy

    # Compute average attempts
    baseline_attempts = [r.attempts for r in baseline_filtered.values()]
    openmath_attempts = [r.attempts for r in openmath_filtered.values()]
    avg_attempts_baseline = (
        sum(baseline_attempts) / len(baseline_attempts) if baseline_attempts else 1.0
    )
    avg_attempts_openmath = (
        sum(openmath_attempts) / len(openmath_attempts) if openmath_attempts else 1.0
    )

    # Compute by level
    by_level = defaultdict(
        lambda: {
            "baseline_correct": 0,
            "openmath_correct": 0,
            "total": 0,
            "baseline_attempts_sum": 0,
            "openmath_attempts_sum": 0,
        }
    )
    for pid in filtered_problems:
        if pid in baseline_filtered and pid in openmath_filtered:
            level = baseline_filtered[pid].level
            by_level[level]["total"] += 1
            by_level[level]["baseline_attempts_sum"] += baseline_filtered[pid].attempts
            by_level[level]["openmath_attempts_sum"] += openmath_filtered[pid].attempts
            if baseline_filtered[pid].is_correct:
                by_level[level]["baseline_correct"] += 1
            if openmath_filtered[pid].is_correct:
                by_level[level]["openmath_correct"] += 1

    # Compute by type
    by_type = defaultdict(
        lambda: {
            "baseline_correct": 0,
            "openmath_correct": 0,
            "total": 0,
            "baseline_attempts_sum": 0,
            "openmath_attempts_sum": 0,
        }
    )
    for pid in filtered_problems:
        if pid in baseline_filtered and pid in openmath_filtered:
            ptype = baseline_filtered[pid].problem_type
            by_type[ptype]["total"] += 1
            by_type[ptype]["baseline_attempts_sum"] += baseline_filtered[pid].attempts
            by_type[ptype]["openmath_attempts_sum"] += openmath_filtered[pid].attempts
            if baseline_filtered[pid].is_correct:
                by_type[ptype]["baseline_correct"] += 1
            if openmath_filtered[pid].is_correct:
                by_type[ptype]["openmath_correct"] += 1

    return ThresholdStats(
        threshold=threshold,
        n_problems=n_problems,
        baseline_correct=baseline_correct,
        openmath_correct=openmath_correct,
        baseline_accuracy=baseline_accuracy,
        openmath_accuracy=openmath_accuracy,
        delta=delta,
        by_level=dict(by_level),
        by_type=dict(by_type),
        avg_attempts_baseline=avg_attempts_baseline,
        avg_attempts_openmath=avg_attempts_openmath,
    )


def generate_csv_rows(
    model: str, mode: str, stats: ThresholdStats
) -> list[dict]:
    """
    Generate CSV rows from threshold stats.

    Args:
        model: Normalized model name
        mode: Experiment mode (greedy or best-of-n)
        stats: ThresholdStats with computed metrics

    Returns:
        List of dicts representing CSV rows (26 rows per threshold: 13 baseline + 13 openmath)
    """
    rows = []
    threshold = stats.threshold

    # Overall rows (level=all, type=all)
    rows.append({
        "model": model,
        "problems": stats.n_problems,
        "correct": stats.baseline_correct,
        "attempts": round(stats.avg_attempts_baseline, 2),
        "condition": "baseline",
        "mode": mode,
        "level": "all",
        "type": "all",
        "threshold": threshold,
    })
    rows.append({
        "model": model,
        "problems": stats.n_problems,
        "correct": stats.openmath_correct,
        "attempts": round(stats.avg_attempts_openmath, 2),
        "condition": "openmath",
        "mode": mode,
        "level": "all",
        "type": "all",
        "threshold": threshold,
    })

    # Per-level rows (type=all)
    for level in LEVELS:
        if level in stats.by_level:
            data = stats.by_level[level]
            total = data["total"]
            b_attempts = data["baseline_attempts_sum"] / total if total > 0 else 1.0
            o_attempts = data["openmath_attempts_sum"] / total if total > 0 else 1.0

            rows.append({
                "model": model,
                "problems": total,
                "correct": data["baseline_correct"],
                "attempts": round(b_attempts, 2),
                "condition": "baseline",
                "mode": mode,
                "level": level,
                "type": "all",
                "threshold": threshold,
            })
            rows.append({
                "model": model,
                "problems": total,
                "correct": data["openmath_correct"],
                "attempts": round(o_attempts, 2),
                "condition": "openmath",
                "mode": mode,
                "level": level,
                "type": "all",
                "threshold": threshold,
            })
        else:
            # No problems at this level for this threshold
            rows.append({
                "model": model,
                "problems": 0,
                "correct": 0,
                "attempts": 1.0,
                "condition": "baseline",
                "mode": mode,
                "level": level,
                "type": "all",
                "threshold": threshold,
            })
            rows.append({
                "model": model,
                "problems": 0,
                "correct": 0,
                "attempts": 1.0,
                "condition": "openmath",
                "mode": mode,
                "level": level,
                "type": "all",
                "threshold": threshold,
            })

    # Per-type rows (level=all)
    for ptype in PROBLEM_TYPES:
        if ptype in stats.by_type:
            data = stats.by_type[ptype]
            total = data["total"]
            b_attempts = data["baseline_attempts_sum"] / total if total > 0 else 1.0
            o_attempts = data["openmath_attempts_sum"] / total if total > 0 else 1.0

            rows.append({
                "model": model,
                "problems": total,
                "correct": data["baseline_correct"],
                "attempts": round(b_attempts, 2),
                "condition": "baseline",
                "mode": mode,
                "level": "all",
                "type": ptype,
                "threshold": threshold,
            })
            rows.append({
                "model": model,
                "problems": total,
                "correct": data["openmath_correct"],
                "attempts": round(o_attempts, 2),
                "condition": "openmath",
                "mode": mode,
                "level": "all",
                "type": ptype,
                "threshold": threshold,
            })
        else:
            # No problems of this type for this threshold
            rows.append({
                "model": model,
                "problems": 0,
                "correct": 0,
                "attempts": 1.0,
                "condition": "baseline",
                "mode": mode,
                "level": "all",
                "type": ptype,
                "threshold": threshold,
            })
            rows.append({
                "model": model,
                "problems": 0,
                "correct": 0,
                "attempts": 1.0,
                "condition": "openmath",
                "mode": mode,
                "level": "all",
                "type": ptype,
                "threshold": threshold,
            })

    return rows


def load_config(config_path: Path) -> dict:
    """Load YAML configuration file."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(
        description="Extract results using the 'flexible' method",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline/6_extract_results.py \\
      --config configs/results/extract_results.yaml

  python pipeline/6_extract_results.py \\
      --config configs/results/extract_results.yaml \\
      --output results/my_results.csv
        """,
    )

    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to YAML configuration file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override output CSV path (default: from config or auto-generated)",
    )

    args = parser.parse_args()

    # Validate config exists
    if not args.config.exists():
        print(f"Error: Config file not found: {args.config}")
        sys.exit(1)

    # Load config
    print("=" * 70)
    print("EXTRACT RESULTS (FLEXIBLE METHOD)")
    print("=" * 70)
    print(f"Config: {args.config}")

    config = load_config(args.config)

    # Get paths from config
    reranked_path = Path(config.get("reranked", DEFAULT_RERANKED))
    if not reranked_path.is_absolute():
        reranked_path = PROJECT_ROOT / reranked_path

    thresholds = config.get("thresholds", [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
    experiments = config.get("experiments", [])

    print(f"Reranked data: {reranked_path}")
    print(f"Thresholds: {thresholds}")
    print(f"Experiment pairs: {len(experiments)}")
    print("=" * 70)

    # Validate reranked exists
    if not reranked_path.exists():
        print(f"Error: Reranked file not found: {reranked_path}")
        sys.exit(1)

    # Load reranked data
    print("\nLoading reranked data...")
    reranked_data = load_reranked_data(reranked_path)
    max_scores = get_max_score_per_problem(reranked_data)
    print(f"  Loaded {len(reranked_data)} problems")

    # Process each experiment pair
    all_rows = []

    for exp in experiments:
        model = exp.get("model", "unknown")
        mode = exp.get("mode", "unknown")
        baseline_path = Path(exp.get("baseline", ""))
        openmath_path = Path(exp.get("openmath", ""))

        # Make paths absolute if needed
        if not baseline_path.is_absolute():
            baseline_path = PROJECT_ROOT / baseline_path
        if not openmath_path.is_absolute():
            openmath_path = PROJECT_ROOT / openmath_path

        print(f"\nProcessing {model} / {mode}...")
        print(f"  Baseline: {baseline_path.name}")
        print(f"  OpenMath: {openmath_path.name}")

        # Validate files exist
        if not baseline_path.exists():
            print(f"  WARNING: Baseline file not found: {baseline_path}")
            continue
        if not openmath_path.exists():
            print(f"  WARNING: OpenMath file not found: {openmath_path}")
            continue

        # Parse experiment files
        baseline_meta, baseline_results = parse_experiment_results(baseline_path)
        openmath_meta, openmath_results = parse_experiment_results(openmath_path)
        print(f"  Parsed {len(baseline_results)} baseline, {len(openmath_results)} openmath results")

        # Normalize model name
        normalized_model = normalize_model_name(baseline_meta.model)
        if normalized_model != model:
            print(f"  Note: Using normalized model name '{normalized_model}' (from '{baseline_meta.model}')")
            model = normalized_model

        # Compute stats for each threshold
        for threshold in thresholds:
            filtered_problems = filter_problems_by_threshold(max_scores, threshold)
            stats = compute_threshold_stats(
                threshold, filtered_problems, baseline_results, openmath_results
            )
            rows = generate_csv_rows(model, mode, stats)
            all_rows.extend(rows)

        delta_str = f"+{stats.delta:.1f}%" if stats.delta > 0 else f"{stats.delta:.1f}%"
        print(f"  Threshold 0.0: {len(baseline_results)} problems, delta={delta_str}")

    # Determine output path
    if args.output:
        output_path = args.output
    elif config.get("output"):
        output_path = Path(config["output"])
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path
    else:
        timestamp = datetime.now().strftime("%y%m%d_%H%M")
        output_path = DEFAULT_OUTPUT_DIR / f"results_flexible_{timestamp}.csv"

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write CSV
    print(f"\nWriting {len(all_rows)} rows to {output_path}...")
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"  Saved to: {output_path}")

    print("\n" + "=" * 70)
    print("EXTRACTION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
