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
| `product/content-factory-context.md` | полный продуктовый контекст: цели, метрики, форматы, hook-система, trend/idea engines, аналитика, autonomy levels, cost model |
| `architecture/` | реализованные механики пайплайна — по файлу на подсистему |
| `architecture/gif-overlays.md` | GIF-вставки KLIPY на эмоциональных пиках сценария |
| `architecture/decisions/` | микро-ADR — по файлу на принятое решение |
| `changelog.md` | changelog; запись обязательна на каждый бамп версии в `pyproject.toml` |
| `TODO/` | нереализованные фичи, по файлу на фичу |
| `incidents/` | разборы инцидентов |
| `skill/SKILL.md` | агентский скилл поверх API рендерера (`mpt_agent.py`) |
| `MoneyPrinterTurbo.ipynb`, `voice-list.txt`, `*.jpg` | апстримные материалы форка |
| `../README.md` | апстримный README (установка, конфиг, FAQ) |
