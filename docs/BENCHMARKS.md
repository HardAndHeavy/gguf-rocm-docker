# Radeon AI PRO R9700: измеренные результаты

Дата: 8–9 ноября 2026. GPU: AMD Radeon AI PRO R9700, `gfx1201`, 32 GiB VRAM
(sysfs сообщает 34 208 743 424 байта). CPU: Ryzen 7 3700X. RAM: 60 GiB + 8 GiB swap.

## Метод

- Один запрос за раз, API на loopback, Open WebUI не участвует, кроме явно названных тестов.
- `temperature=0`, streaming, `stream_options.include_usage=true`.
- Один warm-up и три измерения; в таблицах — медиана, не лучший прогон.
- В начало каждого prompt добавляется UUID, исключающий exact prefix-cache reuse.
- `decode`: 192 токена, `finish_reason=length`; у Qwen/Flint budget может целиком уйти в
  reasoning, поэтому visible answer time тогда отсутствует. В GLM-серии текст был в `content`.
- `short`: ответ завершается естественно, поэтому число токенов немного различается.
- `Decode` = `(completion_tokens - 1) / (последнее token event - первое token event)`.
- `Gross` = `completion_tokens / всё время HTTP-запроса`, включая prefill и overhead.
- Основной источник tokens — `usage.completion_tokens` (`completion_tokens_source=stream_usage`).
  Если старый llama-cpp-python не присылает streaming usage, только при `finish_reason=length`
  используется достигнутый request budget (`finish_reason_length`). Для естественно завершённого
  ответа без usage tokens и throughput остаются `null`, а не оцениваются по SSE chunks.
- Литеральные `<think>...</think>` внутри `content` разбираются отдельно: TTFT reasoning не
  ошибочно записывается как TTFT видимого ответа. Сырой hash и `inline_reasoning` сохраняются.
- VRAM — максимум host sysfs sample за весь JSON-run, а не моментальный snapshot после загрузки.
- Первая серия `matrix-*` выполнялась при активном resumable download GLM и частично при pull
  Docker image. После загрузок выполнена отдельная `control-*` серия Qwen без model/image downloads;
  именно она используется в Qwen-таблице ниже. Все шесть отчётов содержат 3/3 успешных measured
  runs на case. Flint остаётся реальной исходной matrix-серией, но не строго изолированным run;
  GLM измерен после завершения скачивания и SHA-проверки его частей. Outliers не удаляются из JSON.

Команда воспроизведения:

```bash
python3 scripts/benchmark.py \
  --backend LABEL --case short --case decode \
  --runs 3 --warmups 1 --max-tokens 192 \
  --api-key-env COLI_API_KEY \
  --output data/benchmarks/LABEL.json
```

## Qwen3.6-35B-A3B: сопоставимая serving и functional матрица

Общий файл — `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`, revision
`5bc3e238d916f48a861bac2f8a1990a0e9b7e98d`, `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf`,
22 853 663 008 байт (21,28 GiB), SHA-256
`55983c5a75a1ab969824077b3bb3de4146e82a9234072b48ad4e8f92ad3fe9f1`.
Это документированный preset Strata 0.2.9; тот же GGUF используется без подмены на llama.cpp
b12098 и Colibri `0a5504a1`. Context 32k, vision off, один backend за раз.

Для итоговой серии запросы содержат `temperature=0`, `presence_penalty=0`,
`frequency_penalty=0` и `chat_template_kwargs.enable_thinking=false`. Последние поля важны:
provider-default penalties и 768 reasoning tokens в ранних сериях делали coding outputs пустыми.
Correctness preflight требует законченный ответ на short case и видимый content в decode.
Источники — только `qwen36-*-nothink.json`; старые `qwen36-strata-{off,mtp}.json` и
`qwen36-colibri-mtp.json` являются диагностическими inert-MTP сериями и сюда не входят.

### Throughput

