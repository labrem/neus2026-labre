#!/bin/bash
# Generic vLLM server startup script
# Supports both LLM inference (generate) and cross-encoder (pooling) modes
#
# Usage:
#   ./scripts/start_vllm_server.sh --model Qwen/Qwen3-Reranker-0.6B --runner pooling --port 9001
#   ./scripts/start_vllm_server.sh --model DeepSeekMath-7B-Instruct --port 9000
#
# Runner Types:
#   generate (default) - For LLMs, exposes /v1/chat/completions, /v1/completions
#   pooling            - For rerankers/embeddings, exposes /score, /rerank, /pooling

set -e

# Get script directory to find project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Load environment variables if .env exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Activate vLLM virtual environment
VLLM_VENV="$PROJECT_ROOT/.venv"
if [ -d "$VLLM_VENV" ]; then
    source "$VLLM_VENV/bin/activate"
else
    echo "Error: Virtual environment not found at $VLLM_VENV"
    echo "Create it first: python -m venv .venv && pip install vllm"
    exit 1
fi

# Default values
MODEL=""
RUNNER="generate"  # "generate" for LLMs, "pooling" for rerankers/embeddings
PORT="${VLLM_API_PORT:-9000}"
GPU_MEMORY="${VLLM_GPU_MEMORY_UTILIZATION:-0.5}"
HOST="0.0.0.0"
HF_OVERRIDES=""
DTYPE=""
MAX_MODEL_LEN=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --model|-m) MODEL="$2"; shift 2 ;;
        --runner|-r) RUNNER="$2"; shift 2 ;;
        --port|-p) PORT="$2"; shift 2 ;;
        --gpu-memory) GPU_MEMORY="$2"; shift 2 ;;
        --hf-overrides) HF_OVERRIDES="$2"; shift 2 ;;
        --dtype) DTYPE="$2"; shift 2 ;;
        --max-model-len) MAX_MODEL_LEN="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --model MODEL [OPTIONS]"
            echo ""
            echo "Required:"
            echo "  --model, -m       Model name or path (e.g., Qwen/Qwen3-Reranker-0.6B)"
            echo ""
            echo "Options:"
            echo "  --runner, -r      Runner type: 'generate' (LLMs) or 'pooling' (rerankers)"
            echo "                    Default: generate"
            echo "  --port, -p        Server port (default: 9000, or VLLM_API_PORT env)"
            echo "  --gpu-memory      GPU memory utilization 0.0-1.0 (default: 0.5)"
            echo "  --hf-overrides    JSON string for HuggingFace config overrides"
            echo "  --dtype           Data type (auto, float16, bfloat16, float32)"
            echo "  --max-model-len   Maximum model context length"
            echo ""
            echo "Examples:"
            echo "  # Start Qwen3-Reranker for cross-encoder scoring"
            echo "  $0 --model Qwen/Qwen3-Reranker-0.6B --runner pooling --port 9001"
            echo ""
            echo "  # Start DeepSeekMath for LLM inference"
            echo "  $0 --model deepseek-ai/DeepSeekMath-7B-Instruct --port 9000"
            exit 0 ;;
        *) echo "Unknown option: $1. Use --help for usage."; exit 1 ;;
    esac
done

# Validate model
if [ -z "$MODEL" ]; then
    echo "Error: --model is required"
    echo "Use --help for usage information"
    exit 1
fi

# Check if port is in use
if command -v lsof &> /dev/null && lsof -i :"$PORT" > /dev/null 2>&1; then
    echo "Error: Port $PORT is already in use"
    echo "Use --port to specify a different port"
    exit 1
fi

echo "========================================"
echo "Starting vLLM Server"
echo "========================================"
echo "  Environment: $VLLM_VENV"
echo "  Model:      $MODEL"
echo "  Runner:     $RUNNER"
echo "  Port:       $PORT"
echo "  GPU Memory: $GPU_MEMORY"
[ -n "$DTYPE" ] && echo "  Dtype:      $DTYPE"
[ -n "$MAX_MODEL_LEN" ] && echo "  Max Length: $MAX_MODEL_LEN"
[ -n "$HF_OVERRIDES" ] && echo "  HF Overrides: $HF_OVERRIDES"
echo "========================================"
echo ""

# Build command array using full path to vllm
VLLM_BIN="$VLLM_VENV/bin/vllm"
CMD=("$VLLM_BIN" serve "$MODEL")
CMD+=(--runner "$RUNNER")
CMD+=(--host "$HOST")
CMD+=(--port "$PORT")
CMD+=(--gpu-memory-utilization "$GPU_MEMORY")
CMD+=(--trust-remote-code)

# Add optional arguments
[ -n "$DTYPE" ] && CMD+=(--dtype "$DTYPE")
[ -n "$MAX_MODEL_LEN" ] && CMD+=(--max-model-len "$MAX_MODEL_LEN")
[ -n "$HF_OVERRIDES" ] && CMD+=(--hf-overrides "$HF_OVERRIDES")

# Execute
exec "${CMD[@]}"
