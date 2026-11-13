# Issue A — SK=0 / PROMOTE=0, old/new/new/old

**Статус: локальный завершённый throughput-контроль; английский ответ отправлен пользователем 13 ноября.** Дата: 2026-11-13. Предыдущий ответ о matched rebuild и allocator-only контроле уже опубликован пользователем; этот документ его не заменяет. Profiler smoke и две отдельные trace-пары завершены: [результаты и ограничения](A-SK0-TRACE.md).

## Краткий результат

При явно переданных `COLI_CUDA_GEMV_SK=0` и `COLI_CUDA_CHAIN_PROMOTE=0` разрыв между неизменёнными matched-rebuild образами сохраняется: около 40.1 tok/s на `0a6f235b` против 26.2–26.3 tok/s на `b92eccd7`. Две парные оценки new/old: **−34.3619% и −34.5571%**. Это основание переходить к трассировке, а не доказательство конкретного виновного kernel или allocator.

Важная оговорка: это не изолированное изменение одного SK-переключателя относительно предыдущей серии. `PROMOTE=0` одновременно меняет pool coverage, bookkeeping, arena/staging. Поэтому наблюдение следует формулировать как «разрыв сохранился в профиле SK=0 / PROMOTE=0», а не как строгую причинную локализацию.

## Артефакты и идентификация

- Сводка: `data/colibri-investigation/sk0-abba/summary.json`.
- Полные исходные результаты: `data/colibri-investigation/pool-ab/20261113-144141/`.
- Процессы: `01-B`, `02-B`, `03-B`, `04-B`; внутри каждого — `command.json`, `environment-public.json`, `measurements.json`, `telemetry.jsonl`, startup/final logs и pre/post manifests.
- Old `0a6f235b`: `sha256:a989a4141762cce9d0a80819312635d195d5503c9fc87838805d81ec59838d88`.
- New `b92eccd7`: `sha256:7de12e467442f57400a7185713b602127d2cf74f2cb241134e2403a65d11cd62`.
- `source-integrity.json`: `unchanged: true`. Исходный код для этой серии не менялся.

Буква `B` здесь обозначает один и тот же forced-bus профиль, а не new revision. Реальный ABBA по сборкам: old/new/new/old. Использованы ранее подготовленные matched rebuild, не allocator-only диагностический child.

## Протокол

Обе переменные действительно переданы в Docker environment, а не только предложены как будущий тест:

```text
COLI_CUDA_GEMV_SK=0
COLI_CUDA_CHAIN_PROMOTE=0
COLI_CUDA_CHAIN_POOL_READ=1
COLI_CUDA_CHAIN_POOL=1
COLI_CUDA_CHAIN_LAYERWISE=1
COLI_CUDA_HOST_POOL=0
COLI_CUDA_CHAIN_ROWS=64
COLI_LOOKUP=0
Q38_MTP=0
Q38_MTP_DRAFTS=0
COLI_NO_OMP_TUNE=1
OMP_NUM_THREADS=8
```

В command/environment артефактах доступны остальные настройки. `COLI_CUDA=1`, `COLI_VULKAN=0`; баннер native engine с надписью CPU сам по себе не означает CPU-only выполнение: логи содержат resident GPU matrices, VRAM experts и device chain. Хост: Ryzen 7 3700X, 8 ядер / 16 логических CPU; число потоков OMP — 8.

Перед каждым процессом один snapshot восстановлен в тот же путь; `snapshot_matches: true` у всех четырёх. Один и тот же UUID-корпус воспроизводился между процессами, внутри процесса запросы имели свежие маркеры. Thinking override отсутствовал. Short и decode: warmup + три измеренных запроса каждый; отдельного prefill-бенчмарка нет. Decode ограничен 192 completion tokens. Контекст сервера 8192, RAM budget 48; модель Qwen3.8-Flash-Next-GSQ-RCO-IQ2_XS, import `--no-mtp`.

Кэш страниц не сбрасывался; affinity, частоты и power settings не менялись. GPU performance level `auto`, CPU governor `powersave`. Это наблюдение за частотами, **не fixed-clock контроль**. В телеметрии также виден controller-контейнер; полной изоляции хоста не заявляем. Неравное startup time (100.50 / 43.23 / 45.45 / 45.31 s) не является измерением decode и не трактуется как revision effect.

## Измеренные decode результаты

