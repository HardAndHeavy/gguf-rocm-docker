# Draft issue B: HIP memory fault with Qwen3.8 device MTP and no-thinking; standalone W4/split-K checks pass

**Not submitted.** Pinned-revision investigation, not a claim about current upstream. Historical full-model observations are from 2026-11-09; standalone follow-up and bounded startup attempts are from 2026-11-11. Separate from non-MTP throughput observation A.

> Статус после публикации: получен ответ maintainer и выполнены два свежих full-model запуска без fault. См. [allocator follow-up](issue-B-allocator-followup.md). Текст ниже — исторический draft, не текущий статус.

## Summary / question

On Radeon AI PRO R9700 (`gfx1201`), Qwen3.8 Flash-Next device MTP with `chat_template_kwargs.enable_thinking=false` failed with `HSA_STATUS_ERROR_MEMORY_FAULT`, reported in `gemv_i8_w4<4>`. Both full and conservative device placement failed. MTP off and CPU-head controls completed the short/decode request pair; disabling W4 **or** split-K also allowed that pair to complete. These are diagnostic workarounds, **not fixes** or evidence that the kernel itself is the root cause. GPU faults can be reported asynchronously after an earlier bad access.

A new deterministic CPU-reference test passes through the actual production W4 dispatcher, including split-K, NR4 and output/K tails. Thus we have **not** isolated a standalone arithmetic/tail bug. Could you suggest a focused integration diagnostic/base, and whether this interaction is already known? We would prefer to capture the actual tensor dimensions, pointers/strides, scratch allocation/stream lifetime and call sequence before changing code. No global fast-path disable or wholesale dev backport is proposed.

## Pinned environment

