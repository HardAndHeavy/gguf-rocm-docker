#!/usr/bin/env bash
# Narrow offline standalone diagnostic. Does not modify /app/c or the image.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
OUT="$ROOT/data/colibri-investigation"
IMAGE=gguf-rocm-colibri:mtp-dev-0a6f235b
mkdir -p "$OUT"
docker image inspect "$IMAGE" > "$OUT/image-inspect.json"
ID=$(docker image inspect "$IMAGE" --format '{{.Id}}')
[[ "$ID" == sha256:e888c06f9db6a2d55997c43f2b0bd45c0face5d3ff428eba2b8a19dc65a299cc ]] || {
  printf 'Unexpected image ID: %s\n' "$ID" >&2; exit 1;
}
# Pin all containers to the inspected image ID, even if its tag changes.
COMMON=(--rm --pull never --network none --device /dev/kfd --device /dev/dri --group-add "$(stat -c %g /dev/kfd)" --group-add "$(stat -c %g /dev/dri/renderD128)")
docker run "${COMMON[@]}" -v "$ROOT/tests/colibri_gemv_cpu_reference.cu:/harness.cu:ro" -v "$ROOT/scripts/instrument-colibri-gemv.py:/instrument-dispatch.py:ro" -v "$OUT:/out" "$ID" bash -lc '
set -euxo pipefail
hipcc --version
rocminfo | grep -E "Name:|Marketing Name:|Wavefront Size:|Compute Unit:" || true
sha256sum /app/c/backend_cuda.cu /app/c/backend_gpu_compat.h
mkdir /tmp/colibri-gemv
cp -a /app/c/. /tmp/colibri-gemv/
cd /tmp/colibri-gemv
python3 /instrument-dispatch.py backend_cuda.cu
cp backend_cuda.cu /out/backend_cuda.instrumented.cu
cp /harness.cu harness.cu
# Same rocWMMA-enabled backend as production on gfx1201; only optimize level differs.
time hipcc --rocm-path=/opt/rocm/core-10.1 --rocm-device-lib-path=/opt/rocm/core-10.1/lib/llvm/amdgcn/bitcode -O2 -std=c++17 -x hip --offload-arch=gfx1201 -I. harness.cu -L/opt/rocm/core-10.1/lib -Wl,-rpath,/opt/rocm/core-10.1/lib -lamdhip64 -o /out/colibri_gemv_cpu_reference
sha256sum /out/colibri_gemv_cpu_reference /out/backend_cuda.instrumented.cu
' 2>&1 | tee "$OUT/build.log"
status=0
: > "$OUT/run-status.log"
for sk in 1 0; do
  # Separate processes: production dispatch caches its environment switches.
  set +e
  timeout 90s docker run "${COMMON[@]}" -e COLI_CUDA_GEMV_SK="$sk" -e COLI_CUDA_GEMV_W4=1 -v "$OUT:/out:ro" "$ID" /out/colibri_gemv_cpu_reference > "$OUT/run-sk${sk}.log" 2>&1
  rc=$?
  set -e
  printf 'SK=%s exit=%s\n' "$sk" "$rc" | tee -a "$OUT/run-status.log"
  if ((rc!=0)); then status=1; fi
done
exit "$status"
