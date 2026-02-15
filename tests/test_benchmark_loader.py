"""Unit tests for benchmark loader."""

import pytest
from pathlib import Path


@pytest.fixture
def project_root():
    """Get project root."""
    return Path(__file__).parent.parent


@pytest.fixture
def loader(project_root):
    """Create loader instance with project-local cache."""
    from src.benchmark_loader import create_benchmark_loader
    return create_benchmark_loader(project_root=project_root)


def test_load_subset(loader):
    """Test loading a subset of the benchmark."""
    dataset = loader.load_subset(n=10, seed=42)

    assert len(dataset) == 10
    assert all(hasattr(p, "problem") for p in dataset)
    assert all(hasattr(p, "answer") for p in dataset)
    assert all(hasattr(p, "level") for p in dataset)


def test_filter_by_level(loader):
    """Test filtering by difficulty level."""
    dataset = loader.load_subset(n=100, levels=[1, 2], seed=42)

    for problem in dataset:
        assert problem.level in [1, 2]


def test_filter_by_type(loader):
    """Test filtering by problem type."""
    dataset = loader.load_subset(n=50, types=["algebra"], seed=42)

    for problem in dataset:
        assert problem.problem_type == "algebra"


def test_stratified_sample(loader):
    """Test stratified sampling by level."""
    dataset = loader.load_subset(n=50, stratify_by="level", seed=42)

    stats = dataset.get_statistics()
    # Should have problems from multiple levels
    assert len(stats["by_level"]) >= 3


def test_get_statistics(loader):
    """Test statistics generation."""
    dataset = loader.load_subset(n=50, seed=42)
    stats = dataset.get_statistics()

    assert "total" in stats
    assert "by_level" in stats
    assert "by_type" in stats
    assert stats["total"] == 50


def test_cache_directory(loader, project_root):
    """Test that cache directory is project-local."""
    expected_cache = project_root / "data" / "math_benchmark"
    assert loader.cache_dir == expected_cache
    assert loader.cache_dir.exists()