| Процесс | Revision | run 1, tok/s | run 2, tok/s | run 3, tok/s | Медиана, tok/s |
|---|---|---:|---:|---:|---:|
| 01-B | old `0a6f235b` | 40.1240873 | 40.5364486 | 39.7648826 | **40.1240873** |
| 02-B | new `b92eccd7` | 25.8302330 | 26.5269238 | 26.3366828 | **26.3366828** |
| 03-B | new `b92eccd7` | 26.1985721 | **23.5309650** | 26.2807291 | **26.1985721** |
| 04-B | old `0a6f235b` | 39.8833212 | 40.0327179 | 40.3295487 | **40.0327179** |

Формула: `(median_new / median_old − 1) × 100`.

- Пара 02-B / 01-B: −34.3619144%.
- Обратная пара 03-B / 04-B: −34.5570986%.

Это две process-level пары, а не двенадцать независимых повторов. Warmup в медианы не включён; низкий измеренный sample третьего процесса не исключён. Short-результаты также сохранены в raw measurements; основной endpoint этой таблицы — decode.

## Существенная оговорка PROMOTE=0

В предыдущем профиле pool занимал около **33.02 GiB** и покрывал **все 24576 experts**. С явным `COLI_CUDA_CHAIN_PROMOTE=0` **на обеих ревизиях** pool занимает **7.30 GiB** и покрывает только **5390 nonresident experts**. Во всех текущих процессах resident set — **19186 experts**; 19186 + 5390 = 24576.

Предыдущие серии уже показывали нулевое число фактических promotions. Но «promotion не случился» и «promotion отключён настройкой» не эквивалентны: меняются bookkeeping, резервирование arena, staging и coverage пула. Поэтому уменьшение host pool нельзя приписать новой ревизии, а результат нельзя выдавать за чистый SK-only ablation относительно предыдущего запуска. Внутри текущей серии обе ревизии используют одинаковый изменённый профиль.

Финальные логи: old — 61344 layer steps / 17207 slots from host pool; new — 61536 / 17308. Во всех четырёх процессах **0 hybrid steps**. Наличие bus pool/staging не означает hybrid fallback; их следует различать.

## Телеметрия, аномалия и пределы проверки

В `03-B`, `decode-run-2`, сохранён результат **23.5309650 tok/s**. В том же request window есть один sample **MCLK 96 MHz**, время **2026-11-13 14:47:41.886 +03:00**. Это временное совпадение, **причинность неизвестна**: не установлено, что именно этот sample объясняет замедление или связан с revision/SK/allocator. Остальные measured decode request-window MCLK медианы держатся около 1258 MHz; частоты не фиксировались.

Все 12 measured decode requests завершились с 192 tokens и `finish_reason=length`; HTTP/engine/GPU fault signatures в собранных результатах не обнаружены. Это не гарантия отсутствия любых аппаратных проблем и не результат по историческому device-MTP fault.

Decode выдавал reasoning до лимита, без финального ответа (`content` пуст). **Корректность ответа не установлена**, logits parity также не проверялась. Успешное завершение запроса, short smoke и отсутствие fault signatures не заменяют проверки правильности ответа.

## Интерпретация и следующий шаг

Ранее выполненный allocator-only negative control не восстановил примерно 40 tok/s: отмена только persistent-part acquisition на new revision не убрала разрыв. Текущий SK=0 / PROMOTE=0 контроль также его не убрал. Ни один из этих результатов не доказывает превосходство allocator, конкретную arithmetic-проблему или замедление `bd_gemv_i8_k` без трассы.

Разрыв сохранился, поэтому следующий обоснованный шаг — **отдельная ограниченная old/new trace-пара в том же SK=0 / PROMOTE=0 профиле**, по одному warmed decode request на реальном engine process. Это не часть завершённой throughput-серии выше.

**Trace завершён:** [отдельный отчёт](A-SK0-TRACE.md). Получены реальные dispatch records на warmed qwen38, две пары по одному 64-token request, одинаковые counts/shapes. `cc_dnrec_k<128>` показывает ~4.2× median duration и рост Scratch_Size1092→2600; `bd_gemv_i8_k` не демонстрирует общего большого замедления. Traced wall-time сильно и несимметрично возмущён, выбросы сохранены. Это не root cause и не основание автоматически применять sums patch. Следующий узкий discriminator по snapshot-copy/codegen следует согласовать с автором.

## Коммуникация

Краткий новый английский черновик: [issue-A-sk0-ready-to-post.md](issue-A-sk0-ready-to-post.md). Он **отправлен пользователем 13 ноября**, агент автоматически ничего не публиковал. Ждём ответа maintainer. Предыдущий matched-rebuild reply уже опубликован пользователем; новый черновик сообщает именно результат SK=0, существенную оговорку pool и следующий условный trace-шаг.