Все числа — медианы трёх measured runs после одного warm-up, 192 completion tokens.
`Prefill TTFT` относится к отдельному prompt длиной около 2,7k tokens; throughput prompts имеют
UUID. VRAM — максимум sysfs за весь JSON-run.

| Backend / профиль | Decode TTFT, s | Decode, tok/s | Gross, tok/s | Prefill TTFT, s | Prefill decode, tok/s | VRAM max |
|---|---:|---:|---:|---:|---:|---:|
| llama.cpp, non-MTP | 0,184 | 74,43 | 69,82 | 0,936 | 73,89 | 22,41 GiB |
| llama.cpp, `draft-mtp` | 0,235 | 100,23 | 90,22 | 1,078 | 109,49 | 23,47 GiB |
| Strata, non-MTP | 0,077 | 115,12 | 110,60 | 0,452 | 112,55 | 28,92 GiB |
| Strata, batch MTP | 0,079 | **154,14** | **145,64** | 0,594 | **156,52** | 28,97 GiB |
| Colibri, non-MTP, lookup off | 0,200 | 85,53 | 78,91 | 4,928 | 38,34 | 22,15 GiB |
| Colibri, `Q36_MTP=1` | **unsupported для этого GGUF** | — | — | — | — | — |

Strata MTP требует `STRATA_PARALLEL=2`, `STRATA_BATCH_MTP=1`, `STRATA_MTP=on` и
`STRATA_DRAFTING=mtp`. Нельзя добавлять `--set batch=2`: Strata считает его конфликтующим с
любым launch/profile parallel override. Несуществующие для qwen35 engine `--spec`,
`--spec-min-p` и `--suffix-draft` не используются. Замеры остаются последовательными, хотя
engine настроен на две session slots; non-MTP baseline имеет одну. Поэтому MTP/off включает
необходимую batch-конфигурацию, а не является изоляцией одного флага при прочих равных.

MTP действительность проверена логами, а не названием профиля:

- llama.cpp создал MTP draft context; 34 request reports содержат 2448 accepted из 3550 generated
  draft tokens (агрегат по всем correctness/throughput/functional prompts, не общий коэффициент
  ускорения). Non-MTP игнорирует `blk.40.nextn.*` tensors, как и ожидается.
- Strata MTP имеет `--batch 2`, drafts offered > 0 в каждом request; суммарно 2219/2858 accepted.
  У non-MTP launch нет `--mtp`, все requests — `drafts accepted 0 of 0`.
- Colibri пишет `[mtp] Q36_MTP=1: the head stays off`. Loader ожидает converted-container
  `mtp.*` (начиная с `mtp.fc.weight`), а выбранный llama.cpp-style GGUF содержит
  `blk.40.nextn.*`. Это unsupported model/container комбинация, не доказанный HIP-дефект.
  Runner завершается exit 4 и сохраняет `qwen36-colibri-mtp-nothink-unsupported.txt`.
- Strata и Colibri разместили все 10 240 routed experts в VRAM. У Colibri 40 layers, 190 trunk
  matrices и lm_head находятся на HIP device; сообщения `[CUDA]` обозначают общий CUDA/HIP ABI.

### Functional: реальные tools, изменённые файлы и tests

`agent` получает только `read_file`, `write_file`, `run_tests`; `coder` возвращает один Python
source file. Каждый run создаёт свежий fixture, применяет изменение к `statistics_utils.py` и
запускает фиксированный `python3 -m unittest discover -s . -p test_*.py -v`. В таблице wall —
медиана успешных runs; `completion` помогает увидеть цену более длинного ответа. Это smoke
benchmark, не SWE-bench и не оценка общего интеллекта.

