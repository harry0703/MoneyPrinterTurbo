import unittest
from unittest.mock import patch, MagicMock
from app.services import youtube_music

class TestYouTubeMusic(unittest.TestCase):
    @patch("os.path.exists")
    def test_is_enabled(self, mock_exists):
        mock_exists.return_value = True
        self.assertTrue(youtube_music.is_enabled())

    def test_prompt_parsing(self):
        # Test helper logic or prompt splitting if needed
        prompt = "https://www.youtube.com/watch?v=dQw4w9WgXcQ|0:30"
        parts = prompt.split("|", 1)
        self.assertEqual(parts[0], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(parts[1], "0:30")
