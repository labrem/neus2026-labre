"""Unit tests for results storage."""

import pytest
import tempfile
from pathlib import Path


@pytest.fixture
def temp_storage():
    """Create temporary storage."""
    from src.results_storage import create_results_storage

    with tempfile.TemporaryDirectory() as tmpdir:
        yield create_results_storage(tmpdir)


@pytest.fixture
def mock_result():
    """Create mock result."""
    from src.experiment_runner import ProblemResult

    return ProblemResult(
        problem_id="test_001",
        problem_text="What is 2+2?",
        ground_truth="4",
        level=1,
        problem_type="prealgebra",
        condition="baseline",
        is_correct=True,
        predicted_answer="4",
    )


def test_initialize_experiment(temp_storage):
    """Test experiment initialization."""
    exp_id = temp_storage.initialize_experiment(
        model_name="test_model",
        conditions=["baseline", "full_system"],
        n_problems=10,
    )

    assert exp_id.startswith("test_model")
    assert exp_id in temp_storage.list_experiments()


def test_save_and_load_result(temp_storage, mock_result):
    """Test saving and loading a single result."""
    exp_id = temp_storage.initialize_experiment(
        model_name="test",
        conditions=["baseline"],
        n_problems=1,
    )

    # Save
    path = temp_storage.save_result(mock_result, exp_id)
    assert path.exists()

    # Load
    loaded = list(temp_storage.load_results(exp_id))
    assert len(loaded) == 1
    assert loaded[0]["problem_id"] == "test_001"
    assert loaded[0]["is_correct"] == True


def test_export_to_csv(temp_storage, mock_result):
    """Test CSV export."""
    exp_id = temp_storage.initialize_experiment(
        model_name="test",
        conditions=["baseline"],
        n_problems=1,
    )

    temp_storage.save_result(mock_result, exp_id)
    csv_path = temp_storage.export_to_csv(exp_id)

    assert csv_path.exists()

    # Verify CSV content
    with open(csv_path) as f:
        content = f.read()
        assert "test_001" in content
        assert "baseline" in content


def test_get_completed_problems(temp_storage, mock_result):
    """Test tracking completed problems."""
    exp_id = temp_storage.initialize_experiment(
        model_name="test",
        conditions=["baseline"],
        n_problems=10,
    )

    temp_storage.save_result(mock_result, exp_id)

    completed = temp_storage.get_completed_problems(exp_id, "baseline")
    assert "test_001" in completed