| Модель / backend / профиль | Agent | Agent wall, s | Coder | Coder wall, s | Coder completion tokens |
|---|---:|---:|---:|---:|---:|
| Qwen3.6, llama.cpp non-MTP | 3/3 | 5,835 | 3/3 | 1,881 | 121 |
| Qwen3.6, llama.cpp MTP | 3/3 | 3,716 | 3/3 | 1,080 | 121 |
| Qwen3.6, Strata non-MTP | 3/3 | 3,518 | 3/3 | 1,221 | 120 |
| Qwen3.6, Strata MTP | **3/3** | **2,356** | **3/3** | **0,781** | 121 |
| Qwen3.6, Colibri non-MTP | 3/3 | 14,940 | 3/3 | 2,193 | 120 |
| Flint, llama.cpp non-MTP | 3/3 | 5,752 | 3/3 | 8,488 | 556 |
| Flint, Colibri non-MTP | 3/3 | 12,370 | 3/3 | 9,408 | 473 |
| Coder390 Q6_K, llama.cpp non-MTP | 3/3 | 11,587 | 3/3 | 5,502 | 108 |
| Coder390 Q6_K, Colibri non-MTP | 3/3 | 95,236 | 3/3 | 26,375 | 375 |

Все Qwen3.6 runs сделали четыре валидных tool calls в agent case, без invalid calls; controls
также прошли tests 3/3. У естественно завершённых задач trajectories и длина ответа различаются,
поэтому wall time нельзя пересчитывать из decode tok/s. Например, Flint на Colibri имеет самый
быстрый исторический direct decode (117,81 tok/s), но генерирует 473 coder tokens против 121 у
Qwen3.6 и заканчивает задачу за 9,41 с вместо 0,78 с.

**Выбор для этой R9700 на текущем smoke suite:**

- **Agent platform:** Qwen3.6 UD-Q4_K_XL на **Strata 0.2.9 с реально активным batch MTP** —
  3/3 PASS, 2,36 s; следующий non-MTP Strata — 3,52 s. Длинный prefill Colibri делает его
  неподходящим primary agent stack для этого GGUF, несмотря на приличный короткий decode.
- **Coder platform:** тот же **Qwen3.6 + Strata MTP** — 3/3 PASS, 0,78 s; llama.cpp MTP —
  практичный fallback с 1,08 s. Flint и специализированный Coder390 в этом тесте не дают
  преимущества по полному времени. Выбор ограничен одним маленьким regression task; перед
  production-решением нужен более широкий набор репозиториев и длинных задач.

Strata+Flint остаётся unsupported по explicit import preflight ниже. Coder390 на Strata не
тестировался и не объявляется unsupported. Все functional JSON/CSV, config.env, runtime и logs
сохранены в `data/benchmarks/`; runner — `scripts/run-qwen36-backend.sh`, controls —
`scripts/run-functional-control.sh`.

## Покрытие модель × backend × HTTP path

`direct` — `/v1/chat/completions`; `/openai` и полный `/api` — два разных маршрута изолированного
Open WebUI 0.13.0 на порту 3300. Во всех измеренных ячейках есть реальные streaming JSON/CSV,
один warm-up и три measured runs для `short` и `decode`.

| Модель | Colibri | Strata 0.2.9 | Официальный llama.cpp b12098 | Fallback llama-cpp-python 0.3.36 |
|---|---|---|---|---|
| GLM-5.3-Flash UD-IQ2_XXS | direct + `/openai` + `/api` | не тестировался | не тестировался | не тестировался |
| Qwen3.8 Flash Next IQ2_XS | direct + `/openai` + `/api` | direct + `/openai` + `/api` | не тестировался | не тестировался |
| Flint UD-Q4_K_XL | direct + `/openai` + `/api` | **unsupported**: import exit 5, inference paths не запускались | direct + `/openai` + `/api` | direct + `/openai` + `/api` |

«Не тестировался» не означает `unsupported`: такой вывод делается только по явной проверке.
Для Strata+Flint доказательство — реальный isolated preflight ниже, а не отсутствие строки в таблице.
Производительность unsupported-ячеек не обозначается нулём.

## Qwen3.8 Flash Next IQ2_XS: Colibri против Strata

