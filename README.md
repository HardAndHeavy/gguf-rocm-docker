# GGUF на ROCm · Radeon AI PRO R9700

Локальный Docker-проект для **AMD Radeon AI PRO R9700 (`gfx1201`, 32 GiB VRAM)**:
запуск моделей, воспроизводимые benchmark и точечные исправления upstream ROCm/HIP.
Это проверенная конфигурация конкретной машины, не универсальный рецепт для любых GPU.
Поддерживаются и модели целиком в VRAM, и offload в RAM.

## Рабочий фокус

| Назначение | Стек | Статус |
|---|---|---|
| Основная работа, agent/coder | **Qwen3.6-35B-A3B UD-Q4_K_XL + Strata 0.2.9 batch MTP** | 154,14 tok/s decode; agent/coder smoke 3/3 |
| Сложные задачи | **Qwen3.8 Flash-Next IQ2_XS + Strata MTP** | Рабочий тяжёлый профиль; превосходство на сложных задачах отдельно не доказано |
| Контроль и fallback | llama.cpp ROCm | Qwen3.6 non-MTP и draft-MTP |
| Альтернативный runtime / open source | Colibri HIP, pinned main | Qwen3.6 non-MTP; dev device-MTP — отдельное исследование |

Источники и ограничения измерений: [BENCHMARKS](docs/BENCHMARKS.md).
Скорость и один маленький smoke suite не доказывают общее качество модели.
Flint, Coder390, GLM, Vulkan/Kimi — **второй план**, без удаления старых результатов.
Повторно тестируем их после значимых обновлений библиотек или моделей, а не расширяем
матрицу постоянно. Старые инструкции: [справочник](docs/REFERENCE.md).

## Подготовка

- Linux x86_64, Docker/BuildKit, `make`, `curl`, Python 3, `openssl`;
- рабочий amdgpu, `/dev/kfd` и `/dev/dri`; ROCm runtime внутри образов;
- Qwen3.6 GGUF — 21,28 GiB; Flash-Next — около 63,3 GiB и значительный host RAM;
- CPU этой машины — Ryzen 7 3700X, RAM — 60 GiB + swap;
- Colibri собирается поверх локального `llama-rocm:3.0.2` (образ должен быть доступен).

```bash
cp -n .env.example .env
```

`make run-*-api` определяет GPU GID и создаёт отсутствующие ключи в `.env`.
**Существующий `.env` не заменяется.** Старые defaults могут указывать Flint/Flash-Next:
для воспроизводимости ниже заданы явные параметры. Меняем стек только после остановки
предыдущего: у всех общий порт 8080 и Docker project `gguf-rocm`.

## Быстрый старт: основной стек

```bash
make model-qwen36
make verify-model-qwen36
STRATA_FAMILY=qwen36 STRATA_MODEL=ud-q4_k_xl \
STRATA_MODEL_PATH=/models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf \
STRATA_CONTEXT=32k STRATA_VISION=off STRATA_PARALLEL=2 \
STRATA_MTP=on STRATA_DRAFTING=mtp STRATA_BATCH_MTP=1 \
PRESET=qwen36-work make run-strata-api
```

API: `http://localhost:8080/v1`, ключ `STRATA_API_KEY` из `.env`.
Логи: `make logs-strata`; остановка: `make stop-strata`.
Для Open WebUI используйте те же параметры с `make run-strata` вместо `run-strata-api`.
Для бенчмарков UI не запускаем. MTP проверяем по `drafts offered/accepted > 0` в логах,
не только по загрузке head. Не заменяйте parallel setting на `STRATA_SET=batch=2`.

## Сложные задачи: Flash-Next + Strata

```bash
make stop-strata
make model-flash-next
make model-flash-next-mtp
STRATA_FAMILY=qwen STRATA_MODEL=IQ2_XS STRATA_MODEL_PATH=/models \
STRATA_CONTEXT=32k STRATA_PARALLEL=1 STRATA_VISION=off \
STRATA_MTP=on STRATA_DRAFTING=mtp STRATA_BATCH_MTP=0 \
PRESET=flash-next-work make run-strata-api
```

Это другой модельный профиль, не перенос batch-параметров Qwen3.6. Требует RAM/offload;
его скорость нельзя сравнивать с Qwen3.6 как чистую разницу backend.

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

# Strata 0.2.9, подтверждённый batch MTP
STRATA_FAMILY=qwen36 STRATA_MODEL=ud-q4_k_xl \
STRATA_MODEL_PATH=/models/Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf \
STRATA_CONTEXT=32k STRATA_VISION=off STRATA_PARALLEL=2 \
STRATA_MTP=on STRATA_DRAFTING=mtp STRATA_BATCH_MTP=1 \
PRESET=qwen36-work make run-strata-api

# Colibri: non-MTP; embedded MTP этого GGUF pinned loader не поддерживает
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

## Проверки и измерения

```bash
make check
make bench-strata BENCH_ARGS='--case short --case decode --case prefill --runs 3 --warmups 1 --max-tokens 192'
```

`make check` проверяет shell/Python, unit tests, Compose и Dockerfile; это **не HIP integration test**.
Полный runner останавливает текущие backend/UI и по завершении останавливает тестируемый сервис.
Результаты и logs — в gitignored `data/benchmarks/`, веса — в `data/models/`.
Они остаются локально, не входят в коммиты; перед внешним report нужен отдельный sanitised bundle.
Не публикуйте `.env`, API keys, chats и полный Docker inspect с secrets.

Методика, TTFT/reasoning/decode, WebUI overhead: [BENCHMARKS](docs/BENCHMARKS.md),
[справочник](docs/REFERENCE.md). Backend запускается один, без downloads в measured path.

## Open source: две отдельные проблемы Colibri

- **A — non-MTP regression:** main 45,45 → dev 37,26 tok/s (−18,0%) при сопоставимом
  state и lookup off. Причина не доказана; не приписываем её PR #2559 без bisect/profile.
- **B — HIP memory fault:** device MTP + `enable_thinking=false` падает в
  `gemv_i8_w4<4>`. W4 off или split-K off — диагностические обходы, **не исправление**.

Узкий CPU-reference тест выполнен: **2048 × 300 идёт в fallback**, поэтому дополнительно
проверены реальные W4 shapes **2048 × 1100 и 10240 × 300**, split-K on/off, S4 и четыре S1.
Оба процесса прошли; root cause не найден. После ответа maintainer выполнены два свежих
full-model процесса (automatic и forced three drafts): short/decode завершились без fault.
Это не fix: исходный FAIL не воспроизведён, сравнение allocator пока не выполнялось.
Подробности: [B follow-up](docs/issues/issue-B-allocator-followup.md).
Issues опубликованы: [A — #2757](https://github.com/JustVugg/colibri/issues/2757),
[B — #2758](https://github.com/JustVugg/colibri/issues/2758); оба открыты на 11 ноября 2026.
Локальные материалы: [A](docs/issues/colibri-A-non-mtp-regression.md),
[B](docs/issues/colibri-B-hip-device-mtp-fault.md).
Подробные условия, результаты и критерии PR: [MTP-HIP](docs/MTP-HIP.md).
Текущие приоритеты: [ROADMAP](docs/ROADMAP.md). Новые сообщения и PR без разрешения не отправляем.
