"""Offline tests of evidence-gated, explicitly assessed issue-level grading."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark.grade_real_ai import (RUN_ID, RESULTS, grade, combined_summary,
                                     evaluate_saved, render_report, write_reports, digest)
from benchmark.evaluate import metrics

Q1 = 'Payment is due exactly 10 days after receipt.'
Q2 = 'Payment is due exactly 30 days after receipt.'


class SavedGradingTests(unittest.TestCase):
    def setUp(self):
        for target in ('socket.socket.connect', 'ai_reviewer.Anthropic', 'ai_reviewer.send_text_to_claude'):
            guard = patch(target, side_effect=AssertionError('Offline grading must never call AI or the network.'))
            guard.start()
            self.addCleanup(guard.stop)
        self.pages = [{'number': 1, 'text': 'Section 1.1 Payment\n' + Q1},
                      {'number': 2, 'text': 'Section 2.1 Payment\n' + Q2}]
        self.issue = {'id': 'C1', 'category': 'contradiction', 'sections': ['1.1', '2.1'],
                      'description': 'Conflicting exact payment periods', 'explanation': 'Same receipt trigger.',
                      'evidence': [{'quote': Q1, 'page': 1, 'section': '1.1'}, {'quote': Q2, 'page': 2, 'section': '2.1'}]}
        self.finding = {'id': 'F1', 'category': 'contradiction', 'title': 'Conflicting payment deadlines',
                        'explanation': '10 versus 30 days for the same receipt.', 'status': 'unverified',
                        'evidence': [{'quote': Q1, 'page': 1}, {'quote': Q2, 'page': 2}]}
        self.assessment = {'prediction_id': 'F1', 'issue_id': 'C1', 'disposition': 'match',
                           'reason': 'Same exact payment trigger and incompatible periods.'}

    def result(self):
        return grade([self.finding], [self.issue], self.pages, [self.assessment])

    def test_valid_contradiction(self):
        result = self.result()
        self.assertEqual(result['overall'], metrics(1, 1, 1))
        self.assertEqual(len(result['prediction_audit'][0]['supporting_provisions']), 2)

    def test_valid_ambiguity(self):
        self.finding['category'] = self.issue['category'] = 'ambiguity'
        self.finding['evidence'] = self.finding['evidence'][:1]
        self.issue['evidence'] = self.issue['evidence'][:1]
        self.assertEqual(self.result()['categories']['ambiguity'], metrics(1, 1, 1))

    def test_invented_quote_no_credit(self):
        self.finding['evidence'][1]['quote'] = 'Invented obligation.'
        result = self.result()
        self.assertEqual(result['overall'], metrics(1, 1, 0))
        self.assertIn('not found', result['verification_failures'][0]['reasons'][0])

    def test_wrong_page_no_credit(self):
        self.finding['evidence'][0]['page'] = 2
        self.assertEqual(self.result()['overall']['true_positives'], 0)

    def test_missing_evidence_no_credit(self):
        self.finding['evidence'] = []
        self.assertEqual(self.result()['overall']['true_positives'], 0)

    def test_contradiction_needs_both_provisions(self):
        self.finding['evidence'][1] = deepcopy(self.finding['evidence'][0])
        result = self.result()
        self.assertEqual(result['uncertain_prediction_ids'], ['F1'])
        self.assertEqual(result['overall']['true_positives'], 0)

    def test_forged_verified_status_rechecked(self):
        self.finding['status'] = 'verified'
        self.finding['evidence'][0].update(quote='Fabricated.', verification_status='verified')
        self.assertEqual(self.result()['overall']['true_positives'], 0)

    def test_shorter_quote_requires_adjudication(self):
        self.finding['evidence'][0]['quote'] = 'Payment is due exactly 10 days'
        self.assertEqual(self.result()['uncertain_prediction_ids'], ['F1'])

    def test_wrong_section_no_credit(self):
        self.issue['evidence'][0]['section'] = '9.9'
        self.assertEqual(self.result()['overall']['true_positives'], 0)

    def test_repeated_section_location_requires_adjudication(self):
        self.pages[0]['text'] += '\nSection 1.2 Repeat\n' + Q1
        self.assertEqual(self.result()['uncertain_prediction_ids'], ['F1'])

    def test_category_boundary(self):
        self.issue['category'] = 'undefined_term'
        result = self.result()
        self.assertEqual(result['overall']['true_positives'], 0)
        self.assertIn('category boundary', result['prediction_audit'][0]['reason'])

    def test_same_category_alone_not_enough(self):
        self.assessment.update(disposition='unmatched', issue_id=None, reason='Generic commentary; does not identify the payment conflict.')
        self.assertEqual(self.result()['overall'], metrics(1, 1, 0))

    def test_duplicate_prevention(self):
        f2, a2 = deepcopy(self.finding), deepcopy(self.assessment)
        f2['id'] = a2['prediction_id'] = 'F2'
        result = grade([self.finding, f2], [self.issue], self.pages, [self.assessment, a2])
        self.assertEqual(result['overall'], metrics(1, 2, 1))
        self.assertIn('duplicate', result['prediction_audit'][1]['reason'])

    def test_single_prediction_cannot_match_two_issues(self):
        i2 = deepcopy(self.issue)
        i2['id'] = 'C2'
        result = grade([self.finding], [self.issue, i2], self.pages, [self.assessment])
        self.assertEqual(result['overall'], metrics(2, 1, 1))

    def test_uncertain_no_automatic_credit(self):
        self.assessment['disposition'] = 'uncertain'
        result = self.result()
        self.assertEqual(result['overall']['true_positives'], 0)
        self.assertEqual(result['uncertain_prediction_ids'], ['F1'])

    def test_every_prediction_requires_assessment(self):
        with self.assertRaises(ValueError):
            grade([self.finding], [self.issue], self.pages, [])

    def test_duplicate_prediction_ids_rejected(self):
        with self.assertRaises(ValueError):
            grade([self.finding, self.finding], [self.issue], self.pages, [self.assessment])

    def test_duplicate_ground_truth_rejected(self):
        with self.assertRaises(ValueError):
            grade([self.finding], [self.issue, self.issue], self.pages, [self.assessment])

    def test_unknown_issue_rejected(self):
        self.assessment['issue_id'] = 'unknown'
        with self.assertRaises(ValueError):
            self.result()

    def test_missing_reason_rejected(self):
        self.assessment['reason'] = ''
        with self.assertRaises(ValueError):
            self.result()

    def test_no_findings(self):
        result = grade([], [self.issue], self.pages, [])
        self.assertEqual(result['overall'], metrics(1, 0, 0))

    def test_grading_preserves_input(self):
        before = deepcopy((self.finding, self.issue, self.assessment, self.pages))
        self.result()
        self.assertEqual(before, (self.finding, self.issue, self.assessment, self.pages))

    def test_combined_components_not_recategorized(self):
        ai = self.result()
        baseline = {'mode': 'rule_based_only', 'categories': {'broken_reference': metrics(6, 6, 6), 'undefined_term': metrics(5, 11, 5)}}
        combined = combined_summary(ai, baseline)
        self.assertEqual(combined['overall'], metrics(12, 18, 12))
        self.assertEqual(combined['categories']['undefined_term'], metrics(5, 11, 5))

    def test_report_generation_reproducible_and_exclusive(self):
        report = self.result()
        report['provenance'] = {'run_id': 'test-run'}
        summary = combined_summary(report, {'mode': 'rule_based_only', 'categories': {c: metrics(0, 0, 0) for c in ('broken_reference', 'undefined_term')}})
        with tempfile.TemporaryDirectory() as left, tempfile.TemporaryDirectory() as right:
            a, b = write_reports(report, summary, left), write_reports(report, summary, right)
            self.assertEqual([p.read_bytes() for p in a], [p.read_bytes() for p in b])
            self.assertEqual(json.loads(a[0].read_text()), report)
            with self.assertRaises(FileExistsError):
                write_reports(report, summary, left)
            self.assertEqual(a[0].read_bytes(), b[0].read_bytes())

    def test_markdown_escapes_untrusted_content(self):
        self.finding['title'] = '<script>alert(1)</script>|bad'
        text = render_report(self.result())
        self.assertNotIn('<script>', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('\\|bad', text)

    def test_invalid_run_paths(self):
        for run in ('../outside', '.', '..', ''):
            with self.subTest(run=run), self.assertRaises(ValueError):
                evaluate_saved(run)

    def test_actual_saved_run_reproducible_and_immutable(self):
        folder = RESULTS / 'real_ai_runs' / RUN_ID
        if not folder.exists():
            self.skipTest('Real captures remain local, excluded from Git.')
        before = {p.name: digest(p) for p in folder.iterdir() if p.is_file()}
        a, summary = evaluate_saved()
        b, summary2 = evaluate_saved()
        self.assertEqual(a, b)
        self.assertEqual(summary, summary2)
        self.assertEqual(before, {p.name: digest(p) for p in folder.iterdir() if p.is_file()})
        # Check internal accounting, not hardcoded expected model performance.
        self.assertEqual(a['overall']['true_positives'], sum(r['outcome'] == 'matched' for r in a['prediction_audit']))
        self.assertEqual(a['response_metadata']['parsed_findings'], len(a['prediction_audit']))

    def test_changed_assessment_fingerprint_rejected(self):
        folder = RESULTS / 'real_ai_runs' / RUN_ID
        if not folder.exists():
            self.skipTest('Local capture absent.')
        from benchmark.grade_real_ai import ASSESSMENTS
        data = json.loads(ASSESSMENTS.read_text())
        data['source_sha256']['raw'] = 'wrong'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'assessment.json'
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'fingerprints'):
                evaluate_saved(assessment_path=path)
