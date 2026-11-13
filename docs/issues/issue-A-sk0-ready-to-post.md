# Issue A — SK=0 follow-up (posted by user)

**Posted by the user on 13 November 2026 (user confirmation).** Archived local text, not a synchronized copy of GitHub. The agent did not post automatically. Waiting for the maintainer before further diagnostic patches.

---

I have now completed the unmodified-image check with explicit `COLI_CUDA_GEMV_SK=0` and `COLI_CUDA_CHAIN_PROMOTE=0` on both matched rebuilds. Forced bus, MTP/lookup off, no thinking override, the same snapshot restored before each process, old/new/new/old; three measured 192-token decode requests per process after warmup:

| Process | Revision | Median decode tok/s |
|---|---|---:|
| 1 | old `0a6f235b` | 40.1241 |
| 2 | new `b92eccd7` | 26.3367 |
| 3 | new `b92eccd7` | 26.1986 |
| 4 | old `0a6f235b` | 40.0327 |

The paired new-versus-old differences are **−34.3619% and −34.5571%**. These are two process-level comparisons, not twelve independent repeats. The gap survives this profile, alongside the earlier negative allocator-only control; this does not identify the responsible kernel or prove an allocator cause.

**Important caveat:** explicitly disabling promotion also changes pool coverage on **both** revisions: approximately **33.02 → 7.30 GiB**, now covering only **5390 nonresident experts**, rather than all **24576**. All current processes have **19186 resident experts** and zero hybrid steps. Actual promotions were already zero in the prior series, but disabling them still changes bookkeeping/arena/staging. This is therefore not a pure SK-only comparison against the earlier profile.

I retained the third process’s 23.530965 tok/s sample. Its decode-run-2 window contains one MCLK 96 MHz sample at 14:47:41.886 +03:00; causation is unknown. Clocks were observed, not locked. All measured decode requests completed with 192 tokens and `length`, with no captured fault signatures; they stopped in reasoning without a final answer, so this is not an answer-correctness claim. Source integrity remained unchanged.

I also completed a bounded attach smoke and two separate old/new warmed-engine trace pairs (kernel-only, and kernel + HIP runtime/copy/allocation services). Attach targets were the real `qwen38` processes, opted in with `ROCP_TOOL_ATTACH=1` before startup; startup/warmup were outside capture. Each paired capture contains 124899 kernel records, and all 63 kernel-name/workgroup/grid groups have matching old/new call counts. These are repeated/cached-prefix 64-token whole-request captures, not marker-isolated decode.

A repeatable observation is **`cc_dnrec_k<128>`**, 2268 calls each, workgroup 128 / grid 6144:

| Capture mode | Old median | New median |
|---|---:|---:|
| Kernel + HIP/copy | 16.24 µs | 67.76 µs |
| Kernel-only | 16.36 µs | 70.12 µs |

The profiler reports `Scratch_Size` **1092 → 2600**, with VGPR=256, SGPR=128 and LDS=2048 unchanged. This is a resource field, not measured spill traffic. The source diff adds a conditional per-row snapshot-copy block to this kernel; I have not established whether that branch executes in this non-MTP run, or whether compiling it changes HIP codegen/resource pressure.

In contrast, I do not see a uniform large `bd_gemv_i8_k` duration increase. For example, `<23,1,false,false,false>` has 6615 calls in both expanded captures, total 320.05 / 317.96 ms; shape-separated comparisons are in the evidence. The new trace also has more `hipGetDevice` calls (2898 → 37989), but their measured API time alone is small.

**Profiling caveat:** tracing has large asymmetric overhead and extreme retained duration records (about 1.05 s in expanded/new and 645 ms in kernel-only/old). Traced tok/s is therefore not a valid performance comparison. The separate attach-enabled unprofiled controls still give old ~40 / new ~26 tok/s. The `cc_dnrec` duration increase alone does not account for the entire ordinary gap; this is a candidate, not a root-cause claim.

Would you prefer a narrow **HIP-only diagnostic that compiles out/guards the new `cc_dnrec_k` snapshot-copy block for this non-MTP test**, or another codegen/resource check first? I have not applied that patch or the old-sums patch, and have not changed production pins.

---

Local report: [A-SK0-TRACE.md](A-SK0-TRACE.md). Public-ready extract: [A-sk0-trace.json](evidence/A-sk0-trace.json), [SHA256](evidence/A-sk0-trace-SHA256.json). These relative links are local repository references, not uploaded GitHub attachments; attach the extract manually if desired.
