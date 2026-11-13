# A: план после ответа maintainer о CUDA/HIP, 13 ноября 2026

**Обновление: шаги A и B выполнены.** Предыдущий ответ о matched rebuild/allocator-only отправлен пользователем. [SK0/PROMOTE0 ABBA](A-SK0-ABBA.md) сохранил gap ~34.4–34.6%; [bounded warmed-engine traces](A-SK0-TRACE.md) дали конкретную зацепку `cc_dnrec_k<128>` (~4.2×, Scratch_Size1092→2600), но с большим profiler perturbation. [SK0/trace follow-up](issue-A-sk0-ready-to-post.md) отправлен пользователем 13 ноября. Пауза до ответа maintainer; новый diagnostic patch не согласован. Ниже сохранён исходный план; актуальный фактический результат — по ссылкам. Production не меняется.

## Как учесть ответ

CUDA-контроль автора показывает около 1% изменения на его CUDA-машине, а не наши ~32% на HIP. Это усиливает приоритет HIP/runtime/codegen диагностики. Но не исключает shared source: один C++/CUDA source может компилироваться иначе на HIP, как раз случай rounded-FMA helpers.

В отправленном ответе сообщены результаты:

- Обе ревизии пересобраны одной процедурой без кеша; 545 dpkg entries совпали, compiler/flags/base совпали. Бинарники каждой ревизии побайтно совпали с её прежним бинарником. Old/new/new/old = **40.15 / 27.17 / 27.66 / 40.85 tok/s**. Повторять эту работу до trace не нужно.
- На **одной новой ревизии** acquisition persistent split-part buffer отменён одной строкой, fallback async allocation/free сохранён; SK/W4/арифметика не менялись. Stock/diagnostic/diagnostic/stock = **27.74 / 25.67 / 26.35 / 26.40 tok/s**. Возврата к ~40 нет. Это аргумент против простого объяснения замедления новым ownership partials, но не allocator-hit trace, не доказательство безопасности allocator и не результат по fault B.
- Последний stock warmup 12.86 tok/s совпал с 7 samples MCLK96MHz. Сохранить, не выбирать только стабильные samples и не приписывать variant-specific причину.

Компактный обновлённый ответ отправлен; далее следуем предложенному A → B. Не отправлять старую версию draft, где мы снова спрашивали, нужен ли fresh rebuild.

## Шаг A: SK=0 на двух штатных образах

Цель — убрать **весь split path**, а не только persistent acquisition.

Использовать неизменённые rebuilt images:

| Роль | Ревизия | Immutable image |
|---|---|---|
| old | 0a6f235b | `sha256:a989a4141762cce9d0a80819312635d195d5503c9fc87838805d81ec59838d88` |
| new | b92eccd7 | `sha256:7de12e467442f57400a7185713b602127d2cf74f2cb241134e2403a65d11cd62` |

Не использовать async-diagnostic image для этого сравнения. Порядок **old/new/new/old**; fresh processes, общий snapshot восстановлен в один путь, общий сохранённый corpus. Forced bus, MTP/lookup off, no thinking override, context8192/RAM48/OMP8 как раньше. Дополнительно **в обоих контейнерах**:

```text
COLI_CUDA_GEMV_SK=0
COLI_CUDA_CHAIN_PROMOTE=0
```

W4 не отключать. `PROMOTE=0` согласует профиль с автором; прежние фактические promotions у нас были нулевыми. Сохранить все warmups, каждую measured request, output usage, startup/final counters и ~1Hz clocks/power/temp/CPU.

**Важно для реализации:** существующий `scripts/run-colibri-pool-ab.py` строит environment контейнера из явного словаря. Просто prefix `COLI_CUDA_GEMV_SK=0 python3 ...` **не передаст switch внутрь Docker**. До запуска добавить явные, ограниченные runner options для SK и promotions с CPU tests; убедиться, что public env и сохранённая Docker command содержат оба значения. Не предлагать сейчас команду с ещё не существующими flags.

Interpretation:

- Gap сохранился около прежнего уровня → allocation/split path не объясняет основную разницу; переход к B.
- Gap существенно схлопнулся → локализован split region, **не доказан allocator как единственная причина**. SK=0 удаляет partials, reduction и меняет launch geometry/вычислительный путь. При многострочных вызовах может менять batching. С учётом отрицательного allocator-only контроля показать автору оба результата и попросить следующий узкий discriminator.
- Частичное изменение/сильный разброс/clock collapse → не делать binary conclusion; сохранить данные и trace representative paired requests, а не бесконечно перезапускать «до хорошего результата».

Это один диагностический ABBA, не новый production default и не workaround для постоянного включения.

## Шаг B: bounded trace, если gap остаётся

### Исходный preflight (до фактических capture)

