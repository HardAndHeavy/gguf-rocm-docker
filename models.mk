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

.PHONY: model-coder390 model-flash-next model-flash-next-sc117 model-flint model-glm53-flash

model-coder390: $(CODER390_PATH)

model-flash-next: $(FLASH_NEXT_PATHS)

model-flash-next-sc117: $(SC117_PATHS)

model-flint: $(FLINT_PATH)

model-glm53-flash: $(GLM53_FLASH_PATHS)

define download_model
	mkdir -p "$(@D)"
	$(CURL) --fail --location --retry 5 --retry-delay 3 \
		--connect-timeout 30 --continue-at - \
		--output "$@.part" \
		"$(HF_BASE_URL)/$(1)/resolve/main/$(2)"
	mv "$@.part" "$@"
endef

$(CODER390_PATH):
	$(call download_model,$(CODER390_REPO),$(CODER390_FILE))

$(FLASH_NEXT_PATHS):
	$(call download_model,$(FLASH_NEXT_REPO),IQ2_XS/$(notdir $@))

$(SC117_PATHS):
	$(call download_model,$(SC117_REPO),IQ2_XS/$(notdir $@))

$(FLINT_PATH):
	$(call download_model,$(FLINT_REPO),$(FLINT_FILE))

$(GLM53_FLASH_PATHS):
	$(call download_model,$(GLM53_FLASH_REPO),UD-IQ2_XXS/$(notdir $@))
