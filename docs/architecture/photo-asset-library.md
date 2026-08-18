# Библиотека фото-ассетов с векторным поиском

Накопительная библиотека фотографий для оверлеев: файлы лежат обычной папкой,
метаданные и 768-мерные векторы — в Postgres с pgvector, а кадры подбираются по
смыслу визуального brief, тегам и истории использования. Фича выключена по
умолчанию (`photo_library_enabled = false`); старый путь через `photo_dir` при
этом не меняется.

Дата разработки: 2026-08-18.

---

## Зачем

Локальная папка хорошо работает для одного ролика, но не накапливает знания о
материалах: смысл выводится из имени темы, нельзя устойчиво найти похожий кадр,
потребовать конкретные скриншоты в заданном порядке или снизить частоту повторов.

Библиотека решает это отдельным слоем до существующего рендера:

- содержимое изображения получает caption, взвешенные теги, `has_text` и
  рекомендованный `min_display`;
- caption векторизуется, а pgvector ищет ближайшие кадры по косинусной дистанции;
- ручные требования, фильтры тегов и история использований уточняют результат;
- рендер по-прежнему получает только `path`, `start`, `end` и не знает о БД.

---

## Поток данных

```text
файл или каталог
   ↓  library add: копия файла + sha256 + ручные теги
storage/library/<группа>/<файл> + Postgres/pgvector
   ↓  library backfill
Gemini vision или Codex CLI → caption/tags/has_text/min_display
   ↓
Gemini gemini-embedding-001 → vector(768)

сценарий + окна субтитров
   ↓
llm.generate_photo_briefs()             один LLM-вызов на ролик
   ↓  визуальные briefs
Gemini embedding → pgvector HNSW search
   ↓
semantic + tags − recency → accept / gray / reject
   ↓                    ↘ неудовлетворённый brief
обязательные ассеты       Playwright + DuckDuckGo, если scout включён
   ↓
[{path, start, end}] → существующий renderer фото-карточек
```

Векторизация запросов и ассетов всегда выполняется через Gemini. Выбранный
vision-провайдер влияет только на разметку изображения.

---

## Файлы

| Файл | Что делает |
|---|---|
| `app/services/asset_library/` | схема, миграции, ингест, CRUD, поиск и учёт использований |
| `app/services/asset_vision.py` | единый адаптер разметки через Gemini или Codex CLI |
| `app/services/codex_cli.py` | подписочный Codex CLI в ephemeral/read-only режиме со строгой JSON-схемой |
| `app/services/asset_embed.py` | Gemini embeddings, нормировка и проверка размерности 768 |
| `app/services/asset_retrieval.py` | visual briefs, ранжирование, фильтры и обязательные ассеты |
| `app/services/media_scout.py` | опциональная докачка из DuckDuckGo через Playwright |
| `app/services/task.py` | preflight, подключение подбора, тайминги и запись использования |
| `cli.py` | `library add/list/tag/rm/stats/backfill/calibrate` |
| `docker-compose.library.yml` | локальный Postgres 17 + pgvector на `127.0.0.1:5433` |
| `config.example.toml` | все ключи и безопасные дефолты |

---

## Хранение и схема

Изображения хранятся вне Postgres, по умолчанию в `storage/library/`. В БД лежит
относительный путь от `photo_library_root`, поэтому каталог можно перенести вместе
с согласованным изменением корня. Исходник при ингесте не перемещается и не
изменяется.

Идентичность определяется `sha256` содержимого. Повторный ингест не создаёт ни
вторую запись, ни вторую копию, но добавляет новые ручные теги и может выставить
ручные caption/min_display. Ручные значения автоматический backfill не
перезаписывает.

Схема содержит:

- `asset`: путь, sha256, размеры, caption, `has_text`, `min_display`, provenance,
  модели разметки/эмбеддинга, `vector(768)`, время и счётчик использования;
- `asset_tag`: много взвешенных тегов на ассет, с признаком ручного происхождения;
- `asset_usage`: ассет, задача и время использования;
- HNSW-индекс `vector_cosine_ops` для поиска и обычный индекс по тегам.

