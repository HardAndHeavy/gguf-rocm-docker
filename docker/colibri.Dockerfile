# Pinned upstream; the stock slim image builds only the GLM CPU engine.
FROM debian:trixie-slim AS build
ARG COLIBRI_REF=0a5504a1dc64f86fcd0fe7db298b0448c730e7e6
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git build-essential libvulkan-dev glslc \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init . && git remote add origin https://github.com/JustVugg/colibri.git \
    && git fetch --depth 1 origin "${COLIBRI_REF}" && git checkout --detach FETCH_HEAD
# Zen 2 supports x86-64-v3. Do not bake the build host's native ISA into the image.
RUN make -C c -j2 colibri glm53 qwen36 qwen38 ARCH=x86-64-v3 VK=1

FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 libgomp1 libvulkan1 mesa-vulkan-drivers ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app/c
# Keep Python helpers, engine binaries and shaders together as upstream expects.
COPY --from=build /src/c/ /app/c/
COPY scripts/start-colibri.sh /usr/local/bin/start-colibri
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
ENTRYPOINT ["bash", "/usr/local/bin/start-colibri"]
