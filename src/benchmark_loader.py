"""
MATH Benchmark Loader.

Loads and filters competition math problems from the HuggingFace
MATH benchmark (nlile/hendrycks-MATH-benchmark).

Dataset is cached locally in data/math_benchmark/ for fast subsequent loads.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal

logger = logging.getLogger(__name__)

# Problem types in MATH benchmark
ProblemType = Literal[
    "algebra",
    "counting_and_probability",
    "geometry",
    "intermediate_algebra",
    "number_theory",
    "prealgebra",
    "precalculus",
]

# All problem types
ALL_PROBLEM_TYPES: list[ProblemType] = [
    "algebra",
    "counting_and_probability",
    "geometry",
    "intermediate_algebra",
    "number_theory",
    "prealgebra",
    "precalculus",
]

# Difficulty levels (1-5)
ALL_LEVELS: list[int] = [1, 2, 3, 4, 5]


@dataclass
class Problem:
    """A single benchmark problem."""

    id: str
    problem: str
    solution: str
    answer: str
    level: int
    problem_type: str

    @classmethod
    def from_dict(cls, data: dict[str, Any], idx: int) -> "Problem":
        """
        Create a Problem from a HuggingFace dataset row.

        Args:
            data: Row from the dataset
            idx: Index for unique ID

        Returns:
            Problem instance
        """
        # Extract level number from "Level X" string or just integer
        level_str = data.get("level", "Level 1")
        if isinstance(level_str, str):
            level = int(level_str.replace("Level ", ""))
        else:
            level = int(level_str)

        # Handle different field names for problem type
        # The dataset uses 'subject' (e.g., 'Precalculus'), we normalize to lowercase
        problem_type_raw = data.get("type") or data.get("subject") or data.get("source_domain", "unknown")
        problem_type = problem_type_raw.lower().replace(" ", "_")

        return cls(
            id=f"math_{idx:05d}",
            problem=data["problem"],
            solution=data.get("solution", ""),
            answer=data.get("answer", ""),
            level=level,
            problem_type=problem_type,
        )


@dataclass
class BenchmarkDataset:
    """Collection of benchmark problems with metadata."""

    problems: list[Problem] = field(default_factory=list)
    name: str = "MATH"
    split: str = "test"

    def __len__(self) -> int:
        return len(self.problems)

    def __iter__(self) -> Iterator[Problem]:
        return iter(self.problems)

    def __getitem__(self, idx: int) -> Problem:
        return self.problems[idx]

    def filter_by_level(self, levels: list[int]) -> "BenchmarkDataset":
        """
        Filter problems by difficulty level.

        Args:
            levels: List of levels to include (1-5)

        Returns:
            New BenchmarkDataset with filtered problems
        """
        filtered = [p for p in self.problems if p.level in levels]
        return BenchmarkDataset(
            problems=filtered,
            name=self.name,
            split=self.split,
        )

    def filter_by_type(self, types: list[str]) -> "BenchmarkDataset":
        """
        Filter problems by problem type.

        Args:
            types: List of problem types to include

        Returns:
            New BenchmarkDataset with filtered problems
        """
        filtered = [p for p in self.problems if p.problem_type in types]
        return BenchmarkDataset(
            problems=filtered,
            name=self.name,
            split=self.split,
        )

    def sample(self, n: int, seed: int | None = 42) -> "BenchmarkDataset":
        """
        Random sample of n problems.

        Args:
            n: Number of problems to sample
            seed: Random seed for reproducibility

        Returns:
            New BenchmarkDataset with sampled problems
        """
        if n >= len(self.problems):
            return self

        rng = random.Random(seed)
        sampled = rng.sample(self.problems, n)
        return BenchmarkDataset(
            problems=sampled,
            name=self.name,
            split=self.split,
        )

    def stratified_sample(
        self,
        n: int,
        by: Literal["level", "type"] = "level",
        seed: int | None = 42,
    ) -> "BenchmarkDataset":
        """
        Stratified sample maintaining distribution of levels or types.

        Args:
            n: Total number of problems to sample
            by: Stratify by "level" or "type"
            seed: Random seed for reproducibility

        Returns:
            New BenchmarkDataset with stratified sample
        """
        rng = random.Random(seed)

        # Group problems by stratification key
        groups: dict[Any, list[Problem]] = {}
        for p in self.problems:
            key = p.level if by == "level" else p.problem_type
            if key not in groups:
                groups[key] = []
            groups[key].append(p)

        # Calculate samples per group
        n_groups = len(groups)
        per_group = n // n_groups
        remainder = n % n_groups

        sampled = []
        for i, (key, problems) in enumerate(sorted(groups.items())):
            # Add one extra to first groups for remainder
            group_n = per_group + (1 if i < remainder else 0)
            group_n = min(group_n, len(problems))

            sampled.extend(rng.sample(problems, group_n))

        # Shuffle final sample
        rng.shuffle(sampled)

        return BenchmarkDataset(
            problems=sampled,
            name=self.name,
            split=self.split,
        )

    def get_statistics(self) -> dict[str, Any]:
        """
        Get dataset statistics.

        Returns:
            Dictionary with level and type distributions
        """
        level_counts: dict[int, int] = {}
        type_counts: dict[str, int] = {}

        for p in self.problems:
            level_counts[p.level] = level_counts.get(p.level, 0) + 1
            type_counts[p.problem_type] = type_counts.get(p.problem_type, 0) + 1

        return {
            "total": len(self.problems),
            "by_level": dict(sorted(level_counts.items())),
            "by_type": dict(sorted(type_counts.items())),
        }


class BenchmarkLoader:
    """Loads MATH benchmark from HuggingFace with local caching."""

    # Default cache location within project
    DEFAULT_CACHE_DIR = "data/math_benchmark"

    def __init__(
        self,
        dataset_name: str = "nlile/hendrycks-MATH-benchmark",
        split: str = "test",
        cache_dir: str | Path | None = None,
        project_root: Path | None = None,
    ):
        """
        Initialize the benchmark loader.

        Args:
            dataset_name: HuggingFace dataset name
            split: Dataset split ("train" or "test")
            cache_dir: Cache directory for dataset (uses project-local default if None)
            project_root: Project root path (auto-detected if None)
        """
        self.dataset_name = dataset_name
        self.split = split

        # Determine project root
        if project_root is None:
            project_root = Path.cwd()
        self.project_root = Path(project_root)

        # Set cache directory (project-local by default)
        if cache_dir is None:
            self.cache_dir = self.project_root / self.DEFAULT_CACHE_DIR
        else:
            self.cache_dir = Path(cache_dir)

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> BenchmarkDataset:
        """
        Load the full benchmark dataset.

        First load downloads from HuggingFace and caches locally.
        Subsequent loads read from local cache (fast, no internet required).

        Returns:
            BenchmarkDataset with all problems
        """
        try:
            from datasets import load_dataset
        except ImportError:
            raise ImportError(
                "Please install the 'datasets' package: pip install datasets"
            )

        logger.info(f"Loading {self.dataset_name} ({self.split} split)...")
        logger.info(f"Cache directory: {self.cache_dir}")

        # Load dataset from HuggingFace (cached locally after first download)
        dataset = load_dataset(
            self.dataset_name,
            split=self.split,
            cache_dir=str(self.cache_dir),
        )

        # Convert to Problem objects
        problems = []
        for idx, row in enumerate(dataset):
            try:
                problem = Problem.from_dict(row, idx)
                problems.append(problem)
            except Exception as e:
                logger.warning(f"Skipping problem {idx}: {e}")
                continue

        logger.info(f"Loaded {len(problems)} problems from {self.dataset_name}")

        return BenchmarkDataset(
            problems=problems,
            name=self.dataset_name,
            split=self.split,
        )

    def load_subset(
        self,
        n: int = 500,
        levels: list[int] | None = None,
        types: list[str] | None = None,
        stratify_by: Literal["level", "type"] | None = "level",
        seed: int = 42,
    ) -> BenchmarkDataset:
        """
        Load a filtered and sampled subset of the benchmark.

        Args:
            n: Number of problems to load
            levels: Filter by difficulty levels (1-5)
            types: Filter by problem types
            stratify_by: Stratification method ("level", "type", or None)
            seed: Random seed for reproducibility

        Returns:
            BenchmarkDataset with filtered/sampled problems
        """
        # Load full dataset
        dataset = self.load()

        # Apply filters
        if levels:
            dataset = dataset.filter_by_level(levels)
            logger.info(f"Filtered to levels {levels}: {len(dataset)} problems")

        if types:
            dataset = dataset.filter_by_type(types)
            logger.info(f"Filtered to types {types}: {len(dataset)} problems")

        # Sample
        if stratify_by:
            dataset = dataset.stratified_sample(n, by=stratify_by, seed=seed)
        else:
            dataset = dataset.sample(n, seed=seed)

        logger.info(f"Sampled {len(dataset)} problems")

        return dataset


def create_benchmark_loader(
    project_root: Path | None = None,
    split: str = "test",
    cache_dir: str | Path | None = None,
) -> BenchmarkLoader:
    """
    Factory function to create a benchmark loader.

    The dataset is cached locally in data/math_benchmark/ by default.
    First load downloads from HuggingFace (~50MB), subsequent loads
    read from local cache.

    Args:
        project_root: Project root path (auto-detected if None)
        split: Dataset split ("train" or "test")
        cache_dir: Custom cache directory (uses data/math_benchmark/ if None)

    Returns:
        Configured BenchmarkLoader instance
    """
    return BenchmarkLoader(
        dataset_name="nlile/hendrycks-MATH-benchmark",
        split=split,
        cache_dir=cache_dir,
        project_root=project_root,
    )
