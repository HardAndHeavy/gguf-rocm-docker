# PR #2775: проверка на R9700, 13 ноября 2026

Проверен merge [`b92eccd79ac60f196146f784c241ea076adda6f6`](https://github.com/JustVugg/colibri/commit/b92eccd79ac60f196146f784c241ea076adda6f6) в `dev`: отдельный HIP-образ `gguf-rocm-colibri:pr2775-b92eccd7`. Рабочие Dockerfile/Compose pins, `.env` и исходный state не менялись. Чужие контейнеры не останавливались. **Пользователь сообщил об отправке ответов A/B 13 ноября.** Последующее [old/new forced-bus сравнение](A-FORCED-BUS-REVISIONS.md) уже выполнено; ниже сохранены результаты первой проверки.

## Вывод

- **A / #2757:** автоматический выбор работает: оба auto-процесса выбрали bus до измеряемых запросов. Логи также подтверждают пропуск пустых host waits. Но стабильное равенство forced bus и возврат исторической скорости не доказаны: первый auto-процесс заметно медленнее.
- **B / #2758:** off / full-auto / full-forced завершили short+decode без fault. Реальное device MTP подтверждено логами. Это limited smoke, не доказательство устранения исторического fault: старый неизменённый baseline на свежем snapshot тоже уже проходил.
- **Рабочий образ пока не переключаем.** Следующий отдельный performance-эксперимент — старый pinned dev с forced bus против нового forced bus на общем snapshot, в спокойном окне, с записью clocks/power/CPU. Он нужен именно из-за нового уровня ~28 tok/s вместо прежних 40–41; причину по нынешним данным назвать нельзя. Не начинать бесконечный bisect или глобальное отключение W4/SK.

## A: четыре процесса auto → bus → bus → auto

MTP и lookup off, thinking override отсутствует; greedy, max_tokens=192. Общие snapshot и корпус UUID-prompts, snapshot восстановлен в один путь перед каждым процессом. Два preliminary запроса, short warmup+3, decode warmup+3. Auto decision проверен до timed groups. Каждая строка — отдельный процесс; три запроса внутри него не являются независимыми процессными повторами.

| Процесс | Режим | Decode 1 | Decode 2 | Decode 3 | Медиана tok/s | Медиана TTFT s |
|---|---|---:|---:|---:|---:|---:|
| 1 | auto | 24.90 | 28.02 | 24.00 | **24.90** | 1.909 |
| 2 | bus | 28.02 | 27.73 | 27.78 | **27.78** | 2.090 |
| 3 | bus | 28.11 | 28.60 | 28.03 | **28.11** | 2.069 |
| 4 | auto | 27.84 | 27.62 | 27.77 | **27.77** | 1.868 |

Все 12 measured decode — 192 tokens, `length`, reasoning без финального visible answer. Формула `(completion_tokens-1)/(last_token-first_token)`, не end-to-end throughput. Ошибок запросов и engine/GPU fault в этих четырёх процессах не записано.

В первом auto calibration CPU/bus = **54.34/41.22 ms**, во втором — **44.88/36.66 ms**, оба выбрали bus. У каждого только один round: периодическое переизмерение после 4096 decode steps не достигнуто. По **1003 skipped hybrid layer steps** в каждом auto — whole-process totals, не per-request. Promotions/evictions = 0; финальные resident routes = 98.6%. Начальная residency 19186 в процессах 1–2 и 19198 в 3–4, host pool 33.02 GiB во всех. Одинаковые байты snapshot не гарантировали одинаковую placement.

Bus превосходит первый auto по медиане на 11.59%; последний auto ниже предыдущего bus на 1.19%. Медленный auto не исключён. Различаются и prompt-pool пути. Во время процесса 2 была замечена чужая CPU-нагрузка: Ansible container около одного ядра, без GPU devices. Причинность не установлена. Нет lock clocks/power/affinity, page-cache flush или одновременного old-build контроля; историческое сравнение не является доказанной регрессией #2775.

## B: три integration-процесса

Thinking явно false, lookup off, W4/SK default, сериализация не включена. Независимые копии общего snapshot, direct Docker и loopback API. Context 8192, RAM 48 GiB, OMP 8.

| Режим | Readiness | Short | Decode | Fault |
|---|---:|---|---|---|
| MTP off | 211.70 s | `Железо`, 3, stop | 192, length | не обнаружен |
| full-device auto depth | 209.41 s | `Железо`, 3, stop | 192, length | не обнаружен |
| full-device fixed depth 3 | 204.99 s | `Железо`, 3, stop | 192, length | не обнаружен |

Все шесть — HTTP 200, usage, `[DONE]`. Forced: `Q38_MTP_DRAFTS=3 Q38_MTP_PSTEP=0 COLI_SPEC_GATE=0`. В auto decode 108 forwards/191 tokens, acceptance 83/195; forced 98 forwards/191 tokens, acceptance 93/289. Логи подтверждают head/logits и routed MTP experts на карте. Это не sanitizer, не failing-address trace, не stress/endurance и не доказанный allocator root cause. Performance speedup по B не заявляется.

## Ответы и публичная выжимка

- [Ответ A на английском](issue-A-pr2775-ready-to-post.md).
- [Ответ B на английском](issue-B-pr2775-ready-to-post.md).
- [Sanitised evidence JSON](evidence/PR2775-validation.json): build identity, env без ключа, metrics с warmups, counters, snapshot manifest, SHA-256 трёх GGUF.
- [SHA-256 выжимки](evidence/PR2775-SHA256.json).

Все 7 pre-run manifests проверены на совпадение с общим snapshot; исходные snapshots unchanged. Сборка успешна; **23 CPU unit tests PASS**, `git diff --check` PASS. Image ID `sha256:0e99d6b9f4148b30ba4aeeedf66cdeab26807a3c26489a03c426ab2d82dbf141`; HIP 7.16.26385, clang 24.0.0git / LLVM d6f6cb69. Полные SHA моделей — в JSON и ответе B. Ответы затем отправлены пользователем; JSON подготовлен локально, его загрузка в GitHub отдельно не подтверждалась.

## Локальные артефакты и повторение

- Общие: `data/colibri-investigation/pr2775/` (build, toolchain, model hashes, orchestrator, summary, concurrent activity).
- B: `data/colibri-investigation/integration/20261113-085318/`, `20261113-085710/`, `20261113-090106/`.
- A: `data/colibri-investigation/pool-ab/20261113-090452/`.

Новые runner-параметры `--image` разрешают локальный reference один раз и запускают immutable ID, без pull. Без параметра сохранён прежний old-dev default. A `--require-auto-decision` останавливает серию при отсутствии измеренного выбора; resume проверяет image и sequence, не переписывает исходный provenance.

```bash
# Сборка напрямую, без prepare-gpu.sh и изменения .env:
docker build -f docker/colibri.Dockerfile \
  --build-arg COLIBRI_REF=b92eccd79ac60f196146f784c241ea076adda6f6 \
  --build-arg ROCM_IMAGE=llama-rocm:3.0.2 --build-arg HIP_ARCH=gfx1201 \
  -t gguf-rocm-colibri:pr2775-b92eccd7 .

# Каждый запуск — отдельное окно до 570 секунд:
python3 scripts/check-colibri-mtp-direct.py --image gguf-rocm-colibri:pr2775-b92eccd7 --cases off --seconds 570 --ready-seconds 480
python3 scripts/check-colibri-mtp-direct.py --image gguf-rocm-colibri:pr2775-b92eccd7 --cases full --seconds 570 --ready-seconds 480
python3 scripts/check-colibri-mtp-direct.py --image gguf-rocm-colibri:pr2775-b92eccd7 --cases full --force-verify --seconds 570 --ready-seconds 480
python3 scripts/run-colibri-pool-ab.py --image gguf-rocm-colibri:pr2775-b92eccd7 --sequence A B B A --require-auto-decision
```

Не запускать одновременно с другим GPU inference; не останавливать чужие процессы автоматически. Ключ создаётся runner в памяти, модели read-only, API только `127.0.0.1:18080`, тестовые контейнеры удалены.
