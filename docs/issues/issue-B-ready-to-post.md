# Title

[HIP][Qwen3.8 MTP] Memory fault reported in gemv_i8_w4<4> with thinking disabled on R9700

# Body

## Summary

On Radeon AI PRO R9700, Qwen3.8 Flash-Next device MTP with `chat_template_kwargs.enable_thinking=false` failed with `HSA_STATUS_ERROR_MEMORY_FAULT`, reported in `gemv_i8_w4<4>`.

On the tested pinned revision:

- Full and conservative device-MTP configurations both failed.
- MTP off and CPU-head controls completed the short/decode request pair.
- Disabling W4 **or** split-K allowed the device-MTP request pair to complete.

These are diagnostic workarounds, **not fixes**. I have not established that the reported kernel is the original source of the fault; asynchronous GPU error reporting could point to a later operation.

A follow-up standalone CPU-reference test passes through the actual W4/split-K production dispatcher. I therefore do not currently have a demonstrated root cause or a justified source fix.

## Environment

- Colibri dev: `0a6f235b0c7a20726e28e6e0229ef1201de74638`, including device-MTP PR #2559
- GPU: AMD Radeon AI PRO R9700, gfx1201, nominal 32 GiB VRAM, wave32
- Pinned-image toolchain:
  - HIP `7.16.26385-0000000`
  - AMD clang `24.0.0git`
  - LLVM revision `d6f6cb691863e9258034ab48c1dfce21689d5606`
- Model:
  - `Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS-00001-of-00002.gguf`
  - Corresponding second shard
- MTP head: `mtp-Qwen3.8-Flash-Next-Q2_0.gguf`
- Context: 8192
- RAM budget: 48 GiB
- Prompt lookup disabled: `COLI_LOOKUP=0`

Model-content hashes have not yet been captured. This report concerns the pinned revision, not a verified reproduction on current upstream.

## Device-MTP settings

Common device settings:

```text
Q38_MTP=1
Q38_MTP_CHAIN=1
Q38_MTP_DRAFTS=0
```

`Q38_MTP_DRAFTS=0` selects automatic drafts here, not a hard zero-draft configuration.

Full configuration:

```text
COLI_CUDA_CHAIN_MTP_CARD=1
COLI_CUDA_CHAIN_MTP_POOL=1
```

Conservative configuration:

```text
COLI_CUDA_CHAIN_MTP_CARD=0
COLI_CUDA_CHAIN_MTP_POOL=0
```

The CPU-head control used `Q38_MTP_CHAIN=0`. The off control disabled the head.

## Historical full-model reproduction

Each profile started in a fresh process and received the same fixed short request followed by a decode request. The profiles reused mutable dev state rather than independent restores of one hashed snapshot, so cache/history/placement effects are not fully isolated.

First request:

```json
{
  "model": "qwen3.8-flash-next-colibri",
  "messages": [
    {
      "role": "user",
      "content": "Ответь одним словом: какой элемент обозначается символом Fe?"
    }
  ],
  "temperature": 0,
  "max_tokens": 192,
  "stream": true,
  "stream_options": {
    "include_usage": true
  },
  "presence_penalty": 0,
  "frequency_penalty": 0,
  "chat_template_kwargs": {
    "enable_thinking": false
  }
}
```

The second request used the same settings with this user message:

```text
Напиши подробный технический дневник тестирования большой языковой модели на AMD GPU: последовательно опиши подготовку, холодный запуск, prefill, decode, контроль памяти, повторяемость и типичные ошибки. Пиши развёрнуто, не менее 1200 слов, без сокращения ответа.
```

No UUID prefixes were used for this correctness pair.

| Configuration | Short request | Decode request |
|---|---|---|
| MTP off | `Железо`, stop, 3 tokens | Visible text, length, 192 tokens |
| CPU head | Same short answer | Visible text, length, 192 tokens |
| Device full, W4/SK defaults | No completed answer; GPU fault | Engine-error response |
| Device conservative, W4/SK defaults | No completed answer; GPU fault | Engine-error response |
| Device full, `COLI_CUDA_GEMV_W4=0` | Same short answer | Visible text, length, 192 tokens |
| Device full, `COLI_CUDA_GEMV_SK=0` | Same short answer | Visible text, length, 192 tokens |

“Completed” means these requests completed, not exhaustive output correctness or token/logit parity.

The failing short request received HTTP headers but no completed answer or usage. Its saved response alone did not contain an explicit error field; the fault and subsequent engine termination are visible in the logs.

