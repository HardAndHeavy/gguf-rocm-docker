# Colibri investigation checkpoint — 13 November 2026

## Current decision

**Maintainer's scratch hypothesis tested; pinned PR #2809 restores the observed old decode performance.** Following [the correction](https://github.com/JustVugg/colibri/issues/2757#issuecomment-6853957759), the user authorized the [scratch-limit / fix-branch validation](A-SCRATCH-LIMIT.md). Same-image default/1GiB/1GiB/default = **26.52 / 38.00 / 37.04 / 26.66 tok/s**; warmed trace shows per-cc_dnrec use-once scratch churn disappearing with the override. Old/fix/fix/old without override = **40.27 / 40.34 / 40.68 / 40.31 tok/s**. [English follow-up](issue-A-scratch-ready-to-post.md) was confirmed sent by the user on 13 November. Investigation paused pending maintainer feedback. Earlier follow-ups were sent by the user. No automatic comments/PRs, production changes, broad bisect or private kernel patches. Device-MTP/quality not validated by this performance result.

## Completed evidence

1. [PR #2775 validation](PR2775-VALIDATION.md): bounded B integration requests pass without captured fault; A auto selects bus. This is not proof that historical fault B is fixed.
2. [Contemporaneous forced-bus old/new ABBA](A-FORCED-BUS-REVISIONS.md): old ~40, new ~27 tok/s.
3. [Matched no-cache rebuild and allocator-only diagnostic](A-REBUILD-ALLOCATOR.md): matching packages/toolchain and bit-identical respective binaries; gap persists. Reverting only persistent split-part acquisition on new did not restore speed.
4. [SK0/PROMOTE0 ABBA](A-SK0-ABBA.md): medians **40.1241 / 26.3367 / 26.1986 / 40.0327 tok/s**, new/old **−34.36% / −34.56%**. PROMOTE0 changes pool coverage on both revisions (33.02 → 7.30 GiB); not isolated SK ablation against the earlier series. Retained slow sample and MCLK anomaly, no causal attribution.
5. [Warmed-engine profiler smoke and two trace pairs](A-SK0-TRACE.md): actual attach/capture works with startup opt-in `ROCP_TOOL_ATTACH=1`; real qwen38 target. `cc_dnrec_k<128>` shows ~4.2× median duration, scratch field 1092 → 2600, equal dispatch count/geometry. Large asymmetric profiler overhead and extreme records prevent ordinary wall-time attribution. `bd_gemv_i8_k` does not show a uniform large slowdown. This earlier stage alone was not root-cause proof.
6. [Scratch threshold / PR #2809](A-SCRATCH-LIMIT.md): new same-image ABBA improves +43.30%/+38.95%; 2268 per-cc_dnrec use-once scratch allocation/free pairs at default disappear with 1 GiB. Larger reserve changes residency, so not an isolated kernel-cost comparison. Full pinned fix branch restores ~40 tok/s without override; additional capture reports scratch1092, median16.52us, no warmed scratch events. [Public evidence](evidence/A-scratch-limit.json) and checksums prepared. Profiler wall rates remain heavily perturbed. Non-MTP only, not quality/device-MTP or isolated single-commit proof.

## Next step

The user confirmed sending the new qualified [follow-up](issue-A-scratch-ready-to-post.md). Await maintainer feedback; no further experiments are scheduled. PR #2809 was tested as its full pinned branch, not an agent-authored snapshot-removal patch. No need for a broad bisect or another allocator rollback. Do not enable the 1 GiB override as a production default: it changes reservation and expert placement, while the tested fix restores speed without it. Any production adoption or device-MTP validation is a separate decision.

## Preserved local state (not pushed)

Raw build logs, snapshots, full responses, telemetry and profiler traces remain under gitignored `data/colibri-investigation/` (about 1.3 GiB after scratch/fix validation). Models, original control metadata, `.env` and local Docker images also remain local. **The Git commit/push is not a backup of these ignored artifacts or images.** Public extracts and checksums are tracked under [evidence/](evidence/).

Key raw series:

- `pool-ab/20261113-131251` — matched rebuild old/new/new/old.
- `pool-ab/20261113-133252` — new stock/async/async/stock diagnostic.
- `pool-ab/20261113-144141` — SK0/PROMOTE0 ABBA.
- `sk0-abba/` — orchestration, summaries, trace analyses/validation and `profiler-smoke-old`, `trace-old/new`, `kernel-only-old/new` captures.
- `pool-ab/20261113-162340` — same-image scratch threshold ABBA.
- `pool-ab/20261113-163753` — old / PR2809 / PR2809 / old, no override.
- `scratch-limit/` — orchestration, scratch traces default/1GiB/fix, installed-revision source, build/manifests and summaries.

Immutable unmodified images for any later matched comparison:

- old `0a6f235b0c7a20726e28e6e0229ef1201de74638`: `sha256:a989a4141762cce9d0a80819312635d195d5503c9fc87838805d81ec59838d88`.
- new `b92eccd79ac60f196146f784c241ea076adda6f6`: `sha256:7de12e467442f57400a7185713b602127d2cf74f2cb241134e2403a65d11cd62`.
- fix PR2809 `efe73475e1689278e40919dc75ab0f08b09a0e3d`: `sha256:02e93577338f5ef970d4f66966eba69a159a34f259d277ff0e6191dfc5dda1c5`.

Do not confuse these with the async diagnostic image. The profiler helper currently reuses the saved command/environment from the local SK0 series; it needs these ignored artifacts and is not a standalone clean-clone reproducer.

## Safety and checks

Production pins, `.env`, original metadata and models were not changed; no unrelated container was stopped; no clock/power/affinity/cache-flush changes. All owned test containers were cleaned up; only the pre-existing controller remained at the end. No fault signatures were detected in the latest captures, which does not establish answer correctness or fix B. Decode requests generally ended at the reasoning token limit, without a final answer.

CPU suite: **37 tests passed**. Whitespace check passed. Public JSON checksums are verified before commit; secrets/raw environment dumps/models are excluded from Git.
