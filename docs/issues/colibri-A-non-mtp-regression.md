# Draft issue A: lower non-MTP decode throughput on pinned dev versus main, R9700/HIP

**Unsubmitted historical report.** Measurements below were saved on 2026-11-09; this draft was prepared by read-only inspection on 2026-11-11. No containers or benchmarks were run to prepare it. This is observation A from `docs/MTP-HIP.md`, not the separate device-MTP memory-fault investigation B. No claim is made about current upstream branches or a responsible commit, PR, kernel, or subsystem.

## Summary / maintainer question

With MTP disabled and prompt lookup disabled, the saved controlled series shows median decode throughput of **45.4526224365 tok/s on pinned main versus 37.2574301537 tok/s on pinned dev**, a **18.0302% decrease** relative to main. These are three measured requests per case, not interleaved process-level repeats. The result warrants investigation but does not establish a causal regression or identify its source. Internal placement and execution paths visibly differ between the revisions.

Could you recommend a pinned investigation/bisect base, and advise which placement, expert-cache/promotion, pool-server, and per-layer timing diagnostics should be captured for a non-MTP HIP comparison? Are any changes between these exact revisions already known to affect non-MTP decode? We would like to agree on a controlled interleaved test before proposing a patch; we are not attributing this result to MTP PR #2559 or proposing a global fast-path disable.

## Exact revisions and images

| | main baseline | dev comparison |
|---|---|---|
| Colibri revision | `0a5504a1dc64f86fcd0fe7db298b0448c730e7e6` | `0a6f235b0c7a20726e28e6e0229ef1201de74638` |
| Image tag (historical, not immutable) | `gguf-rocm-colibri:local` | `gguf-rocm-colibri:mtp-dev-0a6f235b` |
| Image ID and saved repository digest suffix | `sha256:7c4d2f8c2d9c0553aa05822d31d2a0a361301d7cfcbef22da9ac68951ea7395d` | `sha256:e888c06f9db6a2d55997c43f2b0bd45c0face5d3ff428eba2b8a19dc65a299cc` |
| Throughput report `created_at` (UTC) | `2026-11-09T17:26:48.761947+00:00` | `2026-11-09T17:33:34.735222+00:00` |
| Runtime capture `created_at` (UTC) | `2026-11-09T17:29:59.833460+00:00` | `2026-11-09T17:36:51.276024+00:00` |

The dedicated `ru.hardandheavy.colibri.revision` image labels agree with the respective saved `COLIBRI_REF`. The generic OCI revision label is instead `68e30f4f8403bc2353403246cc0685e414548574` on both images and should not be mistaken for the Colibri revision. Both record base image `hardandheavy/transformers-rocm:3.0.1`, base digest `sha256:a46fe7a3efd7c7f87a20d63f58bed76c499604d959597584ffb117c2b336c74c`. These labels do not by themselves prove identical compiler options or toolchain packages; the selected runtime/config records do not give an exact ROCm/compiler version.

## Hardware, model, settings, and request state

- Radeon AI PRO R9700, `gfx1201` (research notes/build configuration), nominal 32 GiB. Both runtime captures report VRAM total **34,208,743,424 bytes**. Logs identify the AMD GPU under upstream's CUDA-named HIP interface; CUDA labels in these logs do not imply NVIDIA hardware.
- Host recorded by both benchmark JSONs: `Linux-7.0.0-43-generic-x86_64-with-glibc2.43`, Python `3.14.4`. Recorded system RAM total is 65,193,451,520 bytes.
- Model: `Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf`, two GGUF parts, 1,224 tensors, qwen4exp/48 layers, native GGUF link import. Both saved state `gguf.json` files give total size **68,026,093,024 bytes** and two parts. The selected artifacts identify the same filename/size, not a cryptographically verified model hash; model/tokenizer hashes should be added to a reproducibility bundle.
- Saved configuration on both: `COLIBRI_CTX=8192`, `COLIBRI_RAM=48`, `COLIBRI_MTP=off`, `Q38_MTP=0`, `COLI_LOOKUP=0`. Both startup logs explicitly confirm `MTP head: off (--no-mtp)` and chain allocation for 8192 positions.
- Also saved identically: `Q38_MTP_CHAIN=1`, `Q38_MTP_DRAFTS=0`, `COLI_CUDA_CHAIN_MTP_CARD=1`, `COLI_CUDA_CHAIN_MTP_POOL=1`. These recorded settings are not evidence that a head ran: MTP is off. `COLI_CUDA_GEMV_W4`, `COLI_CUDA_GEMV_SK`, and `HIP_LAUNCH_BLOCKING` are recorded empty (no explicit override, not forced off).
- The research notes describe one slot. The current compose configuration specifies `COLI_CUDA=1`, `COLI_VULKAN=0`, `COLI_CUDA_HOST_POOL=0`, chain pool/layerwise defaults 1, chain rows 64, `COLI_NO_OMP_TUNE=1`, and an OpenMP default of eight threads. These are runner/compose context, **not a complete captured historical effective environment**: the saved per-series config does not record every option or a resolved slot/thread override. Dev logs independently report a pool server with 12 threads and a prompt CPU estimate using eight threads.
- Distinct state directories: `./data/colibri-mtp-main-control` and `./data/colibri-mtp-dev-control`. Notes call these comparable snapshots. Both startup logs report **82,646,400 expert-history selections** from `.coli_usage`, but equal selection totals do not prove identical file bytes or identical resident experts. A pre-run snapshot hash manifest was not identified in the selected artifacts. Mutable state after the runs cannot establish its pre-run identity.
- Benchmark request override is **`{}`**, saved as `BENCH_REQUEST_JSON={}` and JSON `parameters.request={}`. The requests use temperature 0, max_tokens 192, streaming, and stream usage. **No `enable_thinking=false` override was applied in these series**; measured decode/prefill output is reasoning-only at the token budget. Do not substitute the runner's current no-thinking default for this historical request.
- A fixed-prompt, cold correctness pair (short then decode) ran before the throughput series. Throughput order is short, decode, prefill, with one warm-up per case followed by three measured requests. Throughput uses fresh UUID prefixes (`unique_prompt_prefix=true`), so prompts, tokenization, routes, and generated text differ across requests and revisions. Warm-up and earlier cases can change expert residency/history; this is not a fresh state per measured request.

