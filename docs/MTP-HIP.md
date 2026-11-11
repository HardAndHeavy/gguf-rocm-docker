# Qwen3.8 MTP на ROCm/HIP: исследование перед вкладом

Снимок исследования: 9 ноября 2026. GPU — Radeon AI PRO R9700, `gfx1201`, 32 GiB.
Рабочий репозиторий закрепляет Colibri `main` на
[`0a5504a1`](https://github.com/JustVugg/colibri/commit/0a5504a1dc64f86fcd0fe7db298b0448c730e7e6).

## Главный результат поиска

**Писать новый GPU MTP head не нужно:** Colibri PR
[#2559 «qwen38 cuda chain: the MTP head on the card, on by default»](https://github.com/JustVugg/colibri/pull/2559)
уже влит в `dev` merge commit
[`457402e4`](https://github.com/JustVugg/colibri/commit/457402e4f68ce173fb843553177b50cd2543882d).
В HIP-сборке используется тот же `COLI_CUDA`/`cuda_chain` код через HIP compatibility layer.
Полезный вклад — **собрать и проверить этот код на R9700, затем исправить только доказанные
HIP-specific проблемы**. Опубликованные в PR цифры получены на NVIDIA RTX PRO 4000, не на ROCm.

Исследованный `dev`:
[`0a6f235b`](https://github.com/JustVugg/colibri/commit/0a6f235b0c7a20726e28e6e0229ef1201de74638).
В PR сообщается рост примерно с 53,3–54,0 до 71,7–72,3 tok/s на NVIDIA; это не обещание
такого результата на R9700.

## Почему pinned main исполняет draft на CPU

1. [`qwen38.c`](https://github.com/JustVugg/colibri/blob/0a5504a1dc64f86fcd0fe7db298b0448c730e7e6/c/qwen38.c#L2895-L2908)
   отключает MTP рядом с CUDA/HIP chain, если явно не задан `Q38_MTP=1`, и прямо сообщает,
   что head выполнялся бы на CPU.
2. [`q38cc_forward`](https://github.com/JustVugg/colibri/blob/0a5504a1dc64f86fcd0fe7db298b0448c730e7e6/c/qwen38_cuda_chain.h#L1651-L1759)
   копирует четыре hyper-connection streams в mapped host buffer (`cc_copy`), делает
   `cc_finish`, затем `memcpy` в `hyper_h`.
3. [`q38_mtp_rows`](https://github.com/JustVugg/colibri/blob/0a5504a1dc64f86fcd0fe7db298b0448c730e7e6/c/qwen38_core.h#L5582-L5622)
   имеет device dispatch только для Vulkan. CUDA/HIP падает в host `q38_mtp_input` →
   `q38_layer_forward` → `q38_gr_read`/`q38_mtp_best_token`. Более глубокие drafts повторяют
   это в `q38_mtp_draft_more`.
4. Router/MoE основной chain также содержит host hand-off: `cc_copy`, ожидание `cc_submit(1)`,
   host `q38_moe_ex`, upload routed rows. Примитивы в
   [`cuda_chain.cu`](https://github.com/JustVugg/colibri/blob/0a5504a1dc64f86fcd0fe7db298b0448c730e7e6/c/cuda_chain.cu#L1667-L1703):
   `cudaMemcpyAsync`, `cudaEventRecord`/`cudaEventSynchronize`, `cudaStreamSynchronize`.
   В HIP-сборке они отображаются на HIP в
   [`backend_gpu_compat.h`](https://github.com/JustVugg/colibri/blob/0a5504a1dc64f86fcd0fe7db298b0448c730e7e6/c/backend_gpu_compat.h).

Следовательно, это не специальный запрет AMD: в pinned revision отсутствует CUDA-chain device
entry point. Простое изменение одного флага не переносит head на GPU.

## Что уже сделано в PR #2559

| Commit | Изменение |
|---|---|
| [`211593eb`](https://github.com/JustVugg/colibri/commit/211593ebad5c812cbee5213284893e9ff6e8f773) | `q38cc_mtp_rows`: input, QSA attention, shared expert, mixer и lm_head на карте; CPU fallback `Q38_MTP_CHAIN=0` |
| [`e7a846ba`](https://github.com/JustVugg/colibri/commit/e7a846ba407d34e4e9dd69ad9bbfb4b48bcd0353) | Routed experts через pool server |
| [`b15ddbdf`](https://github.com/JustVugg/colibri/commit/b15ddbdf5bc281cea0b5ef04df12353481b834a4) | Scoring/pick draft rows на device |
| [`d643139f`](https://github.com/JustVugg/colibri/commit/d643139f1d396f418682dc94df2518569e17d38d) | Q2_0 head experts и routing/compute на device |
| [`87101edf`](https://github.com/JustVugg/colibri/commit/87101edf4723de28f34d65b15d004879d161ffbe) | Default-on там, где device head доступен |

Актуальные точки входа: [`q38cc_mtp_rows`](https://github.com/JustVugg/colibri/blob/0a6f235b0c7a20726e28e6e0229ef1201de74638/c/qwen38_cuda_chain.h#L3530-L3675)
и CUDA dispatch в [`q38_mtp_rows`](https://github.com/JustVugg/colibri/blob/0a6f235b0c7a20726e28e6e0229ef1201de74638/c/qwen38_core.h#L5694-L5709).
Для поэтапной изоляции есть `COLI_CUDA_CHAIN_MTP_CARD=0` и `COLI_CUDA_CHAIN_MTP_POOL=0`.

Другая релевантная история Colibri: [#1832](https://github.com/JustVugg/colibri/pull/1832)
(lossless CPU MTP), [#1927](https://github.com/JustVugg/colibri/pull/1927) (Vulkan MTP experts),
[#2193](https://github.com/JustVugg/colibri/pull/2193) (почему CPU draft проигрывает полной chain),
[#339](https://github.com/JustVugg/colibri/pull/339) (исходный HIP backend).

## Что найдено в llama.cpp

llama.cpp строит MTP как обычный backend graph и не требует CPU draft: см.
[`qwen4exp.cpp`](https://github.com/ggml-org/llama.cpp/blob/e01c9f1875e8a96674756ed144aa9701498b83dd/src/models/qwen4exp.cpp#L577-L667)
и [`common/speculative.cpp`](https://github.com/ggml-org/llama.cpp/blob/e01c9f1875e8a96674756ed144aa9701498b83dd/common/speculative.cpp#L2705-L2834).
CPU placement включается отдельными `--spec-draft-*`/tensor override опциями. Это semantic
reference, а не код для копирования в другой runtime.

Открытые/закрытые reports, важные для HIP validation:

- [llama.cpp #31495](https://github.com/ggml-org/llama.cpp/issues/31495), **open**: HIP draft-MTP
  снижает prefill на 74–80% в reported Qwen3.8-27B setup, decode при этом ускоряется. Поэтому
  нельзя измерять только decode.
- [llama.cpp #29811](https://github.com/ggml-org/llama.cpp/issues/29811), **open**: Flash-Next +
  separate MTP GGUF, HIP/R9700 assertion в QSA k-pool.
- [llama.cpp #29868](https://github.com/ggml-org/llama.cpp/issues/29868), **closed/completed**:
  ROCm dual-GPU tensor split + MTP freeze.
- [llama.cpp #31569](https://github.com/ggml-org/llama.cpp/pull/31569), **merged**: auto-fit учитывает
  skipped NextN layers; иначе слой мог непреднамеренно остаться на CPU.

## План эксперимента на R9700

Образ `gguf-rocm-colibri:mtp-dev-0a6f235b` собирается отдельно от stable. Его metadata пишется в
отдельный state directory, stable image и baseline не перезаписываются.

1. **A: non-MTP** — тот же `dev`, MTP выключен. Проверяет отсутствие регрессии самого обновления.
2. **B: CPU head** — `Q38_MTP=1 Q38_MTP_CHAIN=0`; контроль старого поведения.
3. **C: консервативный device path** — `Q38_MTP=1`,
   `COLI_CUDA_CHAIN_MTP_CARD=0 COLI_CUDA_CHAIN_MTP_POOL=0`.
4. **D: полный #2559** — включить pool/card paths по одному. Сохранить acceptance и tokens/forward.
5. Depth 1–3, forced accept/mixed/reject, prompt prefill + decode, повторное использование slots,
   host/pool/card fallback. Сравнить токены/final logits с non-speculative там, где upstream harness
   это поддерживает; просто совпадение одной фразы недостаточно.
6. Fixed decode 192 tokens + полный `agent_benchmark.py`. Один warm-up и три measured runs как
   минимум; для принятия маленького эффекта — interleaved A/B и больше повторов.
7. Если device path не ускоряет: профилировать HIP events и host mapped copies до оптимизации.
   Замерять отдельно draft input/attention/experts/lm_head, verify, D2H/H2D и каждую sync.

### Фактические результаты на R9700

Прогнан pinned `dev` `0a6f235b` в отдельном образе, context 8192, один slot, тот же Qwen3.8
Flash Next IQ2_XS и Q2 MTP. Для throughput — один warm-up, три measured runs, UUID в prompts,
медиана; полные JSON/CSV и container logs лежат в `data/benchmarks/mtp-hip-*`. Во всех четырёх
сериях выполнены все measured requests.

| Профиль | Decode total, s | TTFT, s | Decode, tok/s | Gross, tok/s | Prefill TTFT, s |
|---|---:|---:|---:|---:|---:|
| MTP off | 5,679 | 1,846 | 50,48 | 33,81 | 31,602 |
| CPU head | 6,687 | 2,064 | 41,31 | 28,71 | 35,293 |
| Device, host experts (`conservative`) | 5,296 | 1,863 | **55,16** | **36,25** | **32,776** |
| Device + card/pool experts (`full`) | 5,425 | 1,909 | 54,12 | 35,39 | 33,717 |

Device conservative дал +9,3% к MTP-off и +33,5% к CPU head по decode; full — соответственно
+7,2% и +31,0%. Разница conservative/full всего около 2%, поэтому победитель между ними без
interleaved repeats не объявляется. По первым 14 turns каждой throughput-серии (correctness и
все speed cases): CPU — 76,2% acceptance и 2,041 tokens/forward, conservative — 72,5% и 2,081,
full — 71,4% и 2,087. Prompts содержат UUID, поэтому acceptance между сериями не является
повтором одного и того же текста.

**Важно:** в основной MTP-off серии оставлен независимый prompt lookup (`COLI_LOOKUP=1`). Это
практический MTP-off preset, но не абсолютный no-speculation baseline. Для чистого измерения
только MTP нужна отдельная серия с lookup off во всех сравниваемых профилях. Также пока не
доказано отсутствие регрессии `dev` против `main`: исторические stable числа получены при другом
cache/history state и не подставляются в эту таблицу.

Functional benchmark (три measured runs после warm-up):

| Профиль | Agent | Agent wall median | Coder | Coder wall median |
|---|---:|---:|---:|---:|
| MTP off | 3/3 PASS | 29,071 s | 3/3 PASS | 14,709 s |
| Device full | 3/3 PASS | **25,228 s** | 3/3 PASS | **11,220 s** |

Каждый agent run сделал три HTTP requests, четыре валидных tool calls и завершился реально
зелёными tests; coder source также применялся к свежему fixture и проходил tests. Full сократил
медианное wall time на 13,2% (agent) и 23,7% (coder), но сгенерированные token counts различаются,
поэтому это результат конкретного smoke task, а не универсальный коэффициент ускорения.

Upstream `qwen38-cuda-chain-check` и `qwen38-tiny-mtp-check` пройдены с точно требуемым
`transformers==5.16.1`: accept/mixed/reject, rollback, device head, prefix reuse/pins/logprobs и
byte identity tiny BF16/FP8/int4 variants. Лог — `data/colibri-mtp-unit.log`.

Дополнительно все четыре профиля перезапущены с `COLI_LOOKUP=0` на одних fixed prompts
(`mtp-hip-*-nolookup-correctness.json`). Это single cold correctness runs, **не performance
результаты**. В short case conservative и full совпали с off по content, reasoning и 66 tokens;
CPU дал тот же видимый ответ, но другой reasoning и 64 tokens. В 192-token decode case у всех
профилей budget ушёл в reasoning, и reasoning hashes различны. Сводка —
`data/benchmarks/mtp-hip-nolookup-comparison.json`. Следовательно, byte identity полной модели
на HIP не заявляется: placement/history и batched verify могут менять floating-point путь, а один
cold run не отделяет эти факторы. Для upstream bug report нужен повторный controlled baseline и
token/final-logit comparison; видимый короткий ответ во всех профилях правильный.

### Критерии PR

- output correctness не хуже baseline; accept/reject/rollback покрыты;
- ускорение повторяется на сохранённых JSON/логах и не является следствием другого prompt/context;
- non-MTP не регрессирует;
- нет silent CPU fallback: placement виден в логе;
- prefill и полная agent task не скрыты за одним красивым decode числом;
- патч минимален относительно #2559 и содержит upstream regression test.

## Текущий статус: A и B расследуются отдельно

**A — регрессия без MTP.** На сопоставимых state snapshots и с `COLI_LOOKUP=0`
main `0a5504a1` дал 45,45 tok/s, dev `0a6f235b` — 37,26 tok/s: −18,0% decode.
Источники: `data/benchmarks/mtp-hip-off-{main,dev}-nolookup-controlled.json`
и соответствующие `-config.env`, `-container.log`, `-runtime.json`.
Это наблюдение, а не доказательство причины: нужен interleaved повтор и bisect/profile.
Нельзя автоматически обвинять MTP PR или считать одинаковыми внутренние code paths.

В отдельной controlled dev-серии с lookup off: off / CPU / full device =
36,88 / 43,38 / 54,73 tok/s (`mtp-hip-{off,cpu,gpu-full}-nolookup-controlled.json`).
Эти результаты заменяют ранние сравнения с lookup on для изоляции MTP, но не отменяют A.

**B — HIP memory fault.** При `chat_template_kwargs.enable_thinking=false` device MTP
в full и conservative падает с `HSA_STATUS_ERROR_MEMORY_FAULT`; runtime указывает
`gemv_i8_w4<4>`. Off/CPU работают; `COLI_CUDA_GEMV_W4=0` **либо**
`COLI_CUDA_GEMV_SK=0` обходят падение. Это локализация, не root-cause fix.
Асинхронная ошибка может обнаружиться позднее первичного повреждения памяти;
название faulting kernel само по себе не доказывает виновника.

Источники: `data/benchmarks/mtp-hip-gpu-{full,conservative}-nolookup-nothink-container.log`,
`mtp-hip-gpu-full-nolookup-nothink-{now4,nosk}-correctness.json` и их config/logs.
Standalone `test_gemv_rows_cuda` прошёл на HIP (`data/colibri-gemv-rows-hip.log`),
но это не покрытие падающего full-model path и не доказательство безопасности всех shapes.
Всё `data/` gitignored: эти файлы локальные, **не приложены к репозиторию**.

## Результат ограниченной сессии 11 ноября

Подготовлены два отдельных английских черновика (на момент подготовки ещё не отправлены):
[issue A](issues/colibri-A-non-mtp-regression.md) и
[issue B](issues/colibri-B-hip-device-mtp-fault.md), с компактными sanitised attachments
в `docs/issues/evidence/`. Полные исходные logs остаются локально в `data/`.

Статус проверен 11 ноября: опубликованы [A — #2757](https://github.com/JustVugg/colibri/issues/2757)
и [B — #2758](https://github.com/JustVugg/colibri/issues/2758), оба открыты.
Локальные drafts сохранены как история подготовки. Ответ по B получен; поздний
[allocator follow-up](issues/issue-B-allocator-followup.md) завершил два fresh-snapshot
full-model процесса (automatic / forced three drafts) без fault, readiness 203/244 s.
Исторический FAIL не воспроизведён; сериализация и persistent scratch не выполнялись.
Ранние startup-limited attempts ниже остаются отдельными inconclusive результатами.

- **A:** исходные JSON/CSV перепроверены: 45,4526 → 37,2574 tok/s (−18,0302%).
  Это исторические thinking-enabled серии (`request={}`), не текущий no-thinking default.
  Найдены различия placement/pool paths; причинность и process-level interleaved repeats
  не установлены. Новый performance benchmark/bisect не запускался.
- **B:** `bash scripts/check-colibri-gemv-hip.sh` выполнил CPU-reference тест на pinned dev
  image, `docker run --network none`, W4 on, split-K on/off в отдельных процессах.
  K=2048/N=300 **не выбирает W4**: N*K ниже 2^21. Добавлены K2048/N1100 и K10240/N300;
  лог подтверждает реальный W4 и splits. S4 и четыре S1, три повтора, 144 row records:
  ноль ошибок по заранее заданному `abs <= 1e-3 + 1e-4*abs(ref)`, нет NaN/Inf и повреждения
  внешних output guards. На K10240/N300 split-off снижает sr с 4 до 1 из-за shared memory,
  поэтому обход SK=0 не изолирует только split reduction. Build O2, не production O3;
  synthetic PASS не доказывает безопасность полной модели и не находит root cause.
- **Integration:** `scripts/check-colibri-mtp-direct.py` использует только direct Docker,
  host network и API bind `127.0.0.1:18080`, отдельные копии state, без compose/OpenWebUI.
  Две ограниченные попытки off/full не достигли API readiness (~198/~183 s), chat requests
  **не отправлены**; нового воспроизведения fault или correctness результата нет.
  CPU/SK0/W40 пропущены по лимиту. Старые fault/controls не смешиваются с новыми попытками.
  Контейнеры удалены. Детали, ограничения и post-run правки runner описаны в issue B.

Минимального обоснованного fix/PR нет. Согласно лимиту исследования дальнейшие долгие
tracing/bisect отложены до ответа maintainer'а или релевантного upstream update.

## Исходный план узкого теста (исторический)

Ниже исходная спецификация; её результат и уточнение dispatch описаны выше. Это не
утверждение, что K2048/N300 проверяет W4. Сначала уточнить в исходнике порядок
размеров: зафиксировать K=2048, N=300 (или явно объяснить иной порядок), NR=4,
layout/strides, dtype/quantization, padding и dispatch predicate. Нет гарантии, что этот
shape автоматически попадёт в нужный W4/split-K kernel.

1. На закреплённом base создать deterministic входы, включая хвост N=300.
   Сохранить seed, build flags, ROCm/compiler, GPU и image digest.
2. Один и тот же вход прогнать **в двух отдельных процессах**: split-K on/off,
   W4 включён. Подтвердить фактически выбранный kernel и число splits логом/trace.
   Флаги могут читаться один раз и кешироваться — не переключать их внутри процесса.
3. Проверить **каждую из четырёх строк относительно CPU reference**, а не только on vs off.
   Reference должен использовать те же деквантованные веса/входы; пороги abs/rel error
   определить заранее по формату и накоплению. Проверять NaN/Inf, max error, sync/launch
   errors; canary/guard regions, если harness позволяет. Один успешный exit недостаточен.
4. Для отделения multi-row/NR4 от split-K добавить NR=1 и при возможности 4 отдельных
   single-row вызова, сохранив тот же dispatch. Если путь иной, явно это отметить.
   Повторы обязательны: race/uninitialised scratch может быть недетерминированным.
5. Если только split-K on падает/ошибается, исследовать scratch, bounds/tail, reduction и
   stream lifetime. Если оба — NR4/layout/bounds. Это направления проверки, не диагноз.
   Если оба проходят — не отключать kernel глобально: переходить к integration trace.

### Настоящий HIP integration regression

- Взять точный падающий prompt из `scripts/benchmark.py` (`short`/`decode`) и конкретного
  `*-nothink-correctness.json`; сохранить сообщения, budget, request JSON и hash модели.
  Не сокращать prompt до проверки, что минимизация сохраняет сбой.
- Стартовать fresh процесс и контролируемую копию state для каждого варианта; lookup off,
  одинаковые weights/context и request order. Runner по умолчанию использует общий dev state:
  для независимых опытов явно задавать `COLIBRI_STATE_DIR` и уникальный `LABEL_SUFFIX`.
- Проверить обе формы prompt (падающую no-thinking и контроль thinking), MTP off/CPU/device,
  затем отдельно W4/SK on/off. Ловить смерть процесса, timeout, memory fault **и неверный ответ**.
- Отдельно сохранить короткий standalone repro и full-model HIP test. Upstream tiny CPU
  или mocked tests не заменяют реальный HIP запуск. После patch повторить обычный NR=1,
  MTP/non-MTP decode, prefill и agent/coder: исправление B не должно маскировать A.

Локальный repro B (останавливает текущий backend; может уронить HIP процесс):

```bash
COLI_LOOKUP=0 CORRECTNESS_ONLY=1 LABEL_SUFFIX=-repro-nothink \
COLIBRI_STATE_DIR=./data/colibri-mtp-repro \
  bash scripts/run-colibri-mtp-hip.sh gpu-full
# Контроли — отдельные запуски с уникальными state/label:
# COLI_CUDA_GEMV_SK=0   либо COLI_CUDA_GEMV_W4=0
```

Это существующий runner, не минимальный standalone reproducer. Модель/head и pinned dev
образ должны быть подготовлены заранее; no-thinking уже является default request runner.

## Порядок взаимодействия с upstream

Сначала подготовить sanitised repro bundle (команда, revisions/digests, model hashes,
точный request, логи fault, CPU/W4/SK controls), затем **после разрешения владельца**
открыть focused discussion/issue. Пока ничего не отправлено. Не ждать ответа для локального
теста, но согласовать base до реализации большого patch. A и B не смешивать в один fix.

Черновик с двумя вопросами (не отправлен):

> Hi @JustVugg! I tested #2559 on Radeon AI PRO R9700 (gfx1201, ROCm/HIP),
> main 0a5504a1 vs dev 0a6f235b. I have two separate observations, not proven related:
> (A) non-MTP decode drops from 45.45 to 37.26 tok/s on comparable state snapshots,
> lookup disabled; (B) device MTP with enable_thinking=false faults with
> HSA_STATUS_ERROR_MEMORY_FAULT reported in gemv_i8_w4<4>. CPU/off work;
> disabling W4 or split-K avoids the fault, but I do not consider those fixes.
> The existing standalone GEMV rows test passes on HIP. I plan a 2048 x 300,
> four-row split-K on/off CPU-reference test plus a real HIP prompt regression.
> Which base revision would you recommend for a focused investigation/patch?
> Is this HIP fault already being investigated, or is there an existing fix/test to try?

Полезный PR — минимальный доказанный root-cause fix и regression test, без глобального
отключения быстрого пути и без деградации обычного режима. Отрицательный результат теста
тоже сохраняется; отсутствие падения не равно доказанной корректности.
