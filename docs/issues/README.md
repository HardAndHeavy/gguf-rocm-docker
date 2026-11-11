# Colibri A/B: черновики для upstream

Подготовлено 11 ноября 2026. **Issues опубликованы:**
[A — #2757](https://github.com/JustVugg/colibri/issues/2757),
[B — #2758](https://github.com/JustVugg/colibri/issues/2758).
Оба открыты на момент проверки 11 ноября; тексты ниже сохранены как локальные материалы
подготовки, а не синхронизированные копии GitHub. Рабочий стек Strata не менялся.

- [Issue A — non-MTP decode observation](colibri-A-non-mtp-regression.md): перепроверка исторических данных, −18,03%; причины и interleaved process repeats ещё нет.
- [Issue B — device-MTP HIP fault](colibri-B-hip-device-mtp-fault.md): исторический fault и обходы, новый standalone PASS, незавершённая новая integration-проверка.
- [`evidence/`](evidence/): компактные отобранные JSON и standalone logs без `.env`, API keys/auth headers, usernames и абсолютных host paths. `SHA256.json` фиксирует байты приложений; это **не** hashes весов модели. Публиковать выборочно после личного просмотра.

В A намеренно сохранены подробности confounders; при необходимости первый раздел Summary можно использовать как короткое вступление, остальное — как техническое приложение. A и B не объединять в утверждение об общей причине или одном fix.

## Что приложено и чего нет

- A: measured request metrics/summary и hashes исходных локальных JSON. Не весь Docker inspect/environment.
- B: точные request bodies, отобранные исторические responses/errors и оба новых standalone run logs. Sanitised fault excerpt включён в текст issue.
- Полные локальные build/startup/runtime logs, metadata snapshots и исходные benchmark JSON остаются в gitignored `data/`; **ссылки на них не являются публичными attachments**.
- Нет content hashes GGUF, завершённого нового fresh-snapshot integration matrix, interleaved A benchmark или доказанного root-cause patch.

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

Исследование остановлено в согласованной границе: дальше — ответ maintainer'а или релевантное
upstream-обновление, не длительный tracing/bisect. Перед отправкой сверить актуальность
upstream отдельно: эти drafts относятся только к указанным pinned revisions.