Отдельного поля `collection` намеренно нет: группа каталога — это ручной тег с
весом 1.0. Решение закреплено в
[`decisions/0001-photo-assets-use-tags-only.md`](decisions/0001-photo-assets-use-tags-only.md).

---

## Первичный запуск

### 1. Настроить `config.toml`

Скопируйте блок `Photo Asset Library` из `config.example.toml` в локальный
`config.toml` и включите библиотеку:

```toml
photo_library_enabled = true
photo_library_db_host = "127.0.0.1"
photo_library_db_port = 5433
photo_library_db_name = "asset_library"
photo_library_db_user = "asset_library"
photo_library_db_password = "asset_library"
photo_library_root = "storage/library"
```

Каталог входящих файлов не должен совпадать с `photo_library_root`: `library add`
копирует исходники внутрь корня библиотеки. Если отдельная качалка ещё пишет в
`storage/library`, дождитесь её окончания либо временно используйте, например,
`photo_library_root = "storage/assets"`.

### 2. Поднять БД и применить миграции

Из корня проекта выполните один copy-paste блок:

```bash
docker compose -f docker-compose.library.yml up -d --wait && \
  uv run python -c 'from app.services.asset_library import init_library; init_library()'
```

`init_library()` создаёт расширение `vector`, таблицы и индексы, записывает
применённые нумерованные SQL-миграции в `schema_migration` и безопасен при
повторном запуске на наполненной базе.

Проверка здоровья и состояния:

```bash
docker compose -f docker-compose.library.yml ps
uv run python cli.py library stats
```

Контейнер должен быть `healthy`; новая база покажет `total=0`. Данные Postgres
лежат в `storage/pgdata/`, порт опубликован только на loopback.

### 3. Добавить материалы

Один файл с ручной разметкой:

```bash
uv run python cli.py library add ./incoming/poster.jpg \
  --group movie-premiere \
  --tags poster,cinema \
  --caption "Афиша фильма у входа в кинотеатр" \
  --min-display 3.5
```

Каталог обходится рекурсивно:

```bash
uv run python cli.py library add ./incoming/photos --tags editorial
```

Имя каждой подпапки становится групповым тегом; для файлов прямо в корне
используется имя добавленного каталога. Поддерживаются jpg/jpeg/png/webp.

Повторите ту же команду безопасно: вывод `exists` означает дедуп по sha256, а
новые ручные теги всё равно применяются.

---

## Разметка и эмбеддинги

### Gemini vision — дефолт

```toml
gemini_api_key = "..."
photo_library_vision_provider = "gemini"
photo_library_vision_model = "gemini-3.6-flash"
photo_library_embed_model = "gemini-embedding-001"
```

Один vision-вызов создаёт русский caption, 3–8 тегов с весами, `has_text` и
`min_display` в диапазоне 1–8 секунд.

### Codex CLI vision — через подписку ChatGPT

Сначала установите Codex CLI, затем войдите интерактивной подпиской и проверьте
сессию:

```bash
codex login
codex login status
```

Настройка:

```toml
gemini_api_key = "..." # всё ещё нужен для embeddings
photo_library_vision_provider = "codex_cli"
photo_library_codex_model = "gpt-5.6-luna"
photo_library_codex_binary_path = "" # поиск codex в PATH
photo_library_codex_effort = "low"
photo_library_codex_timeout = 300
photo_library_embed_model = "gemini-embedding-001"
```

Адаптер принимает только вход через ChatGPT OAuth (`codex login`), запускает
`codex exec` в изолированном временном каталоге, с read-only sandbox, без
approval, инструментов shell/browser/apps и с обязательной JSON-схемой. Переменные
`OPENAI_*` и `CODEX_*`, кроме `CODEX_HOME`, дочернему процессу не передаются.

Подписка ChatGPT оплачивает только vision-разметку через Codex CLI. Она не даёт
API-кредиты: 768-мерные embeddings всё равно расходуют квоту Gemini по
`gemini_api_key`.

### Запустить backfill

