.DEFAULT_GOAL := run-llama

include models.mk
export MODELS_DIR

COMPOSE := docker compose -p gguf-rocm
BENCH_ARGS ?=
BENCH_BACKEND_URL ?= http://colibri:8080/v1
BENCH_BACKEND_KEY_ENV ?= COLI_API_KEY
BENCH_LABEL ?= model-backend
CHECK_ENV := COLI_API_KEY=check STRATA_API_KEY=check VIDEO_GID=44 RENDER_GID=45
BENCH_CHECK_ENV := BENCH_BACKEND_URL=http://colibri:8080/v1 BENCH_BACKEND_API_KEY=check BENCH_WEBUI_SECRET=check

run-%: FORCE
	$(COMPOSE) -f compose.$*.yaml up -d

stop-%: FORCE
	$(COMPOSE) -f compose.$*.yaml down --remove-orphans

logs-%: FORCE
	$(COMPOSE) -f compose.$*.yaml logs -f --tail=100

# API-only targets avoid Open WebUI startup work and isolate inference benchmarks.
run-llama-api: prepare-llama
	$(COMPOSE) -f compose.llama.yaml up -d llama-cpp

run-strata-api: prepare-strata
	$(COMPOSE) -f compose.strata.yaml up -d strata

run-colibri-api: prepare-colibri
	$(COMPOSE) -f compose.colibri.yaml up -d colibri

run-strata: prepare-strata
run-colibri: prepare-colibri
run-llama: prepare-llama

prepare-strata prepare-colibri prepare-llama:
	bash scripts/prepare-gpu.sh $(@:prepare-%=%)

build-colibri: prepare-colibri
	$(COMPOSE) -f compose.colibri.yaml build colibri

# Existing upstream Qwen3.8 device-MTP work (PR #2559), pinned for HIP
# validation. This is an experiment, not the default serving image.
build-colibri-mtp-dev: prepare-colibri
	COLIBRI_REF=0a6f235b0c7a20726e28e6e0229ef1201de74638 \
	COLIBRI_IMAGE=gguf-rocm-colibri:mtp-dev-0a6f235b \
	$(COMPOSE) -f compose.colibri.yaml build colibri

smoke-colibri:
	$(COMPOSE) -f compose.colibri.yaml exec -T colibri python3 < scripts/check-colibri.py

bench-colibri:
	python3 scripts/benchmark.py --backend colibri --api-key-env COLI_API_KEY $(BENCH_ARGS)

bench-strata:
	python3 scripts/benchmark.py --backend strata --api-key-env STRATA_API_KEY $(BENCH_ARGS)

bench-llama:
	python3 scripts/benchmark.py --backend llama --api-key-env LLAMA_API_KEY $(BENCH_ARGS)

bench-agent:
	python3 scripts/agent_benchmark.py --backend $(BENCH_LABEL) \
		--api-key-env $(BENCH_BACKEND_KEY_ENV) $(BENCH_ARGS)

run-bench-webui:
	python3 scripts/openwebui-bench.py up --backend-url $(BENCH_BACKEND_URL) --backend-key-env $(BENCH_BACKEND_KEY_ENV)

auth-bench-webui:
	python3 scripts/openwebui-bench.py auth

stop-bench-webui:
	python3 scripts/openwebui-bench.py down

bench-webui-openai:
	python3 scripts/benchmark.py --backend $(BENCH_LABEL)-openwebui-openai \
		--url http://127.0.0.1:3300/openai --env-file data/open-webui-bench-auth.env \
		--api-key-env OPENWEBUI_API_KEY $(BENCH_ARGS)

bench-webui-full:
	python3 scripts/benchmark.py --backend $(BENCH_LABEL)-openwebui-full \
		--url http://127.0.0.1:3300/api --env-file data/open-webui-bench-auth.env \
		--api-key-env OPENWEBUI_API_KEY $(BENCH_ARGS)

check:
	bash -n scripts/prepare-gpu.sh scripts/start-colibri.sh scripts/run-colibri-mtp-hip.sh \
		scripts/run-qwen36-backend.sh scripts/run-functional-control.sh docker/strata-entrypoint.sh
	python3 -m py_compile scripts/benchmark.py scripts/benchmark_report.py scripts/check-colibri.py \
		scripts/agent_benchmark.py scripts/openwebui-bench.py scripts/openwebui-bench-auth.py \
		scripts/capture-runtime.py
	python3 -m unittest discover -s tests -v
	$(CHECK_ENV) $(COMPOSE) -f compose.colibri.yaml config --quiet
	$(CHECK_ENV) $(COMPOSE) -f compose.strata.yaml config --quiet
	$(CHECK_ENV) $(COMPOSE) -f compose.llama.yaml config --quiet
	$(BENCH_CHECK_ENV) docker compose -p gguf-rocm-bench-ui -f compose.bench-webui.yaml config --quiet
	docker build --check -f docker/colibri.Dockerfile .
	docker build --check -f docker/colibri-vulkan.Dockerfile .

.PHONY: FORCE prepare-strata prepare-colibri prepare-llama build-colibri smoke-colibri \
	bench-colibri bench-strata bench-llama bench-agent check run-llama-api run-strata-api run-colibri-api \
	build-colibri-mtp-dev run-bench-webui auth-bench-webui stop-bench-webui bench-webui-openai bench-webui-full
FORCE:
