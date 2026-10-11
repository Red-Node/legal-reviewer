"""Offline tests: configuration uses fake values and the SDK client is mocked."""

import os
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import ai_reviewer
import pymupdf
from fastapi import UploadFile
from main import analyze_document


class AIReviewerTests(unittest.TestCase):
    def setUp(self):
        # Ignore real credentials and local .env files in every test.
        environment = patch.dict(os.environ, {}, clear=True)
        dotenv = patch("ai_reviewer.load_dotenv")
        sdk = patch("ai_reviewer.Anthropic")
        network = patch("socket.socket.connect", side_effect=AssertionError("Network calls are forbidden in tests."))
        environment.start()
        self.addCleanup(environment.stop)
        self.load_dotenv = dotenv.start()
        self.addCleanup(dotenv.stop)
        self.sdk = sdk.start()
        self.addCleanup(sdk.stop)
        network.start()
        self.addCleanup(network.stop)
        self.client = self.sdk.return_value.__enter__.return_value
        self.client.messages.create.return_value = SimpleNamespace(content=[
            SimpleNamespace(type="text", text="Mock response"),
        ])

    def test_missing_key_and_default_model(self):
        self.assertEqual(ai_reviewer.get_configuration_status(), {
            "api_key_configured": False, "model": "claude-sonnet-5-5",
        })
        self.sdk.assert_not_called()

    def test_status_never_exposes_key_or_creates_client(self):
        os.environ["ANTHROPIC_API_KEY"] = "fake-test-secret"
        status = ai_reviewer.get_configuration_status()
        self.assertTrue(status["api_key_configured"])
        self.assertNotIn("fake-test-secret", repr(status))
        self.assertEqual(set(status), {"api_key_configured", "model"})
        self.sdk.assert_not_called()

    def test_placeholder_and_blank_keys_are_unconfigured(self):
        for key in ["", "  ", "your_key_here", " your_key_here "]:
            with self.subTest(key=key):
                os.environ["ANTHROPIC_API_KEY"] = key
                self.assertFalse(ai_reviewer.get_configuration_status()["api_key_configured"])

    def test_custom_model_and_blank_model_fallback(self):
        os.environ["ANTHROPIC_MODEL"] = " custom-test-model "
        self.assertEqual(ai_reviewer.get_configuration_status()["model"], "custom-test-model")
        os.environ["ANTHROPIC_MODEL"] = "  "
        self.assertEqual(ai_reviewer.get_configuration_status()["model"], ai_reviewer.DEFAULT_MODEL)

    def test_dotenv_uses_project_file_and_preserves_environment(self):
        ai_reviewer.get_configuration_status()
        self.load_dotenv.assert_called_once_with(
            Path(ai_reviewer.__file__).resolve().parent / ".env", override=False,
        )

    def test_missing_key_prevents_request(self):
        with self.assertRaisesRegex(ValueError, "Set ANTHROPIC_API_KEY"):
            ai_reviewer.send_text_to_claude("Synthetic test text")
        self.sdk.assert_not_called()

    def test_invalid_text_prevents_request(self):
        for text in ["", "  ", None, 42]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                ai_reviewer.send_text_to_claude(text)
        self.sdk.assert_not_called()

    def test_future_request_uses_mock_and_default_model(self):
        os.environ["ANTHROPIC_API_KEY"] = "fake-test-key"
        self.assertEqual(ai_reviewer.send_text_to_claude("Synthetic test text"), "Mock response")
        self.sdk.assert_called_once_with(api_key="fake-test-key")
        self.client.messages.create.assert_called_once_with(
            model="claude-sonnet-5-5", max_tokens=1024,
            messages=[{"role": "user", "content": "Synthetic test text"}],
        )
        self.sdk.return_value.__exit__.assert_called_once()

    def test_custom_model_and_text_response_blocks(self):
        os.environ.update(ANTHROPIC_API_KEY="fake-test-key", ANTHROPIC_MODEL="custom-test-model")
        self.client.messages.create.return_value = SimpleNamespace(content=[
            SimpleNamespace(type="text", text="First"),
            SimpleNamespace(type="tool_use"),
            SimpleNamespace(type="text", text="Second"),
        ])
        self.assertEqual(ai_reviewer.send_text_to_claude("Synthetic text"), "First\nSecond")
        self.assertEqual(self.client.messages.create.call_args.kwargs["model"], "custom-test-model")

    def test_pdf_upload_does_not_use_claude_even_with_key_configured(self):
        os.environ["ANTHROPIC_API_KEY"] = "fake-test-key"
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72, 72), '"Closing Date" means the date in the notice.\nThe Closing Date may change.')
            contents = pdf.tobytes()
        result = analyze_document(UploadFile(filename="sample.pdf", file=BytesIO(contents)))
        self.assertEqual(result["total_pages"], 1)
        self.assertEqual(result["defined_terms"][0]["term"], "Closing Date")
        self.sdk.assert_not_called()
        self.load_dotenv.assert_not_called()


if __name__ == "__main__":
    unittest.main()
