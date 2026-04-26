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

    def test_jina_403_warning_is_treated_as_blocked_content(self):
        warning = (
            "Title: URL Source: https://www.reddit.com/r/IndiaTech/comments/1svx5pe/the_fall_of_chegg/ "
            "Warning: Target URL returned error 403: Forbidden Markdown Content: "
            "You've been blocked by network security. To continue, log in to your Reddit account "
            "or use your developer token. "
        )

        self.assertTrue(core._looks_blocked(warning))

    def test_upstream_error_message_handles_gemini_error_array(self):
        response = core.GeminiResponse(
            status_code=429,
            body='[{"error":{"message":"Quota exceeded. Retry later."}}]',
        )

        self.assertEqual(core._extract_error_message(response), "Quota exceeded. Retry later.")

    def test_retry_delay_uses_exponential_backoff(self):
        self.assertEqual(core._retry_delay_seconds(0), 2.0)
        self.assertEqual(core._retry_delay_seconds(1), 4.0)
        self.assertEqual(core._retry_delay_seconds(2), 8.0)

    @patch("api.core._download_image_as_data_url", return_value=None)
    @patch("api.core.FactChecker")
    def test_image_queue_returns_per_image_failure(self, fact_checker_class, _download):
        class FakeChecker:
            def __init__(self, api_key=None):
                self.api_key = api_key or "test-key"
                self.last_image_error = ""

            def extract_image_claims(self, image_url=None, image_data_url=None):
                if image_url and "bad" in image_url:
                    self.last_image_error = "Rate limit exceeded after retries"
                    return []
                return ["Image claim"]

        fact_checker_class.side_effect = lambda api_key=None: FakeChecker(api_key)
        parent_checker = FakeChecker("test-key")

        results = core._analyze_image_urls_with_queue(
            parent_checker,
            ["https://example.test/good.jpg", "https://example.test/bad.jpg"],
        )

        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(results[0]["claims"], ["Image claim"])
        self.assertEqual(results[1]["status"], "failed")
        self.assertEqual(results[1]["reason"], "Rate limit exceeded after retries")


if __name__ == "__main__":
    unittest.main()
