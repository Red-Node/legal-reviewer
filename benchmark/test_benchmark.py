"""Ground-truth integrity tests, not application detection or AI accuracy tests."""

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import pymupdf

from benchmark.build import CATEGORY_TOTALS, DIRECTORY, KEY, PDF, SOURCE, build, extract, normalize, validate


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        network = patch("socket.socket.connect", side_effect=AssertionError("Benchmark tests must stay offline."))
        network.start()
        self.addCleanup(network.stop)
        self.key = json.loads(KEY.read_text())
        self.source = json.loads(SOURCE.read_text())
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def validate_changed_key(self, change):
        key = deepcopy(self.key)
        change(key)
        path = self.directory / "answer_key.json"
        path.write_text(json.dumps(key))
        return validate(PDF, path)

    def build_changed_source(self, change):
        source = deepcopy(self.source)
        change(source)
        path = self.directory / "source.json"
        path.write_text(json.dumps(source))
        return build(path, self.directory / PDF.name, self.directory / KEY.name)

    def test_stored_answer_key_and_actual_pdf_validate(self):
        self.assertEqual(validate(), {"pages": 6, "issues": 20, "category_totals": CATEGORY_TOTALS})

    def test_exact_issue_counts_and_unique_ids(self):
        issues = self.key["issues"]
        self.assertEqual(len({issue["id"] for issue in issues}), 20)
        self.assertEqual(dict(Counter(issue["category"] for issue in issues)), CATEGORY_TOTALS)
        self.assertEqual(sum(len(issue["evidence"]) for issue in issues), 25)

    def test_all_source_paragraphs_are_extractable_and_not_clipped(self):
        pages = extract(PDF)
        for number, part in enumerate(self.source["pages"]):
            text = normalize(pages[number])
            for section in part["sections"]:
                self.assertIn(f'Section {section["number"]} {section["title"]}', text)
                for paragraph in section["paragraphs"]:
                    self.assertIn(normalize(paragraph), text)
        with pymupdf.open(PDF) as pdf:
            for page in pdf:
                for block in page.get_text("dict")["blocks"]:
                    if block["type"] == 0:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                x0, y0, x1, y1 = span["bbox"]
                                self.assertGreaterEqual(x0, 45)
                                self.assertGreaterEqual(y0, 15)
                                self.assertLessEqual(x1, 550)
                                self.assertLessEqual(y1, 832)

    def test_every_quote_occurs_on_its_actual_page(self):
        pages = extract(PDF)
        for issue in self.key["issues"]:
            for item in issue["evidence"]:
                with self.subTest(issue=issue["id"], page=item["page"]):
                    self.assertEqual(normalize(pages[item["page"] - 1]).count(normalize(item["quote"])), 1)

    def test_contradictions_have_two_quotes_and_include_cross_page_controls(self):
        contradictions = [issue for issue in self.key["issues"] if issue["category"] == "contradiction"]
        self.assertTrue(all(len(issue["evidence"]) == 2 for issue in contradictions))
        self.assertEqual(sum(len({item["page"] for item in issue["evidence"]}) == 2 for issue in contradictions), 4)

    def test_regeneration_uses_source_and_actual_pdf_locations(self):
        pdf, key = self.directory / PDF.name, self.directory / KEY.name
        self.assertEqual(build(SOURCE, pdf, key), validate())
        regenerated = json.loads(key.read_text())
        self.assertEqual(regenerated["issues"], self.key["issues"])
        self.assertEqual(pdf.read_bytes(), PDF.read_bytes())

    def test_repagination_recomputes_evidence_pages(self):
        source = deepcopy(self.source)
        source["pages"] = list(reversed(source["pages"]))
        path = self.directory / "source.json"
        path.write_text(json.dumps(source))
        pdf, key = self.directory / PDF.name, self.directory / KEY.name
        build(path, pdf, key)
        regenerated = json.loads(key.read_text())
        for old, new in zip(self.key["issues"], regenerated["issues"]):
            for old_quote, new_quote in zip(old["evidence"], new["evidence"]):
                self.assertEqual(new_quote["page"], 7 - old_quote["page"])

    def test_duplicate_issue_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            self.validate_changed_key(lambda key: key["issues"][1].update(id=key["issues"][0]["id"]))

    def test_wrong_category_totals_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "category totals"):
            self.validate_changed_key(lambda key: key["issues"][0].update(category="ambiguity"))

    def test_invented_quote_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "quote absent"):
            self.validate_changed_key(lambda key: key["issues"][0]["evidence"][0].update(quote="An invented clause not in the PDF."))

    def test_correct_quote_on_wrong_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "quote absent"):
            self.validate_changed_key(lambda key: key["issues"][0]["evidence"][0].update(page=2))

    def test_correct_quote_with_wrong_section_is_rejected(self):
        def change(key):
            key["issues"][0]["sections"] = ["1.1"]
            key["issues"][0]["evidence"][0]["section"] = "1.1"
        with self.assertRaisesRegex(ValueError, "claimed section"):
            self.validate_changed_key(change)

    def test_existing_reference_target_cannot_be_labeled_broken(self):
        with self.assertRaisesRegex(ValueError, "Broken target exists"):
            self.validate_changed_key(lambda key: key["issues"][0].update(target_section="1.1"))

    def test_repairing_missing_heading_invalidates_the_answer_key(self):
        with self.assertRaisesRegex(ValueError, "Broken target exists"):
            self.build_changed_source(lambda source: source["pages"][5]["sections"][4].update(number="12.8"))

    def test_defined_term_cannot_be_labeled_undefined(self):
        with self.assertRaisesRegex(ValueError, "has a definition"):
            self.validate_changed_key(lambda key: key["issues"][6].update(term="Business Day"))

    def test_adding_definition_invalidates_undefined_term_ground_truth(self):
        def change(source):
            source["pages"][5]["sections"][4]["paragraphs"].append('"Delivery Window" means the first week of each month.')
        with self.assertRaisesRegex(ValueError, "has a definition"):
            self.build_changed_source(change)

    def test_changed_pdf_fingerprint_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.validate_changed_key(lambda key: key.update(pdf_sha256="not-the-pdf-fingerprint"))

    def test_missing_contradiction_evidence_is_rejected(self):
        def change(key):
            issue = next(issue for issue in key["issues"] if issue["category"] == "contradiction")
            issue["evidence"] = issue["evidence"][:1]
        with self.assertRaisesRegex(ValueError, "Missing supporting evidence"):
            self.validate_changed_key(change)

    def test_contract_does_not_reveal_answer_ids_and_benchmark_uses_no_ai(self):
        text = "\n".join(extract(PDF))
        for issue in self.key["issues"]:
            self.assertNotIn(issue["id"], text)
        builder = (DIRECTORY / "build.py").read_text()
        self.assertNotIn("import ai_reviewer", builder)
        self.assertNotIn("import anthropic", builder)
        self.assertNotIn("import detection", builder)
        self.assertNotIn("import terms", builder)

    def test_answer_key_is_not_exposed_by_public_application(self):
        from main import app
        with TestClient(app) as client:
            self.assertEqual(client.get("/benchmark/answer_key.json").status_code, 404)
            self.assertEqual(client.get("/benchmark/contract_source.json").status_code, 404)
            self.assertEqual(client.get("/benchmark/fictional_services_agreement.pdf").status_code, 404)
            self.assertNotIn("answer_key.json", client.get("/").text)


if __name__ == "__main__":
    unittest.main()
