#!/usr/bin/env bash
# Run one comparable Qwen3.6 profile; never downloads a model or another image.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

profile=${1:?usage: bash scripts/run-qwen36-backend.sh llama-off|llama-mtp|strata-off|strata-mtp|colibri-off|colibri-mtp}
model=Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf
[[ -f "data/models/$model" ]] || {
    printf 'Missing verified model data/models/%s; run make model-qwen36 first\n' "$model" >&2
    exit 1
}
case "$profile" in
    llama-off|llama-mtp) backend=llama; key=LLAMA_API_KEY; container=gguf-rocm-llama-cpp-1 ;;
    strata-off|strata-mtp) backend=strata; key=STRATA_API_KEY; container=gguf-rocm-strata-1 ;;
    colibri-off|colibri-mtp) backend=colibri; key=COLI_API_KEY; container=gguf-rocm-colibri-1 ;;
    *) printf 'Unknown profile: %s\n' "$profile" >&2; exit 2 ;;
esac
label=qwen36-$profile${LABEL_SUFFIX:-}
# Cross-backend greedy means no provider-default penalties. Empty thinking makes
# short/coding outputs observable within the same budget; generation remains greedy.
request_json='{"presence_penalty":0,"frequency_penalty":0,"chat_template_kwargs":{"enable_thinking":false}}'
mkdir -p data/benchmarks

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

case "$profile" in
    llama-off|llama-mtp)
        spec=none; [[ "$profile" == llama-mtp ]] && spec=draft-mtp
        cat >"data/benchmarks/$label-config.env" <<EOF
LLAMA_GGUF=$model
LLAMA_MODEL_ID=qwen36-llama
LLAMA_CTX=32768
LLAMA_N_GPU_LAYERS=-1
LLAMA_THREADS=8
LLAMA_FLASH_ATTN=on
LLAMA_SPEC_TYPE=$spec
LLAMA_SPEC_DRAFT_N_MAX=3
BENCH_REQUEST_JSON=$request_json
EOF
        LLAMA_GGUF=$model LLAMA_MODEL_ID=qwen36-llama LLAMA_CTX=32768 \
        LLAMA_N_GPU_LAYERS=-1 LLAMA_THREADS=8 LLAMA_FLASH_ATTN=on \
        LLAMA_SPEC_TYPE=$spec LLAMA_SPEC_DRAFT_N_MAX=3 \
            make run-llama-api
        ;;
    strata-off|strata-mtp)
        # `strata launch --mtp off` is different from advanced `--set mtp=...`.
        # Engine 0.1.55 loads Qwen3.6's head with --mtp 2 but, in serve mode,
        # drafts only with batch > 1 and STRATA_BATCH_MTP=1 (upstream #3009).
        # Use the supported parallel setting to create --batch 2. An advanced
        # batch=2 setting conflicts with every launch/profile parallel override.
        # --spec is deliberately absent: the qwen35 engine ignores that flag.
        if [[ "$profile" == strata-off ]]; then
            strata_mtp=off; drafting=off; strata_set=""; batch_mtp=0; strata_parallel=1
        else
            strata_mtp=on; drafting=mtp; strata_set=""; batch_mtp=1; strata_parallel=2
        fi
        cat >"data/benchmarks/$label-config.env" <<EOF
STRATA_FAMILY=qwen36
STRATA_MODEL=ud-q4_k_xl
STRATA_MODEL_PATH=/models/$model
STRATA_CONTEXT=32k
STRATA_PARALLEL=$strata_parallel
STRATA_VISION=off
STRATA_TUNE=skip
STRATA_MTP=$strata_mtp
STRATA_DRAFTING=$drafting
STRATA_SET=$strata_set
STRATA_BATCH_MTP=$batch_mtp
PRESET=$label
BENCH_REQUEST_JSON=$request_json
EOF
        STRATA_FAMILY=qwen36 STRATA_MODEL=ud-q4_k_xl \
        STRATA_MODEL_PATH=/models/$model STRATA_CONTEXT=32k \
        STRATA_PARALLEL=$strata_parallel STRATA_VISION=off STRATA_TUNE=skip \
        STRATA_MTP=$strata_mtp STRATA_DRAFTING=$drafting \
        STRATA_SET="$strata_set" STRATA_BATCH_MTP=$batch_mtp \
        PRESET=$label make run-strata-api
        ;;
    colibri-off|colibri-mtp)
        mtp=0; [[ "$profile" == colibri-mtp ]] && mtp=1
        cat >"data/benchmarks/$label-config.env" <<EOF
