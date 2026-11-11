# B / #2758: ответ maintainer и свежая integration-проверка

11 ноября 2026, follow-up после [ответа JustVugg](https://github.com/JustVugg/colibri/issues/2758#issuecomment-6793822562). **Пользователь отправил [подготовленный follow-up](issue-B-followup-ready-to-post.md) в #2758 11 ноября 2026; ожидаем ответа maintainer. Production stack, образ и backend не изменены.**

## Гипотеза и условие эксперимента

Maintainer идентифицирует по модели и launch geometry hyper-connection read `hc_attn_down` / `hc_ffn_down`: K10240/N320/S4, 7 splits по 1536. Это его идентификация, не захват runtime-аргументов на нашей HIP-машине. Он подозревает stream-ordered allocation/lifetime буфера `part` (`7*4*320*4 = 35840` байт). CUDA memcheck у него чистый, но использует иное разбиение K; HIP-дефект allocator этим не доказан.

План: сначала свежий воспроизводимый baseline FAIL, затем только сериализация `AMD_SERIALIZE_KERNEL=3 AMD_SERIALIZE_COPY=3`; если fault воспроизводится — отдельная диагностическая сборка с persistent scratch, сохраняя SK и четыре строки. Исчезновение fault поддерживало бы проблему allocation/lifetime/order, но само по себе не отличало бы дефект ROCm от неправильного использования API.

## Что выполнено

Pinned dev `0a6f235b`, immutable image `sha256:e888c06f9db6a2d55997c43f2b0bd45c0face5d3ff428eba2b8a19dc65a299cc`. Direct Docker, host network, loopback API `127.0.0.1:18080`, независимые копии одного metadata/history snapshot. Lookup off, device head и routed experts на card; W4/SK без override, thinking явно выключен, greedy, short затем decode, лимит 192 токена. API key не сохранён. Hashes GGUF по-прежнему не получены.

| Сценарий | Readiness | Short | Decode | Fault |
|---|---:|---|---|---|
| Исторические параметры (`Q38_MTP_DRAFTS=0`, automatic) | 203.41 s | `Железо`, stop, 3 tokens | length, 192 tokens | не обнаружен |
| Отдельный forced verify (`Q38_MTP_DRAFTS=3 Q38_MTP_PSTEP=0 COLI_SPEC_GATE=0`) | 244.04 s | `Железо`, stop, 3 tokens | length, 192 tokens | не обнаружен |

Все четыре SSE streams завершились `[DONE]`, HTTP 200 и usage. Логи второго запуска подтверждают `fixed depth` и три draft positions; decode: 110 forwards на 191 token, acceptance 81/328. Это не instrumented launch trace и не sanitizer-проверка, но device MTP действительно выполнялся.

В baseline decode: 104 forwards на 191 token, adaptive depth, acceptance 87/183. Эти counters нельзя выдавать за одинаковые вычислительные последовательности двух сценариев.

Оба исходных snapshot integrity checks: unchanged. Запущенные нами контейнеры удалены. Другие контейнеры не останавливали.

### Почему прежние попытки не достигали readiness

В pinned source после `q38_tier_warm()` вызывается `q38cc_pool_init()`: page-locked host allocations (`hipHostMalloc`), заполнение expert pool, probes и server setup. Завершающий log появляется только после этих операций. В новых запусках pool занимает 33.02 GiB:

- baseline: 26.6 s allocation + 95.4 s read/probes;
- forced: 60.8 s allocation + 97.3 s read/probes.

Поэтому прежние окна ~183–198 секунд могли обрывать нормальный startup. Это объяснение поддерживается успешными новыми запусками, а не доказательство идентичности всех старых условий. В runner readiness теперь отдельно ограничен 360 s; общий предел запуска остаётся до 570 s.

## Решение о продолжении

**Исторический fault в этих двух свежих процессах не воспроизведён. Это не fix и не доказательство исчезновения ошибки.** Исторические запуски использовали изменяемый state между profiles; тождество их pre-run history/placement с нынешним snapshot не установлено.

Сериализация и замена allocator **не выполнялись**, потому что без воспроизводимого исходного FAIL положительный результат не изолирует причину. Долгий tracing/bisect и перебор настроек не начаты. В отправленном пользователем follow-up задан вопрос, какие дополнительные runtime-аргументы/shape/stream/lifetime capture нужны для непостоянного fault. До ответа maintainer новые GPU-эксперименты и изменения allocator отложены.

## Артефакты и повторение

- Публично пригодная локальная выжимка: [`evidence/B-allocator-followup.json`](evidence/B-allocator-followup.json), включая точные payloads, env, usage, content hashes и выбранные MTP logs. Перед публикацией просмотреть лично.
- Полные gitignored данные: `data/colibri-investigation/integration/20261111-172527/` и `20261111-173018/`.
- Сохранённый ответ maintainer и runner/test logs: `data/colibri-investigation/allocator-followup/`.
- В provenance каждого запуска сохранён hash фактически выполнявшегося runner. После запусков env construction вынесен в CPU-testable helper без изменения настроек.

```bash
# Эти два запуска уже выполнены отдельно, не одна общая timeout-квота:
python3 scripts/check-colibri-mtp-direct.py --seconds 570 --ready-seconds 360 --cases full
python3 scripts/check-colibri-mtp-direct.py --seconds 570 --ready-seconds 360 --force-verify --cases full

# Только когда baseline воспроизводит fault; сейчас НЕ выполнялось:
python3 scripts/check-colibri-mtp-direct.py --seconds 570 --ready-seconds 360 --cases full-serialized
# Для forced baseline добавить --force-verify и в serialized запуск.

# Без GPU/Docker:
python3 -m unittest discover -s tests
```

Runner дополнен отдельным serialized profile, явным forced-verify flag, readiness/elapsed timings, startup-inconclusive classification, public env capture и безопасным port preflight с SO_REUSEADDR. Добавлены 5 CPU-only tests; вся suite: **21 tests, PASS**. Persistent scratch patch намеренно не подготовлен как якобы исправление.
