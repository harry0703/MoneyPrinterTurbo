# Task 3 report: MoneyPrinterTurbo bridge client

## Delivered

- Added `app/services/codex_bridge.py` with authenticated bridge generation, health checks, timeout normalization, response validation, and secret-safe errors.
- Added `test/services/test_codex_bridge.py` covering authenticated requests, required token handling, timeout bounds, remote/request failures, invalid JSON shapes, empty/oversized output, and health validation.

## TDD evidence

1. Initial focused test run failed at collection because `app.services.codex_bridge` did not exist.
2. After the initial implementation, focused tests exposed health-timeout handling; the client was corrected and the suite passed.
3. A required-token regression test failed before local empty-token validation was added, then passed.
4. A traceback-safety regression test failed before request exception chaining was suppressed, then passed.

## Verification

- `uv run python -X utf8 -m pytest -q test/services/test_codex_bridge.py` — 14 passed.
- `uv run ruff check app/services/codex_bridge.py test/services/test_codex_bridge.py` — all checks passed.
- `uv run python -X utf8 -m pytest -q` — 459 passed, 10 skipped, 12 dependency deprecation warnings, 164 subtests passed.

## Review notes

- Request errors use stable public messages and suppress exception chaining so traceback output cannot reveal userinfo URLs, bridge tokens, or request bodies.
- Health intentionally retains its documented 10-second default; generation uses the 30..900 second bounded normalization rule.

## Review remediation

- Root cause: the client previously passed the bridge's untrusted `error.message` through to callers. It now reads only the documented `error.code` and HTTP status, mapping them to fixed local messages. Remote error bodies are never emitted.
- Added a sentinel regression test containing instructions, episode input, model, bridge token, and username-only URL userinfo in a remote error message. It verifies that neither the exception text nor `traceback.format_exception(...)` contains any sentinel.
- Broadened URL userinfo redaction coverage to include `http://username@bridge`, in addition to username/password forms.

### Remediation TDD and verification evidence

- RED: `uv run python -X utf8 -m pytest -q test/services/test_codex_bridge.py` returned 2 failures: remote content appeared in the error text and username-only userinfo was not redacted.
- GREEN: `uv run python -X utf8 -m pytest -q test/services/test_codex_bridge.py` returned `16 passed in 0.13s`.
- Lint: `uv run ruff check app/services/codex_bridge.py test/services/test_codex_bridge.py` returned `All checks passed!`.

### Concerns

- None remaining for the two review findings. The full suite was not rerun for this narrowly scoped remediation; the requested focused test and lint commands passed.
