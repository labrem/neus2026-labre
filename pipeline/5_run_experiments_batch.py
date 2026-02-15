#!/usr/bin/env python3
"""
This script orchestrates batch experiments with threshold-filtered OpenMath symbols.
Each experiment in the YAML config specifies a threshold value, and only problems
with OpenMath symbols above that threshold are included.

Key Features:
- Uses 5_run_experiment.py for each experiment
- Parses threshold from YAML config
- Includes threshold in command building
- Log files include threshold in name

Usage:
    python pipeline/5_run_experiments_batch.py                           # Start or resume
    python pipeline/5_run_experiments_batch.py --dry-run                 # Preview commands
    python pipeline/5_run_experiments_batch.py --config custom.yaml      # Custom config
    python pipeline/5_run_experiments_batch.py --retry-failed            # Retry failures
    python pipeline/5_run_experiments_batch.py --reset                   # Start fresh
"""

import argparse
import json
import subprocess
import sys
import logging
from datetime import datetime
from pathlib import Path

import yaml

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "configs/experiments/experiments_batch.yaml"
DEFAULT_STATE = PROJECT_ROOT / "jobs/experiments_batch.json"

# Import model name mapping from filter
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))
from run_threshold_filter import MODEL_NAME_MAP, normalize_model_name

logger = logging.getLogger(__name__)


def load_config(config_path: Path) -> dict:
    """Load batch configuration from YAML."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_job_state(state_path: Path) -> dict:
    """Load existing job state or initialize new."""
    if state_path.exists():
        with open(state_path) as f:
            return json.load(f)
    return {"batch_id": None, "experiments": {}}


def save_job_state(state: dict, state_path: Path) -> None:
    """Persist job state to disk."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def build_command(name: str, exp_config: dict, defaults: dict) -> list[str]:
    """Build subprocess command from experiment config."""
    # Merge defaults with experiment-specific config
    params = {**defaults, **exp_config}

    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "pipeline/5_run_experiment.py"),
        "--model", params["model"],
        "--condition", params["condition"],
        "--mode", params.get("mode", "greedy"),
        "--threshold", str(params.get("threshold", 0.0)),
        "--n-problems", str(params.get("n_problems", 500)),
        "--max-tokens", str(params.get("max_tokens", 4096)),
        "--top-k-symbols", str(params.get("top_k_symbols", 20)),
        "--seed", str(params.get("seed", 42)),
    ]

    # Add best-of-n specific parameters
    if params.get("mode") == "best-of-n":
        cmd.extend(["--max-attempts", str(params.get("max_attempts", 5))])
        cmd.extend(["--temperature", str(params.get("temperature", 0.6))])

    return cmd


