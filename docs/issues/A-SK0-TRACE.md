# A — bounded warmed-engine trace after SK=0 ABBA

**13 November 2026. Local captures completed; preliminary diagnostic evidence, not root-cause proof.** Related [throughput ABBA](A-SK0-ABBA.md). Production images/pins, `.env`, original metadata and hardware settings unchanged. The user confirmed posting the SK0/trace follow-up on 13 November; the agent made no automatic GitHub posts.

## Capture method and validation

- Same unmodified matched rebuilt old `0a6f235b` / new `b92eccd7` images; forced bus, SK=0, PROMOTE=0, MTP/lookup off, context8192/RAM48/OMP8, W4 unchanged.
- Each owned target starts from a copy of the original control state. Explicit **`ROCP_TOOL_ATTACH=1` before HIP initialization** is required by these installed profiler libraries; an ordinary already-running engine is not attach-ready. Dedicated container gets only container-scoped `SYS_PTRACE`, not privileged mode; no global ptrace/security changes. API remains loopback-only with an unsaved random key.
- Identify `/app/c/qwen38`, not Python dispatcher, and verify `rocp-bg-attach` thread. Model startup and two requests (warmup, unprofiled control) precede attachment.
- rocprofv3 1.4.1 attaches successfully for a bounded **15-second** window. Wait for `:: success`, issue one **64-token** saved request, then wait for normal detach/output flush. Fresh target per capture, no tracing-service changes on an existing attached PID.
- First a separate old-image 16-token kernel-only smoke produced **29,667 kernel records**. Then two separate old/new pairs: expanded kernel/HIP runtime/copy/allocation services, and kernel-only to check perturbation. All four paired captures contain **124,899 kernel records**; expanded captures also contain **73 copy records** each. All **63 kernel-name/workgroup/grid groups have equal old/new dispatch counts** in each pair. All observed kernel records use stream 1.
- Real nonzero timestamped dispatches, kernel symbols and shapes are present; attach and detach succeed. No captured fault/dropped/failed diagnostics were found. This is not a mathematical guarantee that no records were lost. No allocation event file was emitted in the expanded capture despite enabling that service; absence must not be called an allocator-hit proof.
- Same decode prompt and token budget per target. The prompt was repeated after warmup and its prefix was cached; **these are whole warmed-request traces, not a separately marked/prefill-isolated decode interval**. Do not equate 64 output tokens with 64 captured forwards without markers. No per-token timestamp instrumentation was added.
- The first smoke and expanded pair have **no dedicated sysfs telemetry capture**. The later kernel-only pair includes phase-tagged ~1Hz telemetry. Keep that limitation; clocks were not fixed in any test.

Implementation: `scripts/profile-colibri-warm-smoke.py`. Local captures and analysis under `data/colibri-investigation/sk0-abba/`: `profiler-smoke-old`, `trace-old/new`, `kernel-only-old/new`, `trace-summary.json`, `kernel-only-summary.json`, `analyze-traces.py`. These gitignored paths are not public attachments.

## Strong profiler perturbation: do not use traced tok/s as benchmark

| Mode / image | Attach-enabled, unprofiled control tok/s | Traced tok/s |
|---|---:|---:|
| Expanded / old | 40.34 | 33.48 |
| Expanded / new | 26.70 | 12.50 |
| Kernel-only / old | 40.10 | 19.33 |
| Kernel-only / new | 26.22 | 21.85 |

The unprofiled controls retain the expected old/new difference. Tracing has large, asymmetric perturbation. Expanded new includes roughly **1.05-second extreme kernel durations** and a **1.052-second hipLaunchKernel API call**; kernel-only old includes an extreme kernel duration of **645 ms**. These records are retained, not silently trimmed. Their cause is unknown. Traced wall throughput even reverses ordering in the kernel-only pair, so it cannot establish variant superiority or partition the ordinary ~34% regression.

For expanded old/new, recorded kernel interval unions are **1290.40 / 3501.41 ms**; unions including recorded device copies are **1294.94 / 3506.48 ms**, within first-to-last device spans **1880.35 / 5038.21 ms**. The remaining **585.42 / 1531.72 ms** are merely time without recorded kernel/copy activity inside that span, **not proven CPU overhead**: dependencies, profiling, omitted events and other waits remain possible. HIP API durations overlap GPU execution and must not be added to these times. Analysis uses interval unions, not wall minus a sum of overlapping kernels.

## Repeatable kernel-local observation: cc_dnrec_k<128>

| Capture | Calls | Workgroup / grid | Median duration | Reported scratch size |
|---|---:|---|---:|---:|
| Expanded old | 2268 | 128×1×1 / 6144×1×1 | 16.24 µs | 1092 |
| Expanded new | 2268 | same | 67.76 µs | 2600 |
| Kernel-only old | 2268 | same | 16.36 µs | 1092 |
| Kernel-only new | 2268 | same | 70.12 µs | 2600 |

The ratio is approximately **4.17× / 4.29×** at matched reported geometry and count, across both tracing modes. Profiler reports VGPR=256, SGPR=128, LDS=2048 in both binaries. Scratch_Size increases from 1092 to 2600; this is the profiler's resource field, **not a measurement of actual spill traffic**. Matching geometry does not prove identical runtime arguments or data.

Read-only source diff already archived in `rebuild-control/source-analysis/cuda_chain.cu.diff` shows that this kernel gained a conditional per-row snapshot write (`s < p.snap_n`, indirect destination, unrolled KD store loop) for MTP verification. That code is compiled even in this non-MTP run; whether its runtime branch executes here has **not** been traced. It is a specific codegen/resource-pressure hypothesis, not an established cause. No diagnostic patch was applied.

This kernel's duration increase alone does **not** explain the full ordinary wall-time gap. It provides a useful next discriminator rather than permission to stop investigating host/runtime gaps.

## bd_gemv and runtime observations

The expanded pair does **not** show a uniform large slowdown in `bd_gemv_i8_k`: for example, `<23,1,false,false,false>` has 6615 calls each and total duration **320.05 / 317.96 ms**; its aggregate median is 37.321 / 36.321 µs, though it contains multiple shapes. Full analysis therefore also groups by workgroup/grid. Several shape medians move only a few percent. This does not exclude arithmetic/codegen changes in all circumstances, but **does not justify jumping straight to the old-sums patch as the demonstrated cause**.

Expanded HIP trace records **2898 → 37989 hipGetDevice calls**; medians 0.161 → 0.111 µs and summed API duration 0.539 → 4.542 ms. Kernel-launch counts match. Extra queries are real, but their recorded duration is much too small to equate directly to the complete ordinary throughput gap; profiler overhead and untraced host bookkeeping remain caveats.

## Next narrow step

The user has sent the completed SK0 result and these qualified observations to the maintainer. Wait for their response about whether to test a **HIP-only compile-time removal/guard of the new snapshot-copy branch in cc_dnrec_k** for the non-MTP diagnostic, or which codegen/resource inspection they prefer. Preserve MTP semantics and production pins; a runtime branch assumed inactive is not equivalent to compile-time removal. No such patch, broad bisect, rounding rollback or new device-MTP test has been performed here. If later authorized, use a disposable diagnostic image, validate actual patch scope and unprofiled throughput first, then inspect resource/kernel changes.

Public extract with provenance, all throughput runs/warmups, shape comparisons and checksums: [A-sk0-trace.json](evidence/A-sk0-trace.json), [SHA256](evidence/A-sk0-trace-SHA256.json). Raw profiler output is large and not automatically uploaded.
