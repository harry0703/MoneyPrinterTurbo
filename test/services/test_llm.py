import unittest
from unittest.mock import patch, MagicMock

# Add the project root to the Python path to allow importing app modules
import sys
import os

# Calculate the project root directory path based on the current file's location
# __file__ is test/services/test_llm.py
# root_dir should be the parent of 'test' directory
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir) # Prepend to sys.path to ensure it's checked first

from app.services import llm # llm.py is in app/services
from app.config import config # Import the config
# from loguru import logger # Import if direct log assertions are needed and set up

class TestLlmService(unittest.TestCase):

    def setUp(self):
        # Basic configuration setup for tests.
        if not hasattr(config, 'app'): # Ensure config.app exists
            config.app = {}
        config.app['llm_provider'] = 'OpenAI' # Default mock provider
        config.app['openai_model_name'] = 'gpt-test-model'

    @patch('app.services.llm._generate_response')
    def test_generate_content_success(self, mock_generate_response):
        expected_content = "This is the successfully generated content."
        mock_generate_response.return_value = expected_content

        prompt = "Tell me a joke."
        instructed_prompt = f"Please generate detailed content based on the following topic or instruction: \"{prompt}\""

        actual_content = llm.generate_content(prompt)

        self.assertEqual(actual_content, expected_content.strip())
        mock_generate_response.assert_called_once_with(instructed_prompt)

    @patch('app.services.llm._generate_response')
    def test_generate_content_llm_failure(self, mock_generate_response):
        error_message_from_llm = "Error: LLM is down. Please try again later."
        mock_generate_response.return_value = error_message_from_llm

        prompt = "Summarize War and Peace."
        instructed_prompt = f"Please generate detailed content based on the following topic or instruction: \"{prompt}\""

        actual_content = llm.generate_content(prompt)

        self.assertTrue(actual_content.startswith("Error:"))
        self.assertIn("LLM is down", actual_content)
        mock_generate_response.assert_called_once_with(instructed_prompt)

    @patch('app.services.llm._generate_response')
    def test_generate_content_exception_handled_by_generate_response(self, mock_generate_response):
        # This test simulates that an exception occurred *inside* _generate_response,
        # and _generate_response caught it and returned a formatted error string.
        simulated_internal_exception_message = "Internal network timeout within _generate_response"
        # _generate_response itself would catch its internal error and return something like this:
        error_returned_by_generate_response = f"Error: {simulated_internal_exception_message}"
        mock_generate_response.return_value = error_returned_by_generate_response

        prompt = "What is the weather?"
        instructed_prompt = f"Please generate detailed content based on the following topic or instruction: \"{prompt}\""

        actual_content = llm.generate_content(prompt)

        self.assertTrue(actual_content.startswith("Error:"))
        self.assertIn(simulated_internal_exception_message, actual_content)
        mock_generate_response.assert_called_once_with(instructed_prompt)

    @patch('app.services.llm._generate_response')
    def test_generate_content_empty_prompt(self, mock_generate_response):
        expected_content = "Content for empty prompt."
        mock_generate_response.return_value = expected_content

        prompt = ""
        instructed_prompt = f"Please generate detailed content based on the following topic or instruction: \"{prompt}\""

        actual_content = llm.generate_content(prompt)

        self.assertEqual(actual_content, expected_content.strip())
        mock_generate_response.assert_called_once_with(instructed_prompt)

if __name__ == '__main__':
    unittest.main()