def get_log_filename(name: str, exp_config: dict) -> str:
    """Generate log filename with threshold."""
    model_clean = normalize_model_name(exp_config["model"])
    condition = exp_config["condition"]
    mode = exp_config.get("mode", "greedy")
    threshold = exp_config.get("threshold", 0.0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"logs_{model_clean}_{condition}_{mode}_{threshold}_{timestamp}.log"


def run_experiment(name: str, cmd: list[str], log_dir: Path, exp_config: dict) -> tuple[bool, Path]:
    """
    Execute single experiment via subprocess.

    Returns:
        Tuple of (success: bool, log_path: Path)
    """
    log_filename = get_log_filename(name, exp_config)
    log_path = log_dir / log_filename
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Running: {' '.join(cmd)}")
    logger.info(f"Log: {log_path}")

    with open(log_path, "w") as log_file:
        # Write command as first line of log
        log_file.write(f"Command: {' '.join(cmd)}\n")
        log_file.write(f"Started: {datetime.now().isoformat()}\n")
        log_file.write("=" * 70 + "\n\n")
        log_file.flush()

        result = subprocess.run(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=PROJECT_ROOT,
        )

        # Write completion status
        log_file.write("\n" + "=" * 70 + "\n")
        log_file.write(f"Finished: {datetime.now().isoformat()}\n")
        log_file.write(f"Exit code: {result.returncode}\n")

    return result.returncode == 0, log_path


def run_batch(
    config_path: Path,
    state_path: Path,
    retry_failed: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Main batch execution loop.

    Args:
        config_path: Path to YAML config file
        state_path: Path to job state JSON file
        retry_failed: If True, retry experiments with status "failed"
        dry_run: If True, print what would be run without executing
    """
    config = load_config(config_path)
    state = load_job_state(state_path)
    defaults = config.get("defaults", {})
    experiments = config["experiments"]

    # Initialize batch if new
    if not state.get("batch_id"):
        state["batch_id"] = f"threshold_batch_{datetime.now().strftime('%Y%m%d_%H%M')}"
        state["config_file"] = str(config_path)
        state["started_at"] = datetime.now().isoformat()
        if not dry_run:
            save_job_state(state, state_path)

    log_dir = PROJECT_ROOT / "logs"

    # Group experiments by model for efficient VRAM usage
    experiments_by_model: dict[str, list] = {}
    for exp in experiments:
        model = exp["model"]
        experiments_by_model.setdefault(model, []).append(exp)

    print(f"\n{'=' * 70}")
    print("PHASE 5: THRESHOLD BATCH EXPERIMENT RUNNER")
    print(f"{'=' * 70}")
    print(f"Batch ID: {state['batch_id']}")
    print(f"Config: {config_path}")
    print(f"State: {state_path}")
    print(f"Total experiments: {len(experiments)}")
    print(f"Models: {len(experiments_by_model)}")
    if dry_run:
        print("MODE: DRY RUN (no experiments will be executed)")
    print(f"{'=' * 70}\n")

    # Show threshold distribution
    thresholds = sorted(set(exp.get("threshold", 0.0) for exp in experiments))
    print(f"Thresholds: {thresholds}")
    print()

    # Execute experiments grouped by model
    for model, model_experiments in experiments_by_model.items():
        model_clean = normalize_model_name(model)
        print(f"\n{'=' * 70}")
        print(f"MODEL: {model} ({model_clean})")
        print(f"{'=' * 70}")

        for exp in model_experiments:
            name = exp["name"]
            threshold = exp.get("threshold", 0.0)
            exp_state = state["experiments"].get(name, {"status": "pending"})

            # Skip completed experiments
            if exp_state.get("status") == "completed":
                print(f"  SKIP  {name} (already completed)")
                continue

            # Skip failed unless retry requested
            if exp_state.get("status") == "failed" and not retry_failed:
                print(f"  SKIP  {name} (failed - use --retry-failed to retry)")
                continue

            # Dry run - just print what would be done
            if dry_run:
                cmd = build_command(name, exp, defaults)
                print(f"  WOULD RUN  {name} (threshold={threshold})")
                print(f"    Command: {' '.join(cmd)}")
                continue

            # Mark as running
            print(f"  RUN   {name} (threshold={threshold})...")
            state["experiments"][name] = {
                "status": "running",
                "started_at": datetime.now().isoformat(),
                "threshold": threshold,
            }
            save_job_state(state, state_path)

            # Execute
            cmd = build_command(name, exp, defaults)
            success, log_path = run_experiment(name, cmd, log_dir, exp)

            # Update state
            if success:
                state["experiments"][name]["status"] = "completed"
                state["experiments"][name]["completed_at"] = datetime.now().isoformat()
                state["experiments"][name]["log_file"] = str(log_path)
                print(f"  DONE  {name}")
            else:
                state["experiments"][name]["status"] = "failed"
                state["experiments"][name]["log_file"] = str(log_path)
                print(f"  FAIL  {name} (see {log_path})")

            save_job_state(state, state_path)

    # Mark batch complete if all done
    if not dry_run:
        all_statuses = [e.get("status") for e in state["experiments"].values()]
        if all(s in ("completed", "failed") for s in all_statuses) and all_statuses:
            state["completed_at"] = datetime.now().isoformat()
            save_job_state(state, state_path)

    # Print summary
    print(f"\n{'=' * 70}")
    print("BATCH SUMMARY")
    print(f"{'=' * 70}")

    completed = sum(1 for e in state["experiments"].values() if e.get("status") == "completed")
    failed = sum(1 for e in state["experiments"].values() if e.get("status") == "failed")
    running = sum(1 for e in state["experiments"].values() if e.get("status") == "running")
    pending = len(experiments) - completed - failed - running

    print(f"  Completed: {completed}/{len(experiments)}")
    print(f"  Failed:    {failed}/{len(experiments)}")
    print(f"  Running:   {running}/{len(experiments)}")
    print(f"  Pending:   {pending}/{len(experiments)}")

    if failed > 0:
        print(f"\nFailed experiments:")
        for name, exp_state in state["experiments"].items():
            if exp_state.get("status") == "failed":
                log_file = exp_state.get("log_file", "unknown")
                threshold = exp_state.get("threshold", "?")
                print(f"  - {name} (threshold={threshold}): {log_file}")

    print(f"\nState file: {state_path}")
    print(f"{'=' * 70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Phase 5: Batch threshold experiment runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python pipeline/5_run_experiments_batch.py                    # Start or resume
  python pipeline/5_run_experiments_batch.py --dry-run          # Preview commands
  python pipeline/5_run_experiments_batch.py --retry-failed     # Retry failed
  python pipeline/5_run_experiments_batch.py --reset            # Start fresh
  python pipeline/5_run_experiments_batch.py --config custom.yaml
        """,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Path to batch config YAML (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        help=f"Path to job state JSON (default: {DEFAULT_STATE})",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry experiments with status 'failed'",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset job state and start fresh (deletes state file)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be run without executing",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Handle reset
    if args.reset and args.state.exists():
        args.state.unlink()
        print(f"Reset: Deleted {args.state}")

    # Validate config exists
    if not args.config.exists():
        print(f"Error: Config file not found: {args.config}")
        print(f"\nCreate a config file at: {args.config}")
        print("Example:")
        print("""
version: "1.0"
defaults:
  n_problems: 500
  max_tokens: 4096
  mode: "greedy"

experiments:
  - name: "model_openmath_0.3"
    model: "gemma2:9b"
    condition: "openmath"
    threshold: 0.3
""")
        sys.exit(1)

    # Run batch
    run_batch(
        config_path=args.config,
        state_path=args.state,
        retry_failed=args.retry_failed,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
