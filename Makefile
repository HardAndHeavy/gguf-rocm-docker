.DEFAULT_GOAL := run-llama

include models.mk
export MODELS_DIR

COMPOSE := docker compose -p gguf-rocm

run-%: FORCE
	$(COMPOSE) -f compose.$*.yaml up -d

stop-%: FORCE
	$(COMPOSE) -f compose.$*.yaml down --remove-orphans

run-strata: prepare-strata
run-colibri: prepare-colibri

.PHONY: FORCE prepare-strata prepare-colibri build-colibri
FORCE:

prepare-strata prepare-colibri:
	bash scripts/prepare-gpu.sh $(@:prepare-%=%)

build-colibri: prepare-colibri
	$(COMPOSE) -f compose.colibri.yaml build colibri
