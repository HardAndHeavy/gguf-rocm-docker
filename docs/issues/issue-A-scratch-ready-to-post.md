Thanks — your scratch hypothesis is strongly supported by both checks on the R9700.

**1. Unpatched `b92eccd7`, same immutable image, unset / 1 GiB / 1 GiB / unset:** median decode **26.5175 / 37.9988 / 37.0431 / 26.6588 tok/s**. Forced bus, SK=0, PROMOTE=0, MTP/lookup off, W4 unchanged, context 8192 / RAM 48 / OMP 8; fresh processes restoring the same metadata snapshot, identical prompts within the series, three measured 192-token requests per process. No profiler in these measurements. Paired improvements are **+43.30% / +38.95%**.

There is a resource side effect: warm resident experts change from 19186/19198 without the override to 18545 with it; the host pool grows from 7.30/7.28 to 8.16 GiB. So I would not interpret the remaining distance from historical ~40 as solely kernel arithmetic. The application's placement is not constant even though the only environment intervention is the scratch limit.

**2. Warmed-engine kernel + scratch trace, one 64-token request per fresh process:** both captures have 124899 kernel records, 2268 `cc_dnrec_k` calls, and equal counts for all 63 symbol/workgroup/grid groups.

- Unset: **2268 use-once allocations of 15974400 bytes and 2268 corresponding frees**, plus 2268 ordinary 1 MiB allocations/frees. Each `cc_dnrec_k` is bracketed by one distinct use-once alloc/free pair on the same queue by timestamp (scratch records have no dispatch correlation ID).
- 1 GiB: **zero scratch records in the JSON buffer** during the warmed interval; kernel records remain populated. The kernel's scratch field is still 2600 in both variants.

Installed ROCr reports `1.21.0-local-build-7da43026`. At that source revision the ordinary default is **140 MiB / 146800640 bytes**, and the async-reclaim path is not enabled on gfx12.0. This is not the application's split-part allocator that we previously tested.

Profiler perturbation remains substantial: unprofiled attach-enabled controls 26.66/38.25 tok/s, traced 21.14/11.27. I use the trace for the allocation pattern, **not** to attribute ordinary wall time or benchmark the variants.

**3. Direct pinned #2809 head `efe73475` versus `0a6f235b`, with no scratch override:** old/fix/fix/old median decode **40.2687 / 40.3424 / 40.6815 / 40.3094 tok/s**. Same SK0/PROMOTE0 forced-bus protocol, no profiler; fix/old **+0.18% / +0.92%** in the two pairs. All four processes had 19198 resident experts and a 7.28 GiB host pool. Thus the large regression is no longer present in this bounded branch test. The image was built with the same pinned base/toolchain/flags; all 545 installed package/version entries match the old matched rebuild. This is the complete fix branch, not a single-commit cherry-pick.

An additional warmed fix capture has 2268 `cc_dnrec_k<128, false>` calls, **scratch back to 1092, median 16.52 µs**, and zero scratch records in the captured interval. All captures attached/detached successfully; no fault signatures were recorded. Old/fix generated texts are not identical, so this remains a performance result, not logits parity.

No production pins, clock/power settings, models or original metadata changed. These are non-MTP performance tests, not device-MTP safety or answer-quality validation. Nothing was automatically posted to GitHub.
