"""Offline endpoint tests: real Claude entry points and network access are blocked."""

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from ai_reviewer import DEMO_CONTRACT_TEXT
from main import MAX_FILE_SIZE, app


class DemoReviewTests(unittest.TestCase):
    def setUp(self):
        self.blocked = []
        for target in ["ai_reviewer.Anthropic", "ai_reviewer.analyze_contract",
                       "ai_reviewer.send_text_to_claude", "ai_reviewer.load_dotenv",
                       "socket.socket.connect"]:
            blocker = patch(target, side_effect=AssertionError("Real AI and network access are forbidden in demo tests."))
            self.blocked.append(blocker.start())
            self.addCleanup(blocker.stop)
        environment = patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-configured-key"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.client = TestClient(app)
        self.pages = [{"number": 1, "text": DEMO_CONTRACT_TEXT}]

    def tearDown(self):
        for blocked in self.blocked:
            blocked.assert_not_called()
        self.client.close()

    def review(self, pages=None):
        return self.client.post("/ai-review-demo", json={"pages": self.pages if pages is None else pages})

    def test_fixture_produces_three_verified_and_failed_mock_findings(self):
        response = self.review()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["mode"], "mock")
        self.assertEqual([finding["category"] for finding in data["findings"]], ["contradiction", "ambiguity", "ambiguity"])
        self.assertEqual([finding["status"] for finding in data["findings"]], ["verified", "verified", "verification_failed"])
        self.assertEqual(len(data["findings"][0]["evidence"]), 2)
        self.assertTrue(all(e["verification_status"] == "verified" for e in data["findings"][0]["evidence"]))
        invented = data["findings"][2]["evidence"][0]
        self.assertEqual(invented["page"], 1)
        self.assertEqual(invented["match_count"], 0)
        self.assertIn("not found", invented["failure_reason"])

    def test_unrelated_contract_returns_explained_empty_result(self):
        response = self.review([{"number": 1, "text": "An unrelated agreement."}])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["findings"], [])
        self.assertIn("does not match", response.json()["message"])

    def test_matching_quotes_alone_do_not_trigger_fixture(self):
        response = self.review([{"number": 1, "text": "Payment is due within 10 days.\nPayment is due within 30 days.\nNotice must be sent promptly."}])
        self.assertEqual(response.json()["findings"], [])

    def test_extra_contract_content_or_changed_words_prevent_fixture_match(self):
        for text in [DEMO_CONTRACT_TEXT + "\nAnother clause.", DEMO_CONTRACT_TEXT.replace("10", "15")]:
            with self.subTest(text=text):
                self.assertEqual(self.review([{"number": 1, "text": text}]).json()["findings"], [])

    def test_wrong_page_layout_does_not_receive_fixture_findings(self):
        for pages in [[{"number": 2, "text": DEMO_CONTRACT_TEXT}],
                      [self.pages[0], {"number": 2, "text": ""}]]:
            with self.subTest(pages=pages):
                self.assertEqual(self.review(pages).json()["findings"], [])

    def test_whitespace_variations_preserve_exact_word_match(self):
        pages = [{"number": 1, "text": DEMO_CONTRACT_TEXT.replace(" ", "  ").replace("\n", "\n\n")}]
        self.assertEqual(len(self.review(pages).json()["findings"]), 3)

    def test_malformed_mock_response_returns_safe_error(self):
        with patch("ai_reviewer.DEMO_RESPONSE", "not JSON PRIVATE_DOCUMENT_TEXT"):
            response = self.review()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("PRIVATE_DOCUMENT_TEXT", response.text)
        self.assertIn("No Anthropic API call", response.json()["detail"])

    def test_invalid_mock_evidence_returns_safe_error(self):
        with patch("ai_reviewer.DEMO_RESPONSE", json.dumps({"findings": [{"category": "ambiguity"}]})):
            self.assertEqual(self.review().status_code, 500)

    def test_processing_failure_does_not_expose_document_or_key(self):
        with patch("ai_reviewer.verify_findings", side_effect=RuntimeError("PRIVATE_DOCUMENT_TEXT fake-configured-key")):
            response = self.review()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("PRIVATE_DOCUMENT_TEXT", response.text)
        self.assertNotIn("fake-configured-key", response.text)

    def test_invalid_input_returns_clear_error(self):
        for payload in [{}, {"pages": []}, {"pages": [{"number": True, "text": "Text"}]},
                        {"pages": [{"number": 1, "text": 123}]}, {"pages": [{"number": 1, "text": ""}]},
                        {"pages": self.pages, "mode": "paid"}]:
            with self.subTest(payload=payload):
                response = self.client.post("/ai-review-demo", json=payload)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post("/ai-review-demo", content="not JSON").status_code, 400)

    def test_oversized_request_is_rejected(self):
        response = self.client.post("/ai-review-demo", content=b"x" * (MAX_FILE_SIZE + 1))
        self.assertEqual(response.status_code, 413)

    def test_responses_are_not_cached(self):
        self.assertEqual(self.review().headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/demo-contract.pdf").headers["cache-control"], "no-store")

    def test_download_upload_and_review_end_to_end(self):
        sample = self.client.get("/demo-contract.pdf")
        self.assertEqual(sample.status_code, 200)
        self.assertEqual(sample.headers["content-type"], "application/pdf")
        upload = self.client.post("/analyze", files={"file": ("demo.pdf", sample.content, "application/pdf")})
        self.assertEqual(upload.status_code, 200)
        self.assertEqual(upload.headers["cache-control"], "no-store")
        document = upload.json()
        self.assertEqual(document["total_pages"], 1)
        self.assertEqual(len(document["sections"]), 3)
        for key in ["references", "broken_references", "defined_terms", "candidate_term_uses", "potentially_undefined_terms"]:
            self.assertIn(key, document)
        response = self.review(document["pages"])
        self.assertEqual([f["status"] for f in response.json()["findings"]], ["verified", "verified", "verification_failed"])

    def test_requests_have_no_shared_document_state(self):
        self.assertEqual(len(self.review().json()["findings"]), 3)
        self.assertEqual(self.review([{"number": 1, "text": "Other document"}]).json()["findings"], [])
        self.assertEqual(len(self.review().json()["findings"]), 3)


if __name__ == "__main__":
    unittest.main()
