#!/usr/bin/env python3
"""
This script processes multiple plot configurations from a batch YAML file,
generating separate output files for each plot.

Usage:
    # Run all plots in default batch config
    python pipeline/7a_plot_lines_bubbles_batch.py

    # Custom batch config
    python pipeline/7a_plot_lines_bubbles_batch.py --config configs/plots/my_batch.yaml

    # Override data file for ALL configs in batch
    python pipeline/7a_plot_lines_bubbles_batch.py --data results/results.csv

    # Preview what would be generated
    python pipeline/7a_plot_lines_bubbles_batch.py --dry-run

Date: 2026-02-07
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import yaml

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Project root detection
PROJECT_ROOT = Path.cwd()
if PROJECT_ROOT.name == "scripts":
    PROJECT_ROOT = PROJECT_ROOT.parent.parent
elif PROJECT_ROOT.name == "experiments":
    PROJECT_ROOT = PROJECT_ROOT.parent

# Add project root to path for imports
sys.path.insert(0, str(PROJECT_ROOT / "pipeline"))

# Import from main plotting script
# Note: Uses hyphenated filename, so we use importlib
import importlib.util

spec = importlib.util.spec_from_file_location(
    "plot_lines_bubbles",
    PROJECT_ROOT / "pipeline" / "7a_plot_lines_bubbles.py"
)
plot_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plot_module)

# Extract functions we need
load_config = plot_module.load_config
load_data_from_config = plot_module.load_data_from_config
build_lines_bubbles_plot = plot_module.build_lines_bubbles_plot
save_outputs = plot_module.save_outputs


def load_batch_config(batch_path: Path) -> list[str]:
    """
    Load batch YAML and return list of config paths.

    Args:
        batch_path: Path to batch configuration YAML

    Returns:
        List of config file paths to process
    """
    if not batch_path.exists():
        raise FileNotFoundError(f"Batch config not found: {batch_path}")

    with open(batch_path, "r", encoding="utf-8") as f:
        batch = yaml.safe_load(f)

    configs = batch.get("configs", [])
    if not configs:
        logger.warning("No configs found in batch file")

    return configs


def run_single_plot(
    config_path: Path,
    project_root: Path,
    show: bool = False,
    data_override: Path | None = None,
) -> dict[str, Any]:
    """
    Run a single plot configuration.

    Args:
        config_path: Path to plot YAML config
        project_root: Project root path
        show: Whether to display the plot
        data_override: Optional path to CSV data file (overrides config's data_file)

    Returns:
        Dict with 'status', 'config_path', 'outputs', and optionally 'error'
    """
    result = {
        "status": "success",
        "config_path": str(config_path),
        "outputs": [],
    }

    try:
        # Load config
        config = load_config(config_path)

        # Apply data file override if provided
        if data_override:
            # Store as relative path if within project, otherwise absolute
            try:
                relative_path = data_override.relative_to(project_root)
                config["data_file"] = str(relative_path)
            except ValueError:
                # data_override is outside project_root, use absolute path
                config["data_file"] = str(data_override)

        # Load and filter data
        df = load_data_from_config(config, project_root)

        # Build plot
        fig, series_data = build_lines_bubbles_plot(df, config)

        # Save outputs
        saved_files = save_outputs(fig, config, project_root, show=show, series_data=series_data)
        result["outputs"] = [str(f) for f in saved_files]

        # Close figure to free memory
        plt.close(fig)

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.error(f"Error processing {config_path}: {e}")

    return result


def main():
    """Main CLI entry point."""
    default_batch = PROJECT_ROOT / "experiments" / "configs" / "batch_plots.yaml"

    parser = argparse.ArgumentParser(
        description="Batch runner for line+bubble plots"
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=default_batch,
        help=f"Batch configuration file (default: {default_batch})",
    )
    parser.add_argument(
        "--data", "-d",
        type=Path,
        default=None,
        help="CSV data file (overrides data_file in ALL plot configs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be generated without running",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Display each plot (default: False for batch mode)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Print banner
    print("=" * 70)
    print("BATCH LINE+BUBBLE PLOT GENERATOR")
    print("=" * 70)

    # Resolve batch config path
    batch_path = args.config
    if not batch_path.is_absolute():
        batch_path = PROJECT_ROOT / batch_path

    # Load batch config
    try:
        config_paths = load_batch_config(batch_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"Batch config: {batch_path}")
    print(f"Found {len(config_paths)} plot configs")
    if args.data:
        data_path = args.data if args.data.is_absolute() else PROJECT_ROOT / args.data
        print(f"Data override: {data_path}")
    print("-" * 70)

    results = []
    start_time = time.time()

    for i, config_path_str in enumerate(config_paths, 1):
        # Resolve config path
        config_path = Path(config_path_str)
        if not config_path.is_absolute():
            config_path = PROJECT_ROOT / config_path

        print(f"\n[{i}/{len(config_paths)}] {config_path.name}")

        if args.dry_run:
            # Just show what would be generated
            try:
                config = load_config(config_path)
                # Show effective data file
                if args.data:
                    data_file = args.data
                else:
                    data_file = config.get("data_file", "N/A")
                print(f"  Data: {data_file}")
                output = config.get("output", {})
                if output.get("png"):
                    print(f"  -> PNG: {output.get('png_file', 'N/A')}")
                if output.get("pdf"):
                    print(f"  -> PDF: {output.get('pdf_file', 'N/A')}")
                results.append({
                    "status": "dry-run",
                    "config_path": str(config_path),
                })
            except Exception as e:
                print(f"  ERROR: {e}")
                results.append({
                    "status": "error",
                    "config_path": str(config_path),
                    "error": str(e),
                })
            continue

        # Run the plot
        # Resolve data override path if provided
        data_override = None
        if args.data:
            data_override = args.data if args.data.is_absolute() else PROJECT_ROOT / args.data
        result = run_single_plot(config_path, PROJECT_ROOT, show=args.show, data_override=data_override)
        results.append(result)

        if result["status"] == "success":
            for output in result.get("outputs", []):
                print(f"  -> {Path(output).name}")
        else:
            print(f"  ERROR: {result.get('error', 'Unknown error')}")

    # Summary
    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print("BATCH SUMMARY")
    print("=" * 70)

    total = len(results)
    success = sum(1 for r in results if r["status"] == "success")
    dry_run = sum(1 for r in results if r["status"] == "dry-run")
    errors = sum(1 for r in results if r["status"] == "error")

    print(f"Total configs: {total}")
    if args.dry_run:
        print(f"Previewed: {dry_run}")
    else:
        print(f"Success: {success}")
    print(f"Errors: {errors}")
    print(f"Time: {elapsed:.1f}s")

    if errors > 0:
        print("\nFailed configs:")
        for r in results:
            if r["status"] == "error":
                print(f"  - {r['config_path']}")
                print(f"    Error: {r.get('error', 'Unknown')}")
        return 1

    print("\n" + "=" * 70)
    print("COMPLETE")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
