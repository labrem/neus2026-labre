# MATH 500 Concepts Extraction

**Phase**: 8b (Zero-Shot Input Parsing - The Denoiser)

This document describes the process and manual corrections applied to `data/math500-concepts.json`.

## Overview

The concepts file contains extracted mathematical concepts for all 500 problems in the MATH benchmark. These concepts are used in Phase 8c for hybrid retrieval (BM25 + Dense Embedding) to match problems with relevant OpenMath symbols.

## Generation Process

### 1. Query Parser (`src/query_parser.py`)

The `QueryParser` class uses `qwen2-math:7b` via Ollama to extract mathematical concepts from problem statements.

**Configuration**:
- Model: `qwen2-math:7b`
- Max tokens: 200 (prevents LLM from solving)
- Temperature: 0.0 (deterministic output)
- Output format: JSON mode `{"concepts": [...]}`

**System Prompt**:
```
You are a mathematical entity extractor. Extract the core mathematical
concepts from a problem WITHOUT solving it.

Return ONLY a JSON object with a "concepts" key containing an array of strings.

Extract these types of concepts:
- Operations: addition, subtraction, multiplication, division, integration, differentiation
- Functions: gcd, lcm, sin, cos, log, factorial, determinant
- Objects: integer, polynomial, matrix, set, sequence, function
- Domains: algebra, calculus, number theory, combinatorics, geometry
```

### 2. Test Script (`experiments/test_phase_8b.py`)

**Usage**:
```bash
# Run ALL 500 problems and save to JSON
python experiments/test_phase_8b.py --all

# Run with default settings (10 problems)
python experiments/test_phase_8b.py

# Test mode only (no MATH 500)
python experiments/test_phase_8b.py --test-mode
```

### 3. Concept Filtering (`_filter_concepts()`)

After LLM extraction, concepts are filtered to ensure quality:

| Filter | Description |
|--------|-------------|
| Non-ASCII removal | Removes Chinese, Vietnamese, and other non-ASCII characters |
| Length check | Removes concepts < 2 or > 50 characters |
| Deduplication | Case-insensitive duplicate removal |
| Max limit | Caps at 15 concepts per problem |

## Statistics

| Metric | Value |
|--------|-------|
| Total problems | 500 |
| Total concepts | 2,998 |
| Average concepts/problem | 6.00 |
| Problems in target range (4-8 concepts) | 453 (91%) |
| Empty concept lists (before fix) | 1 |
| Manual corrections | 1 |

### Concept Count Distribution

| Concepts | Problems |
|----------|----------|
| 0 | 0 (after fix) |
| 3 | 1 |
| 4 | 88 |
| 5 | 184 |
| 6 | 73 |
| 7 | 45 |
| 8 | 63 |
| 9 | 23 |
| 10 | 10 |
| 11 | 4 |
| 12 | 1 |
| 13 | 1 |
| 15 | 6 |

### Top 20 Concepts

| Rank | Concept | Frequency |
|------|---------|-----------|
| 1 | algebra | 314 |
| 2 | number theory | 182 |
| 3 | integer | 41 |
| 4 | combinatorics | 32 |
| 5 | calculus | 30 |
| 6 | algebraic manipulation | 29 |
| 7 | roots | 29 |
| 8 | geometry | 27 |
| 9 | square root | 26 |
| 10 | system of equations | 26 |
| 11 | quadratic equation | 26 |
| 12 | function | 25 |
| 13 | inequality | 24 |
| 14 | geometric properties | 23 |
| 15 | polynomial | 23 |
| 16 | rational function | 20 |
| 17 | divisibility | 20 |
| 18 | exponentiation | 20 |
| 19 | angle | 19 |
| 20 | simplification | 18 |

## Manual Corrections

### math_00393: Chinese Response Edge Case

**Problem**: The LLM responded entirely in Chinese for this physics/algebra problem.

**Original Problem**:
```
It's a well-known physics formula that force equals mass times acceleration.
Jen wants to throw a softball with the same force as Jack throws a baseball.
If the softball has a mass of $200$ g and the baseball has a mass of $150$ g,
what is the ratio of acceleration of Jen's ball to Jack's? Answer as a
fraction in lowest terms.
```

**LLM Raw Response** (Chinese):
```json
{"concepts": ["物理学公式", "力", "质量", "加速度", "比例", "分数"]}
```

Translation:
- 物理学公式 = physics formula
- 力 = force
- 质量 = mass
- 加速度 = acceleration
- 比例 = ratio
- 分数 = fraction

**Filter Result**: All 6 concepts were non-ASCII, so `_filter_concepts()` correctly removed them all, leaving an empty list.

**Manual Fix Applied**:
```json
"math_00393": {
  "level": 3,
  "type": "algebra",
  "concepts": [
    "physics formula",
    "force",
    "mass",
    "acceleration",
    "ratio",
    "fraction"
  ]
}
```

**Root Cause**: `qwen2-math:7b` occasionally responds in Chinese despite English prompts. This is a known behavior of multilingual models.

**Impact**: 1/500 = 0.2% of problems affected. Acceptable for a PoC.

**Prevention**: For production, consider:
1. Retry logic with explicit "respond in English" instruction
2. Translation fallback for detected non-ASCII responses
3. Alternative model with stronger English-only behavior

## File Format

```json
{
  "math_<ID>": {
    "level": <1-5>,
    "type": "<problem_type>",
    "concepts": ["<concept1>", "<concept2>", ...]
  }
}
```

**Problem Types**: algebra, prealgebra, intermediate_algebra, precalculus, geometry, number_theory, counting_and_probability

## Usage in Phase 8c

The concepts are used as queries for hybrid retrieval:

1. **BM25 Search**: Concepts are tokenized and matched against OpenMath Description Cards
2. **Dense Search**: Concepts are embedded using `qwen3-embedding:0.6b` and compared via cosine similarity
3. **RRF Fusion**: Results are combined using Reciprocal Rank Fusion

## Regeneration

To regenerate the concepts file:

```bash
# Run full extraction
python experiments/test_phase_8b.py --all

# Re-apply manual fix for math_00393
# (Currently done manually - could be scripted if more corrections needed)
```
