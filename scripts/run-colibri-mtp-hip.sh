#!/usr/bin/env bash
# Validate upstream Colibri PR #2559 on one AMD GPU. No source patches are applied.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

profile=${1:?usage: bash scripts/run-colibri-mtp-hip.sh off|cpu|gpu-conservative|gpu-full}
image=${COLIBRI_IMAGE:-gguf-rocm-colibri:mtp-dev-0a6f235b}
ref=${COLIBRI_REF:-0a6f235b0c7a20726e28e6e0229ef1201de74638}
model=Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf
mtp=mtp-Qwen3.8-Flash-Next-Q2_0.gguf
state=${COLIBRI_STATE_DIR:-./data/colibri-mtp-dev}
lookup=${COLI_LOOKUP:-1}
label_suffix=${LABEL_SUFFIX:-}
request_json=${BENCH_REQUEST_JSON:-'{"presence_penalty":0,"frequency_penalty":0,"chat_template_kwargs":{"enable_thinking":false}}'}

case "$profile" in
    off)
        colibri_mtp=off; q38_mtp=0; chain=1; card=1; pool=1 ;;
    cpu)
        colibri_mtp=$mtp; q38_mtp=1; chain=0; card=1; pool=1 ;;
    gpu-conservative)
        colibri_mtp=$mtp; q38_mtp=1; chain=1; card=0; pool=0 ;;
    gpu-full)
        colibri_mtp=$mtp; q38_mtp=1; chain=1; card=1; pool=1 ;;
    *) printf 'Unknown profile: %s\n' "$profile" >&2; exit 2 ;;
esac

[[ -f "data/models/$model" && -f "data/models/$mtp" ]] || {
    printf 'Qwen3.8 model or MTP GGUF is missing\n' >&2; exit 1;
}
actual_ref=$(docker image inspect --format '{{index .Config.Labels "ru.hardandheavy.colibri.revision"}}' "$image")
[[ "$actual_ref" == "$ref" ]] || {
    printf 'Image %s has Colibri ref %s, expected %s\n' "$image" "$actual_ref" "$ref" >&2
    exit 1
}

label=mtp-hip-$profile$label_suffix
mkdir -p data/benchmarks "$state"
cat >"data/benchmarks/$label-config.env" <<EOF
COLIBRI_IMAGE=$image
COLIBRI_REF=$ref
COLIBRI_GGUF=$model
COLIBRI_MTP=$colibri_mtp
COLIBRI_CTX=8192
COLIBRI_RAM=48
COLIBRI_STATE_DIR=$state
COLI_LOOKUP=$lookup
Q38_MTP=$q38_mtp
Q38_MTP_CHAIN=$chain
Q38_MTP_DRAFTS=0
COLI_CUDA_CHAIN_MTP_CARD=$card
COLI_CUDA_CHAIN_MTP_POOL=$pool
COLI_CUDA_GEMV_W4=${COLI_CUDA_GEMV_W4:-}
COLI_CUDA_GEMV_SK=${COLI_CUDA_GEMV_SK:-}
HIP_LAUNCH_BLOCKING=${HIP_LAUNCH_BLOCKING:-}
BENCH_REQUEST_JSON=$request_json
EOF

