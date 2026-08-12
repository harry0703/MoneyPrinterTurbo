# Changelog

Запись на каждый бамп `version` в `pyproject.toml`. Формат — что и зачем поменялось,
со ссылками на решения в `architecture/decisions/`.

## Unreleased

- **Фото-вставки из локальной папки** на сильных фразах сценария: моменты выбирает
  LLM (фолбэк — равномерная раскладка), каждое фото показывается 1.5–2.5 сек с
  анимацией появления (`pop`/`slide`/`kenburns`/`random`); выключены по умолчанию
  (`photo_enabled = false`). CLI: `--photo-enabled/--no-photo-enabled`,
  `--photo-dir`, `--photo-amount`, `--photo-size`, `--photo-animation` —
  `architecture/photo-overlays.md`.
- **CLI: gif-флаги** — `--gif-enabled/--no-gif-enabled`, `--gif-amount`, `--gif-size`,
  `--gif-rating`; раньше gif-оверлеи включались только из WebUI или кодом через
  `VideoParams`.
- **Пресет `playbook` включён по умолчанию** (`config.example.toml`): текст ролика
  строится по модели из `docs/playbook/`, а не по апстримному общему промпту.
- **Выбор хука отдельным шагом** — `hook_candidates = 5` кандидатов, детерминированный
  отсев приветствий и анонсов темы, затем скорер; выбранная строка пиннится в сценарий
  дословно, `hook`/`hook_type` уезжают в состояние задачи —
  `architecture/hook-selection.md`.
- **Провайдер `claude_code`** — генерация текста через локальный `claude -p`
  вместо HTTP-API, на интерактивной подписке; ключ и Base URL не нужны.
  Бинарник ставится в Docker-образ (`ARG INSTALL_CLAUDE_CODE=1`), учётные
  данные монтируются с хоста — `architecture/claude-cli-provider.md`.
- **Пресет промпта сценария по плейбуку** (`script_prompt_preset = "playbook"`,
  по умолчанию выключен): такты, правила хука, правило удержания, приоры
  длительности по платформе и опциональный скелет формата.
- **`docs/playbook/`** — ремесленная часть контекста разложена на пять файлов (хуки,
  сценарий, форматы, тайминги, публикация); в `product/content-factory-context.md` на их
  месте остались заголовки-указатели, нумерация разделов сохранена.
- **GIF-вставки KLIPY** на эмоциональных пиках сценария; выключены по умолчанию
  (`gif_enabled = false`), пайплайн без них не меняется — `architecture/gif-overlays.md`.

## 1.3.4 — 2026-08-12

- **ElevenLabs**: API-ключ переживает рестарт.
- **WebUI**: настройка папки вывода.
