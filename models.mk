MODELS_DIR ?= ./data/models
HF_BASE_URL ?= https://huggingface.co
CURL ?= curl

CODER390_REPO := nerkyor/Qwen3.8-27B-Coder390-EfficientThink-Opus5.5-GPT6Astra-Grok4.7-DSV4Pro-K3-SFT-RLOO-MTP-DFlash2
CODER390_FILE := GGUF/Qwen3.8-27B-Coder390-EfficientThink-Q6_K-MTP.gguf
CODER390_PATH := $(MODELS_DIR)/$(notdir $(CODER390_FILE))

FLASH_NEXT_REPO := ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF
FLASH_NEXT_FILES := IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf \
	IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf
FLASH_NEXT_PATHS := $(addprefix $(MODELS_DIR)/,$(notdir $(FLASH_NEXT_FILES)))

FLASH_NEXT_MTP_REPO := quimmedes/Qwen3.8-Flash-Next-MTP-GGUF
FLASH_NEXT_MTP_FILE := mtp-Qwen3.8-Flash-Next-Q2_0.gguf
FLASH_NEXT_MTP_PATH := $(MODELS_DIR)/$(FLASH_NEXT_MTP_FILE)

SC117_REPO := SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF
SC117_FILES := IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ2_XS-00001-of-00002.gguf \
	IQ2_XS/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-IQ2_XS-00002-of-00002.gguf
SC117_PATHS := $(addprefix $(MODELS_DIR)/,$(notdir $(SC117_FILES)))

FLINT_REPO := unsloth/flint-GGUF
FLINT_FILE := flint-UD-Q4_K_XL.gguf
FLINT_PATH := $(MODELS_DIR)/$(FLINT_FILE)

GLM53_FLASH_REPO := unsloth/GLM-5.3-Flash-GGUF
GLM53_FLASH_FILES := $(addprefix UD-IQ2_XXS/GLM-5.3-Flash-UD-IQ2_XXS-,00001-of-00004.gguf 00002-of-00004.gguf 00003-of-00004.gguf 00004-of-00004.gguf)
GLM53_FLASH_PATHS := $(addprefix $(MODELS_DIR)/,$(notdir $(GLM53_FLASH_FILES)))

.PHONY: model-coder390 model-flash-next model-flash-next-mtp model-flash-next-sc117 model-flint model-glm53-flash verify-model-glm53-flash

model-coder390: $(CODER390_PATH)

model-flash-next: $(FLASH_NEXT_PATHS)

model-flash-next-mtp: $(FLASH_NEXT_MTP_PATH)

model-flash-next-sc117: $(SC117_PATHS)

model-flint: $(FLINT_PATH)

model-glm53-flash: $(GLM53_FLASH_PATHS)

# Deliberately do not depend on model-glm53-flash: verification must never start
# a second downloader. Missing or incomplete GGUFs fail sha256sum instead.
verify-model-glm53-flash:
	cd "$(MODELS_DIR)" && sha256sum --check --strict "$(CURDIR)/checksums/glm53-flash.sha256"

# HF's Xet bridge occasionally cancels HTTP/2 streams. HTTP/1.1 plus retry-all
# and a stall timeout keeps multi-GB downloads moving; -C - resumes each .part.
define download_model
	mkdir -p "$(@D)"
	$(CURL) --fail --location --http1.1 \
		--retry 10 --retry-delay 3 --retry-all-errors \
		--connect-timeout 30 --speed-limit 10240 --speed-time 60 \
		--continue-at - --output "$@.part" \
		"$(HF_BASE_URL)/$(1)/resolve/main/$(2)"
	mv "$@.part" "$@"
endef

$(CODER390_PATH):
	$(call download_model,$(CODER390_REPO),$(CODER390_FILE))

$(FLASH_NEXT_PATHS):
	$(call download_model,$(FLASH_NEXT_REPO),IQ2_XS/$(notdir $@))

$(FLASH_NEXT_MTP_PATH):
	$(call download_model,$(FLASH_NEXT_MTP_REPO),$(FLASH_NEXT_MTP_FILE))

$(SC117_PATHS):
	$(call download_model,$(SC117_REPO),IQ2_XS/$(notdir $@))

$(FLINT_PATH):
	$(call download_model,$(FLINT_REPO),$(FLINT_FILE))

$(GLM53_FLASH_PATHS):
	$(call download_model,$(GLM53_FLASH_REPO),UD-IQ2_XXS/$(notdir $@))
