"""Run with: python -m unittest -v"""

import unittest
from io import BytesIO

import pymupdf
from fastapi import HTTPException, UploadFile

from detection import detect_sections_and_references, validate_references
from main import MAX_FILE_SIZE, analyze_document


def detect(text, page=1):
    return detect_sections_and_references([{"number": page, "text": text}])


def validate(pages):
    result = detect_sections_and_references(pages)
    return validate_references(result["sections"], result["references"])


class DetectionTests(unittest.TestCase):
    def test_required_heading_formats(self):
        result = detect("Section 2.1 — Payment Terms\n2.2 Investor Obligations\nSection 3.4: Confidentiality", page=2)
        self.assertEqual([section["number"] for section in result["sections"]], ["2.1", "2.2", "3.4"])
        self.assertEqual([section["title"] for section in result["sections"]], ["Payment Terms", "Investor Obligations", "Confidentiality"])
        self.assertTrue(all(section["page"] == 2 for section in result["sections"]))
        self.assertEqual(result["references"], [])

    def test_required_reference_formats(self):
        result = detect("See Section 9.4\nPursuant to Section 2.1\nAs described in Sections 3.1 and 3.2", page=3)
        self.assertEqual(result["sections"], [])
        self.assertEqual([ref["number"] for ref in result["references"]], ["9.4", "2.1", "3.1", "3.2"])
        self.assertTrue(all(ref["page"] == 3 for ref in result["references"]))
        self.assertEqual(result["references"][-1]["text"], "Sections 3.1 and 3.2")

    def test_ordinary_numbers_and_sentences_are_not_headings(self):
        for text in [
            "The fee is 2.2 million dollars.", "3.5% Annual Interest", "10.00 USD",
            "3.5 Million Dollars", "2026.10.11 Contract Date", "2.2", "2 Investor Obligations",
            "2.2 the investor must pay", "2.2 The investor must pay.",
            "Section 9.4 applies to the investor.", "Section 2.1 shall apply",
        ]:
            with self.subTest(text=text):
                self.assertEqual(detect(text)["sections"], [])

    def test_numbers_without_explicit_section_label_are_not_references(self):
        result = detect("The rate is 3.5 percent. Pay $2.1 million.\nSee paragraph 9.4.\nSubsection 2.1 applies.")
        self.assertEqual(result, {"sections": [], "references": []})

    def test_heading_and_reference_on_different_pages(self):
        result = detect_sections_and_references([
            {"number": 1, "text": "  Section 2.1 — Payment Terms\nSection 2.1 applies.\n"},
            {"number": 2, "text": "See Section 2.1. See Section 2.1."},
        ])
        self.assertEqual([(item["number"], item["page"]) for item in result["sections"]], [("2.1", 1)])
        self.assertEqual([(item["number"], item["page"]) for item in result["references"]], [("2.1", 1), ("2.1", 2), ("2.1", 2)])

    def test_lists_case_and_wrapped_references(self):
        result = detect("SECTION 4.1 - RIGHTS AND DUTIES\nSee sections 3.1, 3.2, and\n3.3. Also Section\n4.1.")
        self.assertEqual([item["number"] for item in result["sections"]], ["4.1"])
        self.assertEqual([item["number"] for item in result["references"]], ["3.1", "3.2", "3.3", "4.1"])

    def test_unsupported_identifiers_are_not_truncated(self):
        for text in ["See Section 3.1(a).", "See Section 3.1b.", "See Sections 3.1–3.3."]:
            with self.subTest(text=text):
                self.assertEqual(detect(text)["references"], [])

    def test_empty_text(self):
        self.assertEqual(detect(""), {"sections": [], "references": []})


