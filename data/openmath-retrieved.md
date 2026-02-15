# OpenMath Retrieved Candidates

This document describes the workflow and structure of `openmath-retrieved.json`, which contains the top-50 OpenMath symbol candidates retrieved for each MATH 500 problem.

## Overview

`openmath-retrieved.json` is the output of **Phase 8c: Hybrid Retrieval (Recall Layer)**. It maps each MATH 500 problem to its extracted concepts (from Phase 8b) and the top-50 OpenMath symbols retrieved using a hybrid BM25 + Dense embedding approach with Reciprocal Rank Fusion (RRF).

## Generation Workflow

```
┌─────────────────────────────────────────────────────────────────────┐
│  INPUT: data/math500-concepts.json (Phase 8b)                       │
│         - Problem ID → List of mathematical concepts                │
│         - Example: "math_00000" → ["rectangular coordinates", ...]  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 1: Initialize HybridRetriever                                 │
│  - Load data/openmath.json (1138 symbols, 1040 after filtering)    │
│  - Build BM25 index from normalized Description Cards              │
│  - Load/compute symbol embeddings (qwen3-embedding:4b via Ollama)  │
│  - Cache: data/openmath-embeddings_qwen3-embedding_4b.npy          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 2: Compute Concept Embeddings                                 │
│  - For each problem: join concepts → embed with qwen3-embedding:4b │
│  - Cache: data/math500-concepts-embeddings_qwen3-embedding_4b.npy  │
│  - Shape: (500, 2560)                                              │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3: Hybrid Retrieval (per problem)                             │
│                                                                     │
│  ┌──────────────────┐         ┌──────────────────────────────────┐ │
│  │ BM25 Retrieval   │         │ Dense Retrieval                  │ │
│  │ - Tokenize query │         │ - Cosine similarity              │ │
│  │ - Query expansion│         │ - Concept embedding vs           │ │
│  │ - Get BM25 scores│         │   symbol embeddings              │ │
│  └────────┬─────────┘         └───────────────┬──────────────────┘ │
│           │                                   │                     │
│           └───────────┬───────────────────────┘                     │
│                       ▼                                             │
│           ┌───────────────────────────┐                             │
│           │ Reciprocal Rank Fusion    │                             │
│           │ RRF(d) = Σ w/(k + rank)   │                             │
│           │ k=60, w_bm25=0.5, w_dense=0.5                           │
│           └───────────────────────────┘                             │
│                       │                                             │
│                       ▼                                             │
│           ┌───────────────────────────┐                             │
│           │ Top-50 symbols by RRF     │                             │
│           │ (deduplicated by name)    │                             │
│           └───────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OUTPUT: data/openmath-retrieved.json                               │
│  - 500 problems × 50 symbols each                                   │
│  - ~14 MB JSON file                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

## File Structure

```json
{
  "math_00000": {
    "concepts": ["rectangular coordinates", "polar coordinates", ...],
    "openmath": {
      "plangeo4:affine_coordinates": {
        "name": "affine_coordinates",
        "cd": "plangeo4",
        "description_normalized": "...",
        "cmp_properties_normalized": [...],
        "examples_normalized": [...],
        "rrf_score": 0.0161
      },
      "complex1:complex_polar": { ... },
      ...
    }
  },
  "math_00001": { ... },
  ...
}
```

### Fields

| Field | Description |
|-------|-------------|
| `concepts` | List of mathematical concepts extracted in Phase 8b |
| `openmath` | Dictionary of retrieved OpenMath symbols (keyed by symbol ID) |
| `name` | Symbol name (e.g., "gcd", "sin") |
| `cd` | Content Dictionary (e.g., "arith1", "transc1") |
| `description_normalized` | LaTeX-normalized description from Phase 8a |
| `cmp_properties_normalized` | LaTeX-normalized mathematical properties |
| `examples_normalized` | LaTeX-normalized usage examples |
| `rrf_score` | Reciprocal Rank Fusion score (higher = more relevant) |

## Regeneration

### Quick Method (using test script)

```bash
# Generate for all 500 problems
python experiments/test_phase_8c.py --all

# Generate for subset (10 problems)
python experiments/test_phase_8c.py --n-problems 10
```

### Manual Regeneration Steps

1. **Ensure prerequisites exist**:
   - `data/openmath.json` (Phase 8a normalized KB)
   - `data/math500-concepts.json` (Phase 8b concepts)

2. **Regenerate embeddings if needed**:
   ```bash
   # OpenMath symbol embeddings
   python scripts/generate_openmath_embeddings.py --force

   # MATH 500 concept embeddings
   python scripts/generate_concept_embeddings.py --force
   ```

3. **Run retrieval**:
   ```bash
   python experiments/test_phase_8c.py --all
   ```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `EMBEDDING_MODEL` | `qwen3-embedding:4b` | Dense embedding model via Ollama |
| `TOP_K` | 50 | Candidates per problem |
| `BM25_WEIGHT` | 0.5 | BM25 weight in RRF fusion |
| `DENSE_WEIGHT` | 0.5 | Dense weight in RRF fusion |
| `RRF_K` | 60 | RRF smoothing constant |

## Dependencies

- **Phase 8a**: `data/openmath.json` with `*_normalized` fields
- **Phase 8b**: `data/math500-concepts.json` with extracted concepts
- **Ollama**: Running with `qwen3-embedding:4b` model

## Embedding Caches

| Cache File | Shape | Purpose |
|------------|-------|---------|
| `data/openmath-embeddings_qwen3-embedding_4b.npy` | (1040, 2560) | OpenMath symbol embeddings |
| `data/math500-concepts-embeddings_qwen3-embedding_4b.npy` | (500, 2560) | MATH 500 concept embeddings |

## Statistics

- **Problems**: 500
- **Symbols per problem**: 50 (max)
- **Total unique symbols retrieved**: ~800-900 (varies by run)
- **File size**: ~14 MB
- **Generation time**: ~3 minutes (with cached embeddings)

## Next Phase

`openmath-retrieved.json` is used as input to **Phase 8d: Cross-Encoder Reranking**, which filters and reranks candidates using a cross-encoder model to improve precision.
