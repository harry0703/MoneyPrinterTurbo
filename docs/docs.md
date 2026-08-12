# Content Factory — обзор и карта документации

Стартовая точка по проекту. Здесь — что это, где граница и куда идти за деталями.
Правда — в исполняемых артефактах (код `app/`, `config.example.toml`, тесты);
остальное дочитывай по указателям из карты ниже.

## Что это

Репозиторий — форк рендерера MoneyPrinterTurbo, который служит **renderer-адаптером**
для более крупной задачи: semi-autonomous factory для TikTok / Reels / Shorts.
Полный продуктовый контекст — `product/content-factory-context.md`; он же
source-of-truth для coding-агента. Из него агент должен понимать:

- **цель:** построить semi-autonomous factory для TikTok / Reels / Shorts;
- **бизнес-задачу:** органически привлекать аудиторию в собственные продукты, а не
  максимизировать доход платформ;
- **основной цикл:** `Trend → Idea → Approve → Research → Script → Visuals → Render →
  Publish → Analytics → Learn`;
- **главный moat:** не renderer, а собственный dataset
  `topic × hook × format × visual × CTA → retention × conversion`;
- **MVP:** простой end-to-end pipeline на Pexels/Pixabay + MoneyPrinterTurbo, без custom
  video-RAG, RL, Kafka и прочего оверинжиниринга;
- **human-in-the-loop:** утром approval трендов, потом approval идей, вечером
  аналитический отчёт;
- **архитектурный принцип:** renderer, media providers и publishers являются заменяемыми
  adapters;
- **оптимизацию:** смотреть не только `views`, а всю цепочку до
  `registration / paid user / revenue`;
- **исследовательские данные 2026:** использовать только как стартовые priors и постепенно
  заменять собственными account-level данными;
- **ограничения:** хранить provenance/licensing видеоматериалов, соблюдать commercial
  disclosures и не превращать систему в repetitive AI-slop farm.

Главное правило проекта:

> Мы не пытаемся заранее идеально предсказать вирусность. Мы строим систему, которая может
> дёшево делать разумные ставки, отдавать их реальным зрителям и учиться на результате
> быстрее ручного контент-мейкера.

При любых изменениях API, pricing, publishing rules, monetization, copyright или
commercial-content policies агент должен перепроверять актуальную официальную документацию,
потому что эти части продуктового контекста со временем устаревают.

## Раскладка репозитория

`app/` — код сервиса: `controllers/` (FastAPI-ручки `v1/`), `services/` (доменная логика:
`task.py` — оркестрация пайплайна, `video.py` — сборка ролика, `material.py` — стоковые
материалы, `voice.py`/`subtitle.py` — озвучка и субтитры, `llm.py` — сценарии, адаптеры
провайдеров вроде `klipy.py`, `elevenlabs_music.py`, `twelvelabs.py`, `upload_post.py`),
`models/` (pydantic-схемы), `config/`, `utils/`. `webui/` — Streamlit-интерфейс,
`cli.py` — CLI поверх того же пайплайна, `test/` — тесты, `resource/` — шрифты и
статика, `storage/` — рабочие артефакты задач (не в гите),
`config.example.toml` — эталон конфига (`config.toml` локальный, в гит не едет).

## Карта документации

| Где | Что |
|---|---|
| `playbook/` | как делать контент — ремесленная часть, канон для сценарных агентов |
| `playbook/hooks.md` | хуки: классы, генератор кандидатов + скорер, `hook_type` в метаданные |
| `playbook/script.md` | структура сценария по тактам, удержание внимания, фактология и claim-цепочка |
| `playbook/formats.md` | реестр форматов (механика сторителлинга ≠ ниша) и стартовый микс |
| `playbook/timing.md` | длительности как приоры, датасеты и источники, приор ≠ константа |
| `playbook/publishing.md` | частота, время публикации, метаданные/хештеги, QA перед публикацией |
| `playbook/media-scouting.md` | массовая скачка картинок/гифок/видео из поисковой выдачи: ddgs + Playwright + yt-dlp, обход граблей Google/YouTube |
| `product/content-factory-context.md` | продуктовый контекст: цели, метрики, trend/idea engines, аналитика, autonomy levels, cost model, ограничения |
| `architecture/` | реализованные механики пайплайна — по файлу на подсистему |
| `architecture/gif-overlays.md` | GIF-вставки KLIPY на эмоциональных пиках сценария |
| `architecture/photo-overlays.md` | фото-вставки из локальной папки с анимациями появления |
| `architecture/continuous-background.md` | непрерывный фон: один отрезок длинного видео с кропом по центру |
| `architecture/claude-cli-provider.md` | провайдер `claude_code` (генерация через `claude -p`) и пресет промпта по плейбуку |
| `architecture/hook-selection.md` | выбор первой строки: генератор кандидатов, фильтр, скорер |
| `architecture/subtitle-highlight.md` | капс и смысловая подсветка ключевого слова в субтитрах |
| `architecture/decisions/` | микро-ADR — по файлу на принятое решение |
| `changelog.md` | changelog; запись обязательна на каждый бамп версии в `pyproject.toml` |
| `TODO/` | нереализованные фичи, по файлу на фичу |
| `incidents/` | разборы инцидентов |
| `skill/SKILL.md` | агентский скилл поверх API рендерера (`mpt_agent.py`) |
| `MoneyPrinterTurbo.ipynb`, `voice-list.txt`, `*.jpg` | апстримные материалы форка |
| `../README.md` | апстримный README (установка, конфиг, FAQ) |
