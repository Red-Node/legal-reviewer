"""Future paid-mode tests: fake settings, mocked SDK, and blocked networking only."""

import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import anthropic
import httpx2
from fastapi.testclient import TestClient

from ai_reviewer import (DEMO_CONTRACT_TEXT, DEMO_RESPONSE, ReviewError,
                         get_real_review_settings, review_contract_real, send_text_to_claude)
from main import app


class RealReviewTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        dotenv = patch("ai_reviewer.load_dotenv")
        dotenv.start()
        self.addCleanup(dotenv.stop)
        sdk = patch("ai_reviewer.Anthropic")
        self.sdk = sdk.start()
        self.addCleanup(sdk.stop)
        network = patch("socket.socket.connect", side_effect=AssertionError("No real networking is permitted."))
        network.start()
        self.addCleanup(network.stop)
        self.client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000),
                                 headers={"Origin": "http://127.0.0.1:8000"})
        self.addCleanup(self.client.close)
        self.messages = self.sdk.return_value.__enter__.return_value.messages
        self.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=DEMO_RESPONSE)], stop_reason="end_turn",
        )
        self.pages = [{"number": 1, "text": DEMO_CONTRACT_TEXT}]

    def enable_fake_test_only(self):
        # These are isolated process settings with a mocked SDK, never a .env edit.
        os.environ.update(ENABLE_REAL_AI="true", ANTHROPIC_API_KEY="fake-test-secret")

    def post(self, **overrides):
        return self.client.post("/ai-review-real", json={"pages": self.pages, "confirmed": True, **overrides})

    def test_default_disabled_configuration_is_public_and_safe(self):
        os.environ["ANTHROPIC_API_KEY"] = "fake-test-secret"
        response = self.client.get("/ai-review-config")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"enabled": False, "max_input_bytes": 20000,
                                         "max_output_tokens": 2048, "timeout_seconds": 30.0})
        self.assertNotIn("fake-test-secret", response.text)
        self.sdk.assert_not_called()

    def test_disabled_endpoint_never_creates_client_even_with_key_and_confirmation(self):
        os.environ["ANTHROPIC_API_KEY"] = "fake-test-secret"
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertIn("disabled", response.json()["detail"])
        self.sdk.assert_not_called()

    def test_disabled_blocks_all_real_python_entry_points(self):
        os.environ["ANTHROPIC_API_KEY"] = "fake-test-secret"
        for call in [lambda: send_text_to_claude("Synthetic text"),
                     lambda: review_contract_real(self.pages, confirmed=True)]:
            with self.assertRaisesRegex(ReviewError, "disabled"):
                call()
        self.sdk.assert_not_called()

    def test_false_or_unrecognized_flags_remain_disabled(self):
        for flag in ["false", "0", "1", "yes", "", "enabled"]:
            with self.subTest(flag=flag):
                os.environ["ENABLE_REAL_AI"] = flag
                self.assertFalse(get_real_review_settings()["enabled"])
                self.assertEqual(self.post().status_code, 403)
        self.sdk.assert_not_called()

    def test_browser_cannot_override_server_settings(self):
        response = self.post(enabled=True, mode="paid", max_input_bytes=999999)
        self.assertEqual(response.status_code, 403)
        self.sdk.assert_not_called()

    def test_confirmation_required_in_future_enabled_mock_mode(self):
        self.enable_fake_test_only()
        for confirmed in [False, "true", 1, None]:
            with self.subTest(confirmed=confirmed):
                self.assertEqual(self.post(confirmed=confirmed).status_code, 400)
        with self.assertRaisesRegex(ReviewError, "Confirm"):
            review_contract_real(self.pages)
        self.sdk.assert_not_called()

    def test_remote_client_is_rejected(self):
        self.enable_fake_test_only()
        with TestClient(app, base_url="http://127.0.0.1:8000", client=("192.0.2.1", 50000)) as remote:
            self.assertEqual(remote.post("/ai-review-real", json={"pages": self.pages, "confirmed": True}).status_code, 403)
            self.assertEqual(remote.get("/ai-review-config").status_code, 403)
        self.sdk.assert_not_called()

    def test_cross_origin_and_nonlocal_host_are_rejected(self):
        self.enable_fake_test_only()
        for origin in ["http://untrusted.example", "null", ""]:
            self.assertEqual(self.client.post("/ai-review-real", headers={"Origin": origin},
                json={"pages": self.pages, "confirmed": True}).status_code, 403)
        with TestClient(app, base_url="http://untrusted.example", client=("127.0.0.1", 50000)) as foreign:
            self.assertEqual(foreign.get("/ai-review-config").status_code, 403)
        self.sdk.assert_not_called()

    def test_missing_key_is_rejected_before_any_sdk_call(self):
        os.environ["ENABLE_REAL_AI"] = "true"
        response = self.post()
        self.assertEqual(response.status_code, 422)
        self.assertIn("ANTHROPIC_API_KEY", response.json()["detail"])
        self.sdk.assert_not_called()

    def test_oversized_text_is_rejected_not_truncated(self):
        self.enable_fake_test_only()
        os.environ["AI_MAX_INPUT_BYTES"] = "10"
        response = self.post()
        self.assertEqual(response.status_code, 422)
        self.assertIn("not truncated", response.json()["detail"])
        self.sdk.assert_not_called()

    def test_utf8_limit_includes_page_markers_and_preserves_full_text(self):
        self.enable_fake_test_only()
        pages = [{"number": 1, "text": "Été"}]
        exact_size = len("[Page 1]\nÉté".encode("utf-8"))
        os.environ["AI_MAX_INPUT_BYTES"] = str(exact_size - 1)
        self.assertEqual(self.post(pages=pages).status_code, 422)
        self.sdk.assert_not_called()
        os.environ["AI_MAX_INPUT_BYTES"] = str(exact_size)
        self.messages.create.return_value.content[0].text = '{"findings": []}'
        self.assertEqual(self.post(pages=pages).status_code, 200)
        self.assertEqual(self.messages.create.call_args.kwargs["messages"][0]["content"], "[Page 1]\nÉté")

    def test_invalid_limit_configuration_fails_closed(self):
        for limit in ["0", "-1", "not-a-number"]:
            os.environ["AI_MAX_INPUT_BYTES"] = limit
            with self.subTest(limit=limit):
                self.assertEqual(self.post().status_code, 503)
        self.sdk.assert_not_called()

    def test_mocked_future_real_response_is_parsed_and_verified(self):
        self.enable_fake_test_only()
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "real")
        self.assertEqual([f["status"] for f in response.json()["findings"]], ["verified", "verified", "verification_failed"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.sdk.assert_called_once_with(api_key="fake-test-secret", max_retries=0, timeout=30.0)
        self.assertEqual(self.messages.create.call_count, 1)
        self.assertEqual(self.messages.create.call_args.kwargs["max_tokens"], 2048)

    def test_empty_real_response_has_no_findings(self):
        self.enable_fake_test_only()
        self.messages.create.return_value.content[0].text = '{"findings": []}'
        self.assertEqual(self.post().json()["findings"], [])

    def test_malformed_or_truncated_response_is_rejected_without_retry(self):
        self.enable_fake_test_only()
        for text, stop_reason in [("not JSON", "end_turn"), ('{"findings": []}', "max_tokens")]:
            with self.subTest(text=text):
                self.messages.create.reset_mock()
                self.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason)
                self.assertEqual(self.post().status_code, 422)
                self.assertEqual(self.messages.create.call_count, 1)

    def test_api_errors_return_safe_messages_without_retry(self):
        self.enable_fake_test_only()
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        cases = [(anthropic.AuthenticationError, 401, "API key"),
                 (anthropic.PermissionDeniedError, 403, "access"),
                 (anthropic.NotFoundError, 404, "model"),
                 (anthropic.RateLimitError, 429, "rate limit"),
                 (anthropic.APIStatusError, 400, "API error"),
                 (anthropic.APIStatusError, 500, "API error")]
        for error_type, code, expected in cases:
            with self.subTest(code=code):
                self.messages.create.reset_mock()
                self.messages.create.side_effect = error_type("fake-test-secret PRIVATE_DOCUMENT",
                    response=httpx2.Response(code, request=request), body=None)
                response = self.post()
                self.assertEqual(response.status_code, 422)
                self.assertIn(expected, response.json()["detail"])
                self.assertNotIn("fake-test-secret", response.text)
                self.assertNotIn("PRIVATE_DOCUMENT", response.text)
                self.assertEqual(self.messages.create.call_count, 1)

    def test_timeout_and_connection_error_are_not_retried(self):
        self.enable_fake_test_only()
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        for error in [anthropic.APITimeoutError(request), anthropic.APIConnectionError(request=request)]:
            with self.subTest(error=type(error).__name__):
                self.messages.create.reset_mock()
                self.messages.create.side_effect = error
                response = self.post()
                self.assertEqual(response.status_code, 422)
                self.assertIn("No automatic retry", response.json()["detail"])
                self.assertEqual(self.messages.create.call_count, 1)

    def test_unexpected_error_does_not_expose_credentials_or_text(self):
        self.enable_fake_test_only()
        self.messages.create.side_effect = RuntimeError("fake-test-secret PRIVATE_DOCUMENT")
        response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("fake-test-secret", response.text)
        self.assertNotIn("PRIVATE_DOCUMENT", response.text)

    def test_demo_upload_and_config_never_call_sdk_even_when_mock_gate_enabled(self):
        self.enable_fake_test_only()
        sample = self.client.get("/demo-contract.pdf")
        self.assertEqual(self.client.post("/analyze", files={"file": ("demo.pdf", sample.content, "application/pdf")}).status_code, 200)
        self.assertEqual(self.client.get("/ai-review-config").status_code, 200)
        self.assertEqual(self.client.post("/ai-review-demo", json={"pages": self.pages}).status_code, 200)
        self.sdk.assert_not_called()

    def test_client_cannot_supply_custom_key_or_token_cap(self):
        self.enable_fake_test_only()
        self.assertEqual(self.post(api_key="anything", max_tokens=9999).status_code, 400)
        self.sdk.assert_not_called()


if __name__ == "__main__":
    unittest.main()
