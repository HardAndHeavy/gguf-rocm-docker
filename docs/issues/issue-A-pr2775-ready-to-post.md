<!-- Пользователь сообщил об отправке этого ответа 13 ноября 2026. Сохранённый локальный текст, не синхронизированная копия GitHub. -->

Retested the automatic host-pool decode choice against forced bus reads on PR #2775 merge **`b92eccd79ac60f196146f784c241ea076adda6f6`**. Both automatic processes selected the bus before the timed requests. The selected path works in this bounded test, but **this does not establish performance parity or resolve the historical performance report**.

### Setup and controls

- AMD Radeon AI PRO R9700 (`gfx1201`), Ryzen 7 3700X; model `Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS`.
- Image `gguf-rocm-colibri:pr2775-b92eccd7`, immutable ID `sha256:0e99d6b9f4148b30ba4aeeedf66cdeab26807a3c26489a03c426ab2d82dbf141`. HIP `7.16.26385-0000000`, AMD clang `24.0.0git` (ROCm LLVM `d6f6cb691863e9258034ab48c1dfce21689d5606`). Full model-content hashes and selected metrics/logs have been prepared in a local sanitized evidence bundle; no attachment has been uploaded by this draft.
- Four separate fresh server processes in **A–B–B–A** order: A = automatic (`COLI_CUDA_CHAIN_POOL_READ` unset), B = forced bus (`COLI_CUDA_CHAIN_POOL_READ=1`). This was not an auto-versus-forced-CPU comparison.
- MTP off (`Q38_MTP=0`), lookup off (`COLI_LOOKUP=0`), **no thinking override**. Common settings included `COLI_CUDA_CHAIN_POOL=1`, `COLI_CUDA_HOST_POOL=0`, `COLI_CUDA_CHAIN_LAYERWISE=1`, `COLI_CUDA_CHAIN_ROWS=64`, `COLI_NO_OMP_TUNE=1`, and `OMP_NUM_THREADS=8`; W4/split-K and serialization settings were left at defaults.
- The same metadata/history snapshot was restored to the **same path before every process**; source/snapshot integrity checks reported unchanged. The same prompt corpus, including the same per-request UUID markers, was replayed across processes, with fresh markers within each process. This controls the input snapshot and corpus, **not identical runtime placement or timing state**.
- Each process received preliminary short/decode checks, then a short warmup plus three measured short requests, then a decode warmup plus three measured decode requests. Requests were greedy, streaming with usage, and capped at 192 completion tokens. No dedicated prefill benchmark was run.
- No page-cache flush, CPU affinity, or clock/power controls were applied. This was not an isolated-host experiment.

### All measured decode results

Rates are streaming decode tokens/s, calculated as `(completion_tokens − 1) / (last_token_time − first_token_time)`, not end-to-end throughput. Warmups and preliminary requests are excluded. Each row contains all three measured decode requests for that process.

| Process / mode | Decode 1 | Decode 2 | Decode 3 | Median tok/s | Median TTFT, s |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 / A, auto | 24.90 | 28.02 | 24.00 | **24.90** | 1.909 |
| 2 / B, forced bus | 28.02 | 27.73 | 27.78 | **27.78** | 2.090 |
| 3 / B, forced bus | 28.11 | 28.60 | 28.03 | **28.11** | 2.069 |
| 4 / A, auto | 27.84 | 27.62 | 27.77 | **27.77** | 1.868 |

The first auto process is materially slower and must not be discarded: the first forced-bus median is **11.59% higher** than the first auto median (27.78 versus 24.90). In the later pair, auto is **1.19% lower** than forced bus (27.77 versus 28.11). These percentages use unrounded medians and different stated denominators; they are descriptive comparisons, not a causal speedup estimate. The later close result does not prove parity or explain the earlier spread.

All 12 measured decode requests completed with **192 completion tokens and `finish_reason=length`**. They emitted reasoning content rather than a visible final answer at this limit. TTFT therefore includes the first reasoning token; this is path/stream completion evidence, **not answer-correctness validation**. There were **no recorded request errors or detected engine/GPU faults** in these four runs.

### What the logs establish

Both automatic decisions are present in the **pre-measurement logs**, so their calibration was not part of the table's timed decode requests:

| Auto process | CPU calibration, ms/step | Bus calibration, ms/step | Choice |
| --- | ---: | ---: | --- |
| 1 / A | 54.34 | 41.22 | Bus |
| 4 / A | 44.88 | 36.66 | Bus |

Each automatic process reports **one measurement/decision**, not repeated sampling or a sustained search. The periodic remeasurement after 4096 decode steps was not reached in these processes.

Each automatic process's cumulative host-skip counter reaches **1003 hybrid layer steps without a host slot**, where the device continued without waiting for the host. These are whole-process counters, including preliminary requests and warmups—not 1003 newly skipped waits per measured request. Final logs show **zero expert promotions, zero evictions back to the pool, zero promotions in flight**, and **98.6% of routes resident on the card** in all four processes.

Despite the identical restored snapshot, startup placement was **19,186 resident experts in processes 1 and 2**, versus **19,198 in processes 3 and 4**. Consequently, snapshot restoration must not be described as proof of stable identical placement. The logs also show differing prompt-pool execution between auto and forced bus; selecting the same decode bus path does not make the complete process histories identical.

### Remaining uncertainty

Unrelated host work was observed during **process 2 / B**: an Ansible container started at 09:11:20 local time and was sampled at about **104% CPU (roughly one core)** at 09:13:50, with no GPU devices configured. This is a possible host-contention confound, not evidence that it caused the measured difference. Additional application/database containers appeared around **09:24**, after process 4's final log timestamp **09:22:50 local (06:22:50 UTC)**; those later containers are not evidence of overlap with process 4's measurements.

The absolute rates here remain below the historical **40–41 tok/s**, but there is **no contemporaneous old-revision performance control** in this ABBA set. That gap cannot be attributed to PR #2775 from these data. Clocks were not controlled, and the cause of the rate difference is unknown.

In short: automatic selection chose the faster calibrated bus path in both tested starts, and that path completed without observed errors/faults. **Performance parity, stable placement, the historical slowdown's cause, and full performance resolution remain unproven.** A quieter, clock-controlled repeat with more independent processes and a contemporaneous old-revision control would be needed to separate these effects.

Local evidence: `data/colibri-investigation/pr2775/{summary.json,concurrent-activity.txt}` and `data/colibri-investigation/pool-ab/20261113-090452/` (`provenance.json`, integrity manifests, and each process's measurements, pre-measurement log, and final log).
