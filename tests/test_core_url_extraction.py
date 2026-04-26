import json
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

    @patch("api.core.requests.get")
    def test_reddit_json_falls_back_to_api_reddit(self, requests_get):
        class FakeResponse:
            def __init__(self, status_code, payload=None):
                self.status_code = status_code
                self._payload = payload

            def json(self):
                return self._payload

        payload = [{
            "data": {
                "children": [{
                    "data": {
                        "title": "The fall of Chegg",
                        "selftext": "",
                        "url_overridden_by_dest": "https://i.redd.it/example.jpeg",
                        "preview": {"images": []},
                    }
                }]
            }
        }]
        requests_get.side_effect = [
            FakeResponse(403),
            FakeResponse(200, payload),
        ]

        result = core._extract_reddit_json("https://www.reddit.com/r/test/comments/abc/example/")

        self.assertEqual(result["title"], "The fall of Chegg")
        self.assertEqual(result["images"], ["https://i.redd.it/example.jpeg"])
        self.assertIn("api.reddit.com", requests_get.call_args_list[1].args[0])

    @patch("api.core.requests.get")
    def test_reddit_old_html_extracts_primary_image(self, requests_get):
        class FakeResponse:
            status_code = 200
            url = "https://old.reddit.com/r/test/comments/abc/example/"
            text = """
            <div class="thing" data-fullname="t3_abc" data-url="https://i.redd.it/example.jpeg">
              <a class="title may-blank outbound" href="https://i.redd.it/example.jpeg">The fall of Chegg</a>
              <img src="//preview.redd.it/example.jpeg?width=720&auto=webp">
            </div>
            """

        requests_get.return_value = FakeResponse()

        result = core._extract_reddit_old_html("https://www.reddit.com/r/test/comments/abc/example/")

        self.assertEqual(result["title"], "The fall of Chegg")
        self.assertIn("https://i.redd.it/example.jpeg", result["images"])
        self.assertIn("https://preview.redd.it/example.jpeg?width=720&auto=webp", result["images"])

    @patch("api.core.requests.get")
    def test_reddit_unfurled_extracts_preview_image(self, requests_get):
        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "data": {
                        "title": "The fall of Chegg : r/IndiaTech",
                        "description": "4.3K votes, 206 comments.",
                        "image": {"url": "https://s.microlink.io/?url=https%3A%2F%2Fshare.redd.it%2Fpreview%2Fpost%2Fabc"},
                    }
                }

        requests_get.return_value = FakeResponse()

        result = core._extract_reddit_unfurled("https://www.reddit.com/r/test/comments/abc/example/")

        self.assertEqual(result["title"], "The fall of Chegg : r/IndiaTech")
        self.assertEqual(result["images"], ["https://s.microlink.io/?url=https%3A%2F%2Fshare.redd.it%2Fpreview%2Fpost%2Fabc"])

    @patch("api.core._fetch_html")
    def test_direct_image_without_extension_is_kept_by_content_type(self, fetch_html):
        fetch_html.return_value = ("", "https://cdn.example.test/media?id=123", "image/jpeg")

        result = core.extract_content_from_url("https://cdn.example.test/media?id=123")

        self.assertEqual(result["image_urls"], ["https://cdn.example.test/media?id=123"])
        self.assertTrue(result["image_detection_info"]["has_images"])

    def test_filter_image_urls_dedupes_preview_variants(self):
        images = core._filter_image_urls([
            "https://i.redd.it/example.jpeg",
            "https://preview.redd.it/example.jpeg?width=720&auto=webp",
            "https://preview.redd.it/example.jpeg?width=108&auto=webp",
        ])

        self.assertEqual(images, ["https://i.redd.it/example.jpeg"])

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

    def test_retry_after_parses_gemini_retry_delay(self):
        response = core.GeminiResponse(
            status_code=429,
            body='[{"error":{"details":[{"retryDelay":"29.5s"}]}}]',
        )

        self.assertEqual(core._retry_after_seconds(response), 29.5)

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

    @patch.object(core.FactChecker, "_post_gemini")
    def test_extract_image_claims_filters_intro_line(self, post_gemini):
        checker = core.FactChecker(api_key="test-key")
        post_gemini.return_value = core.GeminiResponse(
            status_code=200,
            body=json.dumps({
                "choices": [{
                    "message": {
                        "content": (
                            "Here are the factual claims from the image:\n"
                            "1. Chegg Inc is identified as the first company officially wiped out by AI."
                        )
                    }
                }]
            }),
        )

        claims = checker.extract_image_claims(image_url="https://i.redd.it/example.jpeg", image_data_url=None)

        self.assertEqual(claims, ["Chegg Inc is identified as the first company officially wiped out by AI."])

    @patch("api.core._analyze_image_urls_with_queue")
    @patch("api.core.extract_content_from_url")
    @patch("api.core._get_checker")
    def test_url_fact_check_skips_images_when_article_text_is_available(
        self,
        get_checker,
        extract_content,
        analyze_images,
    ):
        class FakeChecker:
            api_key = "test-key"
            last_text_error = ""

            def fact_check_text_claims(self, text):
                return [{
                    "claim": "The administration dismissed the National Science Board.",
                    "result": {
                        "verdict": "TRUE",
                        "confidence": 90,
                        "explanation": "Verified.",
                        "sources": ["https://example.test/source"],
                    },
                }]

        get_checker.return_value = (FakeChecker(), None)
        extract_content.return_value = {
            "text": "The administration dismissed the National Science Board. " * 20,
            "title": "Trump fires the entire National Science Board",
            "image_urls": ["https://example.test/image.jpg"],
            "image_detection_info": {"has_images": True, "image_detected": True, "message": ""},
        }

        response, status = core.fact_check_url_input("https://example.test/article")

        self.assertEqual(status, 200)
        self.assertEqual(response["claims_found"], 1)
        self.assertIn("image_analysis_skipped_reason", response)
        analyze_images.assert_not_called()


if __name__ == "__main__":
    unittest.main()
