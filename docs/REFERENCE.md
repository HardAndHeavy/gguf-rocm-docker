# Справочник и исторические профили

Не основной маршрут запуска. Текущий выбор и быстрый старт — в [README](../README.md).
Flint, GLM, Coder390, Vulkan и Kimi сохранены для повторных проверок после обновлений;
их старые результаты не являются рекомендацией текущего рабочего стека.

# GGUF на AMD ROCm: Colibri, Strata и llama.cpp

Воспроизводимый Docker-стек для больших GGUF, которые **не помещаются целиком в VRAM**.
Основная цель — запускать Colibri на AMD Radeon и сравнивать его с Strata без накладок
Open WebUI и без смешивания prefill, reasoning и decode.

- `compose.colibri.yaml` — [Colibri](https://github.com/JustVugg/colibri), ROCm/HIP;
- `compose.colibri-vulkan.yaml` — альтернативный Colibri/Vulkan и будущий Kimi K3 GPU backend;
- `compose.strata.yaml` — [Strata](https://github.com/Niko1221/Strata), ROCm;
- `compose.llama.yaml` — [llama.cpp](https://github.com/ggml-org/llama.cpp), ROCm;
- `compose.bench-webui.yaml` — изолированный Open WebUI только для benchmark-матрицы.

Измерения на Radeon AI PRO R9700: **[docs/BENCHMARKS.md](BENCHMARKS.md)**.
Текущая матрица Qwen3.6 и план отдельных agent/coder сравнений:
**[docs/ROADMAP.md](ROADMAP.md)**. Исследование Qwen3.8 MTP/HIP и существующий
upstream PR: **[docs/MTP-HIP.md](MTP-HIP.md)**.

## Почему база `llama-rocm`, а не чистый `transformers-rocm`

Образ наследуется от `llama-rocm:3.0.2`, который уже собран поверх
`transformers-rocm:3.0.1`. В нём есть проверенный ROCm/HIP compiler/runtime, rocWMMA,
поддержка `gfx1201` и исправления совместимости ROCm-библиотек. Colibri добавляет только
свои pinned C/CUDA-HIP/Vulkan engines. Не нужно поддерживать второй ROCm toolchain или
собирать его из ComfyUI-проекта.

Colibri source закреплён на commit
[`0a5504a1`](https://github.com/JustVugg/colibri/commit/0a5504a1dc64f86fcd0fe7db298b0448c730e7e6).
`COLIBRI_REF`, `COLIBRI_ROCM_IMAGE` и `COLIBRI_HIP_ARCH` можно переопределить до сборки.

## Требования

- Linux x86_64, Docker с BuildKit, `make`, `curl`, Python 3;
- AMD GPU с `/dev/kfd` и `/dev/dri`; ROCm на хост устанавливать не нужно;
- для текущего образа — архитектура `gfx1201` (Radeon AI PRO R9700); для другой карты
  задайте `COLIBRI_HIP_ARCH` и пересоберите образ;
- место на диске: Qwen IQ2_XS ~63,3 GiB, Flint ~23,3 GiB, GLM IQ2_XXS ~94,8 GiB;
- для быстрого Qwen-профиля Colibri — около 40 GiB RAM под контейнер плюс остальная система;
  для измеренного GLM-профиля — около 50 GiB под контейнер; на машине с 60 GiB RAM использовался swap.

## Быстрый старт: Qwen3.8 Flash Next на Colibri

```bash
cp -n .env.example .env       # существующий .env не перезаписывается
make model-flash-next
```

В `.env` выберите первый shard:

```dotenv
COLIBRI_GGUF=Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf
COLIBRI_CTX=8192
COLIBRI_RAM=48
COLI_CUDA_CHAIN_POOL=1
Q38_MTP=0
```

Сборка и API без Open WebUI:

```bash
make build-colibri
make run-colibri-api
make smoke-colibri
```

API: `http://localhost:8080/v1`. Ключ `COLI_API_KEY` автоматически создаётся в `.env`.
Smoke ждёт реальный `/v1/models` до 10 минут: TCP `healthy` может наступить раньше конца
warmstart. Полный стек с Open WebUI запускается отдельно:

```bash
make run-colibri
# Open WebUI: http://localhost/
```

Остановка и логи:

```bash
make logs-colibri
make stop-colibri
```

## Flint на Colibri

```bash
make model-flint
```

В `.env`:

```dotenv
COLIBRI_GGUF=flint-UD-Q4_K_XL.gguf
```

Затем `make run-colibri` или `make run-colibri-api`. На R9700 Flint целиком размещает
все 12032 эксперта в VRAM. В финальном streaming-замере получено около **122 ток/с decode**
и **0,19 с TTFT**; Open WebUI добавил к TTFT только около 10 мс.

Flint и Qwen могут сначала вернуть `reasoning_content`, а уже затем видимый `content`.
Поэтому пустой ответ при маленьком `max_tokens` и `finish_reason=length` обычно означает,
что лимит закончился ещё на reasoning. Benchmark измеряет оба момента отдельно.

## Flint на llama.cpp

Официальный ROCm `llama-server` запускается с явно выбранной моделью, а не со случайным
первым GGUF из общего каталога:

```bash
make run-llama-api
make bench-llama BENCH_ARGS='--case short --case decode --runs 3 --warmups 1 --max-tokens 192'
```

В `.env` закреплены `LLAMA_GGUF=flint-UD-Q4_K_XL.gguf`, alias `flint-llama`, context 8192,
`LLAMA_N_GPU_LAYERS=-1`, flash attention и 8 CPU threads. Порт без API key слушает только
`127.0.0.1`; Open WebUI обращается к backend по внутренней Docker network. В общей серии
официальный b12098 получил 67,31 tok/s direct decode против 117,81 у Colibri; подробности и
fallback llama-cpp-python отделены в [docs/BENCHMARKS.md](BENCHMARKS.md).

## Strata: тот же Qwen

```bash
make model-flash-next
make run-strata-api
make bench-strata BENCH_ARGS='--case decode --runs 3 --max-tokens 192'
make stop-strata
```

Текущий Strata preset использует MTP, speculative decoding `--spec 4`, KV int8 и контекст
32k. Colibri в измеренном профиле работает без активного MTP и с контекстом 8k. Это
сравнение **реальных рабочих пресетов**, а не утверждение о строго одинаковой конфигурации.
Порты 8080 общие: backends запускайте по очереди. Strata 0.2.9 **не поддерживает Flint GGUF**:
изолированный import возвращает `unsupported_architecture` для `general.architecture=flint`.
Это не ошибка ROCm и не повод подменять Flint похожим Qwen UD-Q4_K_XL.

## Qwen3.6-35B-A3B: один GGUF для трёх backend

Для сопоставимой матрицы используется MTP-aware UD-Q4_K_XL из отдельного репозитория Unsloth.
Файл занимает 21,28 GiB, поддерживается preset Strata 0.2.9 и оставляет запас под context/runtime
на 32-GiB R9700. Revision и официальный LFS SHA-256 закреплены:

```bash
make model-qwen36
make verify-model-qwen36
```

Одинаковый файл выбирается так (backends запускаются по очереди):

```bash
# llama.cpp b12098, non-MTP baseline
LLAMA_GGUF=Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf \
LLAMA_MODEL_ID=qwen36-llama LLAMA_CTX=32768 LLAMA_SPEC_TYPE=none \
  make run-llama-api

# llama.cpp, embedded MTP; замерять отдельно от baseline
LLAMA_GGUF=Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf \
LLAMA_MODEL_ID=qwen36-llama LLAMA_CTX=32768 LLAMA_SPEC_TYPE=draft-mtp \
  make run-llama-api

# Strata 0.2.9, поддерживаемый Qwen3.6 preset (MTP включён upstream по умолчанию)
STRATA_FAMILY=qwen36 STRATA_MODEL=ud-q4_k_xl \
STRATA_MODEL_PATH=/models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf \
STRATA_CONTEXT=32k STRATA_VISION=off STRATA_PARALLEL=1 \
  make run-strata-api

# Colibri: сначала Q36_MTP=0, затем отдельная серия с Q36_MTP=1
COLIBRI_GGUF=Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf \
COLIBRI_CTX=32768 Q36_MTP=0 make run-colibri-api
```

Полный изолированный прогон одного профиля (correctness + throughput + agent/coder + runtime/logs):

```bash
bash scripts/run-qwen36-backend.sh llama-off
bash scripts/run-qwen36-backend.sh llama-mtp
bash scripts/run-qwen36-backend.sh strata-off
bash scripts/run-qwen36-backend.sh strata-mtp
bash scripts/run-qwen36-backend.sh colibri-off
bash scripts/run-qwen36-backend.sh colibri-mtp
```

Скрипт ничего не скачивает: сначала обязателен успешный `make verify-model-qwen36`.
Для throughput используются обычные `bench-*` команды. Coding/agent smoke дополнительно проверяет
фактический tool protocol и unit tests, а не оценивает код только по внешнему виду:

```bash
make bench-agent BENCH_LABEL=qwen36-colibri BENCH_BACKEND_KEY_ENV=COLI_API_KEY \
  BENCH_ARGS='--case agent --case coder --runs 3 --warmups 1 --max-tokens 768'
# Для llama.cpp ключ не нужен: BENCH_BACKEND_KEY_ENV=LLAMA_API_KEY
# Для Strata: BENCH_BACKEND_KEY_ENV=STRATA_API_KEY
```

Это небольшой функциональный regression benchmark, **не SWE-bench**. Полные agent wall time,
pass rate и invalid tool calls сохраняются в `data/benchmarks/` рядом с serving-метриками.

## GLM-5.3-Flash UD-IQ2_XXS

Скачивание четырёх частей с resume:

```bash
make model-glm53-flash
# повторный запуск после обрыва продолжит .part-файлы
```

Файлы скачиваются последовательно: на этой машине параллельные HTTP Range-потоки Hugging Face
были нестабильны и не дали суммарного ускорения. После скачивания обязательно проверьте все части
по официальным Hugging Face LFS SHA-256:

```bash
make verify-model-glm53-flash
```

Проверка сама не запускает загрузку: если какой-то GGUF отсутствует или повреждён, команда завершится
с ошибкой. При обрыве снова выполните `make model-glm53-flash`, затем повторите проверку. После её
успешного завершения укажите первую часть в `.env`:

```dotenv
COLIBRI_GGUF=GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf
COLIBRI_CTX=8192
COLIBRI_RAM=48
```

Далее `make run-colibri-api`. Первый запуск большой модели может быть долгим: API поднимается
только после загрузки весов и warmstart. Healthcheck имеет стартовый период 10 минут, но это
не ограничение самой загрузки.

Все четыре части прошли SHA-256, после чего выполнены реальные import, serve и inference smoke.
В образ добавлен `rocm-smi`, без которого upstream `coli plan` ошибочно оставался CPU-only,
несмотря на рабочий HIP. В измеренном запуске API стал доступен через 179 с; warmstart разместил
3421 expert slot на GPU и 5337 в host pool. Direct decode для 192 токенов составил **2,12 ток/с**
при **26,88 с TTFT**; это значительно медленнее Flint/Qwen, потому что GLM не помещается в VRAM
и эксперты подгружаются по маршрутизации. Память, SHA-256 всех частей и обе Open WebUI-серии
приведены в [docs/BENCHMARKS.md](BENCHMARKS.md#glm-53-flash-ud-iq2_xxs-реальный-запуск-и-измерения).

## Честный benchmark без Open WebUI

```bash
make bench-colibri BENCH_ARGS='--case short --case decode --runs 3 --warmups 1 --max-tokens 192'
make bench-strata  BENCH_ARGS='--case short --case decode --runs 3 --warmups 1 --max-tokens 192'
```

Клиент использует только Python stdlib и streaming OpenAI API. Каждый запрос начинается с
уникальной метки, чтобы повторные прогоны не попадали в exact prefix cache. Сохраняются:

- HTTP headers time и время до первого SSE event;
- TTFT по первому `reasoning_content` **или** `content`;
- отдельный TTFT до первого видимого `content`;
- точные `completion_tokens` из `stream_options.include_usage` и источник этого числа;
  при отсутствии usage только `finish_reason=length` позволяет использовать достигнутый budget;
- decode tok/s между первым и последним событием, gross tok/s за весь запрос;
- p50/p95 интервалов SSE events, finish reason, queue wait;
- VRAM, GPU busy и доступная RAM с хоста во время теста.

JSON и CSV создаются в `data/benchmarks/`. Сводная Markdown-таблица:

```bash
python3 scripts/benchmark_report.py \
  data/benchmarks/colibri-qwen-final-3.0.2-pool.json \
  data/benchmarks/strata-qwen-baseline-0.2.9-mtp.json
```

`--request-json '{"enable_thinking":false}'` добавляет backend-specific параметры запроса,
`--save-text` сохраняет текст ответов. По умолчанию сохраняются только хэши и длины текстов.
Если backend возвращает `<think>` прямо в `content`, parser отделяет reasoning от видимого
ответа и ставит `inline_reasoning=true`. SSE chunks не выдаются за точные tokens.

Runtime-память и digest образа без env/secrets сохраняются отдельно:

```bash
python3 scripts/capture-runtime.py CONTAINER data/benchmarks/LABEL-runtime.json
```

## Тот же запрос через изолированный Open WebUI

Сначала запустите один backend, затем sidecar с явным внутренним URL и именем его ключа:

```bash
make run-bench-webui BENCH_BACKEND_URL=http://colibri:8080/v1 BENCH_BACKEND_KEY_ENV=COLI_API_KEY
make auth-bench-webui
make bench-webui-openai BENCH_LABEL=colibri-qwen \
  BENCH_ARGS='--case short --case decode --runs 3 --warmups 1 --max-tokens 192'
make bench-webui-full BENCH_LABEL=colibri-qwen \
  BENCH_ARGS='--case short --case decode --runs 3 --warmups 1 --max-tokens 192'
make stop-bench-webui
```

Для Strata используйте `BENCH_BACKEND_URL=http://strata:8080/v1` и
`BENCH_BACKEND_KEY_ENV=STRATA_API_KEY`; для llama.cpp — `http://llama-cpp:8080/v1` и
`BENCH_BACKEND_KEY_ENV=LLAMA_API_KEY` (helper сам передаёт безопасный placeholder,
потому что у закреплённого llama-server нет auth).

`bench-webui-openai` измеряет `/openai/chat/completions`, а `bench-webui-full` — полный
`/api/chat/completions`. UI слушает отдельный порт **3300**, хранит БД только в
`data/open-webui-bench`, а учётные данные — в gitignored `data/open-webui-bench-auth.env`
с режимом 0600. Реальные `data/open-webui`, chats/uploads/settings не используются.
RAG retrieval, web search, image generation, code interpreter и внешние downloads отключены,
чтобы инициализация embedding-модели не смешивалась с latency инференса.

## Qwen: важные настройки ROCm

### Pinned host pool — быстрый, но тяжёлый

```dotenv
COLI_CUDA_CHAIN_POOL=1
```

На R9700 пул занимает около 34,6 GiB page-locked RAM, но резко ускоряет prefill. При `0`
контейнерный RSS в проверке упал примерно с 40 до 5 GiB, а запуск сократился примерно со
194 до 80 секунд. Цена: TTFT вырос с 1,78 до 7,95 с, gross throughput упал с 36,7 до
15,9 ток/с. Поэтому low-RAM режим не используется по умолчанию.

Не путайте `COLI_CUDA_HOST_POOL` и `COLI_CUDA_CHAIN_POOL`: для Qwen3.8 chain pool управляет
именно вторая переменная.

### MTP

```bash
make model-flash-next-mtp
```

```dotenv
COLIBRI_MTP=mtp-Qwen3.8-Flash-Next-Q2_0.gguf
Q38_MTP=1
```

MTP совместим и даёт высокий acceptance, но на закреплённом main ROCm chain draft head исполняется
на CPU. Замер показал замедление с 55,8 до 49,8 ток/с и рост TTFT. Поэтому `Q38_MTP=0` оставлен
по умолчанию. `COLIBRI_MTP=off` запрещает даже auto-discovery файла.

В upstream `dev` уже влит PR #2559 с device MTP head. Экспериментальная HIP-проверка не меняет
stable image/state и не содержит локального параллельного MTP-движка:

```bash
make build-colibri-mtp-dev
bash scripts/run-colibri-mtp-hip.sh off
bash scripts/run-colibri-mtp-hip.sh cpu
bash scripts/run-colibri-mtp-hip.sh gpu-conservative
bash scripts/run-colibri-mtp-hip.sh gpu-full
```

Runner сохраняет отдельные fixed-prompt correctness и cache-busted throughput JSON; baseline `off`
и `gpu-full` также прогоняют полный agent/coder smoke (настраивается `RUN_AGENT=0|1`). Технические ссылки и критерии upstream PR:
[docs/MTP-HIP.md](MTP-HIP.md).

### Прочие необязательные параметры

`COLIBRI_CAP`, `COLIBRI_VRAM`, `COLIBRI_KV_SLOTS`, `COLIBRI_POLICY` передаются в `coli serve`
только когда непустые. `OMP_NUM_THREADS=8` соответствует Ryzen 7 3700X; для другого CPU
настройте под физические ядра. Имена `COLI_CUDA` и сообщения `[CUDA]` — внутренний общий
CUDA/HIP ABI upstream; на AMD используется `libamdhip64`, не NVIDIA CUDA.

## Open WebUI и диагностика «лага»

- Для чистых замеров используйте `run-*-api`: UI исключён полностью.
- Полный `/api/chat/completions` и `/openai/chat/completions` Open WebUI были проверены
  отдельно; существенной задержки на Flint не обнаружено.
- Первый запуск с пустым `data/open-webui` может занять минуты: Open WebUI скачивает
  sentence-transformers embedding model для RAG. Это подготовка UI, а не генерация.
- Смотрите не только TTFT reasoning, но и `content_ttft_s`: длинные размышления могут выглядеть
  в браузере как пауза перед видимым ответом.
- HTTP `/health` нельзя использовать как короткий Docker healthcheck во время генерации:
  занятый engine отвечает с задержкой. В Compose используется TCP probe, а реальная генерация
  проверяется отдельно через `make smoke-colibri`.

## Vulkan и Kimi K3

```bash
docker compose -p gguf-rocm -f compose.colibri.yaml \
  -f compose.colibri-vulkan.yaml up -d --build colibri
```

Вернуть ROCm: `make run-colibri-api` (при смене Dockerfile — `make build-colibri`). Теги
ROCm и Vulkan раздельные. Для Flint на этой R9700 ROCm оказался лучше; Vulkan остаётся
альтернативой. В оба образа добавлен `kimi_k3`; **GPU-путь этого upstream engine — Vulkan**.
Upstream tiny-model token-exact тесты пройдены на CPU, а Vulkan tiny-test подтвердил все
6/6 слоёв и 32/32 эксперта на RADV GFX1201. Это проверка engine/backend, а не гарантия
поддержки любого будущего Kimi K3.1 Pro GGUF.

## Проверки проекта

```bash
make check
```

Команда проверяет Bash syntax, Python compile, unit-тесты benchmark, Compose config и оба
Dockerfile. Полный inference smoke требует запущенную модель: `make smoke-colibri`.
