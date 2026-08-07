#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
vllm_bin="$repo_dir/.venv-vllm/bin/vllm"
model_id="nvidia/Qwen3.5-122B-A10B-NVFP4"
model_revision="98915d837c4e7c87ac8296d02e89de19b3207e6d"

if [[ ! -x "$vllm_bin" ]]; then
  echo "vLLM is not installed. Run scripts/bootstrap_local_llm.sh first." >&2
  exit 1
fi

export HF_HOME=${HF_HOME:-"$repo_dir/data/models/huggingface"}
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-0}
# The workstation has the NVIDIA driver/runtime but not the full CUDA toolkit.
# FlashInfer's sampler JITs an extension with nvcc on first boot; vLLM's native
# sampler avoids that unnecessary build dependency while the model kernels
# themselves still use Blackwell-optimised CUTLASS/FlashInfer implementations.
export VLLM_USE_FLASHINFER_SAMPLER=${VLLM_USE_FLASHINFER_SAMPLER:-0}

exec "$vllm_bin" serve "$model_id" \
  --revision "$model_revision" \
  --served-model-name "$model_id" \
  --host 127.0.0.1 \
  --port "${ALEPH_VLLM_PORT:-8001}" \
  --trust-remote-code \
  --quantization modelopt_fp4 \
  --kv-cache-dtype fp8 \
  --tensor-parallel-size 1 \
  --max-model-len "${ALEPH_VLLM_MAX_MODEL_LEN:-32768}" \
  --gpu-memory-utilization "${ALEPH_VLLM_GPU_MEMORY_UTILIZATION:-0.90}" \
  --enforce-eager \
  --attention-backend TRITON_ATTN \
  --reasoning-parser qwen3 \
  --language-model-only
