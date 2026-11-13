# A: matched rebuild и allocator-only контроль, 13 ноября 2026

> **Актуальный статус:** [SK0 ABBA](A-SK0-ABBA.md) и [bounded trace](A-SK0-TRACE.md) выполнены. Rebuild/allocator-only и последующий SK0/trace follow-up отправлены пользователем. Ждём maintainer; новых diagnostic patches пока нет.

Предыдущий forced-bus follow-up пользователь отправил в #2757; отправка подтверждена в GitHub. Затем выполнены **два ограниченных эксперимента, 8 новых процессов**. Новый [английский follow-up](issue-A-rebuild-allocator-ready-to-post.md) **отправлен пользователем**.

## Вывод

1. **История сборки не объясняет разрыв.** Чистые old/new сборки одинаковым Dockerfile, pinned base, compiler/flags и пакетами воспроизвели old ~40 против new ~27 tok/s. Их `qwen38` побайтно совпадают с соответствующими прежними бинарниками.
2. **Откат только persistent split-part acquisition не восстановил скорость.** На одной новой ревизии async-only диагностический вариант остался в диапазоне ~25–26 tok/s против ~26–28 штатного. Не предлагаем такой откат как performance fix и не называем allocator установленной причиной.
3. На этом серия остановлена. Следующий полезный шаг — focused S=1 backend/kernel timing, а не ещё один общий old/new benchmark или массовый bisect. Согласовать диагностику с maintainer; кандидаты в исходниках пока не причины.

Рабочие pins, `.env`, модели и исходный state не менялись. Тестовые контейнеры удалены, чужие контейнеры не останавливались. Диагностический образ остался только отдельным tagged image, не production.

## 1. Контроль чистой сборки

Обе ревизии собраны `--no-cache` одним архивированным `docker/colibri.Dockerfile`, `HIP_ARCH=gfx1201`, base **`llama-rocm@sha256:f5a7d22b7e360e19c7ab43cd91c7c51bc5df15ace4f4897d0d3ed5dce2c4790e`**. Это фактический `FROM`, не унаследованный OCI label от более раннего base.

- Old `0a6f235b0c7a20726e28e6e0229ef1201de74638`: image `a989a4141762…`, тег `gguf-rocm-colibri:rebuild-old-20261113`.
- New `b92eccd79ac60f196146f784c241ea076adda6f6`: image `7de12e467442…`, тег `gguf-rocm-colibri:rebuild-new-20261113`.
- Все **545 dpkg entries совпали**. HIP 7.16.26385-0000000, AMD clang 24.0.0git / LLVM d6f6cb69; GCC 15.2.0, glibc 2.43.
- GPU compile: `hipcc -O3 -std=c++17 -x hip --offload-arch=gfx1201 -Wall -Wextra -fPIE`; CPU `-O3 -march=x86-64-v3 -fopenmp -pthread`.
- SHA-256 rebuilt `qwen38` **совпадает с прежним бинарником каждой ревизии**: old `33f6b28e5a1c687860cd21702622a83db1aa83f3f0d6462dfe1e14ce09c95668`, new `281f028f27bd0b91f7ada8fd89fcafee5f3d9472d8a3eaf5a7bd79987fefc83c`.

Forced bus везде, MTP/lookup off, thinking override отсутствует, context 8192, RAM 48, OMP 8. Порядок old/new/new/old, общий snapshot восстановлен в один путь перед каждым процессом; matching prompt hashes внутри серии. Preliminary short/decode, short warmup+3 и decode warmup+3. Streaming usage, greedy, max_tokens192. Rates `(completion_tokens-1)/(last_token-first_token)`, не end-to-end throughput.

| Процесс | Ревизия | Decode 1 | Decode 2 | Decode 3 | Медиана tok/s |
|---|---|---:|---:|---:|---:|
| 1 | old | 40.1484 | 40.3336 | 39.6054 | **40.1484** |
| 2 | new | 27.1675 | 26.7506 | 27.2156 | **27.1675** |
| 3 | new | 27.6568 | 27.5207 | 27.6680 | **27.6568** |
| 4 | old | 40.8536 | 40.7593 | 40.8838 | **40.8536** |

New/old: **−32.33%** в первой паре, **−32.30%** в обратной. Это подтверждает gap между pinned revisions в данном workload, но не локализует его в #2775: между ревизиями есть другие изменения, generated trajectories не являются token replay.

## 2. Allocator-only A/B на одной новой ревизии

Stock new `7de12e467442…` против дочернего диагностического `c23c6a185d9b…` (`gguf-rocm-colibri:b92eccd7-sk-async-diagnostic`). Изменена **одна source statement**: вызов `gemv_sk_part` в HIP callsite заменён комментарием. `own` остаётся 0; существующий fallback использует `cudaMallocAsync/cudaFreeAsync` (на HIP — соответствующий HIP API).