class BrokenReferenceTests(unittest.TestCase):
    def test_valid_references(self):
        result = validate([{"number": 1, "text": "Section 2.1 — Payment Terms\n2.2 Investor Obligations\nSee Sections 2.1 and 2.2."}])
        self.assertEqual(result, {"broken_references": [], "validation_warning": None})

    def test_missing_reference_details(self):
        result = validate([{"number": 3, "text": "Section 2.1: Payment Terms\nPursuant to Section 9.4, the investor must pay."}])
        self.assertIsNone(result["validation_warning"])
        self.assertEqual(len(result["broken_references"]), 1)
        missing = result["broken_references"][0]
        self.assertEqual((missing["number"], missing["page"], missing["status"]), ("9.4", 3, "Not found"))
        self.assertEqual(missing["excerpt"], "Pursuant to Section 9.4, the investor must pay.")
        self.assertIn("No heading numbered 9.4", missing["explanation"])
        self.assertIn("potential error", missing["explanation"])

    def test_reference_to_later_section(self):
        result = validate([
            {"number": 1, "text": "Section 2.1 Payment Terms\nSee Section 9.4."},
            {"number": 5, "text": "Section 9.4 Confidentiality"},
        ])
        self.assertEqual(result["broken_references"], [])
        self.assertIsNone(result["validation_warning"])

    def test_section_numbers_match_exactly(self):
        for headings, target in [
            ("Section 2 General Terms\nSection 2.10 Payment Terms", "2.1"),
            ("Section 2.1 Payment Terms", "2.10"),
            ("Section 2.1 Payment Terms", "2"),
            ("Section 2.01 Payment Terms", "2.1"),
        ]:
            with self.subTest(target=target, headings=headings):
                result = validate([{"number": 1, "text": f"{headings}\nSee Section {target}."}])
                self.assertEqual([ref["number"] for ref in result["broken_references"]], [target])

    def test_duplicate_missing_references_preserve_every_location(self):
        result = validate([
            {"number": 1, "text": "Section 2.1 Payment Terms\nSee Section 9.4."},
            {"number": 2, "text": "Pursuant to Section 9.4, payment is due.\nSee Section 9.4 again."},
        ])
        self.assertEqual([(ref["number"], ref["page"]) for ref in result["broken_references"]], [("9.4", 1), ("9.4", 2), ("9.4", 2)])
        self.assertIn("Pursuant to Section 9.4", result["broken_references"][1]["excerpt"])

    def test_no_headings_warns_instead_of_flagging_references(self):
        for text in ["See Sections 3.1 and 3.2.", "Unnumbered contract text.", ""]:
            with self.subTest(text=text):
                result = validate([{"number": 1, "text": text}])
                self.assertEqual(result["broken_references"], [])
                self.assertIn("No section headings were detected", result["validation_warning"])
                self.assertIn("unreliable", result["validation_warning"])

    def test_headings_without_references(self):
        result = validate([{"number": 1, "text": "Section 2.1 Payment Terms"}])
        self.assertEqual(result, {"broken_references": [], "validation_warning": None})

    def test_plural_list_can_contain_valid_and_missing_targets(self):
        result = validate([{"number": 1, "text": "Section 3.1 Payment Terms\nSee Sections 3.1, 3.2, and 3.3."}])
        self.assertEqual([ref["number"] for ref in result["broken_references"]], ["3.2", "3.3"])

    def test_excerpt_is_short_and_preserves_wrapped_reference(self):
        text = "Section 2.1 Payment Terms\n" + "Background text. " * 30 + "See Section\n9.4 for details. " + "More text. " * 30
        result = validate([{"number": 1, "text": text}])
        excerpt = result["broken_references"][0]["excerpt"]
        self.assertIn("See Section 9.4 for details.", excerpt)
        self.assertLess(len(excerpt), 140)
        self.assertNotIn("\n", excerpt)


class UploadRegressionTests(unittest.TestCase):
    def test_pdf_upload_preserves_pages_and_adds_detections(self):
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72, 72), "Section 2.1: Payment Terms\nSee Section 9.4.")
            pdf.new_page().insert_text((72, 72), "2.2 Investor Obligations\nAs described in Sections 3.1 and 3.2.")
            contents = pdf.tobytes()
        stream = BytesIO(contents)
        result = analyze_document(UploadFile(filename="contract.pdf", file=stream))
        self.assertTrue(stream.closed)
        self.assertEqual(result["filename"], "contract.pdf")
        self.assertEqual(result["total_pages"], 2)
        self.assertIn("Payment Terms", result["pages"][0]["text"])
        self.assertEqual([(s["number"], s["page"]) for s in result["sections"]], [("2.1", 1), ("2.2", 2)])
        self.assertEqual([(r["number"], r["page"]) for r in result["references"]], [("9.4", 1), ("3.1", 2), ("3.2", 2)])
        self.assertEqual([(r["number"], r["page"]) for r in result["broken_references"]], [("9.4", 1), ("3.1", 2), ("3.2", 2)])
        self.assertIsNone(result["validation_warning"])

    def test_pdf_without_headings_keeps_references_and_returns_warning(self):
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72, 72), "See Section 9.4 for payment details.")
            contents = pdf.tobytes()
        stream = BytesIO(contents)
        result = analyze_document(UploadFile(filename="no-headings.pdf", file=stream))
        self.assertTrue(stream.closed)
        self.assertEqual(result["sections"], [])
        self.assertEqual([ref["number"] for ref in result["references"]], ["9.4"])
        self.assertEqual(result["broken_references"], [])
        self.assertIn("unreliable", result["validation_warning"])

    def test_upload_errors_and_cleanup_still_work(self):
        with pymupdf.open() as pdf:
            pdf.new_page()
            blank = pdf.tobytes()
        for filename, contents, status in [
            ("wrong.txt", b"text", 400), ("bad.pdf", b"not a PDF", 400),
            ("empty.pdf", b"", 400), ("blank.pdf", blank, 400),
            ("large.pdf", b"x" * (MAX_FILE_SIZE + 1), 413),
        ]:
            with self.subTest(filename=filename):
                stream = BytesIO(contents)
                with self.assertRaises(HTTPException) as error:
                    analyze_document(UploadFile(filename=filename, file=stream))
                self.assertEqual(error.exception.status_code, status)
                self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
