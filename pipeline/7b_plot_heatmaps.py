# %%
# Cell 1: Environment Setup
"""
This script generates publication-quality heatmap plots from experiment results CSV data.
The plots show accuracy delta and attempts ratio broken down by problem level and type,
across all models and threshold levels.

Supports both Jupyter notebook and CLI execution modes.

Features:
- YAML-based configuration for plot customization
- Formula parsing for computed values (e.g., accuracy delta between conditions)
- 2x2 grid layout: Level×Accuracy, Level×Attempts, Type×Accuracy, Type×Attempts
- Diverging colormaps (RdYlGn) with appropriate centering
- Publication-quality output at 300 DPI

Usage:
    # CLI: Run with default config
    python pipeline/7b_plot_heatmaps.py

    # CLI: Run with custom config
    python pipeline/7b_plot_heatmaps.py --config configs/plots/plot_heatmap_template.yaml

    # CLI: Quick plot with data file
    python pipeline/7b_plot_heatmaps.py --data results/results.csv

    # Jupyter: Run cells 1-6 sequentially

Date: 2026-02-09
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
import seaborn as sns
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
CONFIG_FILE = "configs/plots/plot_heatmap_template.yaml"

# Override data file (optional, overrides config file setting)
DATA_FILE = None  # e.g., "experiments/results/results_260208_1400.csv"

# Override filters (optional, merged with config file filters)
FILTERS = None  # e.g., {"mode": "greedy"}

# ============================================================================

if _is_jupyter_mode():
    print("=" * 70)
    print("PHASE 7b: HEATMAP PLOT")
    print("=" * 70)
    print(f"Config file: {CONFIG_FILE}")
    if DATA_FILE:
        print(f"Data file override: {DATA_FILE}")
    if FILTERS:
        print(f"Filter overrides: {FILTERS}")
    print("=" * 70)

# %%
# Cell 3: Formula Evaluation and Data Loading
"""Parse and evaluate formulas, load data."""


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


if _is_jupyter_mode():
    print("\nFormula evaluator initialized")
    print("  Base variables:", FormulaEvaluator.BASE_VARS)

# %%
# Cell 4: Heatmap Data Preparation and Rendering
"""Prepare data matrices and render heatmaps."""


def prepare_heatmap_data(
    df: pd.DataFrame,
    breakdown: str,
    metric_name: str,
    evaluator: FormulaEvaluator,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, list[str]]:
    """
    Transform data into heatmap matrix format.

    Args:
        df: Full DataFrame with both conditions
        breakdown: "level" or "type"
        metric_name: Name of metric in evaluator
        evaluator: FormulaEvaluator instance
        config: Full configuration dict

    Returns:
        Tuple of (DataFrame with rows=breakdown values, columns as MultiIndex (threshold, model),
                  list of display labels for rows)
    """
    # Get formula for this metric
    formula = evaluator._expand_metric(metric_name)

    # Get column configuration
    columns_cfg = config.get("columns", {})
    model_order = columns_cfg.get("model_order", sorted(df["model"].unique()))
    threshold_range = columns_cfg.get("threshold_range", "auto")

    # Get unique models and thresholds
    models = [m for m in model_order if m in df["model"].unique()]
    if threshold_range == "auto":
        thresholds = sorted(df["threshold"].unique())
    else:
        thresholds = threshold_range

    # Define row values and labels based on breakdown type
    if breakdown == "level":
        # Get level order from config, default to descending (5, 4, 3, 2, 1)
        level_order = config.get("level_order", [5, 4, 3, 2, 1])
        level_labels = config.get("level_labels", {})
        # Get available levels from data (including "all" if present)
        available_levels_raw = set(df["level"].unique())
        # Convert to comparable format: keep "all" as string, convert others to int
        available_levels = set()
        for x in available_levels_raw:
            if str(x) == "all":
                available_levels.add("all")
            elif str(x).isdigit():
                available_levels.add(int(x))
        # Filter level_order to only levels that exist in data
        row_values = [l for l in level_order if l in available_levels or str(l) in [str(a) for a in available_levels]]
        # Build display labels
        row_display_labels = [str(level_labels.get(l, l)) for l in row_values]
    else:  # type
        # Get type order from config
        type_order = config.get("type_order", None)
        type_labels = config.get("type_labels", {})
        if type_order:
            # Use type_order, filtering to only types that exist in data (includes "all" if configured)
            row_values = [t for t in type_order if t in df["type"].unique()]
        else:
            row_values = sorted([
                x for x in df["type"].unique()
            ])
        # Build display labels
        row_display_labels = [type_labels.get(t, t) for t in row_values]

    # Build matrix - organize by threshold first, then model (for x-axis grouping)
    data = {}
    for threshold in thresholds:
        for model in models:
            col_key = (threshold, model)
            col_data = {}

            for row_val in row_values:
                # Get baseline and openmath rows
                mask_base = (
                    (df["model"] == model) &
                    (df["threshold"] == threshold) &
                    (df[breakdown].astype(str) == str(row_val)) &
                    (df["condition"] == "baseline")
                )
                mask_om = (
                    (df["model"] == model) &
                    (df["threshold"] == threshold) &
                    (df[breakdown].astype(str) == str(row_val)) &
                    (df["condition"] == "openmath")
                )

                baseline_rows = df[mask_base]
                openmath_rows = df[mask_om]

                if len(baseline_rows) == 0 or len(openmath_rows) == 0:
                    logger.debug(
                        f"Missing data for {model}/{threshold}/{row_val}"
                    )
                    col_data[row_val] = np.nan
                    continue

                try:
                    value = evaluator.evaluate(
                        formula,
                        baseline_rows.iloc[0],
                        openmath_rows.iloc[0],
                    )
                    col_data[row_val] = value
                except Exception as e:
                    logger.warning(f"Error computing {model}/{threshold}/{row_val}: {e}")
                    col_data[row_val] = np.nan

            data[col_key] = col_data

    # Create DataFrame with MultiIndex columns (threshold, model)
    result = pd.DataFrame(data)
    result.columns = pd.MultiIndex.from_tuples(
        result.columns,
        names=["threshold", "model"]
    )

    # Replace row index with display labels
    result.index = row_display_labels

    return result, row_display_labels


def render_heatmap(
    ax: plt.Axes,
    data: pd.DataFrame,
    heatmap_cfg: dict[str, Any],
    global_cfg: dict[str, Any],
) -> None:
    """
    Render a single heatmap on the given axes.

    Layout follows example: Models on TOP (rotated), Thresholds at BOTTOM,
    with clear vertical separator lines between threshold groups.

    Args:
        ax: Matplotlib axes to render on
        data: DataFrame with heatmap data (MultiIndex columns: threshold, model)
        heatmap_cfg: Configuration for this specific heatmap
        global_cfg: Global configuration dict
    """
    # Get heatmap-specific settings
    title = heatmap_cfg.get("title", "Heatmap")
    colormap = heatmap_cfg.get("colormap", "RdYlGn")
    center = heatmap_cfg.get("center", 0.0)
    value_format = heatmap_cfg.get("value_format", ".1f")

    # Get layout settings
    layout_cfg = global_cfg.get("layout", {})
    show_colorbar = layout_cfg.get("colorbar", True)
    colorbar_pad = layout_cfg.get("colorbar_pad", 0.02)
    colorbar_shrink = layout_cfg.get("colorbar_shrink", 0.7)
    colorbar_aspect = layout_cfg.get("colorbar_aspect", 30)

    # Get font settings
    fonts_cfg = layout_cfg.get("fonts", {})
    annot_fontsize = fonts_cfg.get("annotation", layout_cfg.get("annotation_fontsize", 8))
    title_fontsize = fonts_cfg.get("title", 11)
    model_label_fontsize = fonts_cfg.get("model_labels", 7)
    threshold_label_fontsize = fonts_cfg.get("threshold_labels", 8)
    threshold_title_fontsize = fonts_cfg.get("threshold_title", 9)
    y_label_fontsize = fonts_cfg.get("y_labels", 8)
    y_title_fontsize = fonts_cfg.get("y_title", 9)

    # Get model label rotation settings
    model_label_rotation = layout_cfg.get("model_label_rotation", 45)
    model_label_ha = layout_cfg.get("model_label_ha", "left")

    # Get separator line settings
    separator_color = layout_cfg.get("separator_color", "white")
    separator_width = layout_cfg.get("separator_width", 2.5)

    # Get unique thresholds and models from MultiIndex
    thresholds = data.columns.get_level_values("threshold").unique()
    models = data.columns.get_level_values("model").unique()
    n_models = len(models)
    n_thresholds = len(thresholds)

    # Get model display labels from config
    columns_cfg = global_cfg.get("columns", {})
    model_labels = columns_cfg.get("model_labels", {})

    # Flatten MultiIndex for seaborn (use display labels if available)
    flat_data = data.copy()
    flat_data.columns = [model_labels.get(col[1], col[1]) for col in data.columns]

    # Render heatmap
    hm = sns.heatmap(
        flat_data,
        ax=ax,
        annot=True,
        fmt=value_format,
        cmap=colormap,
        center=center,
        cbar=show_colorbar,
        linewidths=0.5,
        linecolor="white",
        annot_kws={"fontsize": annot_fontsize},
        cbar_kws={"shrink": colorbar_shrink, "aspect": colorbar_aspect, "pad": colorbar_pad} if show_colorbar else {},
    )

    # Set title
    ax.set_title(title, fontsize=title_fontsize, fontweight="bold", pad=35)

    # Configure model labels on TOP (x-axis at top)
    ax.xaxis.set_ticks_position("top")
    ax.xaxis.set_label_position("top")
    ax.set_xticklabels(
        ax.get_xticklabels(),
        rotation=model_label_rotation,
        ha=model_label_ha,
        fontsize=model_label_fontsize,
    )

    # Set y-axis labels (row labels)
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=y_label_fontsize)

    # Set axis labels (use custom titles from config, or auto-generate from breakdown)
    breakdown = heatmap_cfg.get("breakdown", "")
    y_title = heatmap_cfg.get("y_title", None)
    x_title = heatmap_cfg.get("x_title", None)

    # Y-axis title: use custom if provided, otherwise capitalize breakdown, blank string = no title
    if y_title is None:
        y_title = breakdown.capitalize() if breakdown else ""
    if y_title:  # Only set if non-empty
        ax.set_ylabel(y_title, fontsize=y_title_fontsize)
    else:
        ax.set_ylabel("", fontsize=y_title_fontsize)

    # X-axis title: use custom if provided, blank string = no title
    if x_title is None:
        x_title = ""
    if x_title:  # Only set if non-empty
        ax.set_xlabel(x_title, fontsize=model_label_fontsize)
    else:
        ax.set_xlabel("", fontsize=model_label_fontsize)

    # Add threshold labels at BOTTOM
    # Calculate center position for each threshold group
    threshold_centers = []
    threshold_labels = []
    for i, thresh in enumerate(thresholds):
        center_pos = i * n_models + n_models / 2
        threshold_centers.append(center_pos)
        threshold_labels.append(str(thresh))

    # Add secondary x-axis at bottom for thresholds
    ax2 = ax.secondary_xaxis("bottom")
    ax2.set_xticks(threshold_centers)
    ax2.set_xticklabels(threshold_labels, fontsize=threshold_label_fontsize)
    ax2.tick_params(axis="x", length=0)  # Hide tick marks
    ax2.spines["bottom"].set_visible(False)

    # Add "Threshold" label
    ax2.set_xlabel("Threshold", fontsize=threshold_title_fontsize, labelpad=5)

    # Draw vertical separator lines between threshold groups
    for i in range(1, n_thresholds):
        x_pos = i * n_models
        ax.axvline(x=x_pos, color=separator_color, linewidth=separator_width, linestyle="-")


def build_single_heatmap(
    df: pd.DataFrame,
    heatmap_cfg: dict[str, Any],
    config: dict[str, Any],
    evaluator: FormulaEvaluator,
) -> plt.Figure:
    """
    Build a single heatmap figure.

    Args:
        df: Filtered DataFrame with experiment results
        heatmap_cfg: Configuration for this specific heatmap
        config: Full YAML configuration dictionary
        evaluator: FormulaEvaluator instance

    Returns:
        Matplotlib Figure object with single heatmap
    """
    # Apply publication style
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "Helvetica", "DejaVu Sans"]
    plt.rcParams["font.size"] = 10

    # Get layout configuration
    layout_cfg = config.get("layout", {})
    cell_height = layout_cfg.get("cell_height", None)
    cell_width = layout_cfg.get("cell_width", None)

    # Determine figure size based on breakdown type or cell dimensions
    breakdown = heatmap_cfg.get("breakdown", "level")

    # Calculate number of rows and columns for this heatmap
    if breakdown == "level":
        n_rows = len(config.get("level_order", [5, 4, 3, 2, 1]))
    else:
        n_rows = len(config.get("type_order", []))
        if n_rows == 0:
            n_rows = 7  # default number of types

    # Get column dimensions
    columns_cfg = config.get("columns", {})
    model_order = columns_cfg.get("model_order", [])
    n_models = len(model_order) if model_order else 3
    threshold_range = columns_cfg.get("threshold_range", "auto")
    n_thresholds = 10 if threshold_range == "auto" else len(threshold_range)
    n_cols = n_models * n_thresholds

    # Calculate figsize based on cell dimensions if specified
    if cell_height is not None or cell_width is not None:
        # Default cell dimensions
        cw = cell_width if cell_width is not None else 0.4
        ch = cell_height if cell_height is not None else 0.5
        # Add margins for labels, title, colorbar
        fig_width = n_cols * cw + 3.0  # extra for y-axis labels and colorbar
        fig_height = n_rows * ch + 2.0  # extra for title and x-axis labels
        figsize = (fig_width, fig_height)
    else:
        # Default figsize based on breakdown type
        if breakdown == "level":
            figsize = (8, 5)
        else:
            figsize = (8, 6)

    # Create figure
    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)

    metric = heatmap_cfg.get("metric", "accuracy_delta")

    try:
        # Prepare data matrix
        data, _ = prepare_heatmap_data(df, breakdown, metric, evaluator, config)

        if data.empty:
            ax.text(0.5, 0.5, "No data", ha="center", va="center")
            ax.set_title(heatmap_cfg.get("title", "No Data"))
        else:
            # Render heatmap
            render_heatmap(ax, data, heatmap_cfg, config)

    except Exception as e:
        logger.error(f"Error building heatmap: {e}")
        ax.text(0.5, 0.5, f"Error: {e}", ha="center", va="center")
        ax.set_title(heatmap_cfg.get("title", "Error"))

    return fig


def build_heatmap_figure(
    df: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[plt.Figure, list[tuple[str, plt.Figure]]]:
    """
    Build a Matplotlib figure with multiple heatmaps.

    Args:
        df: Filtered DataFrame with experiment results
        config: YAML configuration dictionary

    Returns:
        Tuple of (combined Figure, list of (heatmap_id, individual Figure))
    """
    # Get user-defined metrics from config
    user_metrics = config.get("metrics", {})
    evaluator = FormulaEvaluator(metrics=user_metrics)

    # Get heatmap configurations
    heatmaps_cfg = config.get("heatmaps", [])
    n_heatmaps = len(heatmaps_cfg)

    if n_heatmaps == 0:
        logger.error("No heatmaps configured")
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, "No heatmaps configured", ha="center", va="center")
        return fig, []

    # Get layout configuration
    layout_cfg = config.get("layout", {})
    figsize = layout_cfg.get("figsize", [16, 10])
    grid = layout_cfg.get("subplot_grid", None)
    cell_height = layout_cfg.get("cell_height", None)
    cell_width = layout_cfg.get("cell_width", None)

    # Auto-determine grid if not specified
    if grid is None:
        if n_heatmaps <= 2:
            grid = [1, n_heatmaps]
        elif n_heatmaps <= 4:
            grid = [2, 2]
        elif n_heatmaps <= 6:
            grid = [2, 3]
        else:
            grid = [3, 3]

    # Calculate figsize based on cell dimensions if specified
    if cell_height is not None or cell_width is not None:
        # Get column dimensions
        columns_cfg = config.get("columns", {})
        model_order = columns_cfg.get("model_order", [])
        n_models = len(model_order) if model_order else 3
        threshold_range = columns_cfg.get("threshold_range", "auto")
        n_thresholds = 10 if threshold_range == "auto" else len(threshold_range)
        n_cols = n_models * n_thresholds

        # Calculate max rows across all heatmaps
        max_rows = 0
        for hm_cfg in heatmaps_cfg:
            breakdown = hm_cfg.get("breakdown", "level")
            if breakdown == "level":
                n_rows = len(config.get("level_order", [5, 4, 3, 2, 1]))
            else:
                n_rows = len(config.get("type_order", []))
                if n_rows == 0:
                    n_rows = 7
            max_rows = max(max_rows, n_rows)

        # Default cell dimensions
        cw = cell_width if cell_width is not None else 0.4
        ch = cell_height if cell_height is not None else 0.5

        # Calculate subplot dimensions
        subplot_width = n_cols * cw + 2.5  # margin for labels/colorbar
        subplot_height = max_rows * ch + 1.5  # margin for title/labels

        # Total figure size based on grid
        figsize = [
            subplot_width * grid[1] + 1.0,  # extra margin between subplots
            subplot_height * grid[0] + 1.5  # extra for main title
        ]
        logger.info(f"Calculated figsize from cell dimensions: {figsize}")

    # Apply publication style
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "Helvetica", "DejaVu Sans"]
    plt.rcParams["font.size"] = 10

    # Create figure and axes
    fig, axes = plt.subplots(
        grid[0], grid[1],
        figsize=figsize,
        constrained_layout=True,
    )

    # Flatten axes array for easy iteration
    if n_heatmaps == 1:
        axes = [axes]
    else:
        axes = axes.flatten()

    # Store individual figures
    individual_figures = []

    # Build each heatmap
    for i, heatmap_cfg in enumerate(heatmaps_cfg):
        if i >= len(axes):
            logger.warning(f"More heatmaps than axes slots, skipping heatmap {i}")
            break

        ax = axes[i]
        breakdown = heatmap_cfg.get("breakdown", "level")
        metric = heatmap_cfg.get("metric", "accuracy_delta")
        heatmap_id = heatmap_cfg.get("id", f"heatmap_{i}")

        logger.info(f"Building heatmap: {heatmap_cfg.get('title', 'Untitled')}")

        try:
            # Prepare data matrix
            data, _ = prepare_heatmap_data(df, breakdown, metric, evaluator, config)

            if data.empty:
                ax.text(0.5, 0.5, "No data", ha="center", va="center")
                ax.set_title(heatmap_cfg.get("title", "No Data"))
                continue

            # Render heatmap on combined figure
            render_heatmap(ax, data, heatmap_cfg, config)

            # Build individual figure
            individual_fig = build_single_heatmap(df, heatmap_cfg, config, evaluator)
            # Store tuple of (id, figure, data) for CSV export
            individual_figures.append((heatmap_id, individual_fig, data))

        except Exception as e:
            logger.error(f"Error building heatmap {i}: {e}")
            ax.text(0.5, 0.5, f"Error: {e}", ha="center", va="center")
            ax.set_title(heatmap_cfg.get("title", "Error"))

    # Hide unused axes
    for j in range(n_heatmaps, len(axes)):
        axes[j].set_visible(False)

    # Add main title if specified
    main_title = config.get("title", None)
    if main_title:
        fig.suptitle(main_title, fontsize=14, fontweight="bold", y=1.02)

    return fig, individual_figures


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
    filters_merged = config.get("filters") or {}
    if FILTERS:
        filters_merged.update(FILTERS)

    df = apply_filters(df_raw, filters_merged)
    print(f"After filtering: {len(df)} rows")

    if filters_merged:
        print(f"  Filters applied: {filters_merged}")

# %%
# Cell 5: Build and Display Heatmap Figure

# Only run in Jupyter mode - CLI uses main()
if _is_jupyter_mode():
    print("\n" + "=" * 70)
    print("BUILDING HEATMAP FIGURE")
    print("=" * 70)

    fig, individual_figures = build_heatmap_figure(df, config)
    n_heatmaps = len(config.get("heatmaps", []))
    print(f"Built figure with {n_heatmaps} heatmaps")
    print(f"Individual figures prepared: {len(individual_figures)}")

# %%
# Cell 6: Save and Display Plot
"""Save the plot and display."""


def save_outputs(
    fig: plt.Figure,
    individual_figures: list[tuple[str, plt.Figure, pd.DataFrame]],
    config: dict[str, Any],
    project_root: Path,
    show: bool = True,
) -> list[Path]:
    """
    Save the figure(s) to configured output files.

    Args:
        fig: Combined Matplotlib Figure object
        individual_figures: List of (heatmap_id, Figure, DataFrame) tuples for individual saves
        config: YAML configuration dictionary
        project_root: Project root path
        show: Whether to display the plot

    Returns:
        List of saved file paths
    """
    output_cfg = config.get("output", {})
    saved_files = []

    # Get base directory (if specified, all paths are relative to it)
    base_dir_str = output_cfg.get("base_dir", None)
    if base_dir_str:
        base_dir = project_root / base_dir_str
    else:
        base_dir = project_root

    # Save combined PNG
    if output_cfg.get("png", True):
        png_path = output_cfg.get("png_file", "heatmap.png")
        # If path is absolute or starts with project structure, use as-is; otherwise relative to base_dir
        if png_path.startswith("/") or (base_dir_str and not png_path.startswith(base_dir_str)):
            png_file = base_dir / png_path
        else:
            png_file = project_root / png_path if not base_dir_str else base_dir / png_path
        png_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            fig.savefig(str(png_file), dpi=300, bbox_inches="tight",
                       facecolor="white", edgecolor="none")
            saved_files.append(png_file)
            print(f"Saved PNG: {png_file} ({png_file.stat().st_size / 1024:.1f} KB)")
        except Exception as e:
            logger.warning(f"Could not save PNG: {e}")

    # Save combined PDF (vector format, good for publications)
    if output_cfg.get("pdf", True):
        pdf_path = output_cfg.get("pdf_file", "heatmap.pdf")
        if pdf_path.startswith("/") or (base_dir_str and not pdf_path.startswith(base_dir_str)):
            pdf_file = base_dir / pdf_path
        else:
            pdf_file = project_root / pdf_path if not base_dir_str else base_dir / pdf_path
        pdf_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            fig.savefig(str(pdf_file), format="pdf", bbox_inches="tight",
                       facecolor="white", edgecolor="none")
            saved_files.append(pdf_file)
            print(f"Saved PDF: {pdf_file} ({pdf_file.stat().st_size / 1024:.1f} KB)")
        except Exception as e:
            logger.warning(f"Could not save PDF: {e}")

    # Save individual heatmap files
    if output_cfg.get("individual_files", False) and individual_figures:
        ind_dir_path = output_cfg.get("individual_dir", "")
        # If individual_dir is empty/blank, use base_dir directly
        if ind_dir_path:
            individual_dir = base_dir / ind_dir_path
        else:
            individual_dir = base_dir
        individual_dir.mkdir(parents=True, exist_ok=True)
        formats = output_cfg.get("individual_format", ["png", "pdf"])

        print(f"\nSaving individual heatmaps to: {individual_dir}")

        # Check if CSV saving is enabled (default: true)
        save_csv = output_cfg.get("save_csv", True)

        for heatmap_id, ind_fig, heatmap_data in individual_figures:
            for fmt in formats:
                out_file = individual_dir / f"{heatmap_id}.{fmt}"
                try:
                    ind_fig.savefig(
                        str(out_file),
                        dpi=300 if fmt == "png" else None,
                        format=fmt,
                        bbox_inches="tight",
                        facecolor="white",
                        edgecolor="none",
                    )
                    saved_files.append(out_file)
                    print(f"  Saved {fmt.upper()}: {out_file.name} ({out_file.stat().st_size / 1024:.1f} KB)")
                except Exception as e:
                    logger.warning(f"Could not save {fmt.upper()} for {heatmap_id}: {e}")

            # Save CSV with heatmap data (same location as PNG, .csv extension)
            if save_csv and heatmap_data is not None and not heatmap_data.empty:
                csv_file = individual_dir / f"{heatmap_id}.csv"
                try:
                    # Flatten MultiIndex columns for CSV: (threshold, model) -> "threshold_model"
                    csv_data = heatmap_data.copy()
                    if isinstance(csv_data.columns, pd.MultiIndex):
                        csv_data.columns = [f"{t}_{m}" for t, m in csv_data.columns]
                    csv_data.to_csv(csv_file, index=True)
                    saved_files.append(csv_file)
                    print(f"  Saved CSV: {csv_file.name} ({csv_file.stat().st_size / 1024:.1f} KB)")
                except Exception as e:
                    logger.warning(f"Could not save CSV for {heatmap_id}: {e}")

            # Close individual figure to free memory
            plt.close(ind_fig)

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
    saved = save_outputs(fig, individual_figures, config, PROJECT_ROOT, show=output_cfg.get("show", True))

    print("\n" + "=" * 70)
    print("PLOT COMPLETE")
    print("=" * 70)

# %%
# Cell 7: CLI Entry Point
"""Command-line interface."""


def main():
    """Main CLI entry point."""
    default_config = PROJECT_ROOT / "experiments" / "configs" / "plots" / "plot_heatmap_template.yaml"

    parser = argparse.ArgumentParser(
        description="Phase 7b: Generate Heatmap plots from experiment results"
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
        help="Filter data (can be repeated). Example: --filter mode greedy",
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
    print("PHASE 7b: HEATMAP PLOT")
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
    filters_merged = config.get("filters") or {}
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
    fig, individual_figures = build_heatmap_figure(df, config)
    n_heatmaps = len(config.get("heatmaps", []))
    print(f"Built figure with {n_heatmaps} heatmaps")
    print(f"Individual figures prepared: {len(individual_figures)}")

    # Save and optionally show
    show = not args.no_show and config.get("output", {}).get("show", True)
    save_outputs(fig, individual_figures, config, PROJECT_ROOT, show=show)

    # Close figure to free memory
    plt.close(fig)

    print("=" * 70)
    print("COMPLETE")
    print("=" * 70)

    return 0


if __name__ == "__main__" and not _is_jupyter_mode():
    exit(main())
