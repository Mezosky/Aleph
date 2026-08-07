#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
venv_dir="$repo_dir/.venv-vllm"
python_bin=${ALEPH_VLLM_PYTHON:-python3}

if [[ ! -x "$venv_dir/bin/python" ]]; then
  "$python_bin" -m venv "$venv_dir"
fi

"$venv_dir/bin/python" -m pip install --upgrade pip
"$venv_dir/bin/python" -m pip install "vllm==0.26.0"

echo "vLLM is installed in $venv_dir"
echo "Start the pinned model with: scripts/serve_local_llm.sh"

