# Pinned source shared with the Vulkan build. Keep ROCm's compiler and runtime
# together: a host-built binary can require a newer glibc than the container.
ARG ROCM_IMAGE=llama-rocm:3.0.2
FROM debian:trixie-slim AS source
ARG COLIBRI_REF=0a5504a1dc64f86fcd0fe7db298b0448c730e7e6
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential libvulkan-dev glslc \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init . && git remote add origin https://github.com/JustVugg/colibri.git \
    && git fetch --depth 1 origin "${COLIBRI_REF}" && git checkout --detach FETCH_HEAD

# Reuse the sibling llama-rocm-docker build: it contains the complete ROCm
# compiler/runtime and rocWMMA, so Colibri does not need a second ROCm stack.
# Override ROCM_IMAGE to reproduce with another validated llama-rocm release.
FROM ${ROCM_IMAGE}
ARG HIP_ARCH=gfx1201
ARG COLIBRI_REF=0a5504a1dc64f86fcd0fe7db298b0448c730e7e6
LABEL org.opencontainers.image.title="gguf-rocm-colibri" \
      org.opencontainers.image.source="https://github.com/JustVugg/colibri" \
      ru.hardandheavy.colibri.revision="${COLIBRI_REF}"
COPY --from=source /src/c/ /app/c/
WORKDIR /app/c
RUN make -j4 colibri glm53 qwen36 qwen38 kimi_k3 ARCH=x86-64-v3 HIP=1 HIP_ARCH="${HIP_ARCH}" \
    && test -x ./colibri && test -x ./glm53 && test -x ./qwen36 && test -x ./qwen38 \
    && test -x ./kimi_k3
# Colibri's resource planner discovers Linux AMD GPUs through rocm-smi, not
# rocminfo. libdrm-dev supplies the unversioned dlopen name used by rocm-smi.
RUN apt-get update && apt-get install -y --no-install-recommends \
    rocm-smi libdrm-dev \
    && rm -rf /var/lib/apt/lists/*
COPY scripts/start-colibri.sh /usr/local/bin/start-colibri
ENV PYTHONUNBUFFERED=1
# A TCP probe stays responsive while the single engine is busy generating. The
# old HTTP probe timed out during valid requests and marked the container sick.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10m --retries=3 \
    CMD python3 -c "import socket; s=socket.create_connection(('127.0.0.1', 8080), 4); s.close()"
EXPOSE 8080
ENTRYPOINT ["bash", "/usr/local/bin/start-colibri"]
CMD []
