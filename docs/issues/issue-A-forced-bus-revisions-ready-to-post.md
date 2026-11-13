# Issue A — forced-bus comparison across pinned revisions

**Пользователь отправил этот follow-up 13 ноября 2026; отправка подтверждена в GitHub.** Ниже сохранён локальный текст сообщения. Следующая проверка — [matched rebuild / allocator-only](A-REBUILD-ALLOCATOR.md).

---

Following up with a forced-bus comparison to separate the build-to-build performance gap from automatic CPU/GPU path selection.

I ran four separate processes in interleaved **old → new → new → old** order, using the existing immutable images:

- **Old:** Colibri `0a6f235b0c7a20726e28e6e0229ef1201de74638`, image `sha256:e888c06f9db6a2d55997c43f2b0bd45c0face5d3ff428eba2b8a19dc65a299cc`.
- **New:** Colibri `b92eccd79ac60f196146f784c241ea076adda6f6`, image `sha256:0e99d6b9f4148b30ba4aeeedf66cdeab26807a3c26489a03c426ab2d82dbf141`.

All four used the forced-bus profile (`COLI_CUDA_CHAIN_POOL_READ=1`, `COLI_CUDA_CHAIN_POOL=1`, `COLI_CUDA_HOST_POOL=0`), not automatic path selection. MTP and lookup were disabled (`Q38_MTP=0`, `Q38_MTP_DRAFTS=0`, `COLI_LOOKUP=0`), and there was **no thinking override**. Layerwise mode, 64 chain rows, and eight OpenMP threads were unchanged.

Before each process I restored the same SHA-256-manifested model-state snapshot to the same path. All four pre-run manifests match the snapshot, including `.coli_usage` and `.coli_analysis.json`; state written during a run was not carried into the next one. The same prompt corpus was replayed across processes, with fresh request markers within each process and matching prompt hashes across the four processes. The model files were reused; the model metadata artifact is explicitly not a content-hash manifest of the weights. There was no page-cache flush, affinity change, or clock/power-setting change.

### Decode results

Each process ran short/decode correctness requests, then a short warmup plus three short measurements, and a decode warmup plus three decode measurements. There was no separate prefill benchmark. Below are **all 12 measured decode results**, excluding the predefined warmups, in tokens/s:

| Process | Build | Decode 1 | Decode 2 | Decode 3 | Median |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | Old `0a6f235b` | 39.8871 | 39.6861 | 39.9045 | **39.8871** |
| 2 | New `b92eccd7` | 27.5913 | 27.6501 | 27.6514 | **27.6501** |
| 3 | New `b92eccd7` | 27.0245 | 26.6914 | 26.9173 | **26.9173** |
| 4 | Old `0a6f235b` | 40.7080 | 40.7034 | 40.1460 | **40.7034** |

Comparing process 2 with process 1, the new-build median is **30.68% lower**. Comparing process 3 with process 4, it is **33.87% lower**, calculated as `(new / old - 1) × 100`. The old build returns to approximately 40 tokens/s after both new-build processes.

Warmups remain in the raw artifacts, rather than being removed as outliers. The decode warmups in process order were 39.1183, 27.4637, 27.2606, and **36.3115 tokens/s**; in particular, the fourth/old process had a 36.31 tokens/s warmup before its three approximately 40 tokens/s measurements.

All measured decode requests returned HTTP 200, produced **192 completion tokens**, and ended with `finish_reason=length`. These were reasoning-channel completions with empty final-content fields, not 192 tokens of final-answer text. The correctness requests also returned HTTP 200. No faults or errors were recorded in the captured run logs, and telemetry reported no collection errors.

### Pool and routing observations

Both builds logged a **33.02 GiB page-locked host pool** and **19,186 resident experts** at warm start. This establishes equal reported pool size and resident **count**, not identical expert-to-residency mapping. All four final summaries reported approximately **98.6% of routes on the card**, **zero promotions**, and **zero hybrid layer steps**, with no routed-expert execution time on the host.

Consequently, this particular gap cannot be explained as the automatic selector taking the wrong CPU path: automatic selection was disabled, and the captured summaries show no hybrid execution. That does not identify which backend operation accounts for the gap.

### Telemetry and its limits

Telemetry was sampled at approximately **1 Hz**. The following medians are for samples inside the three **measured decode request windows** of each process, excluding warmups. These windows include **TTFT/prefill as well as generation**; they are not isolated decode-kernel measurements.

| Process / build | SCLK median (MHz) | MCLK median (MHz) | GPU power median (W) | Power cap (W) | Junction median (°C) | Aggregate CPU busy median (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 / old | 3251 | 1258 | 263 | 300 | 76 | 27.8 |
| 2 / new | 3281 | 1258 | 221 | 300 | 76 | 24.9 |
| 3 / new | 3280 | 1258 | 218 | 300 | 76 | 25.7 |
| 4 / old | 3243.5 | 1258 | 269 | 300 | 80.5 | 29.1 |

The highest sampled junction temperature across these measured request windows was **91°C**. The new build's lower throughput is not accompanied by a lower median observed SCLK in this sample set, but these coarse observations **do not prove the absence of throttling**, power-limit effects, or short transients. The reported 300 W cap is a configured limit, not a claim that every instantaneous power reading stayed below it.

CPU governors remained `powersave` and GPU performance level remained `auto`. Clocks were **observed, not fixed**. CPU busy is host-wide aggregate utilization, with no per-process CPU attribution. Container snapshots showed only the controller and the current test container; those snapshots **do not establish that no external/host workloads were present**.

### What this establishes — and what it does not

This is a repeatable performance gap **between these two pinned existing builds under forced-bus operation**, not proof that PR #2775 caused a regression or that an allocator change is the root cause.

Both images report HIP `7.16.26385-0000000` and AMD clang `24.0.0git` at LLVM revision `d6f6cb691863e9258034ab48c1dfce21689d5606`. However, these were **existing images, not freshly rebuilt old/new binaries under a fully matched source-only build procedure**. Matching reported compiler versions does not establish identical build flags, dependencies, or compilation history. Binary and relevant source hashes were captured in `toolchains.txt` and differ between the images.

Also, matching input prompts and restored starting state is not token replay: the old/new generated outputs differ in places, so generated-token trajectories and exact expert routes are not guaranteed identical. The aggregate routing percentage cannot establish identical prompt routes or identical backend work.

Would the most useful next focused diagnostic be a **fresh old-revision rebuild using the same build procedure/toolchain as the new revision**, followed by the same interleaved forced-bus comparison? If the gap persists, I can then collect a focused backend trace, or run an **allocator-only A/B on the same new revision** while holding the rest of the build and test setup constant. I would treat that as a hypothesis test, not propose an allocator patch as an already-established fix.

Evidence retained locally: `data/colibri-investigation/bus-revision-ab/summary.json`, `data/colibri-investigation/bus-revision-ab/toolchains.txt`, and the actual provenance, image metadata, snapshot/pre-run/post-run manifests, measurements including warmups, logs, and telemetry under `data/colibri-investigation/pool-ab/20261113-123131/` (process directories `01-B` through `04-B`).