## Raw measurements and arithmetic verification

Source basename for each side: `data/benchmarks/mtp-hip-off-{main,dev}-nolookup-controlled`.

Measured **decode case**, request order retained:

| Revision | Run | Completion tokens | Total seconds | TTFT seconds | Decode tok/s |
|---|---:|---:|---:|---:|---:|
| main | 1 | 192 | 7.1587209270 | 2.1323969420 | 38.0013096811 |
| main | 2 | 192 | 6.1784765430 | 1.9961851810 | 45.6700783137 |
| main | 3 | 192 | 6.2449454560 | 2.0425283350 | 45.4526224365 |
| dev | 1 | 192 | 6.9098206020 | 1.8745732280 | 37.9451450307 |
| dev | 2 | 192 | 7.0026317770 | 1.8746426980 | 37.2574301537 |
| dev | 3 | 192 | 7.1071062020 | 1.8835504210 | 36.5750749535 |

All measured requests in all three cases succeeded (three per case per revision); decode requests finish with `length`, zero visible-content characters, and 192 usage-reported completion tokens. Decode prompt token counts are main **160/162/162**, dev **163/162/161**. Main's first measured decode is substantially slower than its other two; it is retained, not discarded.

Medians of the three measured requests, computed per metric (not necessarily from the same request):

| Case / metric | main | dev |
|---|---:|---:|
| short decode tok/s | 46.854717 | 36.046632 |
| short total s | 2.713049 | 2.965393 |
| short TTFT s | 1.497778 | 1.229056 |
| decode decode tok/s | **45.452622** | **37.257430** |
| decode total s | 6.244945 | 7.002632 |
| decode TTFT s | 2.042528 | 1.874643 |
| decode gross tok/s | 30.744864 | 27.418263 |
| decode event-gap p95 ms | 24.324260 | 33.029899 |
| prefill-case TTFT s | 30.299318 | 33.329362 |
| prefill-case total s | 38.227856 | 38.864732 |
| prefill-case decode tok/s | 24.535641 | 34.044366 |

The long-prompt case is **not uniformly worse**: dev has higher decode throughput after that prompt, while TTFT is longer. TTFT is not an isolated kernel-prefill time. Long-prompt token counts differ: main **2754/2758/2753**, dev **2751/2753/2756**. Short completions differ too: main 57/57/57 tokens, dev 62/63/61.

Verification performed directly on the raw JSON/CSV rather than transcribing the rounded research table:

- CSV decode-rate values match the JSON measured `runs` values for all cases on both revisions.
- Recomputed every measured request's decode rate as `(completion_tokens - 1) / (last_token_s - ttft_s)`; agreement with saved rates is within `1e-9` tok/s. This is the client-observed first-to-last streamed-token window, not `192 / total_s` or an instrumented engine-only rate. Gross rate is `completion_tokens / total_s`.
- Recomputed the headline as `100 * (37.257430153715184 / 45.45262243651916 - 1) = -18.030185814360188%`.

## Placement and runtime differences visible with MTP off

These are evidence of differing state/settings/code paths, **not explanations of the throughput result**:

| Startup-log observation | main | dev |
|---|---|---|
| Chain reservation | 2.45 GiB | 2.39 GiB |
| Auto-placed trunk | 4879.9 MB | 4817.8 MB |
| Expert budget | 25.89 GB | 25.93 GB |
| Expert arena | 18,260 fixed-size slots, 1.45 MB | per-layer sizes, three sizes from 1.13 to 1.45 MB; initial estimate ~19,142 |
| Actual warm-start resident experts | 18,260 | 19,186 |
| Host-pool experts not on card | 6,316 | 5,390 |
| Host pool allocation | 34.57 GiB | 33.02 GiB |
| Promotion stop threshold over last 64 frames | 90% resident routes | 97% resident routes |
| Pool decode dispatch message | pooled experts copied first, 16 places / 23.0 MiB | pool server, 12 threads |
| Prompt pooled-expert handling | layer prefetch, 355 places / 511.4 MiB | layer-size prefetch, 355–455 places / 512.0 MiB; additional CPU prompt policy message |

