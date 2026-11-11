# Стратегия экспериментов на Radeon AI PRO R9700

Дата: 11 ноября 2026. Рабочий выбор — **Qwen3.6 + Strata batch MTP**; для сложных задач —
**Flash-Next + Strata** (отдельная оценка качества ещё нужна). llama.cpp и Colibri сохраняются
как варианты запуска и контроль. Остальные модели/Vulkan — второй план до обновлений.
Цель — поддерживать воспроизводимый рабочий стек и вернуть доказанные исправления upstream. Скорость decode не считается
достаточным доказательством качества агента.

## Трек A: Qwen3.6 и выбор рабочего стека

- [x] Освободить место: удалены только четыре GGUF GLM-5.3-Flash из `data/models/`; исторические
  JSON/CSV, SHA-логи и документация сохранены. Освобождено около 95 GiB.
- [x] Выбрать один артефакт для всех backend:
  `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`, revision
  `5bc3e238d916f48a861bac2f8a1990a0e9b7e98d`, файл
  `Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf`, 22 853 663 008 байт (21,28 GiB).
  Это поддерживаемый preset Strata 0.2.9; тот же GGUF читают llama.cpp b12098 и Colibri.
  Q5_K_XL больше и качественнее, но не является документированным preset Strata, поэтому не
  используется для первого сравнения одинаковых весов.
- [x] Скачать с resume и проверить SHA-256:
  `make model-qwen36 && make verify-model-qwen36` (22 853 663 008 байт, проверка пройдена).
- [x] Preflight каждого backend: architecture import, реальный inference, все основные веса и
  runtime помещаются в 32 GiB VRAM; vision выключен, context 32k. Colibri Q36_MTP для выбранного
  llama.cpp-style GGUF явно помечен unsupported (`blk.40.nextn.*` вместо loader `mtp.*`).
- [x] Serving matrix: llama.cpp b12098 / Strata 0.2.9 / Colibri pinned main. Одинаковые GGUF,
  prompt, greedy/no-thinking/zero-penalty protocol и request budget. Runtime/config/logs сохранены.
- [x] Для каждого supported backend: `short`, `decode`, `prefill`, один warm-up и три measured runs;
  медиана, без удаления outliers. Отдельно non-MTP baseline и подтверждённый активный MTP-профиль.
- [x] Functional matrix: `scripts/agent_benchmark.py`, случаи `agent` и `coder`. Проверены
  фактические tool calls, изменённый файл и прохождение unit tests, а не только текст ответа.
  Это небольшой regression/smoke benchmark, не SWE-bench и не оценка общего интеллекта.
- [x] Контрольные сравнения с Flint UD-Q4_K_XL и Coder390 Q6_K-MTP на Colibri и llama.cpp.
  Strata+Flint unsupported по import; Coder390 на Strata не заявляется ни supported, ни unsupported.
- [x] Обновить `docs/BENCHMARKS.md`: скорость, TTFT/prefill, полное время agent task, успешность
  tool protocol и tests. На текущем smoke suite оба выбора — **Qwen3.6 + Strata batch MTP**;
  agent 2,36 s и coder 0,78 s, оба 3/3 PASS. Оговорка о маленьком наборе обязательна.

### Правила сравнения

1. Один inference backend за раз, без downloads и Open WebUI в measured path.
2. Сначала non-MTP при одинаковых условиях, затем рабочие оптимизированные presets. Нельзя
   называть разницу между MTP и non-MTP чистой разницей backend.
3. Уникальная метка в каждом prompt исключает exact prefix reuse. Для slot-reuse дополнительно
   проверяется отсутствие текста из предыдущего запроса (см. llama.cpp issue #29092).
4. Fixed-budget decode — основной throughput case. Естественно завершённые coding tasks имеют
   разную длину, поэтому для них важны wall time и pass rate, а не только tok/s.
5. Неудачный tool call или красивый, но непроходящий тесты ответ — failure, а не частичный успех.

## Трек B: Qwen3.8 MTP на HIP / open source

- [x] Выяснить размещение CPU MTP в pinned main и найти существующую upstream-работу.
  Это не означает, что первопричины регрессии A или fault B найдены.
- [x] Найти связанные issues/PR в Colibri, llama.cpp и ROCm/HIP; детали в `docs/MTP-HIP.md`.
- [x] Собрать существующий Colibri `dev` с PR #2559 отдельным образом и state directory;
  upstream tiny accept/mixed/reject и byte-identity tests пройдены.
- [x] На Qwen3.8 сравнить non-MTP / `Q38_MTP_CHAIN=0` / device MTP с lookup off во всех
  controlled сериях: 36,88 / 43,38 / 54,73 tok/s. Fixed 192-token reasoning совпал; full device
  прошёл agent 3/3 и coder 3/3. Acceptance и полные prefill/functional logs сохранены.
- [x] Проверить non-MTP main/dev на одинаковых state snapshots: main 45,45 против dev 37,26 tok/s.
  **Критерий отсутствия regression не выполнен**; wholesale dev как готовый PR не предлагается.
- [x] Воспроизвести отдельный HIP fault: device MTP + no-thinking на full и conservative даёт
  `HSA_STATUS_ERROR_MEMORY_FAULT` в `gemv_i8_w4<4>`. CPU/off работают; `GEMV_W4=0` и `GEMV_SK=0`
  обходят падение. Standalone GEMV shapes проходят, поэтому нужен integration regression, а не
  необоснованное глобальное отключение kernel.
- [x] Отправить @JustVugg два focused вопроса: non-MTP dev regression/forward-port #2559 на
  main и device-MTP no-thinking W4/SK fault с сохранённым repro. Не создавать параллельную
  реализацию уже влитой функциональности. Открыты [#2757](https://github.com/JustVugg/colibri/issues/2757)
  и [#2758](https://github.com/JustVugg/colibri/issues/2758); ответы получены, follow-up в `docs/issues/`.
- [x] Узкий тест B: CPU reference, split-K on/off в отдельных процессах, S4 и четыре S1.
  2048 × 300 подтвердился как fallback; 2048 × 1100 и 10240 × 300 реально проверили W4.
  Всё проходит; на 10240 × 300 split-off понижает sr до 1. Root cause не найден.
- [ ] Full-model HIP prompt regression: ранние direct Docker attempts ограничились startup.
  После ответа maintainer два свежих full-device процесса (automatic / forced three drafts)
  достигли API readiness за 203/244 s и завершили short/decode без fault. Это не fix и не
  полная regression matrix: baseline FAIL не воспроизведён, serializer/scratch A/B не начат.
  Детали: `docs/issues/issue-B-allocator-followup.md`; исторические fault/controls отдельно.
- [ ] A вести отдельно: interleaved main/dev при одинаковых state и lookup off, затем bisect/profile.
- [ ] После ответа maintainer'а: минимальный patch поверх выбранного base, real-HIP integration
  test для двух prompt variants и W4/SK path, затем повторные decode/prefill/full-agent A/B.
  PR готов только при корректности, воспроизводимом ускорении и отсутствии non-MTP regression.

Подробный технический разбор, ссылки и черновик сообщения maintainer'у: [MTP-HIP.md](MTP-HIP.md).
