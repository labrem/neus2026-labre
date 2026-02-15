"""Unit tests for experiment runner."""

import pytest
from pathlib import Path


@pytest.fixture
def project_root():
    """Get project root."""
    return Path(__file__).parent.parent


@pytest.fixture
def mock_problem():
    """Create a mock problem."""
    from src.benchmark_loader import Problem
    return Problem(
        id="test_001",
        problem="What is 2 + 2?",
        solution="2 + 2 = 4",
        answer="4",
        level=1,
        problem_type="prealgebra",
    )


def test_experiment_config():
    """Test experiment configuration."""
    from src.experiment_runner import ExperimentConfig

    config = ExperimentConfig(
        model_path="/path/to/model",
        conditions=["baseline", "full_system"],
    )

    assert config.model_path == Path("/path/to/model")
    assert "baseline" in config.conditions
    assert "full_system" in config.conditions


def test_problem_result_to_dict(mock_problem):
    """Test ProblemResult serialization."""
    from src.experiment_runner import ProblemResult

    result = ProblemResult(
        problem_id=mock_problem.id,
        problem_text=mock_problem.problem,
        ground_truth=mock_problem.answer,
        level=mock_problem.level,
        problem_type=mock_problem.problem_type,
        condition="baseline",
        is_correct=True,
    )

    d = result.to_dict()
    assert d["problem_id"] == "test_001"
    assert d["is_correct"] == True
    assert d["condition"] == "baseline"


def test_pipeline_integration(project_root, mock_problem):
    """Test that pipeline components can process a problem."""
    import sys
    sys.path.insert(0, str(project_root / "src"))

    from keyword_extractor import KeywordExtractor
    from retriever import create_retriever
    from prompt_builder import create_prompt_builder

    # Initialize components
    extractor = KeywordExtractor(index_path=project_root / "data" / "index.json")
    retriever = create_retriever(project_root)
    builder = create_prompt_builder(project_root)

    # Process problem
    keywords = extractor.extract(mock_problem.problem)
    symbols = retriever.retrieve(keywords.all_terms(), max_symbols=3)
    prompt = builder.build(mock_problem.problem, symbols.symbols, "full_system")

    assert len(prompt.system_prompt) > 0
    assert len(prompt.user_prompt) > 0
