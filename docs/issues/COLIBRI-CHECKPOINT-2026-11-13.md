# Colibri investigation checkpoint — 13 November 2026

## Current decision

**Paused pending maintainer response.** The user confirmed posting the latest [SK0/trace follow-up](issue-A-sk0-ready-to-post.md), as well as the earlier PR validation, forced-bus and matched-rebuild/allocator controls. No automatic issue comments/PRs were posted by the agent. No further GPU experiments, broad bisect or diagnostic patches are currently scheduled.

## Completed evidence

1. [PR #2775 validation](PR2775-VALIDATION.md): bounded B integration requests pass without captured fault; A auto selects bus. This is not proof that historical fault B is fixed.
2. [Contemporaneous forced-bus old/new ABBA](A-FORCED-BUS-REVISIONS.md): old ~40, new ~27 tok/s.
3. [Matched no-cache rebuild and allocator-only diagnostic](A-REBUILD-ALLOCATOR.md): matching packages/toolchain and bit-identical respective binaries; gap persists. Reverting only persistent split-part acquisition on new did not restore speed.
4. [SK0/PROMOTE0 ABBA](A-SK0-ABBA.md): medians **40.1241 / 26.3367 / 26.1986 / 40.0327 tok/s**, new/old **−34.36% / −34.56%**. PROMOTE0 changes pool coverage on both revisions (33.02 → 7.30 GiB); not isolated SK ablation against the earlier series. Retained slow sample and MCLK anomaly, no causal attribution.
5. [Warmed-engine profiler smoke and two trace pairs](A-SK0-TRACE.md): actual attach/capture works with startup opt-in `ROCP_TOOL_ATTACH=1`; real qwen38 target. `cc_dnrec_k<128>` shows ~4.2× median duration, scratch field 1092 → 2600, equal dispatch count/geometry. Large asymmetric profiler overhead and extreme records prevent ordinary wall-time attribution. `bd_gemv_i8_k` does not show a uniform large slowdown. No root-cause proof.

## Next step only after agreement

Ask/await the maintainer's preferred narrow discriminator around the new snapshot-copy block in `cc_dnrec_k` and HIP codegen/resources. Its runtime execution in the non-MTP test was not established. No compile-time snapshot guard/removal or old-sums patch has been tested. Preserve device-MTP semantics and use a disposable diagnostic image if a patch is subsequently authorized.

## Preserved local state (not pushed)

Raw build logs, snapshots, full responses, telemetry and profiler traces remain under gitignored `data/colibri-investigation/` (about 953 MiB at checkpoint). Models, original control metadata, `.env` and local Docker images also remain local. **The Git commit/push is not a backup of these ignored artifacts or images.** Public extracts and checksums are tracked under [evidence/](evidence/).

Key raw series:

- `pool-ab/20261113-131251` — matched rebuild old/new/new/old.
- `pool-ab/20261113-133252` — new stock/async/async/stock diagnostic.
- `pool-ab/20261113-144141` — SK0/PROMOTE0 ABBA.
- `sk0-abba/` — orchestration, summaries, trace analyses/validation and `profiler-smoke-old`, `trace-old/new`, `kernel-only-old/new` captures.

Immutable unmodified images for any later matched comparison:

- old `0a6f235b0c7a20726e28e6e0229ef1201de74638`: `sha256:a989a4141762cce9d0a80819312635d195d5503c9fc87838805d81ec59838d88`.
- new `b92eccd79ac60f196146f784c241ea076adda6f6`: `sha256:7de12e467442f57400a7185713b602127d2cf74f2cb241134e2403a65d11cd62`.

Do not confuse these with the async diagnostic image. The profiler helper currently reuses the saved command/environment from the local SK0 series; it needs these ignored artifacts and is not a standalone clean-clone reproducer.

## Safety and checks

Production pins, `.env`, original metadata and models were not changed; no unrelated container was stopped; no clock/power/affinity/cache-flush changes. All owned test containers were cleaned up; only the pre-existing controller remained at the end. No fault signatures were detected in the latest captures, which does not establish answer correctness or fix B. Decode requests generally ended at the reasoning token limit, without a final answer.

CPU suite: **36 tests passed**. Whitespace check passed. Public JSON checksums are verified before commit; secrets/raw environment dumps/models are excluded from Git.
