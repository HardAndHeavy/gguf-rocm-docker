# A / #2757: old/new forced-bus ABBA, 13 ноября 2026

Пользователь сообщил об отправке предыдущих ответов A/B по PR #2775. После этого выполнен следующий эксперимент: **old → new → new → old**, во всех процессах `COLI_CUDA_CHAIN_POOL_READ=1`. Этот follow-up [отправлен пользователем](issue-A-forced-bus-revisions-ready-to-post.md). Следующий [matched rebuild / allocator-only контроль](A-REBUILD-ALLOCATOR.md) уже выполнен; ниже — сохранённая первая forced-bus серия.

## Главный результат

**В этой серии новый pinned-образ устойчиво медленнее старого примерно на 31–34%, даже с принудительным bus.** Старый образ возвращается к ~40 tok/s после двух новых. Это уже contemporaneous interleaved сравнение, а не сопоставление с историческими цифрами.

Но сравнение существующих образов не устанавливает причину и не локализует проблему в PR #2775, persistent scratch или конкретном kernel. Ревизии включают другие изменения; идентичность compilation history/flags/dependencies не доказана, generated trajectories различаются.

- Old: `0a6f235b0c7a20726e28e6e0229ef1201de74638`, image `sha256:e888c06f9db6a2d55997c43f2b0bd45c0face5d3ff428eba2b8a19dc65a299cc`.
- New: `b92eccd79ac60f196146f784c241ea076adda6f6`, image `sha256:0e99d6b9f4148b30ba4aeeedf66cdeab26807a3c26489a03c426ab2d82dbf141`.
- Обе среды сообщают HIP 7.16.26385-0000000, AMD clang 24.0.0git / LLVM d6f6cb691863e9258034ab48c1dfce21689d5606. Hashes binaries/source записаны отдельно.

## Методика и результаты

R9700 gfx1201 + Ryzen 7 3700X, Qwen3.8-Flash-Next IQ2_XS, context 8192, RAM 48 GiB, OMP 8. MTP и lookup off, thinking override отсутствует, W4/SK defaults, без сериализации. Forced bus везде; env одинаковы. Независимые процессы, общий hashed metadata/history snapshot восстановлен в один и тот же путь перед каждым запуском. Все pre-run manifests совпали, исходный snapshot unchanged. Все prompt hashes совпадают между процессами на соответствующих позициях корпуса.

Каждый процесс: preliminary short/decode, short warmup+3 measured, decode warmup+3 measured. Greedy, streaming usage, max_tokens=192; без отдельного prefill benchmark. Rates `(completion_tokens-1)/(last_token-first_token)`, не end-to-end throughput.

| Порядок | Образ | Decode 1 | Decode 2 | Decode 3 | Медиана tok/s |
|---|---|---:|---:|---:|---:|
| 1 | old | 39.8871 | 39.6861 | 39.9045 | **39.8871** |
| 2 | new | 27.5913 | 27.6501 | 27.6514 | **27.6501** |
| 3 | new | 27.0245 | 26.6914 | 26.9173 | **26.9173** |
| 4 | old | 40.7080 | 40.7034 | 40.1460 | **40.7034** |

New против old в первой паре: **−30.68%**, в обратной: **−33.87%**. Это два процессных сравнения, а не 12 независимых процессов. Все 12 measured decode — HTTP 200, 192 completion tokens, `length`, reasoning без финального visible answer. Ошибок запросов/engine/GPU fault в логах не записано. Warmups сохранены: decode 39.1183 / 27.4637 / 27.2606 / 36.3115 tok/s; медленный warmup old4 не скрыт и не переименован в measurement.

Startup: 202.0 / 214.5 / 205.3 / 215.3 s. Во всех процессах pool **33.02 GiB**, warm resident experts **19186**, финальные resident routes **98.6%**, promotions/evictions **0**, hybrid layer steps **0**. Равное число residents не доказывает одинаковую карту размещения. Нулевые hybrid и forced bus исключают именно объяснение «auto выбрал CPU вместо bus» для этой серии, не все причины расхождения.

