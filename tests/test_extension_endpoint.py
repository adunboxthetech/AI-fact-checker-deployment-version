import unittest
from unittest.mock import patch

from api import core
from app import app


class FakeChecker:
    api_key = "test-key"
    last_text_error = ""
    last_image_error = ""

    def __init__(self):
        self.text_inputs = []
        self.image_inputs = []

    def fact_check_text_claims(self, text):
        self.text_inputs.append(text)
        return [
            {
                "claim": "Visible post claim",
                "result": {
                    "verdict": "TRUE",
                    "confidence": 91,
                    "explanation": "Verified from context.",
                    "sources": [],
                },
            }
        ]

    def fact_check_image_content(self, image_url=None, image_data_url=None, max_claims=4):
        self.image_inputs.append((image_url, image_data_url, max_claims))
        return [
            {
                "claim": "[Image] Visible screenshot claim",
                "result": {
                    "verdict": "PARTIALLY TRUE",
                    "confidence": 72,
                    "explanation": "The visible image contains a checkable claim.",
                    "sources": [],
                },
            }
        ]

    def refine_results_with_web_evidence(self, results):
        return results

    def _rate_limit_pause(self):
        return None


class ExtensionEndpointTests(unittest.TestCase):
    @patch("api.core._get_checker")
    def test_extension_post_fact_check_uses_visible_text_context(self, get_checker):
        checker = FakeChecker()
        get_checker.return_value = (checker, None)

        response, status = core.fact_check_extension_post_input(
            {
                "text": "India launched Chandrayaan-3 in 2023.",
                "page_url": "https://x.com/example/status/1",
                "title": "A space post",
                "author": "@example",
                "platform": "x.com",
                "extraction_method": "article",
            }
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["claims_found"], 1)
        self.assertEqual(response["source_url"], "https://x.com/example/status/1")
        self.assertIn("Visible post text:", checker.text_inputs[0])
        self.assertEqual(
            response["fact_check_results"][0]["result"]["sources"],
            ["https://x.com/example/status/1"],
        )

    @patch("api.core._get_checker")
    def test_extension_post_fact_check_can_fall_back_to_screenshot(self, get_checker):
        checker = FakeChecker()
        get_checker.return_value = (checker, None)

        response, status = core.fact_check_extension_post_input(
            {
                "screenshot_data_url": "data:image/png;base64,abc123",
                "page_url": "https://www.instagram.com/p/example/",
                "platform": "instagram.com",
            }
        )

        self.assertEqual(status, 200)
        self.assertEqual(response["claims_found"], 1)
        self.assertTrue(response["extraction"]["screenshot_used"])
        self.assertEqual(checker.image_inputs[0][1], "data:image/png;base64,abc123")

    def test_extension_route_returns_validation_error(self):
        client = app.test_client()
        response = client.post("/api/extension/fact-check", json={})

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())


if __name__ == "__main__":
    unittest.main()
