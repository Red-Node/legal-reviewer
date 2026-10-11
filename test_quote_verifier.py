"""Synthetic, offline quote checks and integration with the AI response parser."""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from ai_reviewer import parse_analysis_response
from quote_verifier import verify_findings


class QuoteVerifierTests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.socket.connect", side_effect=AssertionError("Network calls are forbidden."))
        network.start()
        self.addCleanup(network.stop)
        self.pages = [
            {"number": 1, "text": "Payment is due within 10 days. Notice must be sent promptly."},
            {"number": 2, "text": "Payment is due within 30 days."},
        ]

    def finding(self, evidence=None, category="ambiguity"):
        if evidence is None:
            evidence = [{"quote": "Notice must be sent promptly.", "page": 1}]
        return {"id": "F1", "category": category, "title": "Potential issue",
                "explanation": "The wording may be unclear.", "evidence": evidence,
                "status": "unverified"}

    def verify(self, finding, pages=None):
        return verify_findings({"findings": [finding]}, self.pages if pages is None else pages)["findings"][0]

    def test_correct_quote_on_correct_page(self):
        result = self.verify(self.finding())
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["failure_reasons"], [])
        self.assertEqual(result["evidence"][0], {
            "quote": "Notice must be sent promptly.", "page": 1,
            "verification_status": "verified", "failure_reason": None, "match_count": 1,
        })

    def test_invented_quote_is_retained_with_reason(self):
        result = self.verify(self.finding([{"quote": "The investor may cancel anytime.", "page": 1}]))
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual(result["evidence"][0]["quote"], "The investor may cancel anytime.")
        self.assertIn("not found", result["evidence"][0]["failure_reason"])
        self.assertEqual(result["evidence"][0]["match_count"], 0)

    def test_correct_quote_on_wrong_page_fails(self):
        result = self.verify(self.finding([{"quote": "Payment is due within 10 days.", "page": 2}]))
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual(result["evidence"][0]["page"], 2)

    def test_line_breaks_and_repeated_whitespace(self):
        quote = "  Payment\t is due within 10 days.  "
        result = self.verify(self.finding([{"quote": quote, "page": 1}]), [
            {"number": 1, "text": "Payment\n is   due\twithin\u00a010\r\ndays."},
        ])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["evidence"][0]["quote"], quote)

    def test_contradiction_with_two_valid_quotes(self):
        result = self.verify(self.finding([
            {"quote": "Payment is due within 10 days.", "page": 1},
            {"quote": "Payment is due within 30 days.", "page": 2},
        ], "contradiction"))
        self.assertEqual(result["status"], "verified")
        self.assertTrue(all(e["verification_status"] == "verified" for e in result["evidence"]))

    def test_contradiction_with_one_invalid_quote(self):
        result = self.verify(self.finding([
            {"quote": "Payment is due within 10 days.", "page": 1},
            {"quote": "Payment is due within 60 days.", "page": 2},
        ], "contradiction"))
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual([e["verification_status"] for e in result["evidence"]], ["verified", "verification_failed"])
        self.assertIn("Evidence 2", result["failure_reasons"][0])

    def test_all_evidence_items_must_pass_even_after_first_two(self):
        result = self.verify(self.finding([
            {"quote": "Payment is due within 10 days.", "page": 1},
            {"quote": "Payment is due within 30 days.", "page": 2},
            {"quote": "Invented third quote.", "page": 1},
        ], "contradiction"))
        self.assertEqual(result["status"], "verification_failed")
        self.assertEqual(len(result["evidence"]), 3)

    def test_contradiction_with_only_one_quote_fails(self):
        result = self.verify(self.finding(category="contradiction"))
        self.assertEqual(result["evidence"][0]["verification_status"], "verified")
        self.assertEqual(result["status"], "verification_failed")
        self.assertIn("at least 2", result["failure_reasons"][0])

    def test_empty_or_non_text_quotes_fail(self):
        for quote in ["", " \n\t", None, 12]:
            with self.subTest(quote=quote):
                result = self.verify(self.finding([{"quote": quote, "page": 1}]))
                self.assertEqual(result["status"], "verification_failed")
                self.assertEqual(result["evidence"][0]["quote"], quote)

    def test_repeated_quotes_report_all_matches_without_unique_location(self):
        quote = "Notice must be sent promptly."
        result = self.verify(self.finding(), [{"number": 1, "text": f"{quote}\n{quote}"}])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["evidence"][0]["match_count"], 2)
        self.assertNotIn("offset", result["evidence"][0])

    def test_overlapping_matches_are_counted(self):
        result = self.verify(self.finding([{"quote": "a a", "page": 1}]), [{"number": 1, "text": "a a a"}])
        self.assertEqual(result["evidence"][0]["match_count"], 2)

    def test_words_punctuation_numbers_and_case_are_not_changed(self):
        for quote in ["payment is due within 10 days.", "Payment is due within 10 days!",
                      "Payment is due within 100 days.", "Payment is payable within 10 days."]:
            with self.subTest(quote=quote):
                self.assertEqual(self.verify(self.finding([{"quote": quote, "page": 1}]))["status"], "verification_failed")

    def test_partial_words_and_numbers_do_not_match(self):
        for quote, text in [("pay", "payment"), ("10", "100"), ("Date", "ClosingDate")]:
            with self.subTest(quote=quote):
                result = self.verify(self.finding([{"quote": quote, "page": 1}]), [{"number": 1, "text": text}])
                self.assertEqual(result["status"], "verification_failed")

    def test_hyphenation_and_smart_quotes_are_not_rewritten(self):
        for quote, text in [("confidentiality", "confiden-\ntiality"), ('"Notice"', '“Notice”')]:
            with self.subTest(quote=quote):
                result = self.verify(self.finding([{"quote": quote, "page": 1}]), [{"number": 1, "text": text}])
                self.assertEqual(result["status"], "verification_failed")

    def test_missing_and_invalid_page_numbers_fail(self):
        for page in [3, 0, -1, "1", True, 1.0, None]:
            with self.subTest(page=page):
                result = self.verify(self.finding([{"quote": "Notice must be sent promptly.", "page": page}]))
                self.assertEqual(result["status"], "verification_failed")
                self.assertEqual(result["evidence"][0]["page"], page)
                self.assertTrue(result["failure_reasons"])

    def test_missing_evidence_is_not_silently_discarded(self):
        for evidence in [[], None]:
            finding = self.finding()
            finding["evidence"] = evidence
            result = self.verify(finding)
            self.assertEqual(result["status"], "verification_failed")
            self.assertEqual(result["evidence"], evidence)

    def test_inputs_and_human_review_decisions_are_preserved(self):
        analysis = {"findings": [self.finding()]}
        analysis["findings"][0]["human_review"] = "pending"
        original_analysis, original_pages = deepcopy(analysis), deepcopy(self.pages)
        result = verify_findings(analysis, self.pages)
        self.assertEqual(analysis, original_analysis)
        self.assertEqual(self.pages, original_pages)
        self.assertEqual(result["findings"][0]["human_review"], "pending")
        self.assertEqual(result["findings"][0]["status"], "verified")

    def test_parser_output_can_be_verified_offline(self):
        parsed = parse_analysis_response(json.dumps({"findings": [self.finding()]}), [1, 2])
        result = verify_findings(parsed, self.pages)
        self.assertEqual(parsed["findings"][0]["status"], "unverified")
        self.assertEqual(result["findings"][0]["status"], "verified")

    def test_failed_findings_stay_in_original_order(self):
        good, bad = self.finding(), self.finding([{"quote": "Invented", "page": 1}])
        bad["id"] = "F2"
        result = verify_findings({"findings": [good, bad]}, self.pages)
        self.assertEqual([f["id"] for f in result["findings"]], ["F1", "F2"])
        self.assertEqual([f["status"] for f in result["findings"]], ["verified", "verification_failed"])

    def test_no_findings(self):
        self.assertEqual(verify_findings({"findings": []}, self.pages), {"findings": []})

    def test_duplicate_original_page_numbers_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique positive integers"):
            verify_findings({"findings": []}, [self.pages[0], self.pages[0]])


if __name__ == "__main__":
    unittest.main()
