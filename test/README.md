# MoneyPrinterTurbo Test Directory

This directory contains unit tests for the **MoneyPrinterTurbo** project.

## Directory Structure

- `services/`: Domain-focused unit and controller tests
  - `test_task.py`: Task pipeline tests
  - `test_task_manager.py`: In-memory and Redis queue tests
  - `test_controller_*.py`: API controller tests split by controller domain
  - `test_video.py`, `test_voice.py`: Media service tests
- `test_main.py`: Application entry-point test

## Running Tests

The CI suite uses pytest, which also runs the existing `unittest.TestCase`
tests:

```bash
# Run all tests
uv run python -X utf8 -m pytest -q test

# Run a specific test file
uv run python -X utf8 -m pytest -q test/services/test_video.py

# Run a specific test class
uv run python -X utf8 -m pytest -q test/services/test_video.py::TestVideoService

# Run a specific test method
uv run python -X utf8 -m pytest -q test/services/test_video.py::TestVideoService::test_preprocess_video
```

To run the same branch coverage check used by CI:

```bash
uv run python -X utf8 -m coverage run -m pytest -q test
uv run python -m coverage report
```

Live provider tests are skipped by default. To run tests that may call external
TTS or LLM services, set `MPT_RUN_INTEGRATION_TESTS=1` and provide the required
provider credentials.

## Adding New Tests

To add tests for other components, follow these guidelines:

1. Name files `test_<domain>.py` and keep each file focused on one domain.
2. Split broad controller suites into files such as `test_controller_video.py`.
3. Use either pytest functions or `unittest.TestCase`; pytest collects both.
4. Name test functions and methods with the `test_` prefix.

## Test Resources

Place any resource files required for testing in the `test/resources` directory.
