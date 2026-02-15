"""
Results Storage for Experiment Outputs.

Provides JSON and CSV storage for experiment results with
metadata tracking and resumption support.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)


@dataclass
class ExperimentMetadata:
    """Metadata for an experiment run."""

    experiment_id: str
    start_time: str
    model_name: str
    conditions: list[str]
    n_problems: int
    dataset_name: str
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "start_time": self.start_time,
            "model_name": self.model_name,
            "conditions": self.conditions,
            "n_problems": self.n_problems,
            "dataset_name": self.dataset_name,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentMetadata":
        return cls(**data)


class ResultsStorage:
    """Stores and retrieves experiment results."""

    def __init__(self, output_dir: Path):
        """
        Initialize results storage.

        Args:
            output_dir: Base directory for results
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._metadata: ExperimentMetadata | None = None

    def initialize_experiment(
        self,
        model_name: str,
        conditions: list[str],
        n_problems: int,
        dataset_name: str = "MATH",
        config: dict[str, Any] | None = None,
    ) -> str:
        """
        Initialize a new experiment and create directory structure.

        Args:
            model_name: Name of the model being evaluated
            conditions: List of experimental conditions
            n_problems: Number of problems in the experiment
            dataset_name: Name of the benchmark dataset
            config: Additional configuration to store

        Returns:
            Experiment ID
        """
        # Generate experiment ID from timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        experiment_id = f"{model_name}_{timestamp}"

        # Create experiment directory
        exp_dir = self.output_dir / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)

        # Create condition subdirectories
        for condition in conditions:
            (exp_dir / condition).mkdir(exist_ok=True)

        # Save metadata
        self._metadata = ExperimentMetadata(
            experiment_id=experiment_id,
            start_time=datetime.now().isoformat(),
            model_name=model_name,
            conditions=conditions,
            n_problems=n_problems,
            dataset_name=dataset_name,
            config=config or {},
        )

        metadata_path = exp_dir / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(self._metadata.to_dict(), f, indent=2)

        logger.info(f"Initialized experiment: {experiment_id}")
        return experiment_id

    def save_result(
        self,
        result: Any,  # ProblemResult
        experiment_id: str | None = None,
    ) -> Path:
        """
        Save a single problem result.

        Args:
            result: ProblemResult to save
            experiment_id: Experiment ID (uses current if None)

        Returns:
            Path to saved result file
        """
        exp_id = experiment_id or (
            self._metadata.experiment_id if self._metadata else "default"
        )

        # Determine output path
        result_dir = self.output_dir / exp_id / result.condition
        result_dir.mkdir(parents=True, exist_ok=True)

        result_path = result_dir / f"{result.problem_id}.json"

        # Save as JSON
        with open(result_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2)

        return result_path

    def save_results_batch(
        self,
        results: list[Any],  # list[ProblemResult]
        experiment_id: str | None = None,
    ) -> list[Path]:
        """
        Save multiple results.

        Args:
            results: List of ProblemResult to save
            experiment_id: Experiment ID

        Returns:
            List of paths to saved files
        """
        paths = []
        for result in results:
            path = self.save_result(result, experiment_id)
            paths.append(path)
        return paths

    def export_to_csv(
        self,
        experiment_id: str,
        output_path: Path | None = None,
    ) -> Path:
        """
        Export all results for an experiment to a single CSV file.

        Args:
            experiment_id: Experiment ID to export
            output_path: Custom output path (uses default if None)

        Returns:
            Path to CSV file
        """
        exp_dir = self.output_dir / experiment_id

        if output_path is None:
            output_path = exp_dir / "results.csv"

        # Collect all results
        results = list(self.load_results(experiment_id))

        if not results:
            logger.warning(f"No results found for experiment {experiment_id}")
            return output_path

        # Write CSV
        fieldnames = [
            "problem_id",
            "condition",
            "level",
            "problem_type",
            "is_correct",
            "predicted_answer",
            "ground_truth",
            "comparison_method",
            "code_extracted",
            "execution_success",
            "response_time",
            "execution_time",
            "total_time",
        ]

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for result in results:
                row = {k: result.get(k, "") for k in fieldnames}
                writer.writerow(row)

        logger.info(f"Exported {len(results)} results to {output_path}")
        return output_path

    def load_results(
        self,
        experiment_id: str,
        condition: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Load results from an experiment.

        Args:
            experiment_id: Experiment ID
            condition: Filter by condition (all if None)

        Yields:
            Result dictionaries
        """
        exp_dir = self.output_dir / experiment_id

        if not exp_dir.exists():
            logger.warning(f"Experiment directory not found: {exp_dir}")
            return

        # Find result files
        if condition:
            search_dirs = [exp_dir / condition]
        else:
            search_dirs = [d for d in exp_dir.iterdir() if d.is_dir()]

        for result_dir in search_dirs:
            if not result_dir.exists():
                continue

            for result_file in result_dir.glob("*.json"):
                if result_file.name == "metadata.json":
                    continue

                try:
                    with open(result_file) as f:
                        yield json.load(f)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON in {result_file}: {e}")

    def load_metadata(self, experiment_id: str) -> ExperimentMetadata | None:
        """
        Load experiment metadata.

        Args:
            experiment_id: Experiment ID

        Returns:
            ExperimentMetadata or None if not found
        """
        metadata_path = self.output_dir / experiment_id / "metadata.json"

        if not metadata_path.exists():
            return None

        with open(metadata_path) as f:
            data = json.load(f)

        return ExperimentMetadata.from_dict(data)

    def list_experiments(self) -> list[str]:
        """
        List all experiment IDs.

        Returns:
            List of experiment IDs
        """
        experiments = []
        for path in self.output_dir.iterdir():
            if path.is_dir() and (path / "metadata.json").exists():
                experiments.append(path.name)
        return sorted(experiments)

    def get_completed_problems(
        self,
        experiment_id: str,
        condition: str,
    ) -> set[str]:
        """
        Get set of completed problem IDs for resumption.

        Args:
            experiment_id: Experiment ID
            condition: Condition to check

        Returns:
            Set of completed problem IDs
        """
        result_dir = self.output_dir / experiment_id / condition

        if not result_dir.exists():
            return set()

        completed = set()
        for result_file in result_dir.glob("*.json"):
            if result_file.name != "metadata.json":
                problem_id = result_file.stem
                completed.add(problem_id)

        return completed


def create_results_storage(output_dir: str | Path = "results") -> ResultsStorage:
    """
    Factory function to create results storage.

    Args:
        output_dir: Base directory for results

    Returns:
        Configured ResultsStorage instance
    """
    return ResultsStorage(output_dir=Path(output_dir))
