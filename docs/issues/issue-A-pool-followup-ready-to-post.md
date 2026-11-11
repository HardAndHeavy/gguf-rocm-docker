Thanks for the explanation. I ran the focused comparison on the same pinned dev revision, `0a6f235b0c7a20726e28e6e0229ef1201de74638` (not current dev).

**The result is mixed: GPU pool reads usually gave about 40–41 tok/s, but one GPU-read process fell to 33.80 tok/s. I retained it. This does not establish a repeatable return to the historical main result of 45.45 tok/s.** Changing the promotion threshold from 97% to 90% made essentially no difference in the tested workload, but promotion never actually occurred, so that part of the experiment did not exercise the policy difference.

### Setup and process order

- Radeon AI PRO R9700, gfx1201; CPU: **Ryzen 7 3700X, 8 cores / 16 threads**. Sysfs reported a negotiated PCIe link of **32.0 GT/s ×16**; this is not a measured transfer bandwidth.
- Same local dev image ID: `sha256:e888c06f9db6a2d55997c43f2b0bd45c0face5d3ff428eba2b8a19dc65a299cc`.
- Same two-part Qwen3.8 Flash Next IQ2_XS model, context 8192, RAM budget 48 GiB; MTP explicitly disabled on import and `Q38_MTP=0`, lookup disabled with `COLI_LOOKUP=0`. `OMP_NUM_THREADS=8`; no explicit pool-server thread override, W4 or split-K override.
- **A:** default pool path and promotion threshold.
- **B:** `COLI_CUDA_CHAIN_POOL_READ=1`, default promotion threshold.
- **C:** `COLI_CUDA_CHAIN_POOL_READ=1` and `COLI_CUDA_CHAIN_PROMOTE_HITS=90`.
- Eight fresh server processes, in order **A B B A | B C C B**: an A/B then B/A pair, followed by B/C then C/B.
- Before every process I restored the same metadata/history snapshot into the **same state-directory path**. Relative filenames, sizes and SHA-256 hashes matched before each launch; the source snapshot remained unchanged. Model shards were mounted read-only, but have **not** been content-hashed.
- This snapshot reports **89,524,320 history selections**, versus 82,646,400 in the historical report. It is common to all the new runs, not a claim to have recovered the original historical pre-run state.
- Request schedule: fixed short/decode smoke requests, then short warmup + three measured requests, then decode warmup + three measured requests. No long-prompt/prefill case in this follow-up. Throughput prompts use a saved UUID corpus, identical across processes and distinct within each process.
- Streaming, temperature 0, max_tokens 192, no thinking override, as before. All **24 measured decode requests** used 192 completion tokens, reported via streaming usage, and finished with `length`; visible answer text was empty at the reasoning budget. These are not no-thinking results or a full correctness comparison.

### Decode results

Client-observed `(completion_tokens - 1) / (last_token_time - first_token_time)`, tok/s. Each row is a separate process; three requests are nested repeats, not three independent process runs.

| Process order | Profile | Measured 1 | Measured 2 | Measured 3 | Process median |
|---|---|---:|---:|---:|---:|
| 1 | A — default | 36.10 | 35.65 | 36.15 | **36.10** |
| 2 | B — pool read | 41.79 | 40.56 | 40.49 | **40.56** |
| 3 | B — pool read | 33.80 | 34.40 | 32.51 | **33.80** |
| 4 | A — default | 35.68 | 35.52 | 35.99 | **35.68** |
| 5 | B — pool read | 41.45 | 41.03 | 40.68 | **41.03** |
| 6 | C — pool read + 90% | 40.72 | 40.67 | 40.84 | **40.72** |
| 7 | C — pool read + 90% | 40.75 | 40.65 | 40.79 | **40.75** |
| 8 | B — pool read | 40.76 | 40.66 | 40.75 | **40.75** |

Within the first block, B versus A is **+12.36%** in the A→B pair but **−5.26%** in the B→A pair. I have not pooled all four B processes against A or discarded process 3. Within the second block, C versus B is **−0.75%** and **+0.004%**, respectively. Main was not rerun, so the historical 45.45 tok/s is context, not a simultaneous control.

### Requested startup lines and runtime checks

Both A processes report:

```text
[chain] qwen38: the pool's server: 12 threads for a decode step's pooled experts (COLI_CUDA_CHAIN_SERVE_THREADS=0: the recording thread's)
```

The first A process reports:

```text
[chain] qwen38: host pool, every expert (the 5390 the card leaves and its own 19186) in 33.02 GiB of page-locked RAM the device reads over the bus (24.8 s to allocate, 95.5 s to read; COLI_CUDA_CHAIN_POOL=0 off)
```

The pool is **33.02 GiB in all eight processes**. Initial residency is 19,186 experts except process 4 (A), which has 19,180, with 5,396 instead of 5,390 experts left off-card. Thus equal starting state bytes did not produce perfectly identical automatic placement.

The A logs confirm decode pooled experts computed on the CPU. Their final cumulative pool-server counters are 9,791 slots / 1,347.4 ms and 9,880 slots / 1,357.5 ms, respectively. These are whole-process totals, not isolated measured-decode timings.

B/C have no CPU pool-server startup line, and their final chain counters report **zero hybrid layer steps**, versus 60,816 in each A process. The startup lines confirm **97% for A/B and 90% for C**. All final counters show **zero promotions**, zero evictions, and **98.6% resident routes**. Therefore the similar B/C rates cannot establish that the thresholds are equivalent when promotion is active.

One additional difference: cumulative prompt-path counters in A show four prompts' pooled experts handled on CPU and six staged; B/C show all ten prompts staged. I did not force a separate prompt-path policy, so this is a comparison of the requested configurations, not a fully isolated decode-only kernel experiment.

### Limits / next question

I did not flush OS page cache, lock clocks, change power settings, or pin CPU affinity. Startup took roughly 186–226 seconds per process, including reading the large RAM pool. There is no synchronized per-request CPU/clock/thermal trace explaining the slow third process, so I am not attributing it to a particular bottleneck. No HIP memory-fault signature appeared in the saved logs.

The runner stopped between processes 1 and 2 because its port-availability preflight did not allow prior connections' TIME_WAIT. I corrected that check with `SO_REUSEADDR` and resumed using the same saved snapshot and corpus; process 1 was retained, and no measured process was rerun or selected away. Subsequent processes completed normally.

Would the most useful next step be to investigate the slow GPU-read process with synchronized CPU/GPU/clock telemetry, or to test a colder/less-resident history snapshot that actually exercises promotion? The current results support investigating machine-specific pool-path selection, but do not yet demonstrate a stable restoration of main's throughput.

I have saved per-request metrics (including warmups), snapshot manifests, public launch settings, and selected startup/final counters. A compact sanitized extract is prepared locally; it is not uploaded as a GitHub attachment by this comment.
