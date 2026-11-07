# Pinned source shared with the Vulkan build. Keep ROCm's compiler and runtime
# together: a host-built binary can require a newer glibc than the container.
ARG ROCM_IMAGE=llama-rocm:3.0.0
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
COPY --from=source /src/c/ /app/c/
WORKDIR /app/c
RUN make -j4 colibri glm53 qwen36 qwen38 ARCH=x86-64-v3 HIP=1 HIP_ARCH="${HIP_ARCH}"
COPY scripts/start-colibri.sh /usr/local/bin/start-colibri
ENV PYTHONUNBUFFERED=1
# Do not inherit llama-server's healthcheck or entrypoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)" || exit 1
EXPOSE 8080
ENTRYPOINT ["bash", "/usr/local/bin/start-colibri"]
CMD []
