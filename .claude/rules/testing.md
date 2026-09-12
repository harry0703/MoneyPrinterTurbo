# Testing

- Run `pytest test/` before reporting a task done.
- New behavior gets a test; bug fixes get a regression test where practical.
- No mocked-only tests for anything touching real DB/API when integration risk exists.
- Adding an LLM/TTS/material provider: add a registry-level test (required fields, adapter selection) and, where practical, an adapter test using a fake client — see `test/services/test_llm.py` for the existing pattern per provider.
- WebUI behavior (Streamlit) is tested via `streamlit.testing.v1.AppTest` in `test/services/test_webui_*.py`, not by running the app manually.