Read-only preflight без GPU devices: в **обоих rebuilt images** `rocprofv3 --version` и `--help` работают; version **1.4.1**, git revision `7da43026e4f2ef7600433c38c820732f7a205d22`. В image доступны `/opt/venv/bin/rocprofv3` и `/opt/rocm/bin/rocprofv3`. Help подтверждает `--kernel-trace`, `--stats`, `--hip-runtime-trace`, `--memory-copy-trace`, `--memory-allocation-trace`, `--pid`, `--attach-duration-msec`, `--attach-sync-output`, `--output-directory`, `--output-format`.

На момент этого preflight capture не проверялся; теперь см. [фактический trace](A-SK0-TRACE.md). Help/version сами по себе **не доказывают**, что attach/injection/capture работает с нашей картой/драйвером/контейнерными правами. Логи preflight: `data/colibri-investigation/maintainer-next-plan/rocprof-*-help.txt`.

### Порядок подготовки и сбора

1. Маленький bounded profiler smoke в отдельном тестовом контейнере. Проверить наличие реальных kernel-dispatch records и отсутствие dropped/errors. Не менять рабочий образ, глобальный ptrace/security policy и clocks; не включать `--privileged` наугад.
2. В каждой штатной image загрузить модель и выполнить warmup **до trace**. Target — реальный engine `qwen38`, не только Python HTTP dispatcher/launcher. Attach к собственному warmed engine предпочтительнее trace всего 200-секундного startup. Если attach не работает — отдельно подготовить launch-under-profiler с сохранением границ request; не молча включать startup в сравниваемые stats.
3. Сначала kernel trace + stats, дополнительно HIP runtime/copy/allocation trace для различения gaps/API waits. Не собирать сразу аппаратные counters, replay или ATT: лишнее возмущение и сложность. Разделить capture на две короткие сессии, если full tracing чрезмерно тормозит.
4. Один одинаковый warmed decode request на old и new с **тем же SK=0 профилем, где gap подтвердился**. Default-SK trace — только если нужно для ответа автору/сопоставления. Сохранить начало/конец request, first/last token, usage, engine forwards, profiler output/config/errors и телеметрию. Нормализовать по реально попавшим в interval decode forwards/tokens, не предполагать 192 GPU forwards из `max_tokens=192`.
5. Выделить prefill и S=1 decode по проверенной разметке/ranges и dispatch metadata. Если надёжно отделить не удалось, назвать результаты **whole-request**, включая prefill, а не isolated decode. Не суммировать startup, warmup и measured request в одну таблицу kernel cost.
6. Завершить profiler/engine корректно, дождаться flush и проверить полноту records. Ограничить длительность/объём. Рядом оставить unprofiled measurements: traced wall tok/s нельзя напрямую смешивать с throughput из обычной серии.

### Что сравнить

- Для `bd_gemv_i8_k` и других крупных contributors: полный symbol/type, сопоставимые launch shapes, число dispatches, median/mean duration, total duration per captured decode forward/token.
- Отдельно `gemv_i8_w4`, split-sum (при default-SK), memory copies, HIP API allocations/synchronizations и очередь launches. При SK=0 split kernels могут отсутствовать — это ожидаемо.
- Увеличение **total** конкретного kernel не равно замедлению его арифметики: могло вырасти число calls или измениться shape/routes. Проверять duration/call и count отдельно.
- Для GPU activity использовать timeline/объединение интервалов, учитывая streams и overlaps. Нельзя объявлять `wall − сумма всех kernel durations` чистым CPU gap: суммы могут перекрываться; есть copies, dependencies и runtime waits.

Branches:

- `bd_gemv_i8_k` становится медленнее на сопоставимом work → передать автору таблицу/trace; принять его предложенный **HIP-only rounded-sums patch** как отдельный A/B на одной pinned new revision. Не откатывать rounding самостоятельно как «исправление» до измерения и не обещать numerical equivalence.
- Kernel work/time примерно прежние, wall/idle gaps выросли → исследовать HIP API/launch/cache tracking, копии и синхронизации; это не автоматическое доказательство «CPU виноват».
- Смешанный результат → показать contributions, не сводить к одной причине.
- Только если A/B не локализуют проблему, вернуться к промежуточной `3a33c7f1` и одинаковой процедуре сборки. Fresh old/new уже есть; не пересобирать их повторно без причины.

## Что отправлять сейчас

[Rebuild/allocator-only reply](issue-A-rebuild-allocator-ready-to-post.md) и [SK0/trace follow-up](issue-A-sk0-ready-to-post.md) отправлены пользователем. Исходный план A → B выполнен; ждём следующего узкого discriminator от maintainer. Полный [отчёт](A-REBUILD-ALLOCATOR.md), [evidence JSON](evidence/A-rebuild-allocator.json) и [one-line diagnostic diff](evidence/A-allocator-only-diagnostic.patch) уже подготовлены локально; attachments не загружены. Перед публикацией просмотреть выбранные файлы; не прикладывать `.env`, raw Docker inspect с environment, API keys или полные address traces без sanitisation.
