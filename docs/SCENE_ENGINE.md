# Scene Engine — интеграция (ТЗ-2)

Этот документ кратко описывает изменения, внесённые для первой итерации интеграции Scene Engine в пайплайн MoneyPrinterTurbo, и инструкции по включению/тестированию.

## Краткое описание изменений

- Добавлен конвейер Scene Engine: генерация scene_plan.json, роутинг ассетов и валидация кандидатов.
- Флаги конфигурации (config.example.toml):
  - `scene_engine_enabled` — включает новый путь (по умолчанию false).
  - `scene_engine_debug` — дополнительное логирование/сохранение артефактов.
  - `scene_engine_strict_validation` — строгая политика проверки ассетов.
  - `h3_enabled` — включение H3 (генерация видео) (по умолчанию false).
- H3: добавлен минимальный stub (app/services/scene_h3.py). Реальная интеграция требует API-клиента и ключей.
- Asset Router (app/services/asset_router.py): формирование asset_plan.json с fallback_chain и меткой `h3_requested`.
- Asset Validator (app/services/asset_validator.py): эвристический скоринг (semantic, duration, aspect, quality, uniqueness).
- API:
  - `GET /tasks/{task_id}/scene_debug` — возвращает scene_plan.json и asset_plan.json.
  - `GET /tasks/{task_id}/qa_export?format=csv|json` — экспорт QA-таблицы для ручной оценки.
  - `POST /tasks/{task_id}/scenes/{scene_id}/regenerate` — перегенерация роутинга/выбора ассета для одной сцены (требует scene_engine_enabled).
- Минимальный A/B harness (app/services/scene_benchmark.py) — сохраняет отчёты в storage/benchmark/<run_id>.json.
- Unit tests: tests/test_asset_validator.py и tests/test_asset_router.py (локально компилируются).

## Артефакты на диске (per-task)

В каталоге задачи (utils.task_dir(task_id)) сохраняются:
- `scene_plan.json` — сгенерированный план сцен
- `asset_plan.json` — решения роутера, кандидаты, скоринги
- (планируется) `timeline.json`, `qa_report.json`, `final.mp4` — не входили в эту итерацию

## Как включить Scene Engine и проверить

1. Скопировать `config.example.toml` → `config.toml` (или править текущий config.toml).
2. Установить `scene_engine_enabled = true` для тестовой задачи.
3. Создать задачу через существующий API; после генерации в каталоге задачи появятся `scene_plan.json` и `asset_plan.json`.
4. Для отладки:
   - GET /tasks/{task_id}/scene_debug
   - GET /tasks/{task_id}/qa_export?format=csv
5. Чтобы перегенерировать одну сцену: POST /tasks/{task_id}/scenes/{scene_id}/regenerate

## Ограничения текущей итерации

- H3 — только stub (возвращает отказ). Для реальной генерации нужно реализовать клиент H3 и иметь ключи.
- Acquisition использует material.download_videos(), требующие внешних ключей (Pexels/Pixabay/Coverr). Без ключей/сети поиск вернёт пусто.
- Нет UI-изменений (только API endpoints).
- Интеграционные end-to-end тесты с реальным скачиванием/рендером не выполнены.

## Рекомендованные следующие шаги

1. Реализовать реальный H3 adapter (требуются ключи и SLA договорённости). Добавить политику доли использования в роутер.
2. Написать интеграционные тесты с использованием тестовых/реальных API-ключей и CI-прогоны.
3. Расширить метрики: fallback rate, scene coverage, asset reuse, render success, semantic accuracy.
4. Добавить WebUI страницу для preview и human QA workflow (импорт human_score и агрегирование).

## Контакты и PR

Изменения собраны в ветке `stacosmax-integrate-scene-engine`. Планирую открыть PR с описанием и инструкциями для ревью.

---

Если нужно, добавлю раздел «Как запустить интеграционный прогон» с примерами команд и окружения (требует ключей).