## Fault diagnostic

Both full and conservative device configurations reported:

```text
Warning: Queue error - HSA_STATUS_ERROR_MEMORY_FAULT

GPU HANG ANALYSIS
grid=[2560, 7, 1]
workgroup=[256, 1, 1]
group_seg_size=27712

kernel:
void gemv_i8_w4<4>(
    float*, float*, float const*, signed char const*,
    float const*, int, int, int, int, int
)

Memory access fault by GPU node-1.
Reason: Page not present or supervisor privilege.

colibri: the engine dispatcher stopped:
colibri engine exited unexpectedly
```

Addresses and container host identifiers are omitted.

The runtime grid x dimension is in work items: 2560 corresponds to 10 blocks of 256. Tensor dimensions and pointer arguments were not captured, so this diagnostic does not establish the actual matrix shape or original bad access.

## Standalone follow-up: actual W4 dispatch passes

I added a deterministic standalone test using the pinned backend with logging-only instrumentation of its dispatcher.

Test conditions:

- Signed int8 row-scaled weights, fmt=1
- Float32 inputs and scales
- CPU double-accumulation reference using those same stored values
- Deterministic xorshift32 seed `0x6d2b79f5`
- An S=4 request and four separate S=1 calls
- Three repeats per shape
- W4 enabled
- Split-K on/off in separate processes because the environment switches are cached
- Preset tolerance: `abs(error) <= 1e-3 + 1e-4*abs(reference)`
- Runtime/launch/synchronization errors, nonfinite outputs and outer output-buffer guards checked

Both processes passed: **144 row-result records, zero failures**.

An important coverage detail: **K=2048, N=300 does not select W4**, because `K*N < 2^21`. I retained it as a fallback control and added shapes that actually select W4.

Observed S=4 production dispatch:

| K / N | Split-K | Path | kz / kc | sr | Shared bytes | Grid in blocks |
|---|---|---|---|---:|---:|---|
| 2048 / 300 | Both | Fallback | — | nr=1 | 9232 | 38,4,1 |
| 2048 / 1100 | On | W4 | 2 / 1024 | 4 | 18496 | 35,2,1 |
| 2048 / 1100 | Off | W4 | 1 / 2048 | 4 | 36928 | 35,1,1 |
| 10240 / 300 | On | W4 | 7 / 1536 | 4 | 27712 | 10,7,1 |
| 10240 / 300 | Off | W4 | 1 / 10240 | 1 | 46096 | 10,1,4 |

The larger shapes exercise partial output tiles; K10240/N300 with split-K also exercises a partial final K split.

Maximum absolute CPU-reference errors:

| K / N | Split-K on | Split-K off |
|---|---:|---:|
| 2048 / 300 | 1.845e-6 | 1.845e-6 |
| 2048 / 1100 | 1.364e-6 | 1.696e-6 |
| 10240 / 300 | 3.434e-6 | 8.769e-6 |

### Important interpretation

For K10240/N300, disabling split-K also reduces `sr` from 4 to 1 due to the shared-memory limit. Therefore, **the full-model SK=0 workaround does not isolate split reduction alone**: it may also change row batching.

K2048/N1100 retains sr=4 with split-K both on and off and passes.

The standalone build used O2 versus production O3. It does not reproduce the full model's allocation, stream, scratch-lifetime or preceding-kernel sequence. No GPU sanitizer or input/scratch guards were used. Passing these tests does not prove the integration path safe.

## Latest full-model follow-up: inconclusive

I also attempted a bounded fresh-snapshot integration follow-up using direct Docker runs, without Compose or OpenWebUI.

Neither the off nor the full-device process reached API readiness within the allocated startup windows, approximately 198 and 183 seconds respectively. **No chat request was submitted**, and no new GPU fault or correctness result was obtained.

These startup-limited attempts should not be counted as a successful reproduction, a passing control, or evidence that the historical fault has disappeared.

## Questions

1. Is this HIP device-MTP/no-thinking interaction already known, and which pinned base would you recommend testing next?
2. Given the passing standalone checks, what would be the most useful next diagnostic: actual dispatch arguments, scratch allocation/free ordering, stream lifetime, or synchronization around preceding kernels?
3. Is there an existing integration/debug test that exercises this device-MTP path with thinking both enabled and disabled?

I can provide the standalone harness, dispatch logs and sanitized historical request/fault artifacts. I have deliberately stopped short of long tracing/bisect or globally disabling W4/split-K without a demonstrated cause.