compose=(docker compose -p gguf-rocm -f compose.colibri.yaml)
"${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
cleanup() {
    docker logs --timestamps gguf-rocm-colibri-1 \
        >"data/benchmarks/$label-container.log" 2>&1 || true
    "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

COLIBRI_IMAGE=$image \
COLIBRI_STATE_DIR=$state \
COLIBRI_GGUF=$model \
COLIBRI_MTP=$colibri_mtp \
COLIBRI_CTX=8192 COLIBRI_RAM=48 COLI_LOOKUP=$lookup \
Q38_MTP=$q38_mtp Q38_MTP_CHAIN=$chain Q38_MTP_DRAFTS=0 \
COLI_CUDA_CHAIN_MTP_CARD=$card COLI_CUDA_CHAIN_MTP_POOL=$pool \
make run-colibri-api

python3 - "$profile" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from scripts.benchmark import parse_env_file

profile = sys.argv[1]
key = parse_env_file(Path('.env')).get('COLI_API_KEY', '')
request = urllib.request.Request(
    'http://127.0.0.1:8080/v1/models',
    headers={'Authorization': 'Bearer ' + key},
)
deadline = time.monotonic() + 900
last = None
while time.monotonic() < deadline:
    state = subprocess.run(
        ['docker', 'inspect', '--format', '{{.State.Running}} {{.State.ExitCode}}', 'gguf-rocm-colibri-1'],
        capture_output=True, text=True, check=False,
    )
    if state.returncode == 0 and not state.stdout.startswith('true '):
        raise RuntimeError(f'{profile}: container exited before API readiness ({state.stdout.strip()})')
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
        if payload.get('data'):
            print(f'{profile}: inference API is ready', flush=True)
            break
    except Exception as error:
        last = f'{type(error).__name__}: {error}'
    time.sleep(5)
else:
    raise RuntimeError(f'{profile}: API did not become ready: {last}')
PY

docker logs --timestamps gguf-rocm-colibri-1 >"data/benchmarks/$label-container.log" 2>&1
if [[ "$profile" == off ]] && ! grep -q 'MTP head: off' "data/benchmarks/$label-container.log"; then
    printf 'MTP-off profile did not confirm a disabled head\n' >&2; exit 1
fi
if [[ "$profile" =~ ^gpu- ]] && ! grep -q "MTP head's layer on device 0" "data/benchmarks/$label-container.log"; then
    printf 'Device MTP profile did not confirm its head on device 0\n' >&2; exit 1
fi

# Fixed prompts are for exact cross-profile output checks only, never throughput.
python3 scripts/benchmark.py \
    --backend "$label-correctness" --case short --case decode \
    --runs 1 --warmups 0 --max-tokens 192 --fixed-prompt --save-text \
    --request-json "$request_json" --api-key-env COLI_API_KEY \
    --output "data/benchmarks/$label-correctness.json"
if [[ "${ALLOW_REASONING:-0}" != 1 ]]; then
python3 - "$label" "data/benchmarks/$label-correctness.json" <<'PY'
import json
from pathlib import Path
import sys
label, output = sys.argv[1:]
report = json.loads(Path(output).read_text())
cases = {case['name']: case for case in report['cases']}
short = cases['short']['runs'][0]
decode = cases['decode']['runs'][0]
if short.get('finish_reason') != 'stop' or 'желез' not in (short.get('content') or '').casefold():
    raise RuntimeError(f'{label}: short response is not a completed usable answer')
if not (decode.get('content') or '').strip():
    raise RuntimeError(f'{label}: decode produced no visible content with thinking disabled')
PY
fi

if [[ "${CORRECTNESS_ONLY:-0}" == 1 ]]; then
    python3 scripts/capture-runtime.py gguf-rocm-colibri-1 \
        "data/benchmarks/$label-runtime.json"
    printf 'Finished correctness-only %s\n' "$label"
    exit 0
fi

python3 scripts/benchmark.py \
    --backend "$label" --case short --case decode --case prefill \
    --runs 3 --warmups 1 --max-tokens 192 --request-json "$request_json" \
    --api-key-env COLI_API_KEY \
    --output "data/benchmarks/$label.json"

# Full-task comparison is most useful for baseline and complete device head.
if [[ "${RUN_AGENT:-auto}" == 1 || ( "${RUN_AGENT:-auto}" == auto && "$profile" =~ ^(off|gpu-full)$ ) ]]; then
    python3 scripts/agent_benchmark.py \
        --backend "$label-agent" --case agent --case coder \
        --runs 3 --warmups 1 --max-turns 8 --max-tokens 768 --request-json "$request_json" \
        --api-key-env COLI_API_KEY \
        --output "data/benchmarks/$label-agent.json" || true
fi

python3 scripts/capture-runtime.py gguf-rocm-colibri-1 \
    "data/benchmarks/$label-runtime.json"
docker logs --timestamps gguf-rocm-colibri-1 \
    >"data/benchmarks/$label-container.log" 2>&1
printf 'Finished %s\n' "$profile"
