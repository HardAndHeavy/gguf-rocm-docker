# Issue B: отправленный follow-up

Пользователь сообщил об отправке текста в [#2758](https://github.com/JustVugg/colibri/issues/2758) 11 ноября 2026. Ожидаем ответа maintainer. Ниже сохранён подготовленный текст комментария.

---

Thanks for identifying the hyper-connection matrices and for the concrete diagnostics. I agree that keeping split-K and four-row batching while changing only the `part` allocation is a more useful isolation test than either workaround.

I first retried the unmodified pinned build to establish a fresh failing baseline. **The historical fault did not reproduce in either of the two new processes**, including your forced-depth configuration.

### Fresh integration results

Same pinned dev revision `0a6f235b0c7a20726e28e6e0229ef1201de74638` and unchanged local image/backend, on the R9700. Each process started from an independent copy of the same hashed metadata/history snapshot. Lookup was off, device MTP and its routed experts were on the card, W4/split-K were left at their defaults, and thinking was explicitly disabled. Each process received the original short request followed by the decode request, greedy with a 192-token limit.

| Configuration | API readiness | Short request | Decode request | GPU fault |
|---|---:|---|---|---|
| Original automatic-depth settings (`Q38_MTP_DRAFTS=0`) | 203 s | `Железо`, stop, 3 tokens | length, 192 tokens | Not observed |
| `Q38_MTP_DRAFTS=3 Q38_MTP_PSTEP=0 COLI_SPEC_GATE=0` | 244 s | `Железо`, stop, 3 tokens | length, 192 tokens | Not observed |

Both also had `Q38_MTP=1 Q38_MTP_CHAIN=1`. All four streams returned HTTP 200, usage and `[DONE]`. The forced-depth run logged `fixed depth`, all three draft positions, and 110 forwards per 191 tokens for the decode turn (81/328 drafts accepted). These were actual device-MTP requests, not just successful startup; however, I did not capture the GEMV launch arguments or run a HIP sanitizer.

The longer readiness window also clarified the earlier startup-limited attempts: after `warm start`, this build constructs a 33.02 GiB page-locked host expert pool without intermediate progress logs. Allocation plus the logged read/probe phase took another ~122 s and ~158 s in these runs. The earlier ~183–198 s startup windows were therefore too short to establish a model-level result.

### Interpretation / next step

This is **not a fix or evidence that the historical fault is gone**. The historical profiles reused mutable state; their exact pre-run history/placement has not been established as identical to these fresh snapshots. Model-content hashes are also still missing.

I have **not yet run serialization or replaced `part`**: with the unmodified baseline completing, another passing run would not tell us whether either change prevents the original fault. I will retain your two diagnostics for a reproducing baseline.

For an intermittent case like this, would you prefer a narrowly scoped capture of the actual GEMV dimensions/pointers and `part` allocation/free stream sequence on the unchanged build before further retries? I can provide the exact requests, environment, completion records and selected MTP logs from these two runs.
