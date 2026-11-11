# Colibri A/B: черновики для upstream

Подготовлено 11 ноября 2026. **Issues опубликованы:**
[A — #2757](https://github.com/JustVugg/colibri/issues/2757),
[B — #2758](https://github.com/JustVugg/colibri/issues/2758).
Оба открыты на момент проверки 11 ноября; тексты ниже сохранены как локальные материалы
подготовки, а не синхронизированные копии GitHub. Рабочий стек Strata не менялся.

- [Issue A — non-MTP decode observation](colibri-A-non-mtp-regression.md): исторические данные, −18,03%; это не установленная причина.
- [Ответ на рекомендацию maintainer по A](issue-A-pool-followup-ready-to-post.md): новые восемь процессов **ABBA / BCCB** на pinned dev, подготовленный английский комментарий (не отправлен). GPU pool-read обычно ~40–41 tok/s, но один процесс 33,80; стабильное восстановление 45,45 не показано. Порог 90% не дал изменения при нулевых promotions. Скрипт: `scripts/run-colibri-pool-ab.py`.
- [Issue B — device-MTP HIP fault](colibri-B-hip-device-mtp-fault.md): исторический fault и обходы, новый standalone PASS, незавершённая новая integration-проверка.
- [`evidence/`](evidence/): компактные отобранные JSON и standalone logs без `.env`, API keys/auth headers, usernames и абсолютных host paths. `SHA256.json` фиксирует байты приложений; это **не** hashes весов модели. Публиковать выборочно после личного просмотра.

В A намеренно сохранены подробности confounders; при необходимости первый раздел Summary можно использовать как короткое вступление, остальное — как техническое приложение. A и B не объединять в утверждение об общей причине или одном fix.

## Что приложено и чего нет

- A: measured request metrics/summary и hashes исходных локальных JSON. Не весь Docker inspect/environment.
- B: точные request bodies, отобранные исторические responses/errors и оба новых standalone run logs. Sanitised fault excerpt включён в текст issue.
- Полные локальные build/startup/runtime logs, metadata snapshots и исходные benchmark JSON остаются в gitignored `data/`; **ссылки на них не являются публичными attachments**.
- Для follow-up A: `evidence/A-pool-ab-measurements.json` и `evidence/A-pool-ab-log-excerpts.txt` — все восемь процессов, measured/warmup metrics, manifest общего metadata/history snapshot и выбранные counters. Полные исходники: gitignored `data/colibri-investigation/pool-ab/20261111-162844/`.
- Нет content hashes GGUF, завершённого нового fresh-snapshot integration B matrix или доказанного root-cause patch. Новый interleaved A benchmark выполнен, но число независимых повторов мало и между процессами есть вариабельность.

## Повторение локально

```bash
# Только standalone, без сети вообще; примерно минута компиляции + короткие тесты.
bash scripts/check-colibri-gemv-hip.sh

# Отдельная потенциально падающая integration-проверка; только local host API.
# Требуются pinned image, models и data/colibri-mtp-dev-control.
# Default общий лимит 540 s может закончиться до всех пяти профилей.
python3 scripts/check-colibri-mtp-direct.py --cases full --seconds 540
```

Не использовать для этого старый compose runner при активном VPN. Direct runner не запускает
OpenWebUI, не создаёт bridge/compose network, не останавливает чужие контейнеры; API bind —
только `127.0.0.1:18080`. Возможен HIP fault. Новые direct off/full attempts в этой сессии
не вышли из startup; не считать команды выше уже успешным новым repro.

По ответу maintainer в A выполнен ограниченный pool-path/promotion follow-up; дальше — обсуждение
результатов, не автоматический длительный tracing/bisect. B этим прогоном не исследуется.
Перед отправкой сверить актуальность upstream отдельно: drafts относятся только к указанным pinned revisions.
