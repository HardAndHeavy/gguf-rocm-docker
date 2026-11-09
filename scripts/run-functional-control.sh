#!/usr/bin/env bash
# Run the functional agent/coder control on an existing local GGUF; never downloads.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

backend=${1:?usage: bash scripts/run-functional-control.sh colibri|llama MODEL.gguf LABEL}
model=${2:?model filename in data/models is required}
label=${3:?benchmark label is required}
[[ "$model" != */* && -f "data/models/$model" ]] || {
    printf 'Missing local model data/models/%s\n' "$model" >&2
    exit 1
}
[[ "$label" =~ ^[A-Za-z0-9._-]+$ ]] || { printf 'Unsafe label: %s\n' "$label" >&2; exit 2; }
context=${CONTROL_CTX:-8192}
request_json='{"presence_penalty":0,"frequency_penalty":0,"chat_template_kwargs":{"enable_thinking":false}}'
mkdir -p data/benchmarks

case "$backend" in
    colibri) key=COLI_API_KEY; container=gguf-rocm-colibri-1 ;;
    llama) key=LLAMA_API_KEY; container=gguf-rocm-llama-cpp-1 ;;
    *) printf 'Unknown backend: %s\n' "$backend" >&2; exit 2 ;;
esac
for service in colibri strata llama; do
    docker compose -p gguf-rocm -f "compose.$service.yaml" down --remove-orphans >/dev/null 2>&1 || true
done
python3 scripts/openwebui-bench.py down >/dev/null 2>&1 || true
compose=(docker compose -p gguf-rocm -f "compose.$backend.yaml")
cleanup() {
    docker logs --timestamps "$container" >"data/benchmarks/$label-container.log" 2>&1 || true
    "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

cat >"data/benchmarks/$label-config.env" <<EOF
CONTROL_BACKEND=$backend
CONTROL_MODEL=$model
CONTROL_CTX=$context
COLI_LOOKUP=0
BENCH_REQUEST_JSON=$request_json
EOF
if [[ "$backend" == colibri ]]; then
    COLIBRI_GGUF=$model COLIBRI_CTX=$context COLIBRI_RAM=48 \
    COLIBRI_MTP=off COLI_LOOKUP=0 Q36_MTP=0 Q38_MTP=0 \
        make run-colibri-api
else
    LLAMA_GGUF=$model LLAMA_MODEL_ID=$label LLAMA_CTX=$context \
    LLAMA_N_GPU_LAYERS=-1 LLAMA_THREADS=8 LLAMA_FLASH_ATTN=on \
    LLAMA_SPEC_TYPE=none \
        make run-llama-api
fi

python3 - "$backend" "$key" "$container" <<'PY'
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from scripts.benchmark import parse_env_file

backend, key_name, container = sys.argv[1:]
key = parse_env_file(Path('.env')).get(key_name, '')
request = urllib.request.Request(
    'http://127.0.0.1:8080/v1/models', headers={'Authorization': 'Bearer ' + key},
)
deadline = time.monotonic() + 900
last = None
while time.monotonic() < deadline:
    state = subprocess.run(
        ['docker', 'inspect', '--format', '{{.State.Running}} {{.State.ExitCode}}', container],
        capture_output=True, text=True, check=False,
    )
    if state.returncode == 0 and not state.stdout.startswith('true '):
        raise RuntimeError(f'{backend}: container exited before API readiness ({state.stdout.strip()})')
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.load(response)
        if payload.get('data'):
            print(f'{backend}: inference API is ready', flush=True)
            break
    except Exception as error:
        last = f'{type(error).__name__}: {error}'
    time.sleep(5)
else:
    raise RuntimeError(f'{backend}: API did not become ready: {last}')
PY

set +e
python3 scripts/agent_benchmark.py \
    --backend "$label-agent" --case agent --case coder \
    --runs 3 --warmups 1 --max-turns 8 --max-tokens 768 --request-json "$request_json" \
    --api-key-env "$key" --output "data/benchmarks/$label-agent.json"
rc=$?
set -e
python3 scripts/capture-runtime.py "$container" "data/benchmarks/$label-runtime.json"
docker logs --timestamps "$container" >"data/benchmarks/$label-container.log" 2>&1
printf 'Finished %s (functional rc=%s)\n' "$label" "$rc"
exit "$rc"
