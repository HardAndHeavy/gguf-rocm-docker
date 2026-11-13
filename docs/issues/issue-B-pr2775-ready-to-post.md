<!-- Пользователь сообщил об отправке этого ответа 13 ноября 2026. Сохранённый локальный текст, не синхронизированная копия GitHub. -->

Tested the PR #2775 merge `b92eccd79ac60f196146f784c241ea076adda6f6` on **AMD Radeon AI PRO R9700 (gfx1201), Ryzen 7 3700X**. The three bounded integration smoke runs below completed without a detected engine/GPU fault.

### Build and setup

- Local image: `gguf-rocm-colibri:pr2775-b92eccd7`; immutable image ID: `sha256:0e99d6b9f4148b30ba4aeeedf66cdeab26807a3c26489a03c426ab2d82dbf141`.
- The image's Colibri-specific revision label is `b92eccd79ac60f196146f784c241ea076adda6f6`.
- HIP `7.16.26385-0000000`; AMD clang `24.0.0git`, ROCm LLVM commit `d6f6cb691863e9258034ab48c1dfce21689d5606`; target `x86_64-unknown-linux-gnu`.
- Model: `Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS` (two GGUF shards), with `mtp-Qwen3.8-Flash-Next-Q2_0.gguf` for full MTP.
- Direct Docker runs, independent fresh server processes, each starting from an independent copy of the **same metadata/history snapshot**. All three snapshot-integrity checks reported unchanged. Each process received the short request followed by the decode request.
- W4 and split-K left at their defaults: **no W4/SK overrides**. No serialization overrides (`AMD_SERIALIZE_KERNEL`, `AMD_SERIALIZE_COPY`, or `HIP_LAUNCH_BLOCKING`). Lookup off (`COLI_LOOKUP=0`); thinking explicitly disabled (`chat_template_kwargs.enable_thinking=false`); greedy requests with a 192-token limit and streaming usage enabled.
- Common settings included `COLI_CUDA=1`, `COLI_VULKAN=0`, `COLI_CUDA_HOST_POOL=0`, `COLI_CUDA_CHAIN_POOL=1`, `COLI_CUDA_CHAIN_LAYERWISE=1`, `COLI_CUDA_CHAIN_ROWS=64`, `COLI_NO_OMP_TUNE=1`, and `OMP_NUM_THREADS=8`.

### Observed results

Readiness below is the measured time until the server was ready, not a throughput measurement.

| Separate process | MTP configuration | Readiness | Short request | Decode request | Detected engine fault |
| --- | --- | ---: | --- | --- | --- |
| off | `Q38_MTP=0` | 211.70 s | `Железо`, 3 completion tokens, `stop` | 192 completion tokens, `length` | No |
| full-auto | `Q38_MTP=1 Q38_MTP_DRAFTS=0`, automatic gate | 209.41 s | `Железо`, 3 completion tokens, `stop` | 192 completion tokens, `length` | No |
| full-forced | `Q38_MTP=1 Q38_MTP_DRAFTS=3 Q38_MTP_PSTEP=0 COLI_SPEC_GATE=0` | 204.99 s | `Железо`, 3 completion tokens, `stop` | 192 completion tokens, `length` | No |

**All six requests returned HTTP 200, reached streaming `[DONE]`, included usage, and recorded no request error.** In each process, short-request usage was 27 prompt / 3 completion / 30 total tokens; decode usage was 79 / 192 / 271. The decode responses contained visible text and ended at the requested token limit.

Both full profiles used `Q38_MTP_CHAIN=1`, `COLI_CUDA_CHAIN_MTP_CARD=1`, and `COLI_CUDA_CHAIN_MTP_POOL=1`. Startup logs confirmed the MTP layer on device 0 and all 512 routed MTP experts on the card in Q2_0 (0.66 GiB). This was not merely successful CPU-only MTP:

| Full profile | Device counters after short request | Device counters after decode request (cumulative) | Decode-turn acceptance |
| --- | --- | --- | --- |
| auto | 29 MTP head rows, 2 drafts' logits on card | 385 MTP head rows, 197 drafts' logits on card | 83/195 drafts (42.6%) |
| forced | 33 MTP head rows, 6 drafts' logits on card | 494 MTP head rows, 295 drafts' logits on card | 93/289 drafts (32.2%) |

These counters establish path execution only; **I am not claiming a performance speedup**.

### Model-content identity

Full SHA-256 hashes are now available (the earlier follow-up lacked these):

```text
92cee27ae5bbadcd732416a0f7a7f0acc092399dbbe8f5a5efa707c2ec0a49d7  Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf
316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113  Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00002-of-00002.gguf
da56287342376566ea31c2688069ea07519739027d8cb3362df65c33d45a927b  mtp-Qwen3.8-Flash-Next-Q2_0.gguf
```

### Limits of this result

The **old, unchanged baseline already passed** the fresh-snapshot auto and forced request pairs before this merge. Thus these passes do **not** demonstrate that PR #2775 fixed the historical memory fault, that the fault is gone, or that an allocator/lifetime issue was its root cause. The historical failing profiles reused mutable state; their exact pre-run history/placement has not been established as identical to this snapshot. The newly recorded model hashes do not retroactively establish that equivalence.

No sanitizer run or failing-pointer capture was performed here. This is a **limited integration smoke test**, not endurance testing, a memory-safety proof, or an allocator diagnosis.

Local evidence: `data/colibri-investigation/pr2775/{summary.json,image.txt,toolchain.txt}` and the selected environments, request/SSE results, and device logs under `data/colibri-investigation/integration/20261113-085318/off`, `20261113-085710/full`, and `20261113-090106/full`.
