import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import logo as logo_service


class TestFetchCompanyLogo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = patch(
            "app.services.logo.utils.storage_dir",
            return_value=self._tmp.name,
        )
        self.addCleanup(patcher.stop)
        patcher.start()
        self.addCleanup(self._tmp.cleanup)

    def _mock_response(self, json_data=None, content=b"", status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.content = content
        resp.json.return_value = json_data or {}
        return resp

    @patch("app.services.logo.Image.open")
    @patch("app.services.logo.requests.get")
    def test_returns_cached_path_on_success(self, mock_get, mock_image_open):
        search_resp = self._mock_response({"search": [{"id": "Q312"}]})
        claims_resp = self._mock_response(
            {"claims": {"P154": [{"mainsnak": {"datavalue": {"value": "Apple logo.svg"}}}]}}
        )
        image_resp = self._mock_response(content=b"fake-png-bytes")
        mock_get.side_effect = [search_resp, claims_resp, image_resp]

        # Mock PIL Image to pass validation
        mock_img = MagicMock()
        mock_image_open.return_value = mock_img

        result = logo_service.fetch_company_logo("Apple")

        self.assertTrue(result.endswith(".png"))
        self.assertTrue(os.path.exists(result))
        with open(result, "rb") as f:
            self.assertEqual(f.read(), b"fake-png-bytes")
        # Verify Image.open was called for validation
        mock_image_open.assert_called_once()

    @patch("app.services.logo.requests.get")
    def test_returns_empty_string_when_no_wikidata_entity_found(self, mock_get):
        mock_get.return_value = self._mock_response({"search": []})

        result = logo_service.fetch_company_logo("Totally Made Up Company Xyz")

        self.assertEqual(result, "")

    @patch("app.services.logo.requests.get")
    def test_returns_empty_string_when_no_logo_property(self, mock_get):
        search_resp = self._mock_response({"search": [{"id": "Q999"}]})
        claims_resp = self._mock_response({"claims": {}})
        mock_get.side_effect = [search_resp, claims_resp]

        result = logo_service.fetch_company_logo("Some Obscure Corp")

        self.assertEqual(result, "")

    @patch("app.services.logo.requests.get")
    def test_returns_empty_string_on_network_error(self, mock_get):
        mock_get.side_effect = ConnectionError("boom")

        result = logo_service.fetch_company_logo("Nike")

        self.assertEqual(result, "")

    @patch("app.services.logo.Image.open")
    @patch("app.services.logo.requests.get")
    def test_second_call_for_same_company_uses_cache_no_http(self, mock_get, mock_image_open):
        search_resp = self._mock_response({"search": [{"id": "Q312"}]})
        claims_resp = self._mock_response(
            {"claims": {"P154": [{"mainsnak": {"datavalue": {"value": "Apple logo.svg"}}}]}}
        )
        image_resp = self._mock_response(content=b"fake-png-bytes")
        mock_get.side_effect = [search_resp, claims_resp, image_resp]

        # Mock PIL Image to pass validation
        mock_img = MagicMock()
        mock_image_open.return_value = mock_img

        first = logo_service.fetch_company_logo("Apple")
        mock_get.reset_mock()
        second = logo_service.fetch_company_logo("Apple")

        self.assertEqual(first, second)
        mock_get.assert_not_called()

    @patch("app.services.logo.utils.storage_dir")
    def test_regression_toctou_race_in_cache_path_returns_empty_string(self, mock_storage_dir):
        """
        Regression test for Finding 1: TOCTOU race in _cache_path
        If utils.storage_dir raises FileExistsError (TOCTOU race), the function
        should degrade to returning "" instead of propagating the exception.
        """
        mock_storage_dir.side_effect = FileExistsError("race condition")

        result = logo_service.fetch_company_logo("SomeCompany")

        self.assertEqual(result, "")

    @patch("app.services.logo.Image.open")
    @patch("app.services.logo.requests.get")
    def test_regression_invalid_image_bytes_not_cached(self, mock_get, mock_image_open):
        """
        Regression test for Finding 2: No validation of downloaded image bytes
        If downloaded bytes are not a valid image (e.g. corrupted or text),
        the function should return "" without caching the bad file.
        """
        search_resp = self._mock_response({"search": [{"id": "Q456"}]})
        claims_resp = self._mock_response(
            {"claims": {"P154": [{"mainsnak": {"datavalue": {"value": "BadLogo.png"}}}]}}
        )
        # Return 200 OK with non-image bytes
        image_resp = self._mock_response(content=b"not an image")
        mock_get.side_effect = [search_resp, claims_resp, image_resp]

        # Mock Image.open to raise an error when validating bad bytes
        mock_image_open.side_effect = Exception("Cannot identify image file")

        result = logo_service.fetch_company_logo("BadImageCompany")

        # Should return empty string on invalid image
        self.assertEqual(result, "")
        # Verify the bad file was not cached
        cache_files = os.listdir(self._tmp.name)
        self.assertEqual(len(cache_files), 0, "Bad image should not be cached")


if __name__ == "__main__":
    unittest.main()
