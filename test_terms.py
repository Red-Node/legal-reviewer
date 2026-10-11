"""Tests for term detection and its integration with the existing PDF reader."""

import unittest
from io import BytesIO

import pymupdf
from fastapi import UploadFile

from main import analyze_document
from terms import detect_terms


def detect(text, page=1):
    return detect_terms([{"number": page, "text": text}])


class TermDetectionTests(unittest.TestCase):
    def test_straight_quotes_and_means(self):
        text = '"Investor" means any person who subscribes for Interests.'
        self.assertEqual(detect(text, page=4)["defined_terms"], [{"term": "Investor", "page": 4, "excerpt": text}])

    def test_curly_quotes_and_shall_mean(self):
        text = '“Closing Date” shall mean the date specified in the notice.'
        result = detect(text, page=2)
        self.assertEqual(result["defined_terms"], [{"term": "Closing Date", "page": 2, "excerpt": text}])
        self.assertEqual(result["candidate_term_uses"], [])

    def test_quote_and_verb_combinations(self):
        for opening, closing in [('"', '"'), ('“', '”')]:
            for verb in ["means", "shall mean", "SHALL MEAN"]:
                with self.subTest(opening=opening, verb=verb):
                    result = detect(f"{opening}Business Day{closing} {verb} a day other than Saturday or Sunday.")
                    self.assertEqual([item["term"] for item in result["defined_terms"]], ["Business Day"])

    def test_multiple_definitions(self):
        text = '\n'.join([
            '"Investor" means any person who subscribes for Interests.',
            '“Closing Date” shall mean the date specified in the notice.',
            '"Business Day" means a day other than Saturday or Sunday.',
        ])
        result = detect(text)
        self.assertEqual([item["term"] for item in result["defined_terms"]], ["Investor", "Closing Date", "Business Day"])
        self.assertEqual(result["candidate_term_uses"], [])

    def test_repeated_uses_preserve_occurrences_and_pages(self):
        result = detect_terms([
            {"number": 1, "text": '“Closing Date” shall mean the date in the notice.\nThe Closing Date must be a Business Day.'},
            {"number": 3, "text": 'Payment is due on the Closing Date. The Closing Date may change.'},
        ])
        self.assertEqual([(item["term"], item["page"]) for item in result["candidate_term_uses"]], [
            ("Closing Date", 1), ("Business Day", 1), ("Closing Date", 3), ("Closing Date", 3),
        ])
        self.assertEqual(result["defined_terms"][0]["page"], 1)

    def test_definition_body_can_use_another_term(self):
        result = detect('"Closing Date" means the first Business Day after notice.')
        self.assertEqual([item["term"] for item in result["candidate_term_uses"]], ["Business Day"])

    def test_non_definition_sentences(self):
        for text in [
            '"Investor" is a person who subscribes.', 'The Investor shall pay.',
            'Closing Date is specified in the notice.', '"Business Day" meaning a working day.',
            '"Closing Date" shall means the notice date.', '"Investor" means',
            '"" means a person.', '"Business Day” means a working day.',
            'See Section 2.1 and Section 2.10.',
        ]:
            with self.subTest(text=text):
                self.assertEqual(detect(text)["defined_terms"], [])

    def test_sentence_capitalization_and_references_are_not_candidate_terms(self):
        result = detect('The Investor shall pay. This Agreement applies.\nSee Section 2.1. Pursuant to Sections 3.1 and 3.2, payment is due.')
        self.assertEqual(result, {"defined_terms": [], "candidate_term_uses": []})

    def test_candidate_without_a_definition_is_only_a_candidate(self):
        result = detect('The Notice Period ends tomorrow.')
        self.assertEqual(result["defined_terms"], [])
        self.assertEqual(result["candidate_term_uses"], [{"term": "Notice Period", "page": 1, "excerpt": 'The Notice Period ends tomorrow.'}])
        self.assertEqual(set(result), {"defined_terms", "candidate_term_uses"})

    def test_lowercase_phrases_and_single_words_are_not_candidates(self):
        self.assertEqual(detect('The investor subscribes for interests. The closing date is tomorrow. Investor shall pay.')["candidate_term_uses"], [])

    def test_wrapped_definition_preserves_original_words(self):
        result = detect('“Closing\nDate” shall\nmean the date specified in the notice.', page=5)
        self.assertEqual(result["defined_terms"], [{
            "term": "Closing Date", "page": 5,
            "excerpt": '“Closing Date” shall mean the date specified in the notice.',
        }])

    def test_excerpts_are_short_and_include_the_matching_text(self):
        definition = detect('"Business Day" means ' + 'a working day ' * 50)["defined_terms"][0]
        self.assertTrue(definition["excerpt"].startswith('"Business Day" means a working day'))
        self.assertLess(len(definition["excerpt"]), 180)
        use = detect('Background text. ' * 30 + 'The Closing Date controls. ' + 'More text. ' * 30)["candidate_term_uses"][0]
        self.assertIn('Closing Date controls.', use["excerpt"])
        self.assertLess(len(use["excerpt"]), 180)

    def test_empty_pages(self):
        self.assertEqual(detect_terms([]), {"defined_terms": [], "candidate_term_uses": []})
        self.assertEqual(detect(''), {"defined_terms": [], "candidate_term_uses": []})


class TermUploadTests(unittest.TestCase):
    def test_terms_are_added_without_changing_existing_results(self):
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72, 72), '\n'.join([
                'Section 2.1 Definitions',
                '"Investor" means a subscriber.',
                '"Closing Date" shall mean the date in the notice.',
                'Payment is due on the Closing Date.',
                'See Section 9.4.',
            ]))
            pdf.new_page().insert_text((72, 72), '\n'.join([
                'Section 2.2 Obligations',
                '"Business Day" means a day other than Saturday or Sunday.',
                'The Closing Date must be a Business Day.',
                'See Section 2.1.',
            ]))
            contents = pdf.tobytes()
        stream = BytesIO(contents)
        result = analyze_document(UploadFile(filename="agreement.pdf", file=stream))
        self.assertTrue(stream.closed)
        self.assertEqual(result["filename"], "agreement.pdf")
        self.assertEqual(result["total_pages"], 2)
        self.assertIn('"Investor" means a subscriber.', result["pages"][0]["text"])
        self.assertEqual([(item["number"], item["page"]) for item in result["sections"]], [("2.1", 1), ("2.2", 2)])
        self.assertEqual([(item["number"], item["page"]) for item in result["references"]], [("9.4", 1), ("2.1", 2)])
        self.assertEqual([(item["number"], item["page"]) for item in result["broken_references"]], [("9.4", 1)])
        self.assertIsNone(result["validation_warning"])
        self.assertEqual([(item["term"], item["page"]) for item in result["defined_terms"]], [("Investor", 1), ("Closing Date", 1), ("Business Day", 2)])
        self.assertEqual([(item["term"], item["page"]) for item in result["candidate_term_uses"]], [("Closing Date", 1), ("Closing Date", 2), ("Business Day", 2)])


if __name__ == "__main__":
    unittest.main()
