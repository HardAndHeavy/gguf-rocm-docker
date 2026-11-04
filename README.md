# llama.cpp / Strata / Colibri + Open WebUI

Три альтернативных стека для AMD GPU:

- `compose.llama.yaml`: [llama.cpp](https://github.com/ggml-org/llama.cpp) + Open WebUI
- `compose.strata.yaml`: [Strata](https://github.com/Niko1221/Strata) + Open WebUI
- `compose.colibri.yaml`: [Colibri](https://github.com/JustVugg/colibri) + Open WebUI

## llama.cpp

```bash
make model-coder390
make run-llama
make stop-llama
```

## Strata

```bash
make model-flash-next
make run-strata
make stop-strata
```

## Colibri

```bash
make model-flint
make run-colibri
make stop-colibri
```

Настройки можно передать через окружение или добавить в `.env`:

```dotenv
COLIBRI_GGUF=flint-UD-Q4_K_XL.gguf
COLIBRI_CTX=8192
COLIBRI_RAM=48
```
