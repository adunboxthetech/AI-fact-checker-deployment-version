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

    def test_invalid_hostname_without_dot_is_rejected(self):
        self.assertFalse(core.is_valid_url("https://not-a-url"))

    def test_private_url_is_rejected(self):
        self.assertFalse(core.is_valid_url("http://127.0.0.1:5000/health"))

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
        self.assertEqual(core._retry_delay_seconds(0), 1.0)
        self.assertEqual(core._retry_delay_seconds(1), 2.0)
        self.assertEqual(core._retry_delay_seconds(2), 4.0)

    def test_retry_after_parses_gemini_retry_delay(self):
        response = core.GeminiResponse(
            status_code=429,
            body='[{"error":{"details":[{"retryDelay":"29.5s"}]}}]',
        )

        self.assertEqual(core._retry_after_seconds(response), 29.5)

    def test_retry_after_parses_millisecond_error_text(self):
        response = core.GeminiResponse(
            status_code=429,
            body="Quota exceeded. Please retry in 258.066462ms.",
        )

        self.assertAlmostEqual(core._retry_after_seconds(response), 0.258066462)

    def test_gemini_payload_uses_lite_fallback_model(self):
        models = core._models_for_payload({"model": core.GEMINI_PRIMARY_MODEL})

        self.assertEqual(models[0], core.GEMINI_PRIMARY_MODEL)
        self.assertIn("gemini-2.0-flash", models)

    def test_grounding_redirect_sources_fall_back_to_titles(self):
        response = {
            "candidates": [{
                "content": {"parts": [{"text": "{}"}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {
                            "uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc",
                            "title": "bbc.com",
                        }},
                        {"web": {
                            "uri": "https://example.test/story?utm_source=x#section",
                            "title": "Example",
                        }},
                    ]
                },
            }]
        }

        self.assertEqual(
            core._extract_grounding_sources(response),
            ["https://bbc.com", "https://example.test/story"],
        )

    def test_clean_sources_drops_google_grounding_redirects(self):
        cleaned = core._clean_sources(
            ["https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"],
            ["https://reuters.com"],
        )

        self.assertEqual(cleaned, ["https://reuters.com"])

    def test_parse_json_block_handles_fenced_array(self):
        parsed = core._try_parse_json_block(
            '```json\n[{"claim":"Chegg declined","verdict":"TRUE"}]\n```'
        )

        self.assertEqual(parsed[0]["claim"], "Chegg declined")

    @patch.object(core.FactChecker, "_post_gemini")
    def test_fact_check_image_content_accepts_single_object_response(self, post_gemini):
        checker = core.FactChecker(api_key="test-key")
        post_gemini.return_value = core.GeminiResponse(
            status_code=200,
            body=json.dumps({
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "claim": "Chegg stock declined sharply.",
                            "verdict": "TRUE",
                            "confidence": "91%",
                            "explanation": "The chart shows a steep decline.",
                            "sources": ["https://example.test/source"],
                        })
                    }
                }]
            }),
        )

        results = checker.fact_check_image_content(image_url="https://i.redd.it/example.jpeg", image_data_url=None)

        self.assertEqual(results[0]["claim"], "[Image] Chegg stock declined sharply.")
        self.assertEqual(results[0]["result"]["confidence"], 91)

    @patch.object(core.FactChecker, "_post_gemini")
    def test_fact_check_image_content_falls_back_to_raw_analysis(self, post_gemini):
        checker = core.FactChecker(api_key="test-key")
        post_gemini.return_value = core.GeminiResponse(
            status_code=200,
            body=json.dumps({
                "choices": [{
                    "message": {
                        "content": "The visible chart indicates Chegg shares fell substantially."
                    }
                }]
            }),
        )

        results = checker.fact_check_image_content(image_url="https://i.redd.it/example.jpeg", image_data_url=None)

        self.assertEqual(results[0]["claim"], "[Image] Visual claim analysis")
        self.assertEqual(results[0]["result"]["verdict"], "ANALYSIS COMPLETE")

    @patch.object(core.FactChecker, "_post_gemini")
    def test_fact_check_text_claims_accepts_single_object_response(self, post_gemini):
        checker = core.FactChecker(api_key="test-key")
        post_gemini.return_value = core.GeminiResponse(
            status_code=200,
            body=json.dumps({
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "claim": "OpenAI released ChatGPT.",
                            "verdict": "TRUE",
                            "confidence": "98%",
                            "explanation": "OpenAI announced ChatGPT publicly.",
                            "sources": ["https://openai.com/blog/chatgpt"],
                        })
                    }
                }]
            }),
        )

        results = checker.fact_check_text_claims("OpenAI released ChatGPT.")

        self.assertEqual(results[0]["claim"], "OpenAI released ChatGPT.")
        self.assertEqual(results[0]["result"]["confidence"], 98)

    @patch.object(core.FactChecker, "_post_gemini")
    def test_fact_check_text_claims_falls_back_to_raw_analysis(self, post_gemini):
        checker = core.FactChecker(api_key="test-key")
        post_gemini.return_value = core.GeminiResponse(
            status_code=200,
            body=json.dumps({
                "choices": [{
                    "message": {
                        "content": "This post contains a general announcement and no specific verifiable claim."
                    }
                }]
            }),
        )

        results = checker.fact_check_text_claims("A social post.")

        self.assertEqual(results[0]["claim"], "Text claim analysis")
        self.assertEqual(results[0]["result"]["verdict"], "ANALYSIS COMPLETE")

    @patch("api.core._download_image_as_data_url", return_value=None)
    @patch("api.core.FactChecker")
    def test_image_queue_returns_per_image_failure(self, fact_checker_class, _download):
        class FakeChecker:
            def __init__(self, api_key=None):
                self.api_key = api_key or "test-key"
                self.last_image_error = ""

            def fact_check_image_content(self, image_url=None, image_data_url=None):
                if image_url and "bad" in image_url:
                    self.last_image_error = "Rate limit exceeded after retries"
                    return []
                return [{
                    "claim": "[Image] Image claim",
                    "result": {
                        "verdict": "TRUE",
                        "confidence": 90,
                        "explanation": "Verified.",
                        "sources": ["https://example.test/source"],
                    },
                }]

        fact_checker_class.side_effect = lambda api_key=None: FakeChecker(api_key)
        parent_checker = FakeChecker("test-key")

        results = core._analyze_image_urls_with_queue(
            parent_checker,
            ["https://example.test/good.jpg", "https://example.test/bad.jpg"],
        )

        self.assertEqual(results[0]["status"], "ok")
        self.assertEqual(results[0]["claims"], ["[Image] Image claim"])
        self.assertEqual(results[0]["checks"][0]["result"]["verdict"], "TRUE")
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

    @patch("api.core._analyze_image_urls_with_queue")
    @patch("api.core.extract_content_from_url")
    @patch("api.core._get_checker")
    def test_url_fact_check_skips_short_title_text_for_image_posts(
        self,
        get_checker,
        extract_content,
        analyze_images,
    ):
        class FakeChecker:
            api_key = "test-key"
            last_text_error = ""

            def fact_check_text_claims(self, text):
                raise AssertionError("short image-post title should not consume a text model call")

        get_checker.return_value = (FakeChecker(), None)
        extract_content.return_value = {
            "text": "The fall of Chegg",
            "title": "The fall of Chegg",
            "image_urls": ["https://i.redd.it/example.jpeg"],
            "image_detection_info": {"has_images": True, "image_detected": True, "message": ""},
        }
        analyze_images.return_value = [{
            "image_url": "https://i.redd.it/example.jpeg",
            "status": "ok",
            "claims": ["[Image] Chegg fell sharply."],
            "checks": [{
                "claim": "[Image] Chegg fell sharply.",
                "result": {
                    "verdict": "TRUE",
                    "confidence": 90,
                    "explanation": "Verified.",
                    "sources": ["https://example.test/source"],
                },
            }],
        }]

        response, status = core.fact_check_url_input("https://reddit.com/r/test/comments/abc/title/")

        self.assertEqual(status, 200)
        self.assertEqual(response["claims_found"], 1)
        self.assertEqual(response["fact_check_results"][0]["claim"], "[Image] Chegg fell sharply.")


if __name__ == "__main__":
    unittest.main()
