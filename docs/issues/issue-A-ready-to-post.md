# Title

[HIP][Qwen3.8] Lower non-MTP decode throughput on pinned dev vs main on Radeon AI PRO R9700

# Body

## Summary

I observed lower non-MTP decode throughput on Radeon AI PRO R9700 when comparing these pinned revisions:

- main: `0a5504a1dc64f86fcd0fe7db298b0448c730e7e6`
- dev: `0a6f235b0c7a20726e28e6e0229ef1201de74638`

With both MTP and prompt lookup disabled, median decode throughput was **45.45 tok/s on main vs 37.26 tok/s on dev**, approximately **18.03% lower**.

This is a pinned-revision observation, not a claim about current upstream. I have not identified the responsible change and am **not attributing this result to device-MTP PR #2559**. The startup logs show differences in expert placement and pool execution paths between the revisions.

## Environment

- GPU: AMD Radeon AI PRO R9700, gfx1201, nominal 32 GiB VRAM
- Backend: ROCm/HIP, using Colibri's CUDA-named backend interfaces
- Model: `Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf` and its second shard
- Context: 8192
- RAM budget: 48 GiB
- MTP disabled: `COLIBRI_MTP=off`, `Q38_MTP=0`
- Prompt lookup disabled: `COLI_LOOKUP=0`
- No explicit W4 or split-K override

Both startup logs explicitly confirm that the MTP head is off.

The historical benchmark records do not include a complete compiler/toolchain manifest or model-content hashes. I can provide the saved benchmark JSON/CSV and sanitized startup/runtime logs.

## Measurement protocol

- Streaming requests, temperature 0, max_tokens 192
- One warm-up followed by three measured requests per case
- Case order: short, decode, long-prompt/prefill
- A fixed-prompt correctness pair ran before the throughput series
- Throughput prompts included fresh UUID prefixes to avoid exact prefix reuse
- No explicit thinking override: the saved request override was `{}`

In particular, these are **not no-thinking measurements**. The measured decode requests consumed the 192-token budget in reasoning.

Decode throughput is client-observed:

```text
(completion_tokens - 1) / (last_token_time - first_token_time)
```

## Results

All measured decode requests completed with 192 completion tokens.

| Revision | Measured run 1 | Measured run 2 | Measured run 3 | Median |
|---|---:|---:|---:|---:|
| main | 38.00 tok/s | 45.67 tok/s | 45.45 tok/s | **45.45 tok/s** |
| dev | 37.95 tok/s | 37.26 tok/s | 36.58 tok/s | **37.26 tok/s** |

The slower first main run is retained, not discarded.

Other per-metric medians:

| Metric | main | dev |
|---|---:|---:|
| Decode-case total time | 6.245 s | 7.003 s |
| Decode-case TTFT | 2.043 s | 1.875 s |
| Short-case decode throughput | 46.85 tok/s | 36.05 tok/s |
| Long-prompt case TTFT | 30.299 s | 33.329 s |
| Decode throughput after the long prompt | 24.54 tok/s | 34.04 tok/s |

The long-prompt case is not uniformly worse on dev: its TTFT is longer, but subsequent decode is faster. TTFT here is not an isolated kernel-prefill measurement.

## Important limitations and runtime differences

This was main followed by dev in two contiguous process series, **not repeated interleaved main/dev and dev/main process pairs**. Three request repeats do not establish between-process variability or eliminate order, warm-up, page-cache, clock or thermal effects.

The two runs used separate state directories described as comparable snapshots. Both startup logs report the same expert-history selection count, but I do not have a pre-run hash manifest proving byte-identical mutable state. Equal history counts do not establish equal expert residency.

The startup logs also show different internal configurations:

| Observation | main | dev |
|---|---|---|
| Expert arena | Fixed-size slots | Per-layer sizes |
| Warm-start resident experts | 18,260 | 19,186 |
| Host-pool allocation | 34.57 GiB | 33.02 GiB |
| Promotion stop threshold | 90% resident routes | 97% resident routes |
| Pool decode path | Pooled-expert copies | Pool server with 12 threads |

These are possible factors to investigate, not demonstrated explanations.

UUID prompts and generated reasoning differ across runs, so this is not an exact token-for-token replay. No confidence interval, statistical significance, or full-model bitwise-equivalence claim is intended.

## Questions

1. Are there known changes between these two revisions that could affect non-MTP HIP decode through placement, expert promotion, or pool execution?
2. Which pinned base and placement/pool controls would you recommend for a fair interleaved comparison?
3. Which diagnostics would be most useful to capture first: expert residency/hit rates, promotion traffic, pool-server CPU time, or per-layer GPU/host timings?

I would like to agree on a focused comparison before undertaking a larger bisect or proposing a patch. I am not proposing a wholesale dev backport or a global fast-path disable based on these measurements.
