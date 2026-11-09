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

## Черновик вопроса maintainer'у

Публикуется только после подтверждения владельца репозитория; на момент исследования сообщение не
отправлялось. Предлагаемый канал — focused Colibri issue со ссылкой на #2559.

> Hi @JustVugg! I validated merged dev PR #2559 on an AMD Radeon AI PRO R9700 (gfx1201, 32 GiB,
> ROCm/HIP), rather than creating a parallel implementation. At pinned dev `0a6f235b`, fixed-budget
> decode medians were 50.48 tok/s without MTP, 41.31 with the CPU head, 55.16 with the conservative
> device head, and 54.12 with the full card/pool path. The upstream tiny accept/reject/rollback and
> byte-identity tests pass, and the full device path passed 3/3 agent and 3/3 coder smoke runs.
> I have saved per-run JSON, placement/acceptance logs and a no-prompt-lookup correctness series.
> Do you already know of HIP blockers on gfx1201, and would you prefer more testing of current dev
> wholesale or a minimal forward-port of #2559 onto main? In particular, conservative is only about
> 2% faster than full here, so I do not treat that difference as resolved. If a HIP-only fix is
> needed, would a focused PR with reproducible R9700 results be useful?

Возможные технические собеседники по прошлым HIP contributions: @huppiflupp и @noobdev-ph;
не упоминать их в первом сообщении без необходимости.
