#!/bin/bash
set -e

echo "=== OpenMath LLM Environment Setup (DGX Spark / GB10) ==="

# Project directories
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DGX_ENV_DIR="$PROJECT_ROOT/vllm_env"
INSTALLER_SCRIPT="$PROJECT_ROOT/.local/dgx-setup/install.sh"
VENV_LINK="$PROJECT_ROOT/.venv"

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "Error: uv is not installed. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Ensure DGX environment exists
if [ ! -d "$DGX_ENV_DIR/.vllm" ]; then
    echo "DGX vLLM environment not found. Running installer..."
    
    # Check if installer script exists
    if [ ! -f "$INSTALLER_SCRIPT" ]; then
        echo "Installer script not found. Cloning repo..."
        git clone https://github.com/eelbaz/dgx-spark-vllm-setup.git "$PROJECT_ROOT/.local/dgx-setup"
    fi
    
    chmod +x "$INSTALLER_SCRIPT"
    
    # Make installer non-interactive by piping yes
    # Use managed python 3.12.12 to ensure headers are available
    echo "Ensuring managed Python 3.12 is installed..."
    uv python install 3.12
    
    MANAGED_PYTHON_VERSION=$(uv python find 3.12 | head -n 1 | awk -F'python' '{print $2}' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')
    if [ -z "$MANAGED_PYTHON_VERSION" ]; then
        MANAGED_PYTHON_VERSION="3.12"
    fi
    
    echo "Running installer with Python $MANAGED_PYTHON_VERSION..."
    yes | "$INSTALLER_SCRIPT" --install-dir "$DGX_ENV_DIR" --python-version "$MANAGED_PYTHON_VERSION"
else
    echo "DGX vLLM environment found at $DGX_ENV_DIR"
fi

# Link .venv to the DGX environment
if [ -L "$VENV_LINK" ] || [ ! -e "$VENV_LINK" ]; then
    echo "Linking .venv to $DGX_ENV_DIR/.vllm"
    ln -sfn "$DGX_ENV_DIR/.vllm" "$VENV_LINK"
else
    echo "Warning: .venv exists and is not a symlink. Please remove it manually if you want to use the DGX environment."
    exit 1
fi

# Activate environment
source "$VENV_LINK/bin/activate"

# Install project dependencies
echo "Installing project dependencies..."
uv pip install transformers accelerate sympy datasets pandas numpy matplotlib seaborn pyyaml tqdm python-dotenv

# Install dev dependencies
echo "Installing dev dependencies..."
uv pip install pytest pytest-asyncio black ruff ipykernel jupyterlab

# Install current package in editable mode
echo "Installing project in editable mode..."
uv pip install --no-deps -e .

# Verify installation
echo "Verifying installation..."
python -c "import torch; print(f'PyTorch version: {torch.__version__}')"
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
if python -c "import torch; exit(0 if torch.cuda.is_available() else 1)"; then
    python -c "import torch; print(f'CUDA device: {torch.cuda.get_device_name(0)}')"
else
    echo "WARNING: CUDA not available!"
fi
python -c "import vllm; print(f'vLLM version: {vllm.__version__}')"
python -c "import sympy; print(f'SymPy version: {sympy.__version__}')"

echo "=== Setup Complete ==="
echo ""
echo "IMPORTANT: Before running inference, set these environment variables:"
echo "  export TORCH_CUDA_ARCH_LIST=\"12.1a\""
echo "  export LD_LIBRARY_PATH=\"/usr/local/cuda/lib64:\$LD_LIBRARY_PATH\""
echo "  export TRITON_PTXAS_PATH=/usr/local/cuda/bin/ptxas"
