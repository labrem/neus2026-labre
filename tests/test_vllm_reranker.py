"""
Unit tests for VLLMReranker class.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests


class TestVLLMReranker:
    """Tests for VLLMReranker class."""

    @pytest.fixture
    def mock_score_response(self):
        """Mock vLLM /score response."""
        return {
            "data": [{"index": 0, "score": 0.85}],
            "usage": {"prompt_tokens": 100, "total_tokens": 100},
        }

    @pytest.fixture
    def sample_candidates(self):
        """Sample OpenMath candidates."""
        return [
            {
                "cd": "arith1",
                "name": "gcd",
                "description_normalized": "The gcd function returns the greatest common divisor of two integers.",
                "cmp_properties_normalized": ["$\\gcd(a,b) = \\gcd(b, a \\mod b)$"],
            },
            {
                "cd": "transc1",
                "name": "sin",
                "description_normalized": "The sine trigonometric function.",
                "cmp_properties_normalized": ["$\\sin^2(x) + \\cos^2(x) = 1$"],
            },
            {
                "cd": "calculus1",
                "name": "int",
                "description_normalized": "The int symbol represents indefinite integration.",
                "cmp_properties_normalized": [],
            },
        ]

    def test_init_default(self):
        """Test VLLMReranker initialization with defaults."""
        from src.reranker_cross_encoder import VLLMReranker

        reranker = VLLMReranker()
        assert reranker.vllm_url == "http://localhost:9001"
        assert reranker.threshold == 0.15
        assert reranker.min_keep == 3
        assert reranker.model == "Qwen/Qwen3-Reranker-0.6B"

    def test_init_custom_url(self):
        """Test VLLMReranker with custom URL."""
        from src.reranker_cross_encoder import VLLMReranker

        reranker = VLLMReranker(vllm_url="http://custom:8000")
        assert reranker.vllm_url == "http://custom:8000"

    def test_init_custom_threshold(self):
        """Test VLLMReranker with custom threshold."""
        from src.reranker_cross_encoder import VLLMReranker

        reranker = VLLMReranker(threshold=0.5, min_keep=5)
        assert reranker.threshold == 0.5
        assert reranker.min_keep == 5

    @patch("src.reranker_cross_encoder.requests.post")
    def test_score_single(self, mock_post, mock_score_response):
        """Test scoring a single candidate."""
        from src.reranker_cross_encoder import VLLMReranker

        mock_post.return_value.json.return_value = mock_score_response
        mock_post.return_value.raise_for_status = MagicMock()

        reranker = VLLMReranker()
        score = reranker.score(
            "Find the GCD of 48 and 18.",
            {"cd": "arith1", "name": "gcd", "description_normalized": "Greatest common divisor."},
        )

        assert score == 0.85
        mock_post.assert_called_once()
        # Verify URL
        call_args = mock_post.call_args
        assert call_args[0][0] == "http://localhost:9001/score"

    @patch("src.reranker_cross_encoder.requests.post")
    def test_score_network_error(self, mock_post):
        """Test graceful handling of network errors during scoring."""
        from src.reranker_cross_encoder import VLLMReranker

        mock_post.side_effect = requests.RequestException("Connection refused")

        reranker = VLLMReranker()
        score = reranker.score(
            "Find the GCD of 48 and 18.",
            {"cd": "arith1", "name": "gcd", "description_normalized": "GCD function."},
        )

        # Should return 0.0 on error
        assert score == 0.0

    @patch("src.reranker_cross_encoder.requests.post")
    def test_rerank_applies_threshold(self, mock_post, sample_candidates):
        """Test that rerank applies threshold rule correctly."""
        from src.reranker_cross_encoder import VLLMReranker

        # Mock scores: [0.9, 0.1, 0.8] - two above default threshold (0.15)
        responses = [
            {"data": [{"index": 0, "score": 0.9}]},
            {"data": [{"index": 0, "score": 0.1}]},
            {"data": [{"index": 0, "score": 0.8}]},
        ]
        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.side_effect = responses

        reranker = VLLMReranker(threshold=0.5, min_keep=2)
        result = reranker.rerank("test", "Find GCD", sample_candidates)

        # Should keep 2 above threshold (0.9, 0.8), min_keep=2
        assert result.success
        assert result.reranked_count == 2
        assert result.original_count == 3
        # Check scores are sorted descending
        assert result.reranked_symbols[0]["reranker_score"] == 0.9
        assert result.reranked_symbols[1]["reranker_score"] == 0.8

    @patch("src.reranker_cross_encoder.requests.post")
    def test_rerank_min_keep(self, mock_post, sample_candidates):
        """Test that min_keep is respected even if all below threshold."""
        from src.reranker_cross_encoder import VLLMReranker

        # Mock all low scores
        responses = [
            {"data": [{"index": 0, "score": 0.1}]},
            {"data": [{"index": 0, "score": 0.05}]},
            {"data": [{"index": 0, "score": 0.08}]},
        ]
        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.side_effect = responses

        reranker = VLLMReranker(threshold=0.5, min_keep=3)
        result = reranker.rerank("test", "Find something", sample_candidates)

        # Should keep min_keep=3 even though all below threshold
        assert result.success
        assert result.reranked_count == 3

    @patch("src.reranker_cross_encoder.requests.post")
    def test_rerank_stores_all_scores(self, mock_post, sample_candidates):
        """Test that all_scores dict contains all candidates."""
        from src.reranker_cross_encoder import VLLMReranker

        responses = [
            {"data": [{"index": 0, "score": 0.9}]},
            {"data": [{"index": 0, "score": 0.1}]},
            {"data": [{"index": 0, "score": 0.5}]},
        ]
        mock_post.return_value.raise_for_status = MagicMock()
        mock_post.return_value.json.side_effect = responses

        reranker = VLLMReranker()
        result = reranker.rerank("test", "Problem text", sample_candidates)

        # all_scores should have all 3 candidates
        assert len(result.all_scores) == 3
        assert "arith1:gcd" in result.all_scores
        assert "transc1:sin" in result.all_scores
        assert "calculus1:int" in result.all_scores

    def test_format_query(self):
        """Test query formatting for Qwen3-Reranker."""
        from src.reranker_cross_encoder import VLLMReranker

        reranker = VLLMReranker()
        query = reranker._format_query("Find the GCD of 48 and 18.")

        assert "<|im_start|>system" in query
        assert "<Query>: Find the GCD of 48 and 18." in query
        assert "<Instruct>:" in query

    def test_format_document(self):
        """Test document formatting for Qwen3-Reranker."""
        from src.reranker_cross_encoder import VLLMReranker

        reranker = VLLMReranker()
        doc = reranker._format_document({
            "cd": "arith1",
            "name": "gcd",
            "description_normalized": "Greatest common divisor.",
        })

        assert "<Document>:" in doc
        assert "arith1:gcd" in doc
        assert "Greatest common divisor." in doc
        assert "<|im_end|>" in doc

    def test_format_description_card(self):
        """Test description card formatting with all fields."""
        from src.reranker_cross_encoder import VLLMReranker

        reranker = VLLMReranker()
        card = reranker._format_description_card({
            "cd": "arith1",
            "name": "gcd",
            "description_normalized": "GCD function.",
            "cmp_properties_normalized": ["prop1", "prop2"],
            "examples_normalized": ["example1"],
        })

        assert "Symbol: arith1:gcd" in card
        assert "Description: GCD function." in card
        assert "Properties: prop1; prop2" in card
        assert "Examples: example1" in card

    def test_format_description_card_minimal(self):
        """Test description card with minimal fields."""
        from src.reranker_cross_encoder import VLLMReranker

        reranker = VLLMReranker()
        card = reranker._format_description_card({
            "cd": "test",
            "name": "symbol",
        })

        assert "Symbol: test:symbol" in card
        assert "Description:" not in card


class TestCreateRerankerFactory:
    """Tests for create_reranker factory with vllm backend."""

    def test_create_vllm_backend(self):
        """Test factory creates VLLMReranker."""
        from src.reranker_cross_encoder import create_reranker, VLLMReranker

        reranker = create_reranker(backend="vllm")
        assert isinstance(reranker, VLLMReranker)

    def test_create_vllm_custom_threshold(self):
        """Test factory with custom threshold."""
        from src.reranker_cross_encoder import create_reranker

        reranker = create_reranker(backend="vllm", threshold=0.3)
        assert reranker.threshold == 0.3

    def test_create_vllm_custom_url(self):
        """Test factory with custom URL."""
        from src.reranker_cross_encoder import create_reranker

        reranker = create_reranker(backend="vllm", vllm_url="http://custom:8080")
        assert reranker.vllm_url == "http://custom:8080"

    def test_create_invalid_backend(self):
        """Test factory raises error for invalid backend."""
        from src.reranker_cross_encoder import create_reranker

        with pytest.raises(ValueError, match="Unknown backend"):
            create_reranker(backend="invalid")


class TestHealthCheck:
    """Tests for health check utility."""

    @patch("src.reranker_cross_encoder.requests.get")
    def test_health_check_healthy(self, mock_get):
        """Test health check when server is healthy."""
        from src.reranker_cross_encoder import check_vllm_reranker_health

        mock_get.return_value.status_code = 200

        health = check_vllm_reranker_health()
        assert health["healthy"] is True
        assert health["error"] is None

    @patch("src.reranker_cross_encoder.requests.get")
    def test_health_check_unhealthy(self, mock_get):
        """Test health check when server returns error status."""
        from src.reranker_cross_encoder import check_vllm_reranker_health

        mock_get.return_value.status_code = 503

        health = check_vllm_reranker_health()
        assert health["healthy"] is False
        assert "503" in health["error"]

    @patch("src.reranker_cross_encoder.requests.get")
    def test_health_check_connection_error(self, mock_get):
        """Test health check when server is unreachable."""
        from src.reranker_cross_encoder import check_vllm_reranker_health

        mock_get.side_effect = requests.RequestException("Connection refused")

        health = check_vllm_reranker_health()
        assert health["healthy"] is False
        assert "Connection refused" in health["error"]


class TestApplyThresholdRule:
    """Tests for apply_threshold_rule function."""

    def test_all_above_threshold(self):
        """Test when all scores are above threshold."""
        from src.reranker_cross_encoder import apply_threshold_rule

        candidates = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        scores = [0.9, 0.8, 0.7]

        result = apply_threshold_rule(candidates, scores, threshold=0.5, min_keep=2)

        assert len(result) == 3  # All above threshold
        # Verify sorted descending
        assert result[0][1] == 0.9
        assert result[1][1] == 0.8
        assert result[2][1] == 0.7

    def test_min_keep_respected(self):
        """Test that min_keep is respected when none above threshold."""
        from src.reranker_cross_encoder import apply_threshold_rule

        candidates = [{"name": "a"}, {"name": "b"}, {"name": "c"}]
        scores = [0.3, 0.2, 0.1]

        result = apply_threshold_rule(candidates, scores, threshold=0.5, min_keep=3)

        assert len(result) == 3  # min_keep=3 ensures all returned

    def test_threshold_wins_over_min_keep(self):
        """Test that threshold can return more than min_keep."""
        from src.reranker_cross_encoder import apply_threshold_rule

        candidates = [{"name": "a"}, {"name": "b"}, {"name": "c"}, {"name": "d"}]
        scores = [0.9, 0.8, 0.7, 0.3]

        result = apply_threshold_rule(candidates, scores, threshold=0.6, min_keep=2)

        # 3 above threshold (0.9, 0.8, 0.7), min_keep=2, so return 3
        assert len(result) == 3

    def test_empty_candidates(self):
        """Test with empty candidates list."""
        from src.reranker_cross_encoder import apply_threshold_rule

        result = apply_threshold_rule([], [], threshold=0.5, min_keep=3)
        assert len(result) == 0