```bash
uv run python cli.py library backfill --limit 500
uv run python cli.py library stats
```

Backfill обрабатывает только записи без разметки и без вектора, а отказ одного
файла не останавливает остальные. Поэтому команду можно повторять после
таймаута, 429 или смены провайдера: уже сохранённые стадии не покупаются повторно.

На живом прогоне Gemini embedding API разрешал 100 запросов в минуту. При 429
нужно дождаться сброса минутного окна и повторить ту же команду — это и есть
идемпотентный retry; автоматического бесконечного ретрая внутри одного запуска
нет. Готовое состояние: `without_annotation=0` и `without_embedding=0`.

Модель разметки сохраняется в `annotate_model`, модель вектора — в `embed_model`.
Это позволяет определить смешанную разметку и выборочно перевекторизовать записи
при смене embedding-модели.

---

## Обслуживание через CLI

```bash
uv run python cli.py library list
uv run python cli.py library list --tags cinema,poster
uv run python cli.py library tag 42 --tags cinema,premiere
uv run python cli.py library rm 42
uv run python cli.py library stats
```

`tag` заменяет ручные теги ассета, `rm` удаляет и запись, и файл внутри
`photo_library_root`. Перед удалением полезно сверить запись через `library list`.

---

## Калибровка и формула отбора

Пороги нельзя выбирать по ощущениям на синтетических данных. Для реального SRT
или текстового сценария запустите:

```bash
uv run python cli.py library calibrate \
  --script storage/tasks/<task-id>/subtitle.srt \
  --subject "тема ролика" \
  --top 5 \
  --amount 12
```

Команда печатает для каждого visual brief top-N кандидатов, раздельные `cosine`,
`tag`, `recency`, итоговый `score`, verdict и отрыв top-1 от top-2. После изменения
состава библиотеки или качества разметки откройте реальные top-1/top-2 глазами и
перепроверьте границы.

Текущая формула, откалиброванная на 466 ассетах:

```text
score = 0.85 × cosine + 0.10 × tag_score − 0.05 × recency_penalty
```

- `score >= 0.68` → `accept`;
- `0.54 <= score < 0.68` → `gray`, кадр также используется;
- `score < 0.54` → `reject`, слот становится неудовлетворённым;
- свежесть считается по использованиям в последних 20 различных задачах, не по
  календарным дням.

Параметры живут в конфиге, а не вшиты в решение. Методика закреплена в
[`decisions/0002-photo-retrieval-thresholds-are-calibrated.md`](decisions/0002-photo-retrieval-thresholds-are-calibrated.md).

---

## Подбор под сценарий

LLM одним вызовом строит visual briefs для выбранных строк сценария. Каждый brief
векторизуется, pgvector возвращает ближайшие ассеты, после чего ранжирование
учитывает три составляющие формулы. При равном score порядок стабилен по `asset.id`.

Параметры задачи:

| Поле | Дефолт | Что делает |
|---|---:|---|
| `photo_require` | `[]` | обязательные `path:<относительный путь>` или `tag:<тег>`; порядок списка = порядок в ролике |
| `photo_prefer_tags` | `[]` | добавляет tag-score, не запрещая другие теги |
| `photo_only_tags` | `[]` | жёстко ограничивает пул любым из тегов и запрещает scout |
| `photo_exclude_tags` | `[]` | исключает ассеты с любым из тегов |
| `photo_max_duration` | `8.0` | верхняя граница показа отдельного кадра, 0.8–20 секунд |

Обязательные ассеты размещаются первыми: подходящая по косинусу свободная строка
выбирается без порогов score и штрафа свежести, а порядок `photo_require`
сохраняется. Если вектора нет, берётся первая допустимая позиция. Требование имеет
приоритет над `only`/`exclude`. Это поведение закреплено в
[`decisions/0003-required-photo-assets-bypass-ranking.md`](decisions/0003-required-photo-assets-bypass-ranking.md).

Перед тратами на LLM/TTS preflight проверяет доступность и непустоту БД, а также
наличие каждого обязательного пути/тега с учётом порядка и кратности.

