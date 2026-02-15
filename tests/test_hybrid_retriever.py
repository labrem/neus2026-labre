"""
Unit tests for the Hybrid Retriever module.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestHybridRetriever:
    """Tests for HybridRetriever class."""

    @pytest.fixture
    def mock_kb(self, tmp_path):
        """Create a mock knowledge base."""
        kb = {
            "version": "1.0.0",
            "symbols": {
                "arith1:plus": {
                    "id": "arith1:plus",
                    "cd": "arith1",
                    "name": "plus",
                    "description": "The symbol representing an n-ary commutative function plus.",
                    "sympy_function": "sympy.Add",
                    "cmp_properties": ["for all a,b | a + b = b + a"],
                },
                "arith1:minus": {
                    "id": "arith1:minus",
                    "cd": "arith1",
                    "name": "minus",
                    "description": "The symbol representing a binary minus function.",
                    "sympy_function": "sympy.Add",
                    "cmp_properties": [],
                },
                "arith1:gcd": {
                    "id": "arith1:gcd",
                    "cd": "arith1",
                    "name": "gcd",
                    "description": "The greatest common divisor of two integers.",
                    "sympy_function": "sympy.gcd",
                    "cmp_properties": ["gcd(a,b) = gcd(b,a)"],
                },
                "transc1:sin": {
                    "id": "transc1:sin",
                    "cd": "transc1",
                    "name": "sin",
                    "description": "The sine trigonometric function.",
                    "sympy_function": "sympy.sin",
                    "cmp_properties": [],
                },
                "no_sympy_symbol": {
                    "id": "no_sympy_symbol",
                    "cd": "test",
                    "name": "test",
                    "description": "A symbol without SymPy mapping.",
                    "sympy_function": "",
                    "cmp_properties": [],
                },
                # Non-mathematical symbols that should be filtered
                "meta:CDName": {
                    "id": "meta:CDName",
                    "cd": "meta",
                    "name": "CDName",
                    "description": "Content Dictionary name.",
                    "sympy_function": "",
                    "cmp_properties": [],
                },
                "scscp1:option_runtime": {
                    "id": "scscp1:option_runtime",
                    "cd": "scscp1",
                    "name": "option_runtime",
                    "description": "SCSCP runtime option.",
                    "sympy_function": "",
                    "cmp_properties": [],
                },
            },
        }
        kb_path = tmp_path / "openmath.json"
        with open(kb_path, "w") as f:
            json.dump(kb, f)
        return kb_path

    @pytest.fixture
    def mock_embeddings(self):
        """Create mock embeddings array."""
        np.random.seed(42)
        return np.random.randn(5, 768).astype(np.float32)

    def test_retrieval_result_structure(self):
        """Test HybridRetrievalResult dataclass."""
        from hybrid_retriever import HybridRetrievalResult

        result = HybridRetrievalResult(
            query="What is the GCD of 12 and 8?",
            symbols=[{"id": "arith1:gcd", "name": "gcd"}],
            symbol_ids=["arith1:gcd"],
            scores={"arith1:gcd": 0.015},
            bm25_scores={"arith1:gcd": 2.5},
            dense_scores={"arith1:gcd": 0.85},
        )

        assert result.query == "What is the GCD of 12 and 8?"
        assert len(result.symbols) == 1
        assert result.symbol_ids == ["arith1:gcd"]
        assert result.scores["arith1:gcd"] == 0.015
        assert result.bm25_scores["arith1:gcd"] == 2.5
        assert result.dense_scores["arith1:gcd"] == 0.85

    def test_get_symbol_from_result(self):
        """Test getting a symbol from retrieval result."""
        from hybrid_retriever import HybridRetrievalResult

        result = HybridRetrievalResult(
            query="test",
            symbols=[
                {"id": "arith1:gcd", "name": "gcd"},
                {"id": "arith1:plus", "name": "plus"},
            ],
            symbol_ids=["arith1:gcd", "arith1:plus"],
            scores={},
        )

        symbol = result.get_symbol("arith1:gcd")
        assert symbol is not None
        assert symbol["id"] == "arith1:gcd"

        missing = result.get_symbol("nonexistent")
        assert missing is None

    def test_non_math_cd_filter(self, mock_kb, tmp_path):
        """Test that non-mathematical CDs are filtered by default."""
        from hybrid_retriever import HybridRetriever, NON_MATHEMATICAL_CDS

        with patch("hybrid_retriever.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"embedding": [0.5] * 768}
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            retriever = HybridRetriever(
                kb_path=mock_kb,
                embeddings_cache=tmp_path / "cache.npz",
                ollama_url="http://test:11434/v1",
                filter_non_math=True,
            )

            # meta:CDName and scscp1:option_runtime should be filtered
            symbol_cds = [s["cd"] for s in retriever.symbols]
            for cd in NON_MATHEMATICAL_CDS:
                assert cd not in symbol_cds

            # Should have 5 symbols (7 original - 2 non-math)
            assert len(retriever.symbols) == 5

    def test_no_filter_option(self, mock_kb, tmp_path):
        """Test that filtering can be disabled."""
        from hybrid_retriever import HybridRetriever

        with patch("hybrid_retriever.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"embedding": [0.5] * 768}
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            retriever = HybridRetriever(
                kb_path=mock_kb,
                embeddings_cache=tmp_path / "cache.npz",
                ollama_url="http://test:11434/v1",
                filter_non_math=False,
            )

            # Should have all 7 symbols
            assert len(retriever.symbols) == 7

    @patch("hybrid_retriever.requests.post")
    def test_bm25_index_creation(self, mock_post, mock_kb, tmp_path):
        """Test that BM25 index is created correctly."""
        from hybrid_retriever import HybridRetriever

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.5] * 768}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        retriever = HybridRetriever(
            kb_path=mock_kb,
            embeddings_cache=tmp_path / "cache.npz",
            ollama_url="http://test:11434/v1",
        )

        # BM25 should be initialized
        assert retriever.bm25 is not None
        assert len(retriever.bm25_corpus) == len(retriever.symbols)

    @patch("hybrid_retriever.requests.post")
    def test_retrieve_returns_rrf_scores(self, mock_post, mock_kb, tmp_path):
        """Test that retrieval returns RRF scores."""
        from hybrid_retriever import HybridRetriever

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.5] * 768}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        retriever = HybridRetriever(
            kb_path=mock_kb,
            embeddings_cache=tmp_path / "cache.npz",
            ollama_url="http://test:11434/v1",
        )

        result = retriever.retrieve("What is the greatest common divisor?", top_k=3)

        # Should have symbols with scores
        assert len(result.symbols) > 0
        for symbol_id in result.symbol_ids:
            assert symbol_id in result.scores
            assert symbol_id in result.bm25_scores
            assert symbol_id in result.dense_scores

    @patch("hybrid_retriever.requests.post")
    def test_rrf_fusion(self, mock_post, mock_kb, tmp_path):
        """Test that RRF fusion combines BM25 and dense scores."""
        from hybrid_retriever import HybridRetriever

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.5] * 768}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        retriever = HybridRetriever(
            kb_path=mock_kb,
            embeddings_cache=tmp_path / "cache.npz",
            ollama_url="http://test:11434/v1",
            rrf_k=60,
        )

        # Query that should match "gcd" via BM25 (keyword)
        result = retriever.retrieve("greatest common divisor", top_k=5, require_sympy=False)

        # RRF scores should be positive
        for score in result.scores.values():
            assert score > 0

    @patch("hybrid_retriever.requests.post")
    def test_require_sympy_filter(self, mock_post, mock_kb, tmp_path):
        """Test that require_sympy filters symbols without SymPy mappings."""
        from hybrid_retriever import HybridRetriever

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.5] * 768}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        retriever = HybridRetriever(
            kb_path=mock_kb,
            embeddings_cache=tmp_path / "cache.npz",
            ollama_url="http://test:11434/v1",
        )

        # With require_sympy=True, should filter out no_sympy_symbol
        result = retriever.retrieve("test query", top_k=10, require_sympy=True)
        symbol_ids = [s["id"] for s in result.symbols]
        assert "no_sympy_symbol" not in symbol_ids

    @patch("hybrid_retriever.requests.post")
    def test_top_k_limit(self, mock_post, mock_kb, tmp_path):
        """Test that top_k limits the number of results."""
        from hybrid_retriever import HybridRetriever

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.5] * 768}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        retriever = HybridRetriever(
            kb_path=mock_kb,
            embeddings_cache=tmp_path / "cache.npz",
            ollama_url="http://test:11434/v1",
        )

        result = retriever.retrieve("test", top_k=2, require_sympy=False)
        assert len(result.symbols) <= 2

    @patch("hybrid_retriever.requests.post")
    def test_deduplication_by_symbol_name(self, mock_post, tmp_path):
        """Test that symbols with same name are deduplicated (highest score wins)."""
        from hybrid_retriever import HybridRetriever

        # Create KB with multiple CDs defining "gcd"
        kb = {
            "version": "1.0.0",
            "symbols": {
                "arith1:gcd": {
                    "id": "arith1:gcd",
                    "cd": "arith1",
                    "name": "gcd",
                    "description": "The greatest common divisor of integers.",
                    "sympy_function": "sympy.gcd",
                    "cmp_properties": [],
                },
                "polynomial3:gcd": {
                    "id": "polynomial3:gcd",
                    "cd": "polynomial3",
                    "name": "gcd",
                    "description": "The greatest common divisor of polynomials.",
                    "sympy_function": "",
                    "cmp_properties": [],
                },
                "poly:gcd": {
                    "id": "poly:gcd",
                    "cd": "poly",
                    "name": "gcd",
                    "description": "GCD for polynomial rings.",
                    "sympy_function": "",
                    "cmp_properties": [],
                },
                "arith1:lcm": {
                    "id": "arith1:lcm",
                    "cd": "arith1",
                    "name": "lcm",
                    "description": "The least common multiple.",
                    "sympy_function": "sympy.lcm",
                    "cmp_properties": [],
                },
            },
        }
        kb_path = tmp_path / "openmath.json"
        with open(kb_path, "w") as f:
            json.dump(kb, f)

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.5] * 768}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        retriever = HybridRetriever(
            kb_path=kb_path,
            embeddings_cache=tmp_path / "cache.npz",
            ollama_url="http://test:11434/v1",
        )

        # Query for GCD - should get multiple gcd symbols from different CDs
        # (deduplication is by full ID cd:name, not just name)
        result = retriever.retrieve("greatest common divisor", top_k=10, require_sympy=False)

        # Count how many "gcd" symbols are in results - should have all 3 from different CDs
        gcd_symbols = [s for s in result.symbols if s["name"] == "gcd"]
        assert len(gcd_symbols) == 3, f"Expected 3 gcd symbols from different CDs, got {len(gcd_symbols)}: {[s['id'] for s in gcd_symbols]}"

        # Verify they're from different CDs
        gcd_ids = {s["id"] for s in gcd_symbols}
        assert "arith1:gcd" in gcd_ids, "arith1:gcd should be retrieved"
        assert "polynomial3:gcd" in gcd_ids, "polynomial3:gcd should be retrieved"
        assert "poly:gcd" in gcd_ids, "poly:gcd should be retrieved"

        # Should also have lcm symbols
        symbol_names = [s["name"] for s in result.symbols]
        assert "gcd" in symbol_names
        assert "lcm" in symbol_names

    @patch("hybrid_retriever.requests.post")
    def test_embeddings_cache(self, mock_post, mock_kb, tmp_path):
        """Test that embeddings are cached and loaded correctly."""
        from hybrid_retriever import HybridRetriever

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.5] * 768}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        cache_path = tmp_path / "embeddings.npz"

        # First initialization should compute embeddings
        retriever1 = HybridRetriever(
            kb_path=mock_kb,
            embeddings_cache=cache_path,
            ollama_url="http://test:11434/v1",
        )

        first_call_count = mock_post.call_count
        assert first_call_count == 5  # 5 filtered symbols

        # Cache should exist
        assert cache_path.exists()

        # Second initialization should load from cache
        retriever2 = HybridRetriever(
            kb_path=mock_kb,
            embeddings_cache=cache_path,
            ollama_url="http://test:11434/v1",
        )

        # No additional calls for computing embeddings
        assert mock_post.call_count == first_call_count

    def test_get_symbol_method(self, mock_kb, tmp_path):
        """Test get_symbol method."""
        from hybrid_retriever import HybridRetriever

        with patch("hybrid_retriever.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {"embedding": [0.5] * 768}
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            retriever = HybridRetriever(
                kb_path=mock_kb,
                embeddings_cache=tmp_path / "cache.npz",
                ollama_url="http://test:11434/v1",
            )

        # Test getting existing symbol
        symbol = retriever.get_symbol("arith1:gcd")
        assert symbol is not None
        assert symbol["id"] == "arith1:gcd"

        # Test getting non-existing symbol
        missing = retriever.get_symbol("nonexistent:symbol")
        assert missing is None


class TestCreateHybridRetriever:
    """Tests for the factory function."""

    @patch("hybrid_retriever.requests.post")
    def test_factory_with_project_root(self, mock_post, tmp_path):
        """Test factory function with explicit project root."""
        from hybrid_retriever import create_hybrid_retriever

        # Create mock KB
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        kb = {"version": "1.0.0", "symbols": {}}
        with open(data_dir / "openmath.json", "w") as f:
            json.dump(kb, f)

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.5] * 768}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        retriever = create_hybrid_retriever(project_root=tmp_path)
        assert retriever is not None

    def test_factory_missing_kb(self, tmp_path):
        """Test factory raises error when KB not found."""
        from hybrid_retriever import create_hybrid_retriever

        with pytest.raises(FileNotFoundError):
            create_hybrid_retriever(project_root=tmp_path)

    @patch("hybrid_retriever.requests.post")
    def test_factory_model_specific_cache(self, mock_post, tmp_path):
        """Test that factory creates model-specific cache file."""
        from hybrid_retriever import create_hybrid_retriever

        # Create mock KB
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        kb = {"version": "1.0.0", "symbols": {}}
        with open(data_dir / "openmath.json", "w") as f:
            json.dump(kb, f)

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.5] * 768}
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        retriever = create_hybrid_retriever(
            project_root=tmp_path,
            embedding_model="custom-model:latest",
        )

        # Cache path should include model name
        expected_cache = data_dir / "hybrid_embeddings_custom-model_latest.npz"
        assert retriever.embeddings_cache == expected_cache


class TestTokenization:
    """Tests for tokenization."""

    def test_tokenize_simple(self):
        """Test basic tokenization with stopword removal."""
        from hybrid_retriever import HybridRetriever

        # We need to test the _tokenize method directly
        # Create a minimal mock to test tokenization
        # Note: "the" is a stopword and is filtered out
        tokens = HybridRetriever._tokenize(None, "The greatest common divisor")
        assert tokens == ["greatest", "common", "divisor"]
        assert "the" not in tokens  # stopword filtered

    def test_tokenize_punctuation(self):
        """Test tokenization removes punctuation."""
        from hybrid_retriever import HybridRetriever

        tokens = HybridRetriever._tokenize(None, "sin(x) + cos(y)")
        assert "(" not in tokens
        assert ")" not in tokens
        assert "+" not in tokens
        assert "sin" in tokens
        assert "cos" in tokens

    def test_tokenize_lowercase(self):
        """Test tokenization lowercases text."""
        from hybrid_retriever import HybridRetriever

        tokens = HybridRetriever._tokenize(None, "GCD LCM")
        assert tokens == ["gcd", "lcm"]
