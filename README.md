# OpenMath: Ontology-Guided Neuro-Symbolic Inference

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

This repository contains the implementation of the paper **"Ontology-Guided Neuro-Symbolic Inference: Grounding Language Models with Mathematical Domain Knowledge"**, submitted to the International Conference on Neuro-Symbolic Systems 2026 ([NeuS 2026](https://sites.google.com/usc.edu/neus2026/home)).

## Overview

Language models exhibit fundamental limitations—hallucination, brittleness, and lack of formal grounding—that are particularly problematic in high-stakes domains. This project investigates whether formal domain ontologies can enhance language model reliability through retrieval-augmented generation.

Using mathematics as a proof of concept, we implement a neuro-symbolic pipeline leveraging the **OpenMath ontology** with hybrid retrieval and cross-encoder reranking to inject relevant definitions into model prompts. Evaluation on the MATH 500 benchmark with three open-source models reveals that ontology-guided context improves performance when retrieval quality is high, but irrelevant context actively degrades it.

## Quick Start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.ai/) installed and running
- [vLLM](https://github.com/vllm-project/vllm) (for reranker)
- ~20GB disk space for models and data

### Setup

```bash
# Clone with OpenMath submodule
git clone --recurse-submodules https://github.com/labrem/neus2026-labre.git
cd neus2026-labre

# Add OpenMath submodule (if not cloned with --recurse-submodules)
git submodule add https://github.com/OpenMath/CDs.git openmath-cds

# Copy environment template and configure
cp .env.template .env
# Edit .env to set PROJECT_ROOT, MODELS_DIR, etc.

# Download Qwen3-Reranker-0.6B model from Hugging Face to a local directory
huggingface-cli download Qwen/Qwen3-Reranker-0.6B \
    --local-dir ~/.models/Qwen3-Reranker-0.6B

# Create a symbolic link to the models directory from within the project
ln -sfn ~/.models ./.models
```

#### Standard Installation (x86_64 / CUDA)

For most systems with standard NVIDIA GPUs:

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .
```

#### DGX Spark / GB10 Installation (ARM64 Blackwell)

For NVIDIA DGX Spark or Dell Pro Max GB10 systems, use the automated setup script which compiles vLLM from source and creates `.venv` as a symlink to the compiled environment:

```bash
# Requires uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# Run automated setup (creates .venv symlink, compiles vLLM, installs deps)
./setup.sh
source .venv/bin/activate
```

See [vLLM Installation](#vllm-installation) below for details on the compilation process.

#### Ollama API Installation

```bash
# Enable Ollama API over Docker: docker-compose.yml
services:
  # Service 1: The Backend (Ollama with GPU)
  ollama-models:
    image: ollama/ollama:latest
    container_name: ollama-models
    restart: unless-stopped
    shm_size: '16gb' # OPTIMIZATION: Faster processing (CPU <-> GPU communication)
    ulimits: # OPTIMIZATION: Prevent swapping to disk during generation
      memlock: -1
      stack: 67108864
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    ports:
      - "127.0.0.1:11434:11434"
    volumes:
      - /home/marcelo/.ollama:/root/.ollama
    environment:
      - OLLAMA_NUM_PARALLEL=4
      - OLLAMA_MAX_LOADED_MODELS=3
      - OLLAMA_KEEP_ALIVE=24h

# Start Ollama API over Docker, from directory where docker-compose.yml is located
docker compose up -d

# Stop Ollama API over Docker
docker compose down
```

#### Pull Required Models

```bash
# Embedding model for retrieval embedding
docker exec -it ollama-models ollama pull qwen3-embedding:4b

# MATH 500 concept extraction model
docker exec -it ollama-models ollama pull qwen2-math:7b

# Inference models (choose one or more)
docker exec -it ollama-models ollama pull gemma2:2b
docker exec -it ollama-models ollama pull gemma2:9b
docker exec -it ollama-models ollama pull johnnyboy/qwen2.5-math-7b:latest

# List available models
docker exec -it ollama-models ollama list

NAME                                         ID              SIZE      MODIFIED
johnnyboy/qwen2.5-math-7b:latest             c8121d6a2d5e    4.7 GB    11 days ago
qwen2-math:7b                                28cc3a337734    4.4 GB    12 days ago
gemma2:2b                                    8ccf136fdd52    1.6 GB    13 days ago
qwen3-embedding:4b                           df5bd2e3c74c    2.5 GB    2 weeks ago
gemma2:9b                                    ff02c3702f32    5.4 GB    6 weeks ago
```

### vLLM Installation

vLLM is required for Phase 4 (Cross-Encoder Reranking).

**Standard Installation (x86_64):** Install via pip after creating your virtual environment:

```bash
pip install vllm
```

**DGX Spark / GB10 (ARM64 Blackwell):** vLLM is compiled from source by `./setup.sh` (see [Installation](#installation) above). The script creates `.venv` as a symlink to the compiled environment.

**Environment Variables** (required for Blackwell GPUs):

```bash
export TORCH_CUDA_ARCH_LIST="12.1a"
export LD_LIBRARY_PATH="/usr/local/cuda/lib64:$LD_LIBRARY_PATH"
export TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas
```

**Compiled Environment (GB10):**

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.12.12 | Managed by `uv` |
| PyTorch | 2.10.0+cu130 | CUDA 13.0 Build |
| vLLM | 0.11.1rc4 | Custom source build |
| Transformers | 4.57.6 | Compatible with vLLM 0.11 |

#### Starting the vLLM Server

For Phase 4 reranking, start the vLLM server with the Qwen3-Reranker model:

```bash
./scripts/start_vllm_server.sh \
    --model Qwen/Qwen3-Reranker-0.6B \
    --runner pooling \
    --port 9001 \
    --hf-overrides '{"architectures":["Qwen3ForSequenceClassification"],"classifier_from_token":["no","yes"],"is_original_qwen3_reranker":true}'
```

**Server Options:**

| Option | Description | Default |
|--------|-------------|---------|
| `--model` | Model name or HuggingFace path | (required) |
| `--runner` | `generate` for LLMs, `pooling` for rerankers | `generate` |
| `--port` | Server port | 9000 |
| `--gpu-memory` | GPU memory utilization (0.0-1.0) | 0.5 |

## Pipeline Overview

The system implements a 7-phase pipeline for ontology-guided inference:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 1: Knowledge Base Normalization/Embeddings                           │
│  Parse OpenMath CDs → Normalize expressions to LaTeX → data/openmath.json   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 2: Concept Extraction/Embeddings                                     │
│  MATH problems → LLM extracts concepts → data/math500-concepts.json         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 3: Hybrid Retrieval (BM25 + Dense)                                   │
│  Concepts → RRF fusion → Top-50 candidates → data/openmath-retrieved.json   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 4: Cross-Encoder Reranking                                           │
│  Problem + symbols → Relevance scoring → data/openmath-reranked.json        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 5: Experiment Execution                                              │
│  Baseline vs OpenMath conditions → results/*.md                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 6: Results Extraction                                                │
│  Parse experiment files → CSV with metrics → results/*.csv                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 7: Visualization                                                     │
│  Generate publication figures → plots/*.png, plots/*.csv                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Running the Full Pipeline

### Phase 1: Knowledge Base Construction & Normalization

Parses OpenMath Content Dictionaries, normalizes mathematical expressions to LaTeX format, and generates embeddings.

```bash
# Step 1a: Build initial knowledge base from OpenMath CDs
python pipeline/1a_build_knowledge_base.py --experimental

# Step 1b: Normalize expressions to LaTeX format
python pipeline/1b_normalize_knowledge_base.py

# Step 1c: Generate knowledge base embeddings
python pipeline/1c_generate_knowledge_base_embeddings.py
```

**Output:**
- `data/openmath.json` (normalized knowledge base with 1,138 symbols)
- `data/openmath-embeddings_qwen3-embedding_4b.npy` (symbol embeddings)

> **Note:** Pre-built data files are included in `data/`. Skip this phase if using provided data.

### Phase 2: Concept Extraction

Extracts mathematical concepts from MATH 500 problems using an LLM and generates embeddings.

```bash
# Step 2a: Extract concepts from all 500 problems
python pipeline/2a_concept_extraction.py --all

# Step 2b: Generate concept embeddings
python pipeline/2b_generate_concept_embeddings.py
```

**Output:**
- `data/math500-concepts.json` (concepts for each problem)
- `data/math500-concepts-embeddings_qwen3-embedding_4b.npy` (concept embeddings)

### Phase 3: Hybrid Retrieval

Combines BM25 (lexical) and dense embedding retrieval using Reciprocal Rank Fusion.

```bash
# Retrieve top-50 candidates per problem
python pipeline/3_hybrid_retrieval.py --all
```

**Output:** `data/openmath-retrieved.json` (top-50 candidates per problem)

### Phase 4: Cross-Encoder Reranking

Scores problem-symbol pairs using a cross-encoder to filter irrelevant symbols.

```bash
# Start vLLM reranker server
./scripts/start_vllm_server.sh --model Qwen/Qwen3-Reranker-0.6B --runner pooling --port 9001 \
  --hf-overrides '{"architectures":["Qwen3ForSequenceClassification"],"classifier_from_token":["no","yes"],"is_original_qwen3_reranker":true}'

# Run reranking on all problems
python pipeline/4_cross_encoder_reranking.py --all --backend vllm
```

**Output:** `data/openmath-reranked.json` (filtered symbols with relevance scores)

### Phase 5: Experiment Execution

Runs comparative experiments with baseline and OpenMath conditions.

```bash
# Single experiment
python pipeline/5_run_experiment.py \
    --model "gemma2:9b" \
    --condition openmath \
    --mode greedy \
    --threshold 0.3 \
    --n-problems 500

# Batch experiments (uses YAML config)
python pipeline/5_run_experiments_batch.py --config configs/experiments/experiments_batch.yaml
```

**Configuration:** `configs/experiments/experiments_batch.yaml`

**Output:** `results/*.md` (detailed per-problem results)

### Phase 6: Results Extraction

Extracts structured metrics from experiment results.

```bash
python pipeline/6_extract_results.py \
    --config configs/results/extract_results.yaml \\
    --output results/my_results.csv
```

**Output:** `results/my_results.csv`

### Phase 7: Visualization

Generates publication-quality figures.

```bash
# Line + bubble plots (accuracy delta and attempts ratio)
python pipeline/7a_plot_lines_bubbles_batch.py

# Heatmaps (by level and problem type)
python pipeline/7b_plot_heatmaps.py
```

**Output:** `plots/*.png` and `plots/*.pdf`

## Project Structure

```
openmath/
├── pipeline/                      # Pipeline execution scripts
│   ├── 1a_build_knowledge_base.py
│   ├── 1b_normalize_knowledge_base.py
│   ├── 1c_generate_knowledge_base_embeddings.py
│   ├── 2a_concept_extraction.py
│   ├── 2b_generate_concept_embeddings.py
│   ├── 3_hybrid_retrieval.py
│   ├── 4_cross_encoder_reranking.py
│   ├── 5_run_experiment.py
│   ├── 5_run_experiments_batch.py
│   ├── 6_extract_results.py
│   ├── 7a_plot_lines_bubbles.py
│   ├── 7a_plot_lines_bubbles_batch.py
│   └── 7b_plot_heatmaps.py
│
├── src/                           # Core source modules
│   ├── benchmark_loader.py        # MATH benchmark loading
│   ├── openmath_parser.py         # OpenMath CD parsing
│   ├── openmath_normalizer.py     # LaTeX normalization
│   ├── sympy_mapper.py            # OpenMath → SymPy mapping
│   ├── query_parser.py            # Concept extraction
│   ├── bm25_retriever.py          # Lexical retrieval
│   ├── hybrid_retriever.py        # BM25 + Dense + RRF
│   ├── reranker_cross_encoder.py  # Cross-encoder reranking
│   ├── prompt_builder.py          # Prompt composition
│   ├── code_extractor.py          # Answer extraction
│   ├── comparator.py              # Answer comparison
│   ├── executor.py                # Sandboxed code execution
│   ├── experiment_runner.py       # Pipeline orchestration
│   ├── results_storage.py         # Results persistence
│   └── metrics.py                 # Evaluation metrics
│
├── scripts/                       # Infrastructure scripts
│   └── start_vllm_server.sh       # vLLM server startup
│
├── configs/                       # YAML configurations
│   ├── experiments/               # Experiment batch configs
│   ├── plots/                     # Plot configurations
│   └── results/                   # Results extraction configs
│
├── data/
│   ├── openmath.json              # Normalized OpenMath KB (1.5 MB)
│   ├── math500-concepts.json      # Extracted concepts (110 KB)
│   ├── openmath-retrieved.json    # Retrieval candidates (14 MB)
│   ├── openmath-reranked.json     # Reranked symbols (992 KB)
│   ├── openmath-embeddings_*.npy  # Symbol embeddings (11 MB)
│   └── math500-concepts-embeddings_*.npy  # Concept embeddings (4.9 MB)
│
├── prompts/
│   └── templates.yaml             # Prompt templates for conditions
│
├── results/                       # Experiment outputs
├── plots/                         # Generated figures
├── latex/                         # Paper LaTeX source
├── tests/                         # Unit tests
├── openmath-cds/                  # OpenMath Content Dictionaries (submodule)
├── pyproject.toml                 # Python dependencies
└── README.md                      # This file
```

## Data Files

| File | Size | Description |
|------|------|-------------|
| `openmath.json` | 1.5 MB | Normalized OpenMath KB (1,138 symbols, 161 CDs) |
| `math500-concepts.json` | 110 KB | Concepts extracted from MATH 500 problems |
| `openmath-retrieved.json` | 14 MB | Top-50 retrieval candidates per problem |
| `openmath-reranked.json` | 992 KB | Filtered symbols with reranker scores |
| `openmath-embeddings_*.npy` | 11 MB | Dense embeddings for OpenMath symbols |
| `math500-concepts-embeddings_*.npy` | 4.9 MB | Dense embeddings for problem concepts |

## Testing

```bash
# Run all unit tests
python -m pytest tests/ -v --ignore=tests/test_inference.py

# Run specific test module
python -m pytest tests/test_hybrid_retriever.py -v
```

## Models Required

| Service | Model | Purpose |
|---------|-------|---------|
| Ollama | `qwen2-math:7b` | Concept extraction, KB normalization |
| Ollama | `qwen3-embedding:4b` | Dense embeddings |
| Ollama | `gemma2:2b`, `gemma2:9b` | Inference (general-purpose) |
| Ollama | `johnnyboy/qwen2.5-math-7b` | Inference (math-specialized) |
| vLLM | `Qwen/Qwen3-Reranker-0.6B` | Cross-encoder reranking |

## Citation

If you use this code or findings in your research, please cite:

```bibtex
@inproceedings{labre2026ontology,
  title={Ontology-Guided Neuro-Symbolic Inference: Grounding Language Models with Mathematical Domain Knowledge},
  author={Labre, Marcelo},
  booktitle={Proceedings of NeuS 2026},
  year={2026}
}
```

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [OpenMath](https://openmath.org/) for the mathematical ontology
- [MATH Benchmark](https://github.com/hendrycks/math) for the evaluation dataset
- Dell Computers for hardware support (Dell Pro Max GB10)
