# Issue A — reply to the CUDA comparison and proposed HIP checks

**Posted by the user (confirmed before the SK=0 experiment).** Archived English reply incorporating the maintainer's CUDA comparison.

---

Thanks for the CUDA comparison and the specific HIP checks. Before seeing your reply, I had completed two controls that I had not posted yet. They seem relevant to deciding what to trace next.

**1. Matched rebuilds reproduce the gap.** Both `0a6f235b` and `b92eccd7` were rebuilt without cache using one archived Dockerfile, the same pinned base image, the same HIP/compiler flags, and matching package lists (545 dpkg entries). Each rebuilt `qwen38` is bit-identical to its respective previous-image binary. Thus the earlier binary-build-history uncertainty is substantially reduced.

Forced bus, MTP/lookup off, no thinking override, the same restored snapshot and prompt corpus within the series, old/new/new/old order; three measured 192-token decode requests per process after warmups:

| Process | Rebuilt revision | Median decode tok/s |
|---|---|---:|
| 1 | old `0a6f235b` | 40.15 |
| 2 | new `b92eccd7` | 27.17 |
| 3 | new `b92eccd7` | 27.66 |
| 4 | old `0a6f235b` | 40.85 |

That is −32.33% and −32.30% for new versus old in the two pairs. These are two independent process comparisons, not twelve independent repeats.

**2. Reverting only the persistent-part acquisition on the same new revision did not restore throughput.** In a disposable child of rebuilt `b92eccd7`, I removed only the HIP call-site assignment to `gemv_sk_part`. This leaves `own=0` and takes the existing `cudaMallocAsync`/`cudaFreeAsync` fallback. W4, split-K, split selection, launch formulas, and arithmetic were left unchanged. The chain object/header, Makefile, and package list match the stock parent.

| Process | New-revision variant | Median decode tok/s |
|---|---|---:|
| 1 | stock persistent | 27.74 |
| 2 | async-only diagnostic | 25.67 |
| 3 | async-only diagnostic | 26.35 |
| 4 | stock persistent | 26.40 |

This did not recover approximately 40 tok/s; I am not claiming allocator superiority/equivalence or a proven cause. There was no allocator-hit trace. All eight corresponding throughput/warmup response texts matched across these four processes, but that is not logits parity. An anomalous final-stock decode warmup of 12.86 tok/s was retained; seven samples in that phase reported MCLK 96 MHz. I have not attributed that transient to either allocator.

Both series had zero hybrid steps and promotions, with approximately 98.6% resident routes. All measured decode requests completed with 192 tokens and `length`, without captured request/engine/GPU faults. The restored state matched before every process; clocks were observed, not locked. These tests do not establish a result for the historical device-MTP fault.

**Next I will follow your A/B sequence:** first `COLI_CUDA_GEMV_SK=0` on both unmodified images, old/new/new/old, with forced bus and `COLI_CUDA_CHAIN_PROMOTE=0`. That split-disable check has not been run yet. I would interpret a collapse of the gap as localizing it to the split path, alongside the negative allocator-only result, rather than as allocation proof by itself.

If the gap remains, I will collect a bounded trace on the real engine process for one warmed decode request per image, using the same SK=0 profile. `rocprofv3` 1.4.1 is present in both rebuilt images; its version/help work, but actual capture/attach has not been tested. I will compare `bd_gemv_i8_k` dispatch counts and durations for comparable launch shapes, other kernels, and HIP/copy/synchronization activity, with prefill separated where the trace allows and profiling overhead recorded. If `bd_gemv_i8_k` becomes slower for comparable work, I will send that evidence and A/B the HIP-only sums patch you offered. No rounding patch or intermediate `3a33c7f1` rebuild has been tested yet.

The full local results and the one-line diagnostic diff are prepared separately; nothing has been uploaded as an attachment by this draft.