Both report 416/416 offered trunk matrices resident, a 48-layer chain with 12 QSA layers and final mixer/lm_head on device, and cache 512 experts/layer. Dev also logs pre-request reservation of 64-row buffers and kernel loading. Dev emits warnings for wrapper-style environment names (including `COLIBRI_CTX`) and qwen36-only settings; these warnings alone do not show that wrapper command-line options were ignored.

Post-series runtime snapshots also differ: Docker memory usage main 39.98 GiB versus dev 38.57 GiB; PIDs 16 versus 28; cgroup memory.current 54,412,861,440 versus 54,044,229,632 bytes; GPU VRAM used 33,906,212,864 versus 33,655,508,992 bytes. These are point-in-time captures, not synchronized request peaks, and Docker's memory figure excludes inactive file pages. They do not establish CPU/GPU utilization, thermal/clock parity, or a bottleneck.

## Correctness scope and confounders

The separate fixed-prompt correctness artifacts use identical prompt hashes across revisions. Both short runs produce `\n\nЖелезо` (iron), 66 completion tokens, and the same content hash `1e404e12d18c9114be38f31d4fa4bca5956fc619502ae9a938ccd690092495d7`; their recorded reasoning lengths differ (250 versus 251 characters). Both decode runs consume 192 tokens with empty visible content. The empty-content hash is not a correctness comparison of reasoning, tokens, or logits. No full-model byte identity or final-logit parity is claimed.

Other limits:

- Main was measured before dev in two contiguous process series, not AB/BA. Three request repeats do not quantify between-process variability or eliminate warm-up/order/page-cache/clock/thermal effects. No confidence interval or significance claim is made.
- Comparable history totals and the same nominal model/context do not ensure equal runtime placement, expert traffic, cache hits, or internal paths. The startup logs explicitly show differences.
- UUID prompts and divergent reasoning prevent interpreting the rates as an exact token-for-token replay. Temperature zero alone does not establish bitwise reproducibility across implementations.
- Earlier `mtp-hip-off.json` used lookup on and a different history/cache state; it is not the no-speculation main baseline. The separate `mtp-hip-off-nolookup-controlled.json` reports another dev series (36.88 tok/s in the notes); it must not be merged with or substituted for this pinned main/dev pair.
- Device-MTP speedups and the no-thinking HIP memory fault belong to different experiments. Neither demonstrates the cause of this non-MTP observation.

## Follow-up still required (not performed for this draft)

1. Agree on pinned endpoints/base with the maintainer. Preserve image IDs, exact build flags, ROCm/compiler/driver versions, GPU/CPU details, power/clock/temperature telemetry, model/tokenizer hashes, full sanitized resolved launch options, and exact request payloads.
2. Restore independent copies of one hashed pre-run state snapshot for each fresh process; retain manifests for history and other mutable files. Keep lookup/MTP off, context/slot count/weights/policy and request order fixed. Document OS page-cache treatment rather than assuming a container restart resets it.
3. Use the same saved prompt corpus and seed/UUID sequence for both sides, fixed 192-token budgets, explicit thinking settings, and an identical correctness/warm-up schedule. Retain generated token counts/hashes and do not pool short or long-prompt case rates with the decode case.
4. Run repeated **interleaved main/dev and dev/main** process pairs (at least the planned one warm-up plus three measured requests per case, with more independent repeats for uncertainty). Capture placement/residency, promotions, pool CPU/server traffic, and per-phase timings alongside decode, TTFT, prefill, and full-task measurements. Keep all runs, including slow first requests and failures.
5. Only if the difference persists, bisect/profile on an agreed base. Test individual execution/placement controls separately in new processes and report what actually dispatched. Do not assume common environment names imply equivalent internal algorithms. A minimal patch and regression test require a demonstrated cause, not this throughput table alone.

## Evidence / attachment checklist

Local sources inspected: `docs/MTP-HIP.md`; for each of main/dev, `data/benchmarks/mtp-hip-off-<revision-name>-nolookup-controlled{.json,.csv,-config.env,-container.log,-runtime.json,-correctness.json,-correctness.csv}`; state `gguf.json`; and the current `scripts/run-colibri-mtp-hip.sh`, `scripts/benchmark.py`, `compose.colibri.yaml` for interpretation. The current runner is not an immutable record of the historical invocation; the saved configurations and request JSONs take precedence.

**`data/` is gitignored and these raw files are not attached to the repository.** A compact sanitized measurement extract is now available at `docs/issues/evidence/A-measurements.json`; its source hashes identify the inspected JSON bytes, not model weights. It is not a complete raw-log/runtime bundle. Before posting a complete reproducibility bundle, add sanitized snapshot manifests, request/prompt definitions, toolchain/build metadata and model hashes. Do not attach `.env`, authentication headers, API keys, usernames, or absolute home paths. This draft includes none of those sensitive values. It is an issue draft only; nothing has been submitted upstream.
