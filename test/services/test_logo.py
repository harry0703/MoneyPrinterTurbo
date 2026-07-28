import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

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

    @patch("app.services.logo.requests.get")
    def test_returns_cached_path_on_success(self, mock_get):
        search_resp = self._mock_response({"search": [{"id": "Q312"}]})
        claims_resp = self._mock_response(
            {"claims": {"P154": [{"mainsnak": {"datavalue": {"value": "Apple logo.svg"}}}]}}
        )
        image_resp = self._mock_response(content=b"fake-png-bytes")
        mock_get.side_effect = [search_resp, claims_resp, image_resp]

        result = logo_service.fetch_company_logo("Apple")

        self.assertTrue(result.endswith(".png"))
        self.assertTrue(os.path.exists(result))
        with open(result, "rb") as f:
            self.assertEqual(f.read(), b"fake-png-bytes")

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

    @patch("app.services.logo.requests.get")
    def test_second_call_for_same_company_uses_cache_no_http(self, mock_get):
        search_resp = self._mock_response({"search": [{"id": "Q312"}]})
        claims_resp = self._mock_response(
            {"claims": {"P154": [{"mainsnak": {"datavalue": {"value": "Apple logo.svg"}}}]}}
        )
        image_resp = self._mock_response(content=b"fake-png-bytes")
        mock_get.side_effect = [search_resp, claims_resp, image_resp]

        first = logo_service.fetch_company_logo("Apple")
        mock_get.reset_mock()
        second = logo_service.fetch_company_logo("Apple")

        self.assertEqual(first, second)
        mock_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
