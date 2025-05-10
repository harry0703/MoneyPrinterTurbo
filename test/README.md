# MoneyPrinterTurbo Test Directory

This directory contains unit tests for the **MoneyPrinterTurbo** project.

## Directory Structure

- `services/`: Tests for components in the `app/services` directory  
  - `test_video.py`: Tests for the video service  
  - `test_task.py`: Tests for the task service  
  - `test_voice.py`: Tests for the voice service  

## Running Tests

You can run the tests using Python’s built-in `unittest` framework:

```bash
# Run all tests
python -m unittest discover -s test

# Run a specific test file
python -m unittest test/services/test_video.py

# Run a specific test class
python -m unittest test.services.test_video.TestVideoService

# Run a specific test method
python -m unittest test.services.test_video.TestVideoService.test_preprocess_video
````

## Adding New Tests

To add tests for other components, follow these guidelines:

1. Create test files prefixed with `test_` in the appropriate subdirectory
2. Use `unittest.TestCase` as the base class for your test classes
3. Name test methods with the `test_` prefix

## Test Resources

Place any resource files required for testing in the `test/resources` directory.