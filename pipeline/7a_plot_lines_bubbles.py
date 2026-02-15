# %%
# Cell 1: Environment Setup
"""
This script generates publication-quality line+bubble plots from experiment results CSV data.
The plot shows accuracy delta (line) and attempts ratio (bubbles) by threshold.

Supports both Jupyter notebook and CLI execution modes.

Features:
- YAML-based configuration for plot customization
- Formula parsing for computed values (e.g., accuracy delta between conditions)
- Bubble size mapping to represent secondary metrics
- Publication-quality output at 300 DPI

Usage:
    # CLI: Run with default config
    python pipeline/7a_plot_lines_bubbles.py

    # CLI: Run with custom config
    python pipeline/7a_plot_lines_bubbles.py --config configs/plots/my_plot.yaml

    # CLI: Quick plot with data file
    python pipeline/7a_plot_lines_bubbles.py --data results/results.csv

    # Jupyter: Run cells 1-6 sequentially

Date: 2026-02-07
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
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
if PROJECT_ROOT.name == "experiments":
    PROJECT_ROOT = PROJECT_ROOT.parent


def _is_jupyter_mode() -> bool:
    """Check if running in Jupyter/IPython mode."""
    try:
        shell = get_ipython().__class__.__name__  # type: ignore
        return shell in ["ZMQInteractiveShell", "TerminalInteractiveShell"]
    except NameError:
        pass
    return "ipykernel" in sys.modules


if _is_jupyter_mode():
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python: {sys.executable}")

# %%
# Cell 2: Configuration
# ============================================================================
# MODIFY THESE PARAMETERS TO CONFIGURE THE PLOT (Jupyter mode)
# ============================================================================

# Path to YAML configuration file (relative to project root)
CONFIG_FILE = "configs/plots/plot_lines-bubbles_template.yaml"

# Override data file (optional, overrides config file setting)
DATA_FILE = None  # e.g., "experiments/results/results_260207_1003.csv"

# Override filters (optional, merged with config file filters)
FILTERS = None  # e.g., {"level": "all", "type": "all"}

# ============================================================================

if _is_jupyter_mode():
    print("=" * 70)
    print("PHASE 7a: LINE + BUBBLE PLOT")
    print("=" * 70)
    print(f"Config file: {CONFIG_FILE}")
    if DATA_FILE:
        print(f"Data file override: {DATA_FILE}")
    if FILTERS:
        print(f"Filter overrides: {FILTERS}")
    print("=" * 70)

# %%
# Cell 3: Formula Evaluation
"""Parse and evaluate formulas for line and bubble values."""


class FormulaEvaluator:
    """
    Evaluate formulas against paired baseline/openmath data rows.

    Formulas can reference:
        - baseline_correct, baseline_problems, baseline_attempts
        - openmath_correct, openmath_problems, openmath_attempts
        - Any user-defined metric from the YAML config's 'metrics' section

    Example formulas:
        - "100 * (openmath_correct / openmath_problems - baseline_correct / baseline_problems)"
        - "openmath_attempts / baseline_attempts"

    User-defined metrics in YAML:
        metrics:
          openmath_acc: "openmath_correct / openmath_problems"
          baseline_acc: "baseline_correct / baseline_problems"
          accuracy_delta_pct: "100 * (openmath_acc - baseline_acc)"

    Then use in series:
        line:
          metric: "accuracy_delta_pct"
    """

    # Base variable names (raw column references)
    BASE_VARS = {
        "baseline_correct", "baseline_problems", "baseline_attempts",
        "openmath_correct", "openmath_problems", "openmath_attempts",
    }

    def __init__(self, metrics: dict[str, str] | None = None):
        """
        Initialize the formula evaluator.

        Args:
            metrics: Dict of metric_name -> formula from YAML config's 'metrics' section
        """
        # Pattern to validate formula content (only allow safe characters)
        self.safe_pattern = re.compile(r"^[\w\s\+\-\*/\(\)\.\d_]+$")
        # User-defined metrics from YAML
        self.user_metrics = metrics or {}
        # Cache for resolved formulas (metric name -> fully expanded formula)
        self._resolved_cache: dict[str, str] = {}

    def resolve_metric(self, config: dict) -> str:
        """
        Resolve a metric name or formula from configuration.

        Args:
            config: Dict with either 'metric' or 'formula' key

        Returns:
            The formula string (fully resolved with all metric references expanded)
        """
        if "metric" in config:
            metric_name = config["metric"]
            return self._expand_metric(metric_name)
        return config.get("formula", "0")

    def _expand_metric(self, metric_name: str, visited: set[str] | None = None) -> str:
        """
        Recursively expand a metric name to its final formula.

        Args:
            metric_name: Name of the metric to expand
            visited: Set of already-visited metrics (for cycle detection)

        Returns:
            The fully expanded formula string
        """
        # Check cache first
        if metric_name in self._resolved_cache:
            return self._resolved_cache[metric_name]

        # Initialize visited set for cycle detection
        if visited is None:
            visited = set()

        # Check for circular reference
        if metric_name in visited:
            raise ValueError(f"Circular metric reference detected: {metric_name}")
        visited.add(metric_name)

        # If not a user-defined metric, return as-is (might be a raw variable or formula)
        if metric_name not in self.user_metrics:
            logger.warning(f"Unknown metric '{metric_name}', using as formula")
            return metric_name

        # Get the formula for this metric
        formula = self.user_metrics[metric_name]

        # Find all potential metric references in the formula
        # These are word tokens that aren't base variables or numbers
        tokens = re.findall(r"\b([a-zA-Z_]\w*)\b", formula)

        # Expand each token that is a user-defined metric
        for token in tokens:
            if token in self.user_metrics and token not in self.BASE_VARS:
                # Recursively expand this metric
                expanded = self._expand_metric(token, visited.copy())
                # Replace the token with its expanded form (wrapped in parens for safety)
                formula = re.sub(rf"\b{token}\b", f"({expanded})", formula)

        # Cache and return
        self._resolved_cache[metric_name] = formula
        return formula

    def validate_formula(self, formula: str) -> bool:
        """Validate that formula only contains safe characters and valid variable names."""
        if not self.safe_pattern.match(formula):
            return False

        # Extract variable names (words that are not numbers)
        variables = re.findall(r"\b([a-zA-Z_]\w*)\b", formula)
        for var in variables:
            if var not in self.BASE_VARS:
                logger.warning(f"Unknown variable in formula: {var}")
                return False
        return True

    def evaluate(
        self,
        formula: str,
        baseline_row: pd.Series,
        openmath_row: pd.Series,
    ) -> float:
        """
        Evaluate a formula against paired baseline and openmath rows.

        Args:
            formula: The formula string
            baseline_row: Row where condition == 'baseline'
            openmath_row: Row where condition == 'openmath'

        Returns:
            The computed value as a float
        """
        if not self.validate_formula(formula):
            raise ValueError(f"Invalid formula: {formula}")

        # Build evaluation context from both rows
        context = {
            "baseline_correct": float(baseline_row.get("correct", 0)),
            "baseline_problems": float(baseline_row.get("problems", 1)),
            "baseline_attempts": float(baseline_row.get("attempts", 1)),
            "openmath_correct": float(openmath_row.get("correct", 0)),
            "openmath_problems": float(openmath_row.get("problems", 1)),
            "openmath_attempts": float(openmath_row.get("attempts", 1)),
        }

        # Avoid division by zero
        for key in ["baseline_problems", "openmath_problems", "baseline_attempts", "openmath_attempts"]:
            if context[key] == 0:
                context[key] = 1.0

        # Evaluate the formula safely
        try:
            result = eval(formula, {"__builtins__": {}}, context)
            return float(result)
        except Exception as e:
            logger.error(f"Error evaluating formula '{formula}': {e}")
            raise


if _is_jupyter_mode():
    print("\nFormula evaluator initialized")
    print("  Base variables:", FormulaEvaluator.BASE_VARS)

# %%
# Cell 4: Load Configuration and Data
"""Load YAML configuration and CSV data."""


def load_config(config_path: Path) -> dict[str, Any]:
    """Load YAML configuration file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_data(data_path: Path) -> pd.DataFrame:
    """Load CSV data file."""
    return pd.read_csv(data_path)