В WebUI эти пять параметров появляются рядом с настройками фото, когда включены
`photo_enabled`: четыре списка вводятся через запятую, длительность — числом. Тот
же контракт доступен через `VideoParams` в API; отдельной HTTP-ручки управления
самой библиотекой нет, для неё используется CLI.

---

## Докачка через Playwright

Scout опционален и выключен по умолчанию. Установить зависимость и Chromium:

```bash
uv sync --extra scout
uv run playwright install chromium
```

Затем включить:

```toml
photo_scout_enabled = true
photo_scout_search_limit = 3
```

Для reject/no-candidates слота visual brief становится запросом DuckDuckGo.
Playwright открывает выдачу, извлекает URL полноразмерных картинок из `i.js`, а
скачивание проверяет HTTP content-type, минимальный размер 5 KiB и sha256. В БД
сохраняются исходный запрос и URL.

Лимит считается в поисковых запросах на один прогон. Новый ассет можно вставить
в текущий ролик сразу, до backfill. При `photo_only_tags` scout не запускается:
жёсткий фильтр означает «использовать только свои разрешённые материалы».

---

## Тайминги и использование в пайплайне

Библиотека включается только когда одновременно активны `photo_enabled = true` и
`photo_library_enabled = true`. Если библиотека выключена, выполняется прежняя
ветка `photo_dir`.

Для библиотечного кадра:

1. старт равен началу своей фразы — карточка никогда не начинает показ раньше;
2. длительность берётся из `asset.min_display`; без него сохраняется legacy
   `photo_duration ± 0.5` с детерминированным jitter;
3. длительность ограничивается `photo_max_duration`, началом следующей вставки и
   концом таймлайна;
4. интервал короче 1 секунды отбрасывается;
5. только фактически созданная вставка записывается в `asset_usage`.

Форма `{"path", "start", "end"}` и код рендера не менялись. `stop_at` также не
получил новой стадии: preflight библиотеки запускается только для
`stop_at = materials|video`, до генерации сценария, озвучки и скачивания видео.

---

## Конфигурация

Все ключи находятся в секции `[app]` файла `config.toml`.

| Ключ | Дефолт | Назначение |
|---|---:|---|
| `photo_library_enabled` | `false` | включает БД-путь вместо `photo_dir` |
| `photo_library_db_host` | `127.0.0.1` | хост Postgres |
| `photo_library_db_port` | `5433` | порт Postgres |
| `photo_library_db_name` | `asset_library` | база |
| `photo_library_db_user` | `asset_library` | пользователь |
| `photo_library_db_password` | `asset_library` | пароль локального compose |
| `photo_library_root` | `storage/library` | корень файлов ассетов |
| `photo_library_vision_provider` | `gemini` | `gemini` или `codex_cli` |
| `photo_library_vision_model` | `gemini-3.6-flash` | Gemini vision-модель |
| `photo_library_codex_model` | `gpt-5.6-luna` | Codex vision-модель |
| `photo_library_codex_binary_path` | `""` | бинарник Codex; пусто = PATH |
| `photo_library_codex_effort` | `low` | reasoning effort Codex |
| `photo_library_codex_timeout` | `300` | таймаут одного изображения, секунды |
| `photo_library_embed_model` | `gemini-embedding-001` | embedding-модель, 768 измерений |
| `photo_library_weight_semantic` | `0.85` | вес cosine similarity |
| `photo_library_weight_tags` | `0.10` | вес совпадений prefer-тегов |
| `photo_library_weight_recency` | `0.05` | максимальный штраф свежести |
| `photo_library_score_accept` | `0.68` | граница accept |
| `photo_library_score_reject` | `0.54` | нижняя граница gray |
| `photo_library_recency_window` | `20` | число последних задач для свежести |
| `photo_scout_enabled` | `false` | разрешает автоматическую докачку |
| `photo_scout_search_limit` | `3` | поисковых запросов на один ролик |

Значения `false` у библиотеки и scout — часть контракта обратной совместимости.

---

## Поведение при сбоях

