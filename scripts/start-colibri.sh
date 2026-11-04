#!/usr/bin/env bash
set -euo pipefail
# Explicit CLI arguments allow doctor/plan/vulkaninfo without starting the API.
if (($#)); then
    exec "$@"
fi
: "${COLIBRI_GGUF:?Set COLIBRI_GGUF to the first GGUF shard's filename}"
[[ -f "/models/$COLIBRI_GGUF" ]] || {
    printf 'Missing GGUF: /models/%s\n' "$COLIBRI_GGUF" >&2
    exit 1
}
# Separate metadata/cache per model; GGUFs stay read-only and are never copied.
model="/state/${COLIBRI_GGUF%.gguf}.colibri"
python3 ./coli import "/models/$COLIBRI_GGUF" --out "$model" --mode link
exec python3 ./coli serve --model "$model" --host 0.0.0.0 --port 8080 \
    --ctx "${COLIBRI_CTX:-8192}" --ram "${COLIBRI_RAM:-48}"