Один и тот же GSQ-RCO GGUF. Strata 0.2.9 использует MTP Q2, `--spec 4`, KV int8 и 32k context;
Colibri — pinned host pool, 8k context, без активного MTP. Это сравнение рабочих пресетов.

| Backend / HTTP path | TTFT, s | Decode, tok/s | Gross, tok/s | Всего, s | VRAM max |
|---|---:|---:|---:|---:|---:|
| Colibri direct `/v1` | 2,311 | 63,37 | 36,06 | 5,325 | 31,79 GiB |
| Colibri → Open WebUI `/openai` | 1,858 | 64,28 | 39,82 | 4,822 | 31,79 GiB |
| Colibri → Open WebUI полный `/api` | 1,868 | 63,61 | 39,45 | 4,867 | 31,79 GiB |
| Strata direct `/v1` | 0,819 | **89,82** | **65,16** | 2,947 | 31,83 GiB |
| Strata → Open WebUI `/openai` | 0,807 | 98,67 | 70,97 | 2,705 | 31,82 GiB |
| Strata → Open WebUI полный `/api` | 0,805 | 99,61 | 70,29 | 2,732 | 31,83 GiB |

Все строки — `decode`, 192 токена, один warm-up и медиана трёх измерений контрольной серии.
В коротком direct case Colibri получил TTFT 1,667 с, видимый ответ 2,652 с, decode 52,28 и
gross 20,76 tok/s; Strata — 0,683 с, 1,251 с, 93,75 и 43,25 tok/s соответственно.

**Вывод:** на этих пресетах Strata быстрее Qwen в **1,42 раза по direct decode** и
в **1,81 раза по direct gross**, с заметно меньшим TTFT. Open WebUI не добавляет устойчивой
большой задержки ни одному backend. Более поздние Strata `/openai` и `/api` серии дали 98–100 tok/s
против 89,82 direct; порядок серий, speculative/cache history и обычная вариативность влияют на
эти различия, поэтому нельзя называть proxy «ускорителем». Утверждение, что Colibri всегда быстрее
Strata на Qwen, контрольные измерения не подтверждают. Исходные `matrix-*` JSON сохранены отдельно;
текущая таблица воспроизводится из `data/benchmarks/control-{colibri,strata}-qwen-*.json`.

В контрольном запуске Colibri API стал доступен примерно через 215 с
(warmstart экспертов 70,1 с; чтение host pool 94,8 с; page-locked allocation 34,2 с),
Strata — через 106 с. Это наблюдаемые запуски с уже существующими metadata/history и горячим
страничным кэшем, не контролируемый cold-boot benchmark.

## Flint: Colibri, llama.cpp, Strata и Open WebUI

| Backend / HTTP path | TTFT, s | Decode, tok/s | Gross, tok/s | Всего, s | VRAM max |
|---|---:|---:|---:|---:|---:|
| Colibri direct `/v1` | 0,191 | **117,81** | **105,83** | 1,814 | 25,58 GiB |
| Colibri → Open WebUI `/openai` | 0,197 | 121,07 | 108,03 | 1,777 | 25,58 GiB |
| Colibri → Open WebUI полный `/api` | 0,203 | 118,45 | 105,59 | 1,818 | 25,58 GiB |
| Официальный llama.cpp b12098 direct | 0,127 | 67,31 | 64,76 | 2,965 | 24,62 GiB |
| b12098 → Open WebUI `/openai` | 0,131 | 67,43 | 64,79 | 2,963 | 24,62 GiB |
| b12098 → Open WebUI полный `/api` | 0,134 | 67,38 | 64,70 | 2,968 | 24,62 GiB |
| Fallback llama-cpp-python 0.3.36 direct | 0,153 | 58,10 | 55,80 | 3,441 | 25,31 GiB |
| Fallback → Open WebUI `/openai` | 0,081 | 59,07 | 57,93 | 3,314 | 25,31 GiB |
| Fallback → Open WebUI полный `/api` | 0,083 | 59,89 | 58,66 | 3,273 | 25,31 GiB |

