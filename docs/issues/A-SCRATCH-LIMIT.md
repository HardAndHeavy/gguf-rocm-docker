# A / #2757: ROCr scratch threshold and PR #2809 validation

13 November 2026. Follow-up to the [maintainer's correction](https://github.com/JustVugg/colibri/issues/2757#issuecomment-6853957759), authorized by the user. Earlier [SK0 trace](A-SK0-TRACE.md) remains historical evidence; this experiment tests a different allocator from the earlier split-part diagnostic.

## Same-image threshold test — complete

Unmodified new `b92eccd79ac60f196146f784c241ea076adda6f6`, immutable image `sha256:7de12e467442f57400a7185713b602127d2cf74f2cb241134e2403a65d11cd62`. **Only `HSA_SCRATCH_SINGLE_LIMIT` differs**: genuinely unset / `1073741824` / `1073741824` / unset, independent fresh processes. No source or binary patch.

Forced bus, SK=0, PROMOTE=0, MTP/lookup off, W4 unchanged, no thinking override, context 8192 / RAM 48 / OMP 8. Same hashed metadata snapshot restored to the same working path per process; matching prompt hashes across processes. Preliminary short/decode, short warmup+3 and decode warmup+3, greedy streaming usage, max_tokens 192. Decode rate `(completion_tokens-1)/(last_token-first_token)` is not end-to-end throughput.

| Process | Scratch limit | Decode 1 | Decode 2 | Decode 3 | Median tok/s |
|---|---|---:|---:|---:|---:|
| 1 | unset | 26.5175 | 26.6599 | 26.4267 | **26.5175** |
| 2 | 1 GiB | 38.1642 | 37.9988 | 37.9942 | **37.9988** |
| 3 | 1 GiB | 37.0431 | 37.3418 | 36.6347 | **37.0431** |
| 4 | unset | 26.7018 | 26.5272 | 26.6588 | **26.6588** |

Paired improvements **+43.30% / +38.95%**. This recovers most, but not all, of the historical ~40 versus ~26 gap. This stage has no contemporaneous old image, so do not turn that historical comparison into a precise residual percentage.

**Resource side effect retained:** the 1 GiB setting also changes ROCr reservation and the application's placement. Warm resident experts are **19186 / 18545 / 18545 / 19198**; host pools **7.30 / 8.16 / 8.16 / 7.28 GiB**. Final cumulative host-pool slots are 17085/22784/22784/16975, hybrid layer steps 0 throughout. The environment variable is the only intervention, but residency is not held constant. Do not attribute the remaining difference solely to the kernel's arithmetic or use this as a free production tuning knob. The larger reserve is a plausible reason for placement changes; no additional matched-residency experiment was performed.

Read-only ~1Hz telemetry, measured decode request windows including TTFT/prefill:

| Process | SCLK MHz median | MCLK MHz median | GPU W median | Junction °C median |
|---|---:|---:|---:|---:|
| 1 | 3283.5 | 1258 | 216.5 | 75.5 |
| 2 | 3256 | 1258 | 264.5 | 82 |
| 3 | 3248.5 | 1258 | 260 | 80 |
| 4 | 3283 | 1258 | 219 | 77 |

Power cap 300 W unchanged; clocks not fixed. No request/fault signatures or telemetry collection errors recorded. All 12 measured decode requests: HTTP 200, 192 tokens, length, reasoning without a final visible answer. This is not a quality/logit-parity or device-MTP test. All pre-run manifests match and original source state is unchanged. Raw: `data/colibri-investigation/pool-ab/20261113-162340/`.

## Scratch trace — complete

Fresh own container per variant; actual warmed `/app/c/qwen38`; startup opt-in `ROCP_TOOL_ATTACH=1`, container-scoped SYS_PTRACE; 15s bounded attach with `--kernel-trace --scratch-memory-trace`. Two warmup/control requests before attachment, then one repeated cached-prefix 64-token request. **Whole warmed-request capture, not marker-isolated decode.** No overlapping GPU experiments.

Both captures: 124899 kernel records, 2268 `cc_dnrec_k` dispatches, all 63 symbol/workgroup/grid count groups equal, stream 1. Reported scratch stays 2600 in both: changing threshold does not fix the kernel's intrinsic scratch requirement.

- **Unset:** 9072 scratch records, comprising 2268 allocations of 15974400 bytes with Alloc_Flags 1, 2268 corresponding frees with flag 1, plus 2268 ordinary 1 MiB allocations and 2268 flag 0 frees. Each of the 2268 `cc_dnrec_k` dispatches is timestamp-bracketed on the same queue by one distinct flag 1 allocation and one distinct flag 1 free. The runtime source identifies the use-once path. Scratch records themselves have no dispatch correlation ID, so this association is temporal, not an explicit ID join.
- **1 GiB:** zero scratch records in the JSON buffer; no scratch CSV emitted. Kernel records and shapes remain populated and matched. This absence is for the captured warmed interval, not proof of no startup allocation.
- `cc_dnrec_k` medians 68.68/57.84 µs, scratch 2600/2600. Unprofiled attach-enabled controls 26.66/38.25 tok/s; **profiled 21.14/11.27 tok/s**. The profiler again heavily and asymmetrically perturbs wall time. Do not benchmark variants or apportion ordinary wall time with these traced rates.
- Scratch callback durations total 4.00 ms in the unset capture; these short callback intervals are **not total queue-stall latency**. Do not equate their sum to the overhead removed by the setting.
- Both attach/detach exits 0, final fault signature false, telemetry errors null, source unchanged. No automatic GitHub publication.

Together, reversible unprofiled improvement and disappearance of per-dispatch scratch churn strongly support the maintainer's ROCr use-once mechanism as the major component, without claiming every lost millisecond is attributed.

Raw captures/analysis: `data/colibri-investigation/scratch-limit/trace-default`, `trace-1GiB`, `scratch-trace-summary.json`, `analyze-scratch.py`.

## Installed runtime and threshold

Read-only inspection of this image: installed packages 10.1.0-3, runtime `libhsa-runtime64.so.1.21.0`, embedded build ID `1.21.0-local-build-7da43026`. This coexists with the reported HIP 7.16/clang 24 toolchain; do not substitute a guessed ROCm version.

Installed-revision [flag.h](https://github.com/ROCm/rocm-systems/blob/7da43026/projects/rocr-runtime/runtime/hsa-runtime/core/util/flag.h) defines the default as **140 MiB = 146800640 bytes**. The nearby queue-code comment saying 128 MB is stale. [amd_gpu_agent.cpp](https://github.com/ROCm/rocm-systems/blob/7da43026/projects/rocr-runtime/runtime/hsa-runtime/core/runtime/amd_gpu_agent.cpp) selects use-once when device-slot scratch exceeds the threshold, or under allocation pressure, then shrinks the allocation to the dispatch requirement. This is a retention threshold, not a hard maximum scratch capacity, and also affects a process/GPU reserve.

Image Config.Env and a fresh image shell have all four scratch controls unset: `HSA_SCRATCH_SINGLE_LIMIT`, `HSA_SCRATCH_SINGLE_LIMIT_ASYNC`, `HSA_NO_SCRATCH_RECLAIM`, `HSA_ENABLE_SCRATCH_ASYNC_RECLAIM`. The test passes only the requested single limit. `HSA_NO_SCRATCH_RECLAIM=1` would change the mechanism and was not tested. [amd_gpu_agent.h](https://github.com/ROCm/rocm-systems/blob/7da43026/projects/rocr-runtime/runtime/hsa-runtime/core/inc/amd_gpu_agent.h) does not enable asynchronous scratch reclaim on gfx12.0; gfx12 requires minor >= 5 in this revision. Thus the ordinary limit is relevant to this gfx1201 device. Generic [environment reference](https://rocm.docs.amd.com/projects/ROCR-Runtime/en/latest/api-reference/environment_variables.html) may describe limits/features for other releases/hardware.

## Direct fix-branch test — complete

Pinned PR#2809 head `efe73475e1689278e40919dc75ab0f08b09a0e3d`, not a moving branch. Disposable image built with the same Dockerfile, pinned base `llama-rocm@sha256:f5a7d22b7e360e19c7ab43cd91c7c51bc5df15ace4f4897d0d3ed5dce2c4790e`, no-cache, gfx1201 and x86-64-v3 flags as the old matched rebuild. All 545 installed package/version entries match the old image. Image `sha256:02e93577338f5ef970d4f66966eba69a159a34f259d277ff0e6191dfc5dda1c5`, qwen38 SHA256 `275428d5abdb11d73ca743d5017bbc1ca7c2ce373ef5ba3d0495a98f22027d78`.

Old `0a6f235b` / fix / fix / old, same SK0/PROMOTE0 forced-bus profile, **no scratch override or profiler**. This tests the branch as requested by maintainer, not isolated attribution to one commit: it is 39 commits ahead of b92eccd7, including merges; full comparison is archived locally. Device-MTP safety/quality remains outside this test.

| Process | Revision | Decode 1 | Decode 2 | Decode 3 | Median tok/s |
|---|---|---:|---:|---:|---:|
| 1 | old 0a6f235b | 40.2207 | 40.3677 | 40.2687 | **40.2687** |
| 2 | fix efe73475 | 40.6944 | 40.3424 | 40.1863 | **40.3424** |
| 3 | fix efe73475 | 40.6995 | 40.6815 | 40.5269 | **40.6815** |
| 4 | old 0a6f235b | 40.3655 | 40.3094 | 40.1496 | **40.3094** |

Fix/old **+0.18% / +0.92%**, i.e. the observed ~34% regression is no longer present in this bounded test. Not a statistical claim of equivalence or a proven <1% universal bound. All four start with 19198 resident experts and 7.28 GiB host pool; equal counts do not establish identical maps. Median SCLK 3246/3236/3246.5/3247 MHz, MCLK 1258 MHz, power 269/269/270.5/269 W, junction 81/81/82/82 °C. All 12 measured decode requests HTTP 200, 192 tokens, length; no recorded faults or telemetry errors, snapshots match and original state unchanged. Warmups and all requests are retained.

Raw: `data/colibri-investigation/pool-ab/20261113-163753/`; build/manifests/summary: `data/colibri-investigation/scratch-limit/pr2809/`.

**Additional warmed fix capture completed:** same 124899 kernel records, 2268 `cc_dnrec_k<128, false>` calls; scratch **1092**, median **16.52 µs**, zero scratch records during the captured warmed interval. Attach/detach exit 0, fault signature false, telemetry error null, original state unchanged. Unprofiled control 40.29 tok/s, traced 30.40 tok/s: traced throughput is still not part of the benchmark. Raw: `data/colibri-investigation/scratch-limit/trace-fix/`.

All eight throughput/warmup response texts match across the four threshold processes. Old versus fix branch texts are not identical; this is ordinary greedy generation, not token replay or a logits-parity test. A performance recovery is not an answer-correctness result.

Production pins, `.env`, original metadata, models, clock/power/affinity/cache policy unchanged. Only owned test containers are cleaned up. Runner now has `--compare-scratch-limit`; profiler helper has `--scratch-trace` and explicit `--scratch-limit`. Legacy unset defaults preserved; 37 CPU tests pass. Local profiler helper still depends on the saved SK0 launch template, not a clean-clone reproducer.

## Public extracts

- [English follow-up](issue-A-scratch-ready-to-post.md), confirmed sent by the user on 13 November; paused pending maintainer feedback. No automatic post.
- [Sanitised evidence](evidence/A-scratch-limit.json), [SHA-256](evidence/A-scratch-limit-SHA256.json): both ABBA series including every warmup/measurement, telemetry summaries, provenance, scratch event counts and fix resource capture. Raw traces/build logs remain ignored, not uploaded.
