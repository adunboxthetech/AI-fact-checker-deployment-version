import unittest
from unittest.mock import patch

from api import core


class UrlExtractionTests(unittest.TestCase):
    def test_default_headers_do_not_request_brotli(self):
        self.assertNotIn("br", core.DEFAULT_HEADERS.get("Accept-Encoding", ""))

    @patch("api.core._fetch_html")
    @patch("api.core._extract_reddit")
    def test_reddit_adapter_with_image_skips_html_fallback(self, extract_reddit, fetch_html):
        extract_reddit.return_value = {
            "text": "The fall of Chegg",
            "title": "The fall of Chegg",
            "images": ["https://i.redd.it/example.jpeg"],
        }

        result = core.extract_content_from_url("https://www.reddit.com/r/test/comments/abc/example/")

        fetch_html.assert_not_called()
        self.assertEqual(result["text"], "The fall of Chegg")
        self.assertEqual(result["image_urls"], ["https://i.redd.it/example.jpeg"])

    @patch("api.core._fetch_html")
    def test_direct_image_without_extension_is_kept_by_content_type(self, fetch_html):
        fetch_html.return_value = ("", "https://cdn.example.test/media?id=123", "image/jpeg")

        result = core.extract_content_from_url("https://cdn.example.test/media?id=123")

        self.assertEqual(result["image_urls"], ["https://cdn.example.test/media?id=123"])
        self.assertTrue(result["image_detection_info"]["has_images"])

    def test_binary_noise_is_treated_as_blocked_content(self):
        self.assertTrue(core._looks_blocked("\ufffd" * 40 + "not useful text" * 20))

    def test_upstream_error_message_handles_gemini_error_array(self):
        response = core.GeminiResponse(
            status_code=429,
            body='[{"error":{"message":"Quota exceeded. Retry later."}}]',
        )

        self.assertEqual(core._extract_error_message(response), "Quota exceeded. Retry later.")


if __name__ == "__main__":
    unittest.main()