Все поддерживаемые строки — case `decode`, 192 токена. Fallback не возвращает streaming usage;
здесь tokens получены из достигнутого budget и явно помечены `finish_reason_length`. Для его
естественно завершённого short case throughput не вычисляется. Официальный b12098 присылает
настоящий `usage.completion_tokens` и отдельный `reasoning_content`. В самых ранних Colibri/Flint
JSON ещё нет отдельного `completion_tokens_source`, но исходный streaming `usage` с тем же числом
сохранён; они не смешаны с fallback-методом `finish_reason_length`.

**Вывод:** в direct decode Colibri быстрее официального llama.cpp примерно в **1,75 раза** и
быстрее старого fallback примерно в **2,03 раза**. Официальный server быстрее fallback примерно
на 16%. Это разные serving stacks; старые in-process/non-stream числа сюда не подмешиваются.

Flint в Colibri разместил все 12032 эксперта в VRAM. Полный UI API добавляет к TTFT официального
llama.cpp лишь около 6 мс; у Colibri разница direct/full около 12 мс. Существенного постоянного
«лага Open WebUI» на этих HTTP-путях нет. Отдельный исторический первый запуск с обычным пустым
UI volume потратил более двух минут на sentence-transformers для RAG — это не генерация Flint.
В новой матрице используется `data/open-webui-bench`, порт 3300 и отключённый retrieval.

### Strata + Flint: неподдерживаемая комбинация

Strata 0.2.9 (engine `0.1.55-linux-x86_64-hip-rx9070`) проверена изолированной командой
`strata models import /model.gguf --plan --output json`, без GPU и записи в пользовательский state.
GGUF корректно читается: `general.architecture=flint`, 779 tensors, payload extents валидны.
Но import завершился exit code **5** до inference:

```text
model.gguf: unsupported_architecture
unsupported_or_missing_architecture
This model type isn't supported by the Strata engine.
Add it as a Custom model API (llama-server) instead.
```

Следовательно, ячейки Strata+Flint direct/Open WebUI — **unsupported**, а не нулевая скорость.
Qwen3.8 Unsloth `UD-Q4_K_XL` из каталога Strata не подменял Flint. JSON preflight сохранён как
`data/benchmarks/strata-flint-preflight.json`.

## Эксперименты Colibri/Qwen

Все строки — case `decode`, 192 токена. Между запусками менялись `.coli_usage`, page cache и
expert placement, поэтому маленькие различия между базовыми образами нельзя приписывать только
версии ROCm. Для решений используются большие эффекты и отдельные профили.

| Профиль | TTFT, s | Decode, tok/s | Gross, tok/s | Всего, s | Вывод |
|---|---:|---:|---:|---:|---|
| 3.0.0, host pool, без MTP | 1,783 | 55,77 | 36,73 | 5,227 | Исходный baseline |
| 3.0.2, host pool, без MTP | 2,039 | **61,76** | **37,28** | 5,150 | Основной профиль |
| 3.0.0, host pool, MTP Q2 на CPU | 2,329 | 49,85 | 31,16 | 6,161 | MTP замедляет |
| 3.0.0, без host pool | 7,947 | 46,34 | 15,91 | 12,070 | Экономия RAM слишком дорогая |
| 3.0.0, host pool, `CHAIN_LAYERWISE=0` | 2,131 | 53,65 | 34,16 | 5,620 | Улучшения не найдено |

### MTP

Стандартный `mtp-Qwen3.8-Flash-Next-Q2_0.gguf` прошёл upstream compatibility check.
Acceptance в длинных прогонах был примерно 72–77%, до 2,51 tokens/forward. Однако draft head
на текущем HIP chain выполняется на CPU: итоговый decode стал медленнее baseline примерно
на 11%, а TTFT вырос. Поэтому файл и опция сохранены, но `Q38_MTP=0` по умолчанию.