| Ситуация | Что происходит |
|---|---|
| Библиотека выключена | используется прежний `photo_dir`, БД и Codex/Playwright не нужны |
| Библиотека включена, но БД недоступна или пуста | задача завершается на preflight до LLM/TTS |
| Обязательный path/tag отсутствует | задача завершается на preflight с перечнем требований |
| Один vision-вызов не удался | ассет пропускается, остальные продолжают разметку |
| Один embedding-вызов не удался или вернул не 768 значений | вектор не сохраняется; повторный backfill докупит его |
| Codex не установлен, не залогинен через ChatGPT или превысил таймаут | разметка этого ассета пропускается с warning |
| Gemini вернул 429 | текущие успехи остаются; после окна квоты backfill запускается повторно |
| LLM не создал visual briefs | библиотечные вставки не добавляются |
| Поиск/embedding brief/запрос к БД упал после preflight | retrieval возвращает пустой результат, ролик продолжает сборку без этих вставок |
| Scout выключен, нет браузера/сети или выдача изменилась | неудовлетворённые места остаются без фото |
| Scout исчерпал лимит | остальные места остаются без вставки; это не ошибка задачи |
| Файл исчез с диска | он не выдаётся поиском; исчезнувший после подбора файл пропускается |
| Запись usage не удалась | готовая вставка сохраняется, только freshness не узнает об использовании |

---

## Проверено

- Локальный `pgvector/pgvector:pg17` поднят на `127.0.0.1:5433`, healthcheck —
  `healthy`; миграции повторяемы.
- В живую библиотеку загружено **466 ассетов**; контрольная статистика 18.08.2026:
  `total=466`, `without_annotation=0`, `without_embedding=0`.
- Все 466 изображений получили разметку и 768-мерный embedding. Codex CLI vision
  прошёл live smoke через ChatGPT OAuth; пакетный прогон не дал rate-limit ошибок.
- Gemini embedding на живом backfill встретил лимит 100 RPM; после сброса
  минутного окна повторный идемпотентный запуск завершил остаток.
- Калибровка на 12 visual briefs: 2 accept / 9 gray / 1 reject. Оба accept
  визуально релевантны, четыре опасных ложных top-1 не попали в accept.
- Pipeline integration: 16 целевых тестов; legacy-регрессия — 99 passed,
  3 skipped и 11 subtests. Полный suite после интеграции — 914 passed,
  11 skipped, coverage 77%.
- Проверены инварианты: старт на своей фразе, запрет scout при hard-only,
  `record_usage` реального asset id, неизменная renderer shape и старый путь без БД.

---

## Ограничения и открытые вопросы

1. **Свежесть пока откалибрована без живой истории.** В базе на момент G1 не было
   usage events. После первых 20 реальных задач нужно повторить калибровку веса
   0.05 и окна 20.
2. **Почти-дубли.** Дедуп только по sha256; одно изображение в другом разрешении
   считается новым. Перцептивный хеш сознательно не добавлялся.
3. **Ассет без embedding не участвует в обычном семантическом поиске**, даже если
   у него есть теги. Его можно потребовать по `path:`/`tag:` или завершить
   backfill. Свежескачанный scout-ассет — исключение только для текущего прогона.
4. **Gray используется автоматически.** Порог `0.54` означает нижнюю границу
   допустимого, а не ручную очередь модерации. Если gray даёт много слабых кадров,
   нужно повторно калибровать границы.
5. **DuckDuckGo `i.js` — внешний неофициальный контракт.** Изменение выдачи ведёт
   к мягкой деградации scout, но потребует обновления адаптера.
6. **Codex CLI vision зависит от интерактивной подписки и локального OAuth.** Это
   удобный backfill для рабочей станции, но не безголовый production API.
7. **Смешанные vision-модели допустимы.** Provenance записывается, но отдельной
   CLI-команды принудительно переразметить уже заполненные captions пока нет.
8. **Права на контент остаются ответственностью владельца.** Provenance хранит
   URL поискового результата, но не доказывает лицензию на коммерческое использование.
