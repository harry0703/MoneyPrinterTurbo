# Code style

- No comments unless explaining non-obvious WHY. This repo already follows that closely — many existing comments are in Chinese explaining a subtle constraint or past bug; match that pattern in adjacent code rather than translating it or adding narrative comments elsewhere.
- Prefer editing existing files over new ones.
- No premature abstraction — 3 similar lines beats a helper for 1 use case.
- Match existing formatting/linting config in the repo (`ruff` — see `pyproject.toml`).