- Colibri dev: `0a6f235b0c7a20726e28e6e0229ef1201de74638` (includes device-MTP PR #2559).
- Local image: `gguf-rocm-colibri:mtp-dev-0a6f235b`; immutable image ID `sha256:e888c06f9db6a2d55997c43f2b0bd45c0face5d3ff428eba2b8a19dc65a299cc`.
- GPU: AMD Radeon AI PRO R9700, nominal 32 GiB, gfx1201, wave32. Current pinned-image toolchain: HIP `7.16.26385-0000000`, AMD clang `24.0.0git`, LLVM revision `d6f6cb691863e9258034ab48c1dfce21689d5606`.
- Model: `Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf` plus second shard; head: `mtp-Qwen3.8-Flash-Next-Q2_0.gguf`. Model **content hashes have not been captured**; names/sizes alone are not cryptographic identity.
- Context 8192, RAM budget 48 GiB, lookup disabled, one-slot research setup; `Q38_MTP=1 Q38_MTP_CHAIN=1 Q38_MTP_DRAFTS=0` (automatic drafts, not a hard zero-draft claim).
- Full: `COLI_CUDA_CHAIN_MTP_CARD=1 COLI_CUDA_CHAIN_MTP_POOL=1`. Conservative: both 0, keeping device head but routed head experts on host. CPU control: `Q38_MTP_CHAIN=0`; off control: head disabled.
- Upstream CUDA-named interfaces/environment variables are also used by the HIP backend; this is not an NVIDIA run.

## Historical integration evidence (November 9)

Requests: fresh process per profile, fixed short then decode prompts from `scripts/benchmark.py`, greedy (`temperature=0`), budget 192, streaming with usage, zero presence/frequency penalties, thinking explicitly disabled. Historical runner reused mutable dev state across these profile launches: **not independent restores of one hashed pre-run snapshot**. This limits isolation of placement/cache/history effects.

| Profile | Short | Decode | Evidence scope |
|---|---|---|---|
| MTP off | `Железо`, stop, 3 tokens | visible text, length, 192 tokens | request completion, not exhaustive correctness |
| CPU head | same short answer | visible text, length, 192 tokens | same limitation |
| Device full, W4/SK defaults | no completed answer; GPU fault | engine-error response | failed process, not merely a content mismatch |
| Device conservative, W4/SK defaults | no completed answer; GPU fault | engine-error response | same reported kernel |
| Device full, `COLI_CUDA_GEMV_W4=0` | same short answer | visible text, length, 192 tokens | diagnostic bypass only |
| Device full, `COLI_CUDA_GEMV_SK=0` | same short answer | visible text, length, 192 tokens | diagnostic bypass; may also change NR |

The faulting short response artifact has HTTP headers but no completed answer/usage, and no explicit error field in its saved run. This is **not success**: logs show a fault followed by engine termination. The following decode request records an engine error.

Sanitized fault excerpt (full and conservative have the same listed launch geometry):

```text
Warning: Queue error - HSA_STATUS_ERROR_MEMORY_FAULT
GPU HANG ANALYSIS
 grid=[2560, 7, 1], workgroup=[256, 1, 1], group_seg_size=27712
 kernel: void gemv_i8_w4<4>(float*, float*, float const*, signed char const*, float const*, int, int, int, int, int)
Memory access fault by GPU node-1. Reason: Page not present or supervisor privilege.
colibri: the engine dispatcher stopped: colibri engine exited unexpectedly
```

Addresses and container host identifiers omitted. Runtime grid x=2560 is work items (10 blocks of 256), not 2560 blocks. It is compatible with, but **does not identify**, the standalone K10240/N300/S4 split configuration below; tensor arguments were not captured in the original fault. In particular, N=300 was chosen for tail coverage, not recovered from the fault.

Exact first request (server model ID from saved reports):

```json
{
  "model": "qwen3.8-flash-next-colibri",
  "messages": [{"role": "user", "content": "Ответь одним словом: какой элемент обозначается символом Fe?"}],
  "temperature": 0,
  "max_tokens": 192,
  "stream": true,
  "stream_options": {"include_usage": true},
  "presence_penalty": 0,
  "frequency_penalty": 0,
  "chat_template_kwargs": {"enable_thinking": false}
}
```

The second prompt is preserved verbatim in the evidence JSON alongside both request bodies. No UUID prefix is used for this correctness pair.

## New standalone follow-up (November 11): PASS, not a root cause

Files in this reproducer repository:

- `tests/colibri_gemv_cpu_reference.cu`
- `scripts/instrument-colibri-gemv.py` (logging-only, exact-anchor edits to an ephemeral backend copy)
- `scripts/check-colibri-gemv-hip.sh`

Run `bash scripts/check-colibri-gemv-hip.sh`. It uses existing local image only, `docker run --network none`, separate processes for `COLI_CUDA_GEMV_SK=1` and `=0`, W4 enabled. It does not change production sources or the image. ROCm paths are specific to this pinned image. Normal rocWMMA-enabled backend compiled at **O2**, versus production O3; this matters when interpreting a negative result.

Deterministic xorshift32 seed `0x6d2b79f5`, signed int8 row-scaled weights (fmt=1), float32 activations/scales, CPU double accumulation from those same stored values. Three repeats per shape; every row of S4 and four separate S1 calls compared to CPU. Predeclared criterion: `abs(error) <= 1e-3 + 1e-4*abs(reference)`. Runtime/launch/sync errors, nonfinite outputs and outer output-buffer guards checked. Both processes exited 0, **144 row-result records total, zero failures**.

The originally planned **K2048/N300 cannot select W4**: 614400 elements are below the dispatch threshold `N*K >= 2^21`. We retained it as fallback control and added actual W4 shapes. This is why a generic passing rows test is insufficient coverage.

Observed S4 production dispatch (no forced branch/parameter overrides):

| K / N | SK | Kernel/path | kz / kc | sr | shared bytes | grid in blocks |
|---|---|---|---|---:|---:|---|
| 2048 / 300 | both | fallback | — | nr=1 | 9232 | 38,4,1 |
| 2048 / 1100 | on | W4 | 2 / 1024 | 4 | 18496 | 35,2,1 |
| 2048 / 1100 | off | W4 | 1 / 2048 | 4 | 36928 | 35,1,1 |
| 10240 / 300 | on | W4 | 7 / 1536 | 4 | 27712 | 10,7,1 |
| 10240 / 300 | off | W4 | 1 / 10240 | **1** | 46096 | 10,1,4 |

Single-row controls used W4 sr=1 for the larger shapes. K10240 split-off lowers sr because of the 48 KiB shared-memory limit: **disabling split-K also changes row batching**, so the full-model bypass does not isolate split reduction alone. K2048/N1100 does retain sr=4 on both sides and passes. K10240/N300 split-on includes a partial final K split; both larger shapes include partial 32-output tiles.

Maximum absolute errors over rows/repeats:

| K / N | SK on | SK off |
|---|---:|---:|
| 2048 / 300 | 1.845e-6 | 1.845e-6 |
| 2048 / 1100 | 1.364e-6 | 1.696e-6 |
| 10240 / 300 | 3.434e-6 | 8.769e-6 |

Relative error near zero can exceed 1e-4; all values pass the combined criterion. No GPU sanitizer, input/scratch/per-row guard instrumentation or bitwise identity assertions. One seed/GPU/image/format, synthetic allocations, no MTP stream/lifetime sequence. These results do **not** prove the real integration path safe or establish performance.

## Bounded direct full-model attempt (November 11): INCONCLUSIVE

`python3 scripts/check-colibri-mtp-direct.py` is a separate direct-container runner: host networking, API bound only to `127.0.0.1:18080`, no Compose/OpenWebUI/bridge network, random API key not saved, read-only models, independent metadata snapshot copies and manifests, bounded startup/request deadlines and cleanup.

Two bounded attempts (off ~198 s and full ~183 s) **did not reach API readiness**. No chat request was submitted, no new fault was reproduced, and no correctness/performance result exists. Warm-start completed but startup did not finish; process snapshots showed disk-sleep states, without proving an I/O root cause. CPU/SK0/W40 were skipped to respect the session limit. All test containers were removed and the port released. Do not merge these attempts with the historical successful/failing requests.

The final direct runner adds post-run safety corrections: reject a missing control snapshot, use `--no-mtp` import for off, explicitly recognize the HSA fault status, and fail promptly on a failed Docker launch. The executed off attempt imported the head while setting `Q38_MTP=0`; it never reached readiness and cannot validate a fully disabled-head startup. Final runner syntax was checked; the full matrix was **not rerun** after these edits. Reproduction requires the local model files, pinned image and saved control snapshot; these are not distributed by this repository.

## Evidence and stopping point

Compact sanitized attachments are in `docs/issues/evidence/`. Full local logs remain gitignored under `data/benchmarks/mtp-hip-*-nolookup-nothink*` and `data/colibri-investigation/` (not implicitly attached to this issue). No `.env`, API key or auth headers should be uploaded. Model hashes and a completed fresh-snapshot integration matrix remain missing.

We stopped after the passing narrow test and bounded integration attempts, rather than undertaking long tracing/bisect. Suggested next step after maintainer guidance: capture real dispatch arguments and allocation/stream sequence for both thinking variants on a known base, then test a demonstrated minimal fix. We do not currently have a justified source fix or PR.