def apply_filters(df: pd.DataFrame, filters: dict[str, Any] | None) -> pd.DataFrame:
    """Apply filters to DataFrame."""
    if not filters:
        return df

    filtered = df.copy()
    for col, val in filters.items():
        if col in filtered.columns:
            # Handle both string and numeric comparisons
            filtered = filtered[filtered[col].astype(str) == str(val)]
        else:
            logger.warning(f"Filter column '{col}' not found in data")

    return filtered


def load_data_from_config(
    config: dict[str, Any],
    project_root: Path | None = None,
    filter_overrides: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """
    Load and filter data based on configuration.

    This is a convenience function for batch processing that combines:
    - Loading CSV from config's data_file path
    - Applying global filters from config
    - Optionally merging filter overrides

    Args:
        config: YAML configuration dictionary
        project_root: Project root path (defaults to PROJECT_ROOT)
        filter_overrides: Additional filters to merge with config filters

    Returns:
        Filtered DataFrame ready for plotting
    """
    if project_root is None:
        project_root = PROJECT_ROOT

    # Get data file path from config
    data_file = config.get("data_file", "results/results.csv")
    data_path = project_root / data_file

    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    # Load data
    df_raw = load_data(data_path)
    logger.info(f"Loaded {len(df_raw)} rows from {data_path.name}")

    # Build filters (handle None case from empty YAML section)
    filters_merged = config.get("filters") or {}
    filters_merged = filters_merged.copy()
    if filter_overrides:
        filters_merged.update(filter_overrides)

    # Apply filters
    df = apply_filters(df_raw, filters_merged)
    logger.info(f"After filtering: {len(df)} rows")

    return df


def prepare_series_data(
    df: pd.DataFrame,
    series_config: dict[str, Any],
    evaluator: FormulaEvaluator,
) -> dict[str, Any]:
    """
    Prepare data for a single series (line + bubbles).

    Args:
        df: Full DataFrame
        series_config: Configuration for this series
        evaluator: FormulaEvaluator instance

    Returns:
        Dict with:
            - thresholds: list of threshold values
            - line_values: list of computed line values
            - bubble_values: list of computed bubble values
            - label: series label
            - colors: dict with line and bubble colors
    """
    # Apply series filter
    series_filter = series_config.get("filter", {})
    series_df = df.copy()

    for col, val in series_filter.items():
        if col in series_df.columns and col != "condition":
            series_df = series_df[series_df[col].astype(str) == str(val)]

    if len(series_df) == 0:
        logger.warning(f"No data after applying filter: {series_filter}")
        return None

    # Get unique thresholds
    if "threshold" not in series_df.columns:
        logger.error("'threshold' column not found in data")
        return None

    thresholds = sorted(series_df["threshold"].unique())

    # Get formulas (resolve predefined metrics if used)
    line_config = series_config.get("line", {})
    bubble_config = series_config.get("bubble", {})
    line_formula = evaluator.resolve_metric(line_config)
    bubble_formula = evaluator.resolve_metric(bubble_config)

    # Compute values for each threshold
    line_values = []
    bubble_values = []
    valid_thresholds = []

    for threshold in thresholds:
        threshold_df = series_df[series_df["threshold"] == threshold]

        # Get baseline and openmath rows
        baseline_rows = threshold_df[threshold_df["condition"] == "baseline"]
        openmath_rows = threshold_df[threshold_df["condition"] == "openmath"]

        if len(baseline_rows) == 0 or len(openmath_rows) == 0:
            logger.debug(f"Missing baseline or openmath data for threshold {threshold}")
            continue

        baseline_row = baseline_rows.iloc[0]
        openmath_row = openmath_rows.iloc[0]

        try:
            line_val = evaluator.evaluate(line_formula, baseline_row, openmath_row)
            bubble_val = evaluator.evaluate(bubble_formula, baseline_row, openmath_row)
            line_values.append(line_val)
            bubble_values.append(bubble_val)
            valid_thresholds.append(threshold)
        except Exception as e:
            logger.warning(f"Error computing values for threshold {threshold}: {e}")
            continue

    if len(valid_thresholds) == 0:
        logger.warning(f"No valid data points for series: {series_config.get('label', 'Unknown')}")
        return None

    return {
        "thresholds": valid_thresholds,
        "line_values": line_values,
        "bubble_values": bubble_values,
        "label": series_config.get("label", "Series"),
        "line_color": line_config.get("color", "#1f77b4"),
        "bubble_color": bubble_config.get("color", "#1f77b4"),
    }


# Only run in Jupyter mode - CLI uses main()
if _is_jupyter_mode():
    print("\n" + "=" * 70)
    print("LOADING CONFIGURATION AND DATA")
    print("=" * 70)

    # Load config
    config_path = PROJECT_ROOT / CONFIG_FILE
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    config = load_config(config_path)
    print(f"Loaded config: {config_path.name}")

    # Determine data file
    if DATA_FILE:
        data_path = PROJECT_ROOT / DATA_FILE
    else:
        data_path = PROJECT_ROOT / config.get("data_file", "results/results.csv")

    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    # Load data
    df_raw = load_data(data_path)
    print(f"Loaded data: {data_path.name} ({len(df_raw)} rows)")

    # Apply global filters
    filters_merged = config.get("filters", {})
    if FILTERS:
        filters_merged.update(FILTERS)

    df = apply_filters(df_raw, filters_merged)
    print(f"After filtering: {len(df)} rows")

    if filters_merged:
        print(f"  Filters applied: {filters_merged}")

# %%
# Cell 5: Build Line + Bubble Plot
"""Build the Matplotlib line + bubble figure."""


def build_lines_bubbles_plot(
    df: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[plt.Figure, list[dict[str, Any]]]:
    """
    Build a Matplotlib line + bubble figure.

    Args:
        df: Filtered DataFrame with experiment results
        config: YAML configuration dictionary

    Returns:
        Tuple of (Matplotlib Figure object, list of series data dicts for CSV export)
    """
    # Get user-defined metrics from config
    user_metrics = config.get("metrics", {})
    evaluator = FormulaEvaluator(metrics=user_metrics)

    # Get configuration
    layout_cfg = config.get("layout", {})
    defaults = config.get("defaults", {})
    series_configs = config.get("series", [])

    # Figure dimensions
    fig_width = layout_cfg.get("width", 1000) / 100  # Convert px to inches
    fig_height = layout_cfg.get("height", 600) / 100

    # Apply publication style
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['font.sans-serif'] = ['Arial', 'Helvetica', 'DejaVu Sans']
    plt.rcParams['font.size'] = 10
    plt.rcParams['axes.labelsize'] = 11
    plt.rcParams['axes.titlesize'] = 12
    plt.rcParams['xtick.labelsize'] = 9
    plt.rcParams['ytick.labelsize'] = 9

    # Create figure and axis
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    # Prepare data for all series
    all_series_data = []
    all_bubble_values = []

    for series_cfg in series_configs:
        series_data = prepare_series_data(df, series_cfg, evaluator)
        if series_data is not None:
            all_series_data.append(series_data)
            all_bubble_values.extend(series_data["bubble_values"])

    if len(all_series_data) == 0:
        logger.error("No valid series data to plot")
        ax.text(0.5, 0.5, "No data to display", ha='center', va='center',
                transform=ax.transAxes, fontsize=14)
        return fig, []

    # Compute bubble size normalization
    bubble_defaults = defaults.get("bubble", {})
    min_bubble_size = bubble_defaults.get("min_size", 50)
    reference_bubble_size = bubble_defaults.get("reference_size", 225)
    max_bubble_size = bubble_defaults.get("max_size", 500)
    bubble_opacity = bubble_defaults.get("opacity", 0.6)
    bubble_edge_width = bubble_defaults.get("edge_width", 1.5)

    # Get legend config
    legend_cfg = config.get("legend", {})
    bubble_legend_cfg = legend_cfg.get("bubble", {})
    bubble_levels = bubble_legend_cfg.get("levels", None)
    reference_value = bubble_legend_cfg.get("reference_value", 1.0)

    # Data-driven bubble normalization with fixed reference anchor
    # Reference value always maps to reference_size (225 by default)
    # Values below/above reference are interpolated to min/max sizes
    # Include legend levels in range so legend bubbles get meaningful sizes
    data_min = min(all_bubble_values)
    data_max = max(all_bubble_values)
    if bubble_levels:
        data_min = min(data_min, min(bubble_levels))
        data_max = max(data_max, max(bubble_levels))

    logger.info(f"Bubble normalization: range [{data_min:.4f}, {data_max:.4f}], "
                f"reference {reference_value} → size {reference_bubble_size}, "
                f"size range [{min_bubble_size}, {max_bubble_size}]")

    def normalize_bubble_size(val: float) -> float:
        """Normalize bubble value to size using piecewise linear interpolation.

        Reference value is anchored at reference_size.
        Values below reference interpolate between min_size and reference_size.
        Values above reference interpolate between reference_size and max_size.
        """
        # Exactly at reference
        if abs(val - reference_value) < 1e-9:
            return reference_bubble_size

        # Below reference: interpolate [data_min, reference_value] → [min_size, reference_size]
        if val < reference_value:
            if data_min >= reference_value:
                # All data is at or above reference
                return reference_bubble_size
            # Clamp to data range
            clamped = max(data_min, val)
            normalized = (clamped - data_min) / (reference_value - data_min)
            return min_bubble_size + normalized * (reference_bubble_size - min_bubble_size)

        # Above reference: interpolate [reference_value, data_max] → [reference_size, max_size]
        else:
            if data_max <= reference_value:
                # All data is at or below reference
                return reference_bubble_size
            # Clamp to data range
            clamped = min(data_max, val)
            normalized = (clamped - reference_value) / (data_max - reference_value)
            return reference_bubble_size + normalized * (max_bubble_size - reference_bubble_size)

    # Line defaults
    line_defaults = defaults.get("line", {})
    default_line_width = line_defaults.get("width", 2.5)
    default_line_opacity = line_defaults.get("opacity", 0.9)

    # Compute marker size to match reference value (1.0 by default)
    # Reference value always maps to reference_bubble_size (225 by default)
    # This makes the white line markers represent the "no change" baseline
    # Convert scatter size (area) to marker size (diameter in points)
    # matplotlib marker size is diameter, scatter s is area
    reference_marker_size = np.sqrt(reference_bubble_size)

    # Plot each series
    legend_handles = []
    legend_labels = []

    for series_data in all_series_data:
        thresholds = series_data["thresholds"]
        line_values = series_data["line_values"]
        bubble_values = series_data["bubble_values"]
        label = series_data["label"]
        line_color = series_data["line_color"]
        bubble_color = series_data["bubble_color"]

        # Plot line with markers sized to reference value (1.0)
        # Markers are transparent (none) so data bubbles show through
        line, = ax.plot(
            thresholds, line_values,
            color=line_color,
            linewidth=default_line_width,
            alpha=default_line_opacity,
            marker='o',
            markersize=reference_marker_size,
            markerfacecolor='none',  # Transparent so bubbles show through
            markeredgecolor=line_color,
            markeredgewidth=2,
            zorder=4,  # Above bubbles
            label=label,
        )

        # Plot bubbles (no edge for soft appearance)
        bubble_sizes = [normalize_bubble_size(v) for v in bubble_values]
        ax.scatter(
            thresholds, line_values,
            s=bubble_sizes,
            c=bubble_color,
            alpha=bubble_opacity,
            edgecolors='none',  # No edge for soft appearance
            zorder=3,
        )

        # Create line-only legend handle (no marker) for model legend
        from matplotlib.lines import Line2D
        line_only_handle = Line2D([0], [0], color=line_color,
                                   linewidth=default_line_width,
                                   alpha=default_line_opacity,
                                   linestyle='-',
                                   marker='')  # Explicitly no marker
        legend_handles.append(line_only_handle)
        legend_labels.append(label)

    # Configure axes
    x_axis_cfg = config.get("x_axis", {})
    y_axis_cfg = config.get("y_axis", {})

    ax.set_xlabel(x_axis_cfg.get("label", "Threshold"), fontweight='bold')
    ax.set_ylabel(y_axis_cfg.get("label", "Value"), fontweight='bold')

    # Set axis ranges if specified
    if "range" in x_axis_cfg:
        ax.set_xlim(x_axis_cfg["range"])
    if "range" in y_axis_cfg:
        ax.set_ylim(y_axis_cfg["range"])

    # Add grid
    if layout_cfg.get("grid", True):
        ax.grid(True, alpha=layout_cfg.get("grid_alpha", 0.3), linestyle='-', linewidth=0.5)

    # Add horizontal line at y=0 if configured
    if layout_cfg.get("hline_at_zero", False):
        ax.axhline(y=0, color='gray', linestyle='--', linewidth=1, alpha=0.7, zorder=1)

    # Remove top and right spines for cleaner look
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    # Add title
    title = config.get("title", "Line + Bubble Plot")
    ax.set_title(title, fontsize=12, fontweight='bold', pad=15)

    # Add legend - supports both old and new YAML structure
    # Note: legend_cfg, bubble_legend_cfg, bubble_levels defined earlier for normalization

    # Support new structure: legend.line.show / legend.bubble.show
    # Also support old structure: legend.show / legend.show_bubble_legend
    line_legend_cfg = legend_cfg.get("line", {})

    # Determine if line legend should be shown
    show_line_legend = line_legend_cfg.get("show", legend_cfg.get("show", True))
    line_legend_pos = line_legend_cfg.get("position", legend_cfg.get("position", "upper right"))
    line_legend_title = line_legend_cfg.get("title", None)

    # Determine if bubble legend should be shown
    show_bubble_legend = bubble_legend_cfg.get("show", legend_cfg.get("show_bubble_legend", True))
    bubble_legend_pos = bubble_legend_cfg.get("position", "lower right")
    bubble_legend_title = bubble_legend_cfg.get("title", legend_cfg.get("bubble_legend_title", "Bubble Size"))

    main_legend = None
    if show_line_legend:
        # Create main legend for series
        main_legend = ax.legend(
            legend_handles, legend_labels,
            loc=line_legend_pos,
            title=line_legend_title,
            frameon=True,
            fancybox=True,
            framealpha=0.9,
            fontsize=9,
        )

    # Add bubble size legend if configured
    if show_bubble_legend and len(all_bubble_values) > 0:
        # Add main legend as artist so it doesn't get replaced
        if main_legend is not None:
            ax.add_artist(main_legend)

        # Determine bubble legend values
        if bubble_levels is not None:
            # Use custom levels from config
            bubble_legend_vals = sorted(bubble_levels)
        else:
            # Auto-generate levels including reference_value (1.0 by default)
            bubble_legend_vals = sorted(set([bubble_min, reference_value, bubble_max]))
            # Filter out values outside data range if reference_value was added
            bubble_legend_vals = [v for v in bubble_legend_vals
                                  if bubble_min <= v <= bubble_max or v == reference_value]

        # Use the SAME normalization as data bubbles so legend sizes match
        # This ensures a legend bubble of 1.0 matches a data bubble with value 1.0
        bubble_legend_sizes = [normalize_bubble_size(v) for v in bubble_legend_vals]
        logger.info(f"Legend bubble sizes: {list(zip(bubble_legend_vals, bubble_legend_sizes))}")

        # Create legend handles for bubble sizes
        from matplotlib.lines import Line2D
        bubble_handles = []
        bubble_labels_text = []
        for val, size in zip(bubble_legend_vals, bubble_legend_sizes):
            # Convert scatter size (area) to marker size (diameter in points)
            # Use same formula as line markers for consistency
            marker_diameter = np.sqrt(size)

            # Reference value (1.0) matches line marker style: transparent fill, colored edge
            is_reference = abs(val - reference_value) < 0.001
            if is_reference:
                # Transparent circle with black edge (matches line markers)
                handle = Line2D([0], [0], marker='o', color='w',
                               markerfacecolor='none', markeredgecolor='black',
                               markeredgewidth=2,
                               markersize=marker_diameter,
                               alpha=1.0, linestyle='None')
            else:
                # Soft colored bubble (no edge, like data bubbles)
                handle = Line2D([0], [0], marker='o', color='w',
                               markerfacecolor='gray', markeredgecolor='none',
                               markersize=marker_diameter,
                               alpha=0.6, linestyle='None')
            bubble_handles.append(handle)
            bubble_labels_text.append(f"{val:.2f}")

        # Get legend sizing from YAML config (with defaults)
        legend_fontsize = bubble_legend_cfg.get("fontsize", 8)
        handle_height = bubble_legend_cfg.get("handle_height", None)
        label_spacing = bubble_legend_cfg.get("label_spacing", None)
        border_pad = bubble_legend_cfg.get("border_pad", 1.0)

        # Auto-calculate sizing if not specified in YAML
        if handle_height is None or label_spacing is None:
            max_marker_diameter = max(np.sqrt(s) for s in bubble_legend_sizes)
            if handle_height is None:
                handle_height = max(1.5, max_marker_diameter / legend_fontsize * 1.2)
            if label_spacing is None:
                label_spacing = max(0.8, max_marker_diameter / legend_fontsize * 0.6)

        # Add bubble size legend with configurable sizing
        ax.legend(
            bubble_handles, bubble_labels_text,
            title=bubble_legend_title,
            loc=bubble_legend_pos,
            frameon=True,
            fancybox=True,
            framealpha=0.9,
            fontsize=legend_fontsize,
            title_fontsize=9,
            handleheight=handle_height,
            labelspacing=label_spacing,
            borderpad=border_pad,
        )

    # Adjust layout
    plt.tight_layout()

    return fig, all_series_data


# Only run in Jupyter mode - CLI uses main()
if _is_jupyter_mode():
    print("\n" + "=" * 70)
    print("BUILDING PLOT")
    print("=" * 70)

    fig, series_data = build_lines_bubbles_plot(df, config)
    n_series = len(config.get("series", []))
    print(f"Plot built with {n_series} series")

# %%
# Cell 6: Display and Save Plot
"""Display the plot and save to files."""


def save_outputs(
    fig: plt.Figure,
    config: dict[str, Any],
    project_root: Path,
    show: bool = True,
    series_data: list[dict[str, Any]] | None = None,
) -> list[Path]:
    """
    Save the figure to configured output files.

    Args:
        fig: Matplotlib Figure object
        config: YAML configuration dictionary
        project_root: Project root path
        show: Whether to display the plot
        series_data: List of series data dicts for CSV export (from build_lines_bubbles_plot)

    Returns:
        List of saved file paths
    """
    output_cfg = config.get("output", {})
    saved_files = []

    # Save PNG
    if output_cfg.get("png", True):
        png_file = project_root / output_cfg.get("png_file", "plots/lines_bubbles.png")
        png_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            fig.savefig(str(png_file), dpi=300, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            saved_files.append(png_file)
            print(f"Saved PNG: {png_file} ({png_file.stat().st_size / 1024:.1f} KB)")
        except Exception as e:
            logger.warning(f"Could not save PNG: {e}")

    # Save PDF (vector format, good for publications)
    if output_cfg.get("pdf", True):
        pdf_file = project_root / output_cfg.get("pdf_file", "plots/lines_bubbles.pdf")
        pdf_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            fig.savefig(str(pdf_file), format='pdf', bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            saved_files.append(pdf_file)
            print(f"Saved PDF: {pdf_file} ({pdf_file.stat().st_size / 1024:.1f} KB)")
        except Exception as e:
            logger.warning(f"Could not save PDF: {e}")

    # Save CSV (default: true)
    if output_cfg.get("save_csv", True) and series_data:
        # Determine CSV path from PNG path (same location, different extension)
        png_path = output_cfg.get("png_file", "plots/lines_bubbles.png")
        csv_file = project_root / png_path.replace(".png", ".csv")
        csv_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Build DataFrame from series data
            csv_rows = []
            for series in series_data:
                model = series["label"]
                for threshold, line_val, bubble_val in zip(
                    series["thresholds"],
                    series["line_values"],
                    series["bubble_values"]
                ):
                    csv_rows.append({
                        "model": model,
                        "threshold": threshold,
                        "line_value": line_val,
                        "bubble_value": bubble_val,
                    })
            csv_df = pd.DataFrame(csv_rows)
            csv_df.to_csv(csv_file, index=False)
            saved_files.append(csv_file)
            print(f"Saved CSV: {csv_file} ({csv_file.stat().st_size / 1024:.1f} KB)")
        except Exception as e:
            logger.warning(f"Could not save CSV: {e}")

    # Show plot
    if show:
        plt.show()

    return saved_files


# Only run in Jupyter mode - CLI uses main()
if _is_jupyter_mode():
    print("\n" + "=" * 70)
    print("SAVING AND DISPLAYING PLOT")
    print("=" * 70)

    output_cfg = config.get("output", {})
    saved = save_outputs(fig, config, PROJECT_ROOT, show=output_cfg.get("show", True),
                         series_data=series_data)

    print("\n" + "=" * 70)
    print("PLOT COMPLETE")
    print("=" * 70)

# %%
# Cell 7: CLI Entry Point
"""Command-line interface."""


def main():
    """Main CLI entry point."""
    default_config = PROJECT_ROOT / "experiments" / "configs" / "lines_bubbles_template.yaml"

    parser = argparse.ArgumentParser(
        description="Phase 7a: Generate Line + Bubble plots from experiment results"
    )
    parser.add_argument(
        "--config", "-c",
        type=Path,
        default=default_config,
        help=f"YAML configuration file (default: {default_config})",
    )
    parser.add_argument(
        "--data", "-d",
        type=Path,
        default=None,
        help="CSV data file (overrides config file setting)",
    )
    parser.add_argument(
        "--filter",
        action="append",
        nargs=2,
        metavar=("COL", "VAL"),
        help="Filter data (can be repeated). Example: --filter level all --filter mode greedy",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Don't display the plot (only save to files)",
    )
    parser.add_argument(
        "--png",
        type=Path,
        default=None,
        help="Output PNG file path (overrides config)",
    )
    parser.add_argument(
        "--pdf",
        type=Path,
        default=None,
        help="Output PDF file path (overrides config)",
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
    print("PHASE 7a: LINE + BUBBLE PLOT")
    print("=" * 70)

    # Load configuration
    config_path = args.config
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        return 1

    config = load_config(config_path)
    print(f"Config file: {config_path}")

    # Determine data file
    if args.data:
        data_path = args.data if args.data.is_absolute() else PROJECT_ROOT / args.data
    else:
        data_path = PROJECT_ROOT / config.get("data_file", "results/results.csv")

    if not data_path.exists():
        print(f"ERROR: Data file not found: {data_path}")
        return 1

    print(f"Data file: {data_path}")

    # Load data
    df_raw = load_data(data_path)
    print(f"Loaded {len(df_raw)} rows")

    # Build filters
    filters_merged = config.get("filters", {})
    if args.filter:
        for col, val in args.filter:
            filters_merged[col] = val

    df = apply_filters(df_raw, filters_merged)
    print(f"After filtering: {len(df)} rows")

    if filters_merged:
        print(f"Filters: {filters_merged}")

    # Override output paths if specified
    if args.png:
        config.setdefault("output", {})["png"] = True
        config["output"]["png_file"] = str(args.png)
    if args.pdf:
        config.setdefault("output", {})["pdf"] = True
        config["output"]["pdf_file"] = str(args.pdf)

    print("-" * 70)

    # Build plot
    fig, series_data = build_lines_bubbles_plot(df, config)
    n_series = len(config.get("series", []))
    print(f"Built plot with {n_series} series")

    # Save and optionally show
    show = not args.no_show and config.get("output", {}).get("show", True)
    save_outputs(fig, config, PROJECT_ROOT, show=show, series_data=series_data)

    # Close figure to free memory
    plt.close(fig)

    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)

    return 0


if __name__ == "__main__" and not _is_jupyter_mode():
    exit(main())