COLIBRI_GGUF=$model
COLIBRI_CTX=32768
COLIBRI_RAM=48
COLIBRI_MTP=off
COLI_LOOKUP=0
Q36_MTP=$mtp
Q36_MTP_DRAFTS=1
COLIBRI_STATE_DIR=./data/colibri
BENCH_REQUEST_JSON=$request_json
EOF
        COLIBRI_GGUF=$model COLIBRI_CTX=32768 COLIBRI_RAM=48 \
        COLIBRI_MTP=off COLI_LOOKUP=0 Q36_MTP=$mtp Q36_MTP_DRAFTS=1 \
            make run-colibri-api
        ;;
esac

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
    'http://127.0.0.1:8080/v1/models',
    headers={'Authorization': 'Bearer ' + key},
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

# Refuse silent fallback before recording an MTP profile as a real measurement.
docker logs --timestamps "$container" >"data/benchmarks/$label-container.log" 2>&1
if [[ "$profile" == colibri-mtp ]] && \
   grep -q 'Q36_MTP=1: the head stays off' "data/benchmarks/$label-container.log"; then
    printf 'Unsupported: this GGUF exposes blk.40.nextn.*, not the mtp.* head Colibri loads\n' \
        | tee "data/benchmarks/$label-unsupported.txt" >&2
    exit 4
fi
engine_log="data/strata/state/strata/launch/$label.engine.log"
if [[ "$backend" == strata ]]; then
    [[ -r "$engine_log" ]] || { printf 'Missing Strata engine log: %s\n' "$engine_log" >&2; exit 1; }
    cp "$engine_log" "data/benchmarks/$label-engine.log"
    if [[ "$profile" == strata-off ]] && grep -m1 'engine started:' "$engine_log" | grep -q -- '--mtp'; then
        printf 'Strata off profile still launches MTP\n' >&2; exit 1
    fi
    if [[ "$profile" == strata-mtp ]] && ! grep -m1 'engine started:' "$engine_log" | grep -q -- '--batch 2'; then
        printf 'Strata MTP profile lacks --batch 2\n' >&2; exit 1
    fi
fi

# Same-prompt outputs support correctness checks; unique prompts below are for speed.
python3 scripts/benchmark.py \
    --backend "$label-correctness" --case short --case decode \
    --runs 1 --warmups 0 --max-tokens 192 --fixed-prompt --save-text \
    --request-json "$request_json" \
    --api-key-env "$key" --output "data/benchmarks/$label-correctness.json"

python3 - "$label" "data/benchmarks/$label-correctness.json" <<'PY'
import json
import re
from pathlib import Path
import sys

label, output = sys.argv[1:]
report = json.loads(Path(output).read_text())
cases = {case["name"]: case for case in report["cases"]}
short = cases["short"]["runs"][0]
decode = cases["decode"]["runs"][0]
if short.get("finish_reason") != "stop" or "желез" not in (short.get("content") or "").casefold():
    raise RuntimeError(f"{label}: short response is not a completed usable answer: {short!r}")
if not (decode.get("content") or "").strip():
    raise RuntimeError(f"{label}: decode produced no visible content with thinking disabled")
if label.startswith("qwen36-strata-mtp"):
    text = Path(f"data/strata/state/strata/launch/{label}.engine.log").read_text()
    offered = sum(int(n) for n in re.findall(r"drafts accepted \d+ of (\d+)", text))
    if not offered:
        raise RuntimeError(f"{label}: MTP is inert (0 draft tokens offered)")
PY
if [[ "$profile" == llama-mtp ]]; then
    docker logs --timestamps "$container" >"data/benchmarks/$label-container.log" 2>&1
    if ! grep -Eq 'draft acceptance.*\([[:space:]]*[1-9][0-9]* accepted' "data/benchmarks/$label-container.log"; then
        printf 'llama.cpp MTP produced no accepted drafts in correctness run\n' >&2; exit 1
    fi
fi

python3 scripts/benchmark.py \
    --backend "$label" --case short --case decode --case prefill \
    --runs 3 --warmups 1 --max-tokens 192 --request-json "$request_json" \
    --api-key-env "$key" --output "data/benchmarks/$label.json"
python3 scripts/agent_benchmark.py \
    --backend "$label-agent" --case agent --case coder \
    --runs 3 --warmups 1 --max-turns 8 --max-tokens 768 --request-json "$request_json" \
    --api-key-env "$key" --output "data/benchmarks/$label-agent.json" || true

python3 scripts/capture-runtime.py "$container" "data/benchmarks/$label-runtime.json"
docker logs --timestamps "$container" >"data/benchmarks/$label-container.log" 2>&1
if [[ "$backend" == strata ]]; then
    cp "$engine_log" "data/benchmarks/$label-engine.log"
fi
printf 'Finished %s\n' "$profile"
