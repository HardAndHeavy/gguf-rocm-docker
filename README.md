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
make build-colibri
make run-colibri
make stop-colibri
```

Настройки можно передать через окружение или добавить в `.env`:

```dotenv
COLIBRI_GGUF=flint-UD-Q4_K_XL.gguf
COLIBRI_CTX=8192
COLIBRI_RAM=48
```

### AMD ROCm (основной вариант Colibri)

Colibri собирается с `HIP=1` для `gfx1201` (RDNA 4). Нужны устройства
`/dev/kfd`, `/dev/dri` и рабочий драйвер amdgpu на хосте; ROCm/HIP и rocWMMA
уже находятся в закреплённом образе. Для другой поддерживаемой карты задайте
`COLIBRI_HIP_ARCH` в `.env` **до пересборки**. Имена `COLI_CUDA` и метки
`[CUDA]` в логах — внутренние имена общего CUDA/HIP backend upstream;
на AMD реально используется `libamdhip64`, а не NVIDIA CUDA.

- Web UI: `http://localhost/` (порт 80).
- OpenAI API: `http://localhost:8080/v1` (нужен `COLI_API_KEY`).
- Готовность API не гарантирует успешную генерацию. Проверка реальным запросом:

  ```bash
  docker compose -p gguf-rocm -f compose.colibri.yaml exec -T colibri \
    python3 < scripts/check-colibri.py
  ```

На Radeon AI PRO R9700 (gfx1201) Flint UD-Q4_K_XL размещается целиком на GPU:
49 слоёв, `lm_head`, 343 trunk-матрицы и все 12032 routed-эксперта; fallback
экспертов на CPU и hybrid layer steps в замере не было. Smoke-тест вернул `4`.
Один из запусков до `healthy` занял около 71 с, из них warmstart экспертов —
57,4 с. После загрузки занято примерно 27,5–27,84 GB VRAM. Это измерения одной
машины, а не гарантированное время запуска.

`QT_NO_WARMSTART=1` в закреплённом upstream действительно пропускает предварительную
загрузку, но тогда VRAM-уровень изначально пуст, а промахи обслуживает CPU с
асинхронным продвижением экспертов. Это отладочный компромисс «быстрее открыть API,
медленнее первые ответы», а не способ бесплатно ускорить запуск; для постоянной
конфигурации оставлен обычный warmstart. Файл `.coli_usage` сохраняет историю
маршрутизации, но не сохраняет содержимое VRAM между перезапусками контейнера.

Flint может генерировать `reasoning_content` до финального `content`, поэтому
слишком маленький `max_tokens` может обрезать ответ ещё на размышлениях.
`finish_reason=length` при пустом `content` и непустом `reasoning_content` —
такое обрезание по лимиту, а не признак того, что генерация выполняется на CPU.

### Vulkan (альтернатива)

```bash
docker compose -p gguf-rocm -f compose.colibri.yaml \
  -f compose.colibri-vulkan.yaml up -d --build
```

Для возврата к ROCm выполните `make run-colibri`. Альтернативный образ имеет
отдельный тег и не перезаписывает ROCm-сборку.

На RADV GFX1201 исходная конфигурация загружала экспертов 1785 с и не давала
первого ответа в разумное время. С `COLI_VK_UP_IMPORT=0`, `Q36_ILV16=0`,
`COLI_VK_TIER_HOST=0` и чанками по 64 строки Vulkan стал работоспособен.
Эти настройки избегают временных импортов страниц памяти при каждой загрузке,
лишней перепаковки и дублирования экспертов в host pool. Вклад каждого
переключателя отдельно не измерялся; отключение host pool рассчитано на модель,
помещающуюся в VRAM.

В проверенном запуске resident weights загрузились за 5,8 с, создание 80 pipelines
заняло 56,2 с, warmstart 11988 экспертов — ещё 6,8 с; API слушал только после
этих этапов. Поэтому 6,8 с — именно expert warmstart, не полный холодный запуск.
На устройстве 49/49 слоёв и 11988 из 12032 экспертов. После прогрева 99,9–100%
routed-выборов обслуживались устройством, хотя оставались единичные RAM/disk hits
и CPU rows. В проверенных условиях ROCm быстрее и обеспечивает более полное
размещение Flint, поэтому остаётся основным backend.

### Сопоставление скорости Flint на R9700

Одинаковые короткий и два длинных prompt, `temperature=0`; длинные ответы
ограничены 384 токенами. Для Colibri использован non-stream OpenAI-compatible HTTP
API, поэтому ниже — `completion_tokens / всё время запроса` (**gross throughput**,
включая prefill и overhead), не чистый decode и не TTFT. llama.cpp запускался
in-process через `llama-cpp-python 0.3.36`, `n_gpu_layers=-1`, `n_ctx=8192`,
`flash_attn=True`; это не идеально идентичный HTTP serving benchmark.

| Backend | Короткий запрос | Длинный запрос 1 | Длинный запрос 2 |
|---|---:|---:|---:|
| Colibri ROCm/HIP | 89 ток. / 1,069 с = **83,22 ток/с** | 384 / 5,252 с = **73,11 ток/с** | 384 / 5,376 с = **71,43 ток/с** |
| llama.cpp ROCm/HIP | 76 ток. / 1,813 с = **41,92 ток/с** | 384 / 5,816 с = **66,02 ток/с** | 384 / 5,829 с = **65,88 ток/с** |
| Colibri Vulkan, после прогрева | — | **56,87–58,76 ток/с** в стабильных сериях | — |

У llama.cpp загрузка заняла 6,589 с, offload — 50/50 слоёв, model buffer на ROCm0 —
23577,22 MiB и CPU_Mapped — 311,58 MiB. Первая холодная генерация Vulkan заняла
18,342 с, а в первой серии встретился outlier 33,79 ток/с; их нельзя смешивать с
прогретыми измерениями. Вывод относится к этой R9700, Flint, закреплённым сборкам
и настройкам, а не ко всем GPU и prompt.

Исходники: [Makefile (HIP=1)](https://github.com/JustVugg/colibri/blob/0a5504a1dc64f86fcd0fe7db298b0448c730e7e6/c/Makefile),
[документация Vulkan](https://github.com/JustVugg/colibri/blob/0a5504a1dc64f86fcd0fe7db298b0448c730e7e6/docs/vulkan.md).