## Телеметрия

Read-only sysfs/proc, около 1 Hz, с метками каждой фазы запроса. Ни clock/power/governor/affinity, ни page cache не изменялись. Полные JSONL сохранены по процессам. В таблице медианы samples из measured decode **request windows, включая TTFT/prefill**, не отдельные kernel timings.

| Процесс | SCLK MHz | MCLK MHz | GPU W | Power cap W | Junction °C | CPU busy, % всех CPU |
|---|---:|---:|---:|---:|---:|---:|
| old1 | 3251 | 1258 | 263 | 300 | 76 | 27.8 |
| new2 | 3281 | 1258 | 221 | 300 | 76 | 24.9 |
| new3 | 3280 | 1258 | 218 | 300 | 76 | 25.7 |
| old4 | 3243.5 | 1258 | 269 | 300 | 80.5 | 29.1 |

У нового нет снижения **медианы наблюдаемой SCLK**, memory clock одинаков; old4 быстрее при более высокой median junction. Это не похоже на простое объяснение «новый работал на пониженной частоте/старый был холоднее», но **не доказывает отсутствие throttling или коротких transients**. Peak sampled junction — 91°C. Lower power/memory busy у нового — наблюдения, не diagnosis bottleneck. GPU mode auto, CPU governors powersave; частоты наблюдались, а не фиксировались. CPU busy — общесистемный, без attribution по процессам.

В sampled container lists только текущий тест и уже существовавший controller; последний перед стартом имел около 0% CPU. Это не доказательство полной изоляции хоста: прочие host-процессы и между-sample нагрузка не исключены. Ошибок сбора telemetry не было. Чужие контейнеры не останавливались.

## Что делать дальше

1. Передать maintainer этот результат: **разница остаётся с forced bus, auto уже не является достаточным объяснением**.
2. Следующий контроль — свежая сборка старой ревизии тем же Dockerfile/base/toolchain и flags, что новый образ, затем короткий old/new forced-bus repeat. Это отделит source revision от истории сборки существующих образов.
3. Если разрыв сохраняется — согласовать focused backend timings/trace либо allocator-only A/B **на одной новой ревизии**. Не объявлять allocator виновным и не отключать глобально W4/SK. Полный bisect пока не выполнялся.
4. Рабочий production pin не менять на new как performance upgrade. Этот тест не выбирает лучший production backend/model и не заменяет проверку качества.

## Артефакты и изменения

- [Отправленный английский ответ](issue-A-forced-bus-revisions-ready-to-post.md).
- [Sanitised JSON](evidence/A-forced-bus-revisions.json), [SHA-256](evidence/A-forced-bus-revisions-SHA256.json): все измерения/warmups, summaries telemetry, env без ключа, images/provenance/snapshot manifest.
- Raw: `data/colibri-investigation/pool-ab/20261113-123131/`, процессные `01-B`…`04-B`: measurements, telemetry JSONL, pre/post-run manifests, startup/final logs.
- Общая выжимка и toolchain: `data/colibri-investigation/bus-revision-ab/`.
- Runner: `--compare-bus-image` строит фиксированный old/new/new/old план с forced bus и запрещает resume/auto-decision в таком сравнении; `--telemetry` включает phase-annotated read-only сборщик. Старые single-image режимы сохранены.
- **33 CPU tests PASS**, `git diff --check` PASS. Production pins, `.env`, модели и исходный state не изменены; тестовые контейнеры удалены.

```bash
python3 scripts/run-colibri-pool-ab.py \
  --image gguf-rocm-colibri:mtp-dev-0a6f235b \
  --compare-bus-image gguf-rocm-colibri:pr2775-b92eccd7 \
  --telemetry --startup-timeout 480
```