MTP GGUF из внутреннего каталога Strata (`qwen4exp-mtp`, собственный `strata.mtp.*` format)
напрямую несовместим с Colibri. Для теста использован отдельный стандартный `qwen4exp` GGUF.

### Host pool

`COLI_CUDA_CHAIN_POOL=0` сократил наблюдаемый запуск примерно с 194 до 80 с и RSS контейнера
примерно с 40 до 5 GiB. Но prefill стал в разы медленнее. Для Qwen на машине с 60 GiB RAM
основной профиль оставляет pool включённым. Для Flint действует другой путь размещения;
эту Qwen-настройку нельзя механически переносить на все архитектуры.

## GLM-5.3-Flash UD-IQ2_XXS: реальный запуск и измерения

### Целостность и import

Все четыре части скачаны полностью и проверены командой `make verify-model-glm53-flash` по
официальным Hugging Face LFS SHA-256. Общий размер — 101 844 951 904 байта (94,85 GiB).

| Shard | Байтов | SHA-256 |
|---|---:|---|
| `GLM-5.3-Flash-UD-IQ2_XXS-00001-of-00004.gguf` | 9 429 984 | `337870cefce5fb34b2aa3ade54a0fbf61676697f7f9a906670c20edde74561f4` |
| `GLM-5.3-Flash-UD-IQ2_XXS-00002-of-00004.gguf` | 49 896 298 080 | `d51a3d9ca05022d53e71753df75ee64ed5fd4e47655650ae023e9717b3ec158d` |
| `GLM-5.3-Flash-UD-IQ2_XXS-00003-of-00004.gguf` | 49 248 507 840 | `89180f13784dc1128586b98adf1ca876279881a20bc4f01747703ce352563372` |
| `GLM-5.3-Flash-UD-IQ2_XXS-00004-of-00004.gguf` | 2 690 716 000 | `9e0ef47daa1fdffce3cf2ac1594ce4634d176ad018be6e692729757f38d5fbf6` |

Проверки сохранены в `data/benchmarks/glm53-all-sha256.log` и повторно после всех серий — в
`data/benchmarks/glm53-all-sha256-final.log`; постоянная копия ожидаемых хэшей —
в `checksums/glm53-flash.sha256`. Первый файл действительно маленький: в этом split GGUF он в
основном содержит metadata; проверка не подменяет его другой частью.

Полный import в Colibri определил `glm5-next`, 45 слоёв (34 KDA + 11 MLA/DSA), из них 42 sparse,
288 routed-экспертов, 8 активных на токен и 3 начальных dense-слоя. Движок прочитал четыре части
как один checkpoint: 38 435 tensors, 1283 renamed и 129 fused expert tensors split per expert.
Реальный non-stream smoke завершился HTTP 200 с ответом `4`, `prompt_tokens=26`,
`completion_tokens=2`, за 29,091 с. Это уже inference полной модели, а не header-only preflight.

### Старт, размещение и память

В базовом образе `rocminfo` видел R9700 и HIP-инференс работал, но `coli plan` не находил GPU:
upstream planner на Linux использует отдельную команду `rocm-smi`. Она добавлена в оба Dockerfile
вместе с DRM runtime для ROCm-варианта. Ниже — фактический запуск с `--ram 48`, `--ctx 8192`,
одним KV slot и уже существующим metadata directory:

- от `container StartedAt` до `OpenAI-compatible API listening` прошло **179,0 с**;
  сам warmstart занял **162,1 с**; smoke завершился примерно через 208 с после старта;
- GPU tier получил budget **25,16 GiB = 3421 expert slots**; после smoke занято 24,40 GiB;
- pinned host pool получил **39,25 GiB = 5337 expert slots**; warmstart заполнил суммарно
  **8758 slots** на GPU и в host pool за 162,1 с;