Математика, W4, split-K, split selection/launch formulas не менялись. `cuda_chain.o`, chain header, Makefile и packages совпадают с parent. Source SHA-256 после патча `fc3da8248b66a0ea72c387386bcd117e83a1b62492dc23345154c32d8e3fa0bd`; helper требует исходный SHA и ровно один anchor, fail-closed. Обычная O3-сборка `make qwen38 ARCH=x86-64-v3 HIP=1 HIP_ARCH=gfx1201`; source изменён только внутри disposable image. [Диагностический diff](evidence/A-allocator-only-diagnostic.patch) — **не предлагаемый upstream fix**.

| Процесс | Вариант new b92eccd7 | Decode 1 | Decode 2 | Decode 3 | Медиана tok/s |
|---|---|---:|---:|---:|---:|
| 1 | stock persistent | 27.4553 | 27.8072 | 27.7410 | **27.7410** |
| 2 | async-only diagnostic | 25.6721 | 24.6430 | 26.2419 | **25.6721** |
| 3 | async-only diagnostic | 24.8218 | 26.5015 | 26.3496 | **26.3496** |
| 4 | stock persistent | 26.3968 | 25.4735 | 26.9540 | **26.3968** |

Async/stock −7.46% и −0.18% в двух парах. Этих данных недостаточно для заявления о superiority/equivalence allocator; важнее **отсутствие восстановления ~40 tok/s**. В raw plan `old` означает stock, `new` — diagnostic, не другую ревизию.

Все **8 соответствующих throughput/warmup response texts** (content + reasoning, short/decode × 4) совпали между четырьмя процессами. Это наблюдаемая text agreement, не доказательство logits parity или полной корректности.

## Телеметрия и ограничения

Все 24 measured decode двух серий: HTTP 200, 192 completion tokens, `length`, reasoning без финального visible answer. В 8 процессах не записано request/engine/GPU faults или telemetry collection errors. Все pre-run manifests совпали с общим snapshot, source integrity unchanged; env одинаковы. UUID corpus общий внутри серии, но не заявляется одинаковым между двумя сериями.

Pool 33.02 GiB, 98.6% resident routes, 0 hybrid layer steps, 0 promotions во всех процессах. Rebuild residency counts 19186 в 1–2 и 19198 в 3–4; allocator серия — наоборот. Counts равны внутри соответствующих соседних пар, не доказывают одинаковый residency map.

Read-only telemetry ~1 Hz, GPU auto / CPU powersave, clocks не фиксировались; measured decode request windows **включают TTFT/prefill**. В rebuilt old/new медианы SCLK 3249/3286/3281.5/3242 MHz, MCLK 1258 MHz везде, power cap 300 W, median junction 74.5/75/76/79.5°C. Нет пониженной median SCLK у новых, но coarse samples не исключают throttling/короткие transients. Host CPU — aggregate, не attribution. Sampled docker lists содержали только тест и существовавший controller; это не исключение внешней host-нагрузки.

**Аномалия сохранена:** последний stock decode warmup allocator-серии — **12.86 tok/s**. В 7 telemetry samples этой фазы MCLK reported `freq2_input=96 MHz`, при часто высокой GPU busy; затем вернулась 1258 MHz. Причину не установили, warmup не скрыт и не переименован в measurement. Measured запросы этого процесса 26.40/25.47/26.95 также сохранены. Это ограничивает выводы о небольших различиях allocator-вариантов.

Allocator-hit trace/sanitizer не выполнялись; performance rollback не доказывает, какие именно вызовы были выполнены. Device MTP в этой серии **не проверялся**; это не результат по историческому fault B. Не делать вывод «allocator безопасен» или «ROCm невиновен».

Read-only source analysis отметил также GGUF GEMV rounded-FMA helpers и per-matmul tracking/cache bookkeeping как возможные активные изменения в S1. Никакие дополнительные kernels/математика не патчились, broad bisect не запускался. Следующее исследование должно измерить их вклад, а не объявить виновником по diff.

## Файлы

- [Английский follow-up](issue-A-rebuild-allocator-ready-to-post.md), отправлен пользователем.
- [Sanitised evidence](evidence/A-rebuild-allocator.json), [diagnostic patch](evidence/A-allocator-only-diagnostic.patch), [SHA-256](evidence/A-rebuild-allocator-SHA256.json).
- Raw rebuild: `data/colibri-investigation/rebuild-control/` — executed Dockerfile, build logs, input/base identity, manifests, build-comparison, source-analysis, summary.
- Rebuild benchmark: `data/colibri-investigation/pool-ab/20261113-131251/`.
- Diagnostic: `data/colibri-investigation/rebuild-control/allocator-diagnostic/`, benchmark `data/colibri-investigation/pool-ab/20261113-133252/`.

Новый software runner не менялся в этой серии; ранее добавленные **33 CPU tests PASS**. Архивы и helper находятся в gitignored `data/`; publicly пригодная выжимка не содержит ключа API или полных host paths. До публикации JSON и diff просмотреть отдельно.
