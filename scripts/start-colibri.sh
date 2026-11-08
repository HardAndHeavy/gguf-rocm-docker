#!/usr/bin/env bash
set -euo pipefail

# Explicit CLI arguments allow doctor/plan/vulkaninfo without starting the API.
if (($#)); then
    exec "$@"
fi

: "${COLIBRI_GGUF:?Set COLIBRI_GGUF to the filename of the first GGUF shard}"
[[ -f "/models/$COLIBRI_GGUF" ]] || {
    printf 'Missing GGUF: /models/%s\n' "$COLIBRI_GGUF" >&2
    exit 1
}

# Separate metadata/cache per model; GGUFs stay read-only and are never copied.
model="/state/${COLIBRI_GGUF%.gguf}.colibri"
import_args=(import "/models/$COLIBRI_GGUF" --out "$model" --mode link)
case "${COLIBRI_MTP:-}" in
    '')
        # Upstream auto-discovers a compatible mtp-*.gguf beside the model.
        ;;
    off|none|0)
        import_args+=(--no-mtp)
        ;;
    *)
        [[ -f "/models/$COLIBRI_MTP" ]] || {
            printf 'Missing MTP GGUF: /models/%s\n' "$COLIBRI_MTP" >&2
            exit 1
        }
        import_args+=(--mtp "/models/$COLIBRI_MTP")
        ;;
esac
python3 ./coli "${import_args[@]}"

serve_args=(
    serve --model "$model"
    --host 0.0.0.0
    --port "${COLIBRI_INTERNAL_PORT:-8080}"
    --ctx "${COLIBRI_CTX:-8192}"
    --ram "${COLIBRI_RAM:-48}"
)

# Optional upstream knobs stay absent unless explicitly requested. This keeps
# defaults aligned with the pinned Colibri revision instead of duplicating them.
for option in CAP VRAM KV_SLOTS POLICY MODEL_ID; do
    variable="COLIBRI_${option}"
    value="${!variable:-}"
    [[ -n "$value" ]] || continue
    flag="${option,,}"              # kv_slots / model_id
    flag="--${flag//_/-}"
    serve_args+=("$flag" "$value")
done

exec python3 ./coli "${serve_args[@]}"