- отдельный CPU LRU после выделения host pool имеет cap 8 slots на sparse layer. Строка
  `96 per layer` раньше в журнале — исходный capacity этого LRU, а не число экспертов модели;
- 530 dense matrices заняли **5,31 GiB VRAM**, KV cache для 11 DSA layers при 8k — около
  **0,28 GiB**. Максимум host sysfs в direct JSON-run — **31,38 GiB VRAM**;
- runtime snapshot после smoke: Docker `MemUsage=50,42 GiB`, cgroup `memory.peak=53,13 GiB`;
  после полного `/api` — соответственно 48,23 GiB и 53,38 GiB (cgroup current 52,09 GiB).
  Эти величины не противоречат друг другу: Docker `MemUsage` исключает inactive file pages,
  а snapshots относятся к разным моментам серии;
- на первом smoke зафиксированы 1019 disk loads и 71,2% routed-expert обращений к device tier.
  Hit rate в последующих ответах меняется: это не постоянная гарантированная residency.

Таким образом, ранний header-only план с projected 4150 GPU experts и 73% residency не используется
как результат. Полные веса на R9700 не помещаются: холодные эксперты подгружаются по маршрутизации,
что объясняет большие TTFT и низкий decode ниже. Startup — наблюдение одного реального запуска,
а не контролируемый cold-boot benchmark со сброшенным page cache.

### Direct и Open WebUI

Все строки — `decode`, 192 токена, один warm-up и медиана трёх измерений. В этих GLM-запусках
backend возвращал текст непосредственно в `content`, без отдельного `reasoning_content`, поэтому
`content_ttft_s` совпадает с TTFT. У Qwen/Flint длинный budget может целиком уйти в reasoning;
это отражено в их JSON отдельно и не переносится на GLM.

| Backend / HTTP path | TTFT, s | Decode, tok/s | Gross, tok/s | Всего, s | VRAM max |
|---|---:|---:|---:|---:|---:|
| Colibri direct `/v1` | 26,876 | 2,12 | 1,60 | 120,284 | 31,38 GiB |
| Colibri → Open WebUI `/openai` | 23,285 | 2,15 | 1,72 | 111,870 | 31,38 GiB |
| Colibri → Open WebUI полный `/api` | 22,631 | 2,19 | 1,76 | 109,358 | 31,38 GiB |

Short case сильно зависит от естественной длины ответа и прогретого expert cache: direct median
составил 38,214 с при 35 completion tokens, а `/openai` — 30,109 с при 38 tokens. Поэтому вывод
о скорости делается по fixed-budget decode, а не по сравнению разных short answers. Более быстрый
proxy в отдельных сериях не означает ускорение Open WebUI: порядок запусков и expert/cache history
у GLM дают эффект намного больше обычного proxy overhead.

Финальные runtime/logs: `data/benchmarks/matrix-colibri-glm-runtime-final.json` и
`data/benchmarks/matrix-colibri-glm-container-final.log`. Все benchmark JSON/CSV, включая short,
сохраняются без текстов ответов по умолчанию; usage и finish reason доступны для проверки.

## Что ещё измерять

Для следующего раунда полезны отдельные серии:

1. длинный prefill (`--case prefill`) при 8k/32k context;
2. стабильность на 20–30 повторах, а не только три;
3. параллельные запросы и `COLIBRI_KV_SLOTS` — текущие числа описывают только concurrency=1;
4. холодный старт после явно контролируемого сброса page cache — без этого нельзя сравнивать
   секунды загрузки как строгий benchmark;
5. отдельный GLM cache/tuning-run: холодный и прогретый expert cache, другие GPU/host budgets и
   стабильность disk loads; текущая матрица сравнивает serving paths, а не оптимизирует GLM.

Сырые JSON/CSV этой машины находятся в gitignored `data/benchmarks/`. Автоматически построенная
таблица всех 18 поддерживаемых ячеек (36 case-строк) — `data/benchmarks/final-summary.md`.
