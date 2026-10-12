"""Offline evaluation tests: synthetic matching cases and actual pipeline parity."""

from copy import deepcopy
import json
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from benchmark.build import PDF, KEY
from benchmark.evaluate import (grade_predictions, metrics, one_to_one_assignment,
                                production_predictions, render_markdown, run_evaluation, write_reports)
from main import app


REFERENCE_QUOTE = "The route is set out in Section 8.1."
TERM_QUOTE = "The supplier shall provide the Delivery Window."


def issue(identifier, category, identity, quote, section="1.1", page=1):
    return {"id": identifier, "category": category, "description": identity + " needs clarification",
            "target_section" if category == "broken_reference" else "term": identity,
            "sections": [section], "explanation": "Synthetic ground truth for matcher testing.",
            "evidence": [{"page": page, "section": section, "quote": quote}]}


def prediction(identifier="P001", category="broken_reference", identity="8.1", excerpt=REFERENCE_QUOTE, page=1):
    return {"id": identifier, "category": category, "identity": identity, "excerpt": excerpt, "page": page}


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.socket.connect", side_effect=AssertionError("Offline evaluation must not use the network."))
        network.start()
        self.addCleanup(network.stop)
        sdk = patch("ai_reviewer.Anthropic", side_effect=AssertionError("No API client permitted."))
        self.sdk = sdk.start()
        self.addCleanup(sdk.stop)
        self.pages = [{"number": 1, "text": f"Section 1.1 Routing\n{REFERENCE_QUOTE}\n{TERM_QUOTE}\nSection 1.2 Other\nAn unrelated provision."},
                      {"number": 2, "text": "Section 2.1 Records\nAn unrelated provision."}]
        self.issues = [issue("BR01", "broken_reference", "8.1", REFERENCE_QUOTE),
                       issue("UT01", "undefined_term", "Delivery Window", TERM_QUOTE)]

    def tearDown(self):
        self.sdk.assert_not_called()

    def grade(self, predictions, issues=None, pages=None):
        return grade_predictions(predictions, self.issues if issues is None else issues, self.pages if pages is None else pages)

    def test_exact_reference_and_term_evidence_match(self):
        preds = [prediction(), prediction("P002", "undefined_term", "Delivery Window", TERM_QUOTE)]
        report = self.grade(preds)
        self.assertEqual({match["issue_id"] for match in report["matched_issues"]}, {"BR01", "UT01"})
        self.assertEqual(report["overall"]["true_positives"], 2)
        self.assertEqual(report["overall"]["precision"], 1)
        self.assertEqual(report["overall"]["recall"], 1)
        for match in report["matched_issues"]:
            self.assertEqual(match["matching_reason"]["section"], "1.1")
            self.assertIn("source mention", match["matching_reason"]["criterion"])

    def test_same_category_wrong_reference_identifier_is_not_correct(self):
        pages = deepcopy(self.pages)
        pages[0]["text"] += "\nUse Section 8.10 instead."
        report = self.grade([prediction(identity="8.10", excerpt="Use Section 8.10 instead.")], pages=pages)
        self.assertEqual(report["overall"]["true_positives"], 0)
        self.assertEqual(report["overall"]["false_positives"], 1)
        self.assertEqual(report["overall"]["false_negatives"], 2)

    def test_reference_number_is_not_matched_as_a_prefix(self):
        report = self.grade([prediction(identity="8")])
        self.assertEqual(report["overall"]["true_positives"], 0)
        self.assertEqual(report["unmatched_predictions"][0]["source_locations"], [])

    def test_complete_term_names_case_and_pluralization_are_preserved(self):
        for term in ["Window", "Final Delivery Window", "Delivery Windows", "delivery window"]:
            with self.subTest(term=term):
                report = self.grade([prediction(category="undefined_term", identity=term, excerpt=TERM_QUOTE)])
                self.assertEqual(report["overall"]["true_positives"], 0)

    def test_surrounding_quotes_and_whitespace_in_term_names_are_normalized(self):
        report = self.grade([prediction(category="undefined_term", identity=' “Delivery   Window” ', excerpt=TERM_QUOTE)])
        self.assertEqual(report["overall"]["true_positives"], 1)

    def test_categories_cannot_cross_match_even_at_same_location(self):
        gt = issue("UT01", "undefined_term", "Section 8.1", REFERENCE_QUOTE)
        report = self.grade([prediction()], issues=[gt])
        self.assertEqual(report["overall"]["true_positives"], 0)
        self.assertEqual(report["categories"]["broken_reference"]["false_positives"], 1)
        self.assertEqual(report["categories"]["undefined_term"]["false_negatives"], 1)

    def test_wrong_page_cannot_match(self):
        report = self.grade([prediction(page=2)])
        self.assertEqual(report["overall"]["true_positives"], 0)
        self.assertEqual(report["unmatched_predictions"][0]["source_locations"], [])

    def test_same_identifier_at_unrelated_section_cannot_match(self):
        pages = deepcopy(self.pages)
        pages[0]["text"] += "\nA different task uses Section 8.1."
        report = self.grade([prediction(excerpt="A different task uses Section 8.1.")], pages=pages)
        self.assertEqual(report["overall"]["true_positives"], 0)
        self.assertEqual(report["unmatched_predictions"][0]["source_locations"][0]["section"], "1.2")

    def test_same_section_different_source_mention_cannot_match(self):
        pages = deepcopy(self.pages)
        pages[0]["text"] = pages[0]["text"].replace("Section 1.2 Other", "Another task uses Section 8.1.\nSection 1.2 Other")
        report = self.grade([prediction(excerpt="Another task uses Section 8.1.")], pages=pages)
        self.assertEqual(report["overall"]["true_positives"], 0)
        self.assertEqual(report["unmatched_predictions"][0]["source_locations"][0]["section"], "1.1")

    def test_invented_excerpt_is_not_credited_by_identifier_alone(self):
        report = self.grade([prediction(excerpt="The invention refers to Section 8.1.")])
        self.assertEqual(report["overall"]["true_positives"], 0)
        self.assertEqual(report["unmatched_predictions"][0]["source_locations"], [])

    def test_pdf_whitespace_and_clipped_edge_markers_are_supported(self):
        pages = deepcopy(self.pages)
        pages[0]["text"] = pages[0]["text"].replace(REFERENCE_QUOTE, "The route is set out in Section\n 8.1.")
        report = self.grade([prediction(excerpt="…e route is set out in Section 8.1.…")], pages=pages)
        self.assertEqual(report["overall"]["true_positives"], 1)

    def test_punctuation_is_not_changed_to_force_a_match(self):
        report = self.grade([prediction(excerpt=REFERENCE_QUOTE.replace(".", "!", 1))])
        self.assertEqual(report["overall"]["true_positives"], 0)

    def test_ambiguous_repeated_source_excerpt_is_not_assumed_unique(self):
        pages = deepcopy(self.pages)
        pages[0]["text"] += "\n" + REFERENCE_QUOTE
        report = self.grade([prediction()], pages=pages)
        self.assertEqual(report["overall"]["true_positives"], 0)
        self.assertIn("multiple", report["unmatched_predictions"][0]["reason"])

    def test_duplicate_predictions_do_not_inflate_true_positives(self):
        report = self.grade([prediction(), prediction("P002")], issues=self.issues[:1])
        self.assertEqual(report["overall"], {"scope": ["broken_reference", "undefined_term"],
            "ground_truth_count": 1, "predictions_produced": 2, "true_positives": 1, "false_positives": 1,
            "false_negatives": 0, "precision": 0.5, "recall": 1.0,
            "total_ground_truth_count": 1, "not_evaluated_ground_truth_count": 0})
        duplicate = report["unmatched_predictions"][0]
        self.assertEqual(duplicate["candidate_issue_ids"], ["BR01"])
        self.assertEqual(duplicate["duplicate_of_prediction_ids"], ["P001"])

    def test_prediction_can_match_at_most_one_ground_truth_issue(self):
        extra = deepcopy(self.issues[0])
        extra["id"] = "BR02"
        report = self.grade([prediction()], issues=[self.issues[0], extra])
        self.assertEqual(len(report["matched_issues"]), 1)
        self.assertEqual(len(report["missed_issues"]), 1)

    def test_assignment_avoids_greedy_under_counting(self):
        self.assertEqual(one_to_one_assignment([["A", "B"], ["A"]]), {0: "B", 1: "A"})
        result = one_to_one_assignment([["A"], ["A"], ["B"]])
        self.assertEqual(len(result), 2)
        self.assertEqual(len(set(result.values())), 2)

    def test_missed_rule_issues_are_listed_with_evidence(self):
        report = self.grade([prediction()])
        self.assertEqual(report["missed_issues"], self.issues[1:])
        self.assertEqual(report["categories"]["undefined_term"]["false_negatives"], 1)
        self.assertIn(TERM_QUOTE, render_markdown(report))

    def test_zero_denominators_are_not_misreported_as_perfect_scores(self):
        report = self.grade([])
        self.assertIsNone(report["overall"]["precision"])
        self.assertEqual(report["overall"]["recall"], 0)
        self.assertEqual(report["overall"]["false_negatives"], len(self.issues))
        report = self.grade([prediction()], issues=[])
        self.assertEqual(report["overall"]["precision"], 0)
        self.assertIsNone(report["overall"]["recall"])
        self.assertEqual(metrics(0, 0, 0)["precision"], None)
        self.assertIn("N/A", render_markdown(self.grade([])))

    def test_ai_categories_are_not_scored_as_false_negatives(self):
        ai = [{"id": "CT01", "category": "contradiction", "description": "Potential conflict"},
              {"id": "AM01", "category": "ambiguity", "description": "Potential ambiguity"}]
        report = self.grade([prediction()], issues=self.issues[:1] + ai)
        self.assertEqual(report["overall"]["false_negatives"], 0)
        self.assertEqual(report["overall"]["ground_truth_count"], 1)
        self.assertEqual(report["overall"]["total_ground_truth_count"], 3)
        self.assertEqual(report["overall"]["not_evaluated_ground_truth_count"], 2)
        for category in ["contradiction", "ambiguity"]:
            self.assertEqual(report["categories"][category]["status"], "not_evaluated")
            for field in ["predictions_produced", "true_positives", "false_positives", "false_negatives", "precision", "recall"]:
                self.assertIsNone(report["categories"][category][field])
        self.assertIn("not false negatives", render_markdown(report))

    def test_ai_predictions_are_rejected_in_rule_only_evaluator(self):
        for category in ["contradiction", "ambiguity", "other"]:
            with self.subTest(category=category), self.assertRaisesRegex(ValueError, "rule-based categories only"):
                self.grade([prediction(category=category)])

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "IDs must be unique"):
            self.grade([prediction(), prediction()])
        with self.assertRaisesRegex(ValueError, "IDs must be unique"):
            self.grade([prediction()], issues=[self.issues[0], self.issues[0]])

    def test_grading_preserves_input_predictions_and_ground_truth(self):
        predictions = [prediction()]
        before = deepcopy((predictions, self.issues, self.pages))
        self.grade(predictions)
        self.assertEqual((predictions, self.issues, self.pages), before)

    def test_real_pipeline_outputs_are_preserved_without_ai_or_configuration_reads(self):
        with patch("ai_reviewer.load_dotenv", side_effect=AssertionError("No configuration or credentials needed")), \
             patch("main.review_contract_demo", side_effect=AssertionError("No mock AI findings")), \
             patch("main.review_contract_real", side_effect=AssertionError("No real AI findings")):
            predictions, analysis = production_predictions(PDF)
            with TestClient(app) as client:
                response = client.post("/analyze", files={"file": (PDF.name, PDF.read_bytes(), "application/pdf")})
                self.assertEqual(response.status_code, 200)
                application = response.json()
        self.assertEqual(analysis, application)
        self.assertEqual([p["raw"] for p in predictions if p["category"] == "broken_reference"], application["broken_references"])
        self.assertEqual([p["raw"] for p in predictions if p["category"] == "undefined_term"], application["potentially_undefined_terms"])
        self.assertEqual(len({p["id"] for p in predictions}), len(predictions))

    def test_full_benchmark_metrics_are_computed_not_hardcoded(self):
        first, second = run_evaluation(), run_evaluation()
        self.assertEqual(first, second)
        key = json.loads(KEY.read_text())
        predictions, _ = production_predictions(PDF)
        for category, metrics_result in first["categories"].items():
            self.assertEqual(metrics_result["ground_truth_count"], sum(i["category"] == category for i in key["issues"]))
            if metrics_result["status"] == "evaluated":
                produced = sum(p["category"] == category for p in predictions)
                matched = sum(m["matching_reason"]["category"] == category for m in first["matched_issues"])
                self.assertEqual(metrics_result["predictions_produced"], produced)
                self.assertEqual(metrics_result["true_positives"], matched)
                self.assertEqual(metrics_result["false_positives"], produced - matched)
        self.assertEqual(first["overall"]["true_positives"], len(first["matched_issues"]))
        self.assertEqual(first["overall"]["false_negatives"], len(first["missed_issues"]))
        self.assertEqual(first["overall"]["false_positives"], len(first["unmatched_predictions"]))
        self.assertIn("code_sha256", first["provenance"])

    def test_exported_json_and_markdown_reports_are_consistent(self):
        report = run_evaluation()
        with tempfile.TemporaryDirectory() as directory:
            json_path, markdown_path = write_reports(report, directory)
            self.assertEqual(json.loads(json_path.read_text()), report)
            markdown = markdown_path.read_text()
            self.assertEqual(markdown, render_markdown(report))
            self.assertIn("## Matched issues", markdown)
            self.assertIn("## Unmatched predictions / false positives", markdown)
            for match in report["matched_issues"]:
                self.assertIn(match["issue_id"], markdown)
            for item in report["unmatched_predictions"]:
                self.assertIn(item["prediction"]["id"], markdown)
            self.assertIn("## AI issues not evaluated", markdown)

    def test_reports_remain_unavailable_in_public_application(self):
        with TestClient(app) as client:
            for path in ["/benchmark/results/rule_based_baseline.json", "/benchmark/results/rule_based_baseline.md", "/benchmark/answer_key.json"]:
                self.assertEqual(client.get(path).status_code, 404)
            self.assertNotIn("rule_based_baseline", client.get("/").text)


if __name__ == "__main__":
    unittest.main()
