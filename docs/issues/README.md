# Colibri A/B: черновики для upstream

**[Checkpoint 13 ноября](COLIBRI-CHECKPOINT-2026-11-13.md): новый ответ maintainer проверен — [ROCr scratch и PR #2809](A-SCRATCH-LIMIT.md). Scratch override: 26.52 → 38.00/37.04 → 26.66 tok/s; old/fix/fix/old без override: 40.27/40.34/40.68/40.31. [Новый follow-up](issue-A-scratch-ready-to-post.md) **отправлен пользователем 13 ноября; ждём ответа maintainer**. Автоматической отправки не было. Production не менялся.**

Актуализация **13 ноября 2026**. Issues [A — #2757](https://github.com/JustVugg/colibri/issues/2757) и [B — #2758](https://github.com/JustVugg/colibri/issues/2758) остаются открытыми по проверке 13 ноября. Ответы maintainer привели к влитому [PR #2775](https://github.com/JustVugg/colibri/pull/2775).

**Новая проверка:** [PR2775-VALIDATION](PR2775-VALIDATION.md): 3 integration B процесса без fault; 4 процесса A auto/bus/bus/auto, оба auto выбрали bus. Первый auto медленнее, стабильная performance resolution не доказана. Рабочие pins/`.env`/исходный state не менялись.

- **Ответы по первой проверке отправлены пользователем 13 ноября:** [A](issue-A-pr2775-ready-to-post.md), [B](issue-B-pr2775-ready-to-post.md).
- **Следующий эксперимент выполнен:** [old/new forced-bus ABBA](A-FORCED-BUS-REVISIONS.md): old 39.89/40.70, new 27.65/26.92 tok/s, новый ниже на 30.68–33.87%. Причина и виновный commit не установлены.
- **Forced-bus follow-up отправлен пользователем:** [английский ответ](issue-A-forced-bus-revisions-ready-to-post.md), [sanitised evidence](evidence/A-forced-bus-revisions.json).
- **Следующий контроль выполнен:** [matched rebuild / allocator-only](A-REBUILD-ALLOCATOR.md). Rebuilt old/new ~40/~27; соответствующие binaries побайтно совпали с прежними, packages совпали. Async-only diagnostic на new не вернул скорость (~25–26).
- **Matched-rebuild follow-up отправлен пользователем:** [английский ответ](issue-A-rebuild-allocator-ready-to-post.md) обновлён с учётом нового CUDA/HIP ответа maintainer; [evidence](evidence/A-rebuild-allocator.json).
- **SK0 и bounded trace выполнены:** [ABBA](A-SK0-ABBA.md) old40.12/40.03, new26.34/26.20, gap34.4–34.6%; [trace](A-SK0-TRACE.md) указывает на `cc_dnrec_k<128>` (~4.2×, scratch1092→2600), но wall-time сильно возмущён. [SK0/trace follow-up](issue-A-sk0-ready-to-post.md) **отправлен пользователем 13 ноября**, [evidence](evidence/A-sk0-trace.json). Полученный ответ привёл к [scratch-limit / PR #2809 validation](A-SCRATCH-LIMIT.md): use-once churn исчезает с override, fix branch без override возвращает ~40 tok/s. Новый follow-up отправлен пользователем 13 ноября; исследование на паузе до ответа maintainer.
- **Новая sanitised выжимка:** [PR2775-validation.json](evidence/PR2775-validation.json), включая полные hashes GGUF; [её SHA-256](evidence/PR2775-SHA256.json).
- Ниже — исторические материалы 9–11 ноября, не синхронизированные копии GitHub. Старые ограничения и формулировки «ожидаем ответа» относятся к датам тех запусков.

- [Issue A — non-MTP decode observation](colibri-A-non-mtp-regression.md): исторические данные, −18,03%; это не установленная причина.
- [Ответ на рекомендацию maintainer по A](issue-A-pool-followup-ready-to-post.md): новые восемь процессов **ABBA / BCCB** на pinned dev, английский комментарий отправлен пользователем 11 ноября (подтверждён в GitHub). GPU pool-read обычно ~40–41 tok/s, но один процесс 33,80; стабильное восстановление 45,45 не показано. Порог 90% не дал изменения при нулевых promotions. Скрипт: `scripts/run-colibri-pool-ab.py`.
- [Issue B — device-MTP HIP fault](colibri-B-hip-device-mtp-fault.md): исторический fault и обходы, standalone PASS; прежние startup-limited attempts сохранены отдельно.
- [B — ответ maintainer и allocator follow-up](issue-B-allocator-followup.md): два свежих full-model процесса (automatic / forced three drafts) завершили short+decode без fault. Исходный FAIL не воспроизведён; сериализация и замена scratch не выполнялись.
- [Отправленный ответ по B](issue-B-followup-ready-to-post.md): английский follow-up с двумя завершёнными запусками и вопросом о targeted capture; **пользователь отправил 11 ноября, ожидаем ответа**.
- [`evidence/`](evidence/): компактные отобранные JSON и standalone logs без `.env`, API keys/auth headers, usernames и абсолютных host paths. `SHA256.json` фиксирует байты приложений; это **не** hashes весов модели. Публиковать выборочно после личного просмотра.

В A намеренно сохранены подробности confounders; при необходимости первый раздел Summary можно использовать как короткое вступление, остальное — как техническое приложение. A и B не объединять в утверждение об общей причине или одном fix.

## Что приложено и чего нет

- A: measured request metrics/summary и hashes исходных локальных JSON. Не весь Docker inspect/environment.
- B: точные request bodies, отобранные исторические responses/errors и оба новых standalone run logs. Sanitised fault excerpt включён в текст issue.
- Полные локальные build/startup/runtime logs, metadata snapshots и исходные benchmark JSON остаются в gitignored `data/`; **ссылки на них не являются публичными attachments**.
- Для follow-up A: `evidence/A-pool-ab-measurements.json` и `evidence/A-pool-ab-log-excerpts.txt` — все восемь процессов, measured/warmup metrics, manifest общего metadata/history snapshot и выбранные counters. Полные исходники: gitignored `data/colibri-investigation/pool-ab/20261111-162844/`.
- В материалах 11 ноября не было content hashes GGUF, полной fresh-snapshot integration B matrix или доказанного root-cause patch. Hashes получены 13 ноября; новый off/full/forced smoke выше, root cause по-прежнему не доказан. Два full-device B процесса уже завершились без fault; это не passing off/CPU/SK0/W40 matrix. Новый interleaved A benchmark выполнен, но число независимых повторов мало и между процессами есть вариабельность.

## Повторение локально

```bash
# Только standalone, без сети вообще; примерно минута компиляции + короткие тесты.
bash scripts/check-colibri-gemv-hip.sh

# Отдельная потенциально падающая integration-проверка; только local host API.
# Требуются pinned image, models и data/colibri-mtp-dev-control.
# Default общий лимит 540 s может закончиться до всех профилей; лучше по одному процессу.
python3 scripts/check-colibri-mtp-direct.py --cases full --seconds 540
```

Не использовать для этого старый compose runner при активном VPN. Direct runner не запускает
OpenWebUI, не создаёт bridge/compose network, не останавливает чужие контейнеры; API bind —
только `127.0.0.1:18080`. Возможен HIP fault. Ранние direct off/full attempts не вышли из startup. Позднее два full-device запуска
достигли readiness за 203/244 s и завершили запросы без fault; см. follow-up B выше.

По ответу maintainer в A выполнен ограниченный pool-path/promotion follow-up; дальше — обсуждение
результатов, не автоматический длительный tracing/bisect. B этим прогоном не исследуется.
Перед отправкой сверить актуальность upstream отдельно: drafts относятся только к указанным pinned revisions.
