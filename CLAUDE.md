# CLAUDE.md — MoneyPrinterTurbo

Форк рендерера коротких вертикальных роликов на Python: сценарий → озвучка → субтитры →
подбор стоковых материалов → сборка → публикация. В рамках проекта это **renderer-адаптер**
для content factory (TikTok / Reels / Shorts), а не самостоятельный продукт.

## Порядок работы с доками

1. Перед задачами про контент (текст, хуки, длительность, публикация) — **`docs/playbook/`**:
   это канон, а не пожелания.
2. Перед продуктовыми вопросами (зачем, какие метрики, где границы MVP) —
   **`docs/product/content-factory-context.md`**.
3. **`docs/docs.md`** — карта остальной документации; дочитывай по указателям
   (`architecture/`, `TODO/`, `incidents/`).
4. Перед рефакторингом — **`docs/architecture/decisions/`**: там зафиксированные решения,
   молча их не откатывать.

## После разработки

Обнови затронутое:

- `docs/changelog.md` — блок `## Unreleased`, при релизе переименовывается в версию из
  `pyproject.toml`;
- `config.example.toml` — при любом новом ключе конфига (это эталон, `config.toml`
  локальный и в гит не едет);
- `docs/architecture/<feature>.md` — при новой механике пайплайна;
- `docs/playbook/*` — если менялись правила производства контента.

## Команды

```bash
uv sync --frozen                      # окружение по uv.lock
uv sync --extra twelvelabs            # опциональная интеграция TwelveLabs
uv run ruff check app cli.py main.py webui test   # линт (как в CI)
uv run ruff format <файлы>            # форматтер — ruff, не black/isort
uv run pytest -q test                 # тесты
uv run coverage run -m pytest -q test && uv run coverage report   # покрытие
./webui.sh                            # Streamlit WebUI на 127.0.0.1:8501
uv run python main.py                 # FastAPI, Swagger на /docs, порт из config.toml
uv run python cli.py --help           # тот же пайплайн из CLI
```

CI (`.github/workflows/ci.yml`) на 3.11 и 3.13 гоняет `compileall` → `ruff check` →
`pytest` под coverage; отдельная job — smoke-тесты на Windows. Порог покрытия
`fail_under = 70` с `branch = true` живёт в `pyproject.toml`, source считается по
`app`, `cli`, `webui`, `main`, `docs/skill`.

## Раскладка

`app/` — сервис: `controllers/v1/` (FastAPI-ручки) · `controllers/manager/` (очередь
задач: memory/redis) · `services/` (доменная логика и адаптеры провайдеров) ·
`models/schema.py` (pydantic-контракты) · `config/` · `utils/`.
`webui/Main.py` — Streamlit · `cli.py` — CLI · `test/` — тесты · `resource/` — шрифты и
статика · `storage/` — рабочие артефакты задач (в гит не едут) · `docs/` — документация.

## Конвенции

- **Пайплайн** — `app/services/task.py::_run_pipeline`, семь шагов: script → terms →
  audio → subtitle → materials → final video → cross-post. Параметр `stop_at`
  (`script|terms|audio|subtitle|materials|video`) обрывает его на промежуточном артефакте —
  это часть контракта, новые шаги обязаны его уважать.
- **Провайдеры — заменяемые адаптеры**, файл на провайдера в `app/services/`
  (`klipy.py`, `elevenlabs_music.py`, `twelvelabs.py`, `upload_post.py`, `sonilo.py`).
  Новый провайдер не должен протекать в `task.py` ничем, кроме регистрации.
- **Новая фича — выключена по умолчанию.** Ключ в `config.example.toml` со значением
  `false`/пустым; поведение пайплайна без ключа не меняется (образец — `gif_enabled`,
  `docs/architecture/gif-overlays.md`).
- **Дорогие проверки — до траты квот.** Отсутствие ключа, превышение лимита промпта и
  прочее валится в `preflight` до LLM/TTS/скачивания материалов, а не после сборки ролика.
- **Состояние задач** — `app/services/state.py`: `MemoryState` по умолчанию, `RedisState`
  при `app.enable_redis`. Любое новое поле задачи должно переживать оба бэкенда.
- **Конфиг** — `app/config/config.py`; правки из WebUI идут через
  `update_config_nonblocking` с отложенным flush, а не прямой записью в файл.
- **Типы** — аннотации обязательны в новом коде. Апстримный код местами без них и с
  китайскими комментариями; переписывать его заодно не нужно, свои комментарии — по-английски
  и только там, где код сам за себя не скажет.

## Тесты

- `pytest`, каталог `test/`, файл на модуль (`test/services/test_<модуль>.py`).
- Сеть, LLM, TTS и провайдеры в тестах не дёргаются — подменяются.
- Красный тест → сначала проверь логику прода, потом тест. Не подгонять тест под
  неправильное поведение.

## Git

Апстрим `harry0703/MoneyPrinterTurbo` — ремоут `origin`, **в него не пушим**. Свой форк —
`sobak333N/MoneyPrinterTurbo`, ремоут `fork`, он же `remote.pushDefault`.

## Рабочий режим

Приоритет — time-to-market. По умолчанию писать код самому и доводить до зелёного
`ruff check` и `pytest`. Объяснять решения кратко по ходу, не вместо работы. План до кода —
на архитектуру, рефакторинги, новые модули и наборы тестов; мелкие изолированные правки
(≤2 файлов) делать сразу.
