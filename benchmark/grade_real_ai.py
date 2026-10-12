"""Offline grading of saved responses, using explicit, inspectable semantic assessments.

No request runner is imported or executed. Evidence alone cannot establish issue identity.
"""
import argparse
import hashlib
import json
from pathlib import Path

from ai_reviewer import format_document_pages, parse_analysis_response
from quote_verifier import verify_findings
from benchmark.build import KEY, PDF, normalize, validate
from benchmark.evaluate import (AI_CATEGORIES, RESULTS, metrics, percentage,
                                production_predictions, section_blocks, quoted_lines)

RUN_ID = '20261012T073514543612Z_d5175dad358f430084ec7de3cb29d8b7'
ASSESSMENTS = Path(__file__).with_name('ai_assessments.json')
LIMITATIONS = [
    'No merging or recategorization of AI predictions into rule-based issues.',
    'Cross-category AI warnings remain AI false positives under this answer key, not necessarily false substantive observations.',
    'Grouped findings count as one prediction; this is issue-level grading, not per-quote accuracy.',
    'Semantic assessments were made by the coding assistant; independent human review is welcome.',
    'Full expected-quote containment is conservative and may under-credit valid shorter quotations.',
    'One clean synthetic agreement and one model run do not estimate general legal-document accuracy.'
]
POLICY = ('Credit requires an explicit semantic assessment, the same category, all quotations '
          'independently verified, and every ground-truth provision supported on its original page '
          'and section. Conservative full ground-truth quote containment is required. '
          'One prediction and one issue receive credit at most once. Uncertain assessments receive '
          'no automatic credit; provisional FP/FN totals include them pending human adjudication.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def evidence_support(prediction, issue, blocks):
    """Require complete expected evidence in verified quotes and uniquely identified sections."""
    supported = []
    for expected in issue['evidence']:
        quote = normalize(expected['quote'])
        for actual in prediction['evidence']:
            if actual.get('verification_status') != 'verified' or actual['page'] != expected['page']:
                continue
            fragment = normalize(actual['quote'])
            locations = [b for b in blocks if b['page'] == actual['page'] and fragment in b['text']]
            if quote in fragment and len(locations) == 1 and locations[0]['section'] == expected['section']:
                supported.append(expected)
                break
    return supported


def grade(findings, issues, pages, assessments):
    if len({f['id'] for f in findings}) != len(findings):
        raise ValueError('Duplicate prediction IDs.')
    if len({i['id'] for i in issues}) != len(issues):
        raise ValueError('Duplicate ground-truth IDs.')
    decisions = {a['prediction_id']: a for a in assessments}
    if len(decisions) != len(assessments) or set(decisions) != {f['id'] for f in findings}:
        raise ValueError('Every prediction needs exactly one semantic assessment.')
    verified = verify_findings({'findings': findings}, pages)['findings']
    blocks, owners, audit, uncertain = section_blocks(pages), {}, [], []
    truth = {i['id']: i for i in issues}
    for finding in verified:
        if finding['category'] not in AI_CATEGORIES:
            raise ValueError('Only AI categories can be scored here.')
        assessment = decisions[finding['id']]
        disposition = assessment['disposition']
        if disposition not in ('match', 'unmatched', 'uncertain') or not assessment.get('reason', '').strip():
            raise ValueError('Assessment needs a valid disposition and nonempty reason.')
        identifier = assessment.get('issue_id')
        if identifier is not None and identifier not in truth:
            raise ValueError('Unknown ground-truth ID.')
        row = {'prediction': finding, 'assessment': assessment, 'outcome': 'unmatched',
               'matched_issue_id': None, 'reason': assessment['reason'], 'supporting_provisions': []}
        if disposition == 'uncertain':
            row['outcome'] = 'needs_human_adjudication'
            uncertain.append(finding['id'])
        elif disposition == 'match':
            if identifier is None:
                raise ValueError('A proposed match needs an issue ID.')
            issue = truth[identifier]
            support = evidence_support(finding, issue, blocks)
            row['supporting_provisions'] = support
            if issue['category'] != finding['category']:
                row['reason'] += ' No credit: category boundary mismatch.'
            elif finding['status'] != 'verified':
                row['reason'] += ' No credit: evidence verification failed.'
            elif len(support) != len(issue['evidence']):
                row['outcome'] = 'needs_human_adjudication'
                row['reason'] += ' No automatic credit: incomplete or nonunique provision evidence.'
                uncertain.append(finding['id'])
            elif identifier in owners:
                row['reason'] += f' No credit: duplicate of {owners[identifier]} for the same issue.'
            else:
                owners[identifier] = finding['id']
                row.update(outcome='matched', matched_issue_id=identifier)
        audit.append(row)
    ai_truth = [i for i in issues if i['category'] in AI_CATEGORIES]
    categories = {category: metrics(sum(i['category'] == category for i in ai_truth),
                                  sum(f['category'] == category for f in verified),
                                  sum(r['outcome'] == 'matched' and r['prediction']['category'] == category for r in audit))
                  for category in AI_CATEGORIES}
    return {'scope': 'saved_real_ai_only', 'matching_policy': POLICY, 'categories': categories,
            'overall': metrics(len(ai_truth), len(verified), len(owners)), 'prediction_audit': audit,
            'missed_issues': [{'issue': i, 'reason': 'No credited prediction identifies this planted issue with sufficient verified evidence.'}
                              for i in ai_truth if i['id'] not in owners],
            'uncertain_prediction_ids': uncertain,
            'verification_failures': [{'prediction_id': f['id'], 'reasons': f['failure_reasons'], 'evidence': f['evidence']}
                                      for f in verified if f['status'] != 'verified']}


def combined_summary(ai, baseline):
    if baseline['mode'] != 'rule_based_only':
        raise ValueError('Expected the saved rule-based baseline.')
    categories = {**{c: baseline['categories'][c] for c in ('broken_reference', 'undefined_term')}, **ai['categories']}
    totals = [metrics_ for metrics_ in categories.values()]
    return {'scope': 'Single synthetic benchmark; separate category-scoped components, not universal accuracy.',
            'categories': categories,
            'overall': metrics(sum(m['ground_truth_count'] for m in totals), sum(m['predictions_produced'] for m in totals),
                               sum(m['true_positives'] for m in totals)),
            'limitations': LIMITATIONS}



def evaluate_saved(run_id=RUN_ID, directory=RESULTS, assessment_path=ASSESSMENTS):
    if not run_id or Path(run_id).name != run_id or run_id in ('.', '..'):
        raise ValueError('Invalid run ID.')
    folder = Path(directory) / 'real_ai_runs' / run_id
    paths = {name: folder / (name + '.json') for name in ('preflight', 'raw', 'parsed', 'verified')}
    before = {name: digest(path) for name, path in paths.items()}
    validate(PDF, KEY)
    key, semantic = read_json(KEY), read_json(assessment_path)
    if semantic['run_id'] != run_id or semantic['source_sha256'] != before or semantic['answer_key_sha256'] != digest(KEY):
        raise ValueError('Semantic assessments do not match the saved source fingerprints.')
    raw, parsed, saved_verified, preflight = (read_json(paths[n]) for n in ('raw', 'parsed', 'verified', 'preflight'))
    _, analysis = production_predictions(PDF)  # Same production extraction; no AI calls.
    pages = analysis['pages']
    if preflight['pdf_sha256'] != digest(PDF) or preflight['document_sha256'] != hashlib.sha256(format_document_pages(pages).encode()).hexdigest():
        raise ValueError('Saved run did not use this complete PDF input.')
    if parse_analysis_response(raw['raw_text'], [p['number'] for p in pages]) != parsed:
        raise ValueError('Saved parsed findings differ from raw response parsing.')
    reverified = verify_findings(parsed, pages)
    if reverified != saved_verified:
        raise ValueError('Saved verification differs from independent offline re-verification.')
    report = grade(parsed['findings'], key['issues'], pages, semantic['assessments'])
    error_path = folder / 'processing_error.json'
    report['response_metadata'] = {'model': raw['response_model'], 'usage': raw['usage'], 'stop_reason': raw['stop_reason'],
        'stream_completed': raw['stream_completed'], 'request_errors': raw['errors'],
        'processing_errors': read_json(error_path) if error_path.exists() else None,
        'parsed_findings': len(parsed['findings']),
        'fully_verified_findings': sum(f['status'] == 'verified' for f in reverified['findings']),
        'evidence_items': sum(len(f['evidence']) for f in reverified['findings'])}
    baseline_path = Path(directory) / 'rule_based_baseline.json'
    baseline = read_json(baseline_path)
    if baseline['provenance']['pdf_sha256'] != digest(PDF) or baseline['provenance']['answer_key_sha256'] != digest(KEY):
        raise ValueError('Baseline uses different benchmark inputs.')
    report['provenance'] = {'run_id': run_id, 'source_sha256': before, 'pdf_sha256': digest(PDF),
        'answer_key_sha256': digest(KEY), 'assessments_sha256': digest(assessment_path),
        'baseline_sha256': digest(baseline_path), 'grader_sha256': digest(__file__),
        'semantic_review_method': 'Coding-assistant inspection of issue identity and source provisions; explicit assessments, not automated semantic inference.'}
    summary = combined_summary(report, baseline)
    summary['provenance'] = report['provenance']
    if before != {name: digest(path) for name, path in paths.items()}:
        raise ValueError('Original files changed during evaluation.')
    return report, summary


def table_cell(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '\\|').replace('\n', ' ')


def render_report(report):
    lines = ['# Combined synthetic benchmark summary' if 'prediction_audit' not in report else '# Saved Claude benchmark evaluation', '', 'Offline grading only. No API calls. Quote verification is not legal validation.', '',
             POLICY, '', '## Metrics', '', '| Category | Truth | Predictions | TP | FP | FN | Precision | Recall |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for category, m in {**report['categories'], 'overall': report['overall']}.items():
        lines.append('| ' + category + ' | ' + ' | '.join(str(m[k]) for k in ('ground_truth_count', 'predictions_produced', 'true_positives', 'false_positives', 'false_negatives')) + f" | {percentage(m['precision'])} | {percentage(m['recall'])} |")
    if 'response_metadata' in report:
        lines += ['', '## Response metadata', '', '```json', json.dumps(report['response_metadata'], indent=2), '```']
    if 'prediction_audit' in report:
        lines += ['', '## Auditable prediction table', '', '| Prediction | Category / title | Outcome | Ground truth | Reason |', '| --- | --- | --- | --- | --- |']
        for row in report['prediction_audit']:
            f = row['prediction']
            lines.append('| ' + ' | '.join(table_cell(v) for v in (f['id'], f['category'] + ': ' + f['title'], row['outcome'], row['matched_issue_id'] or 'None', row['reason'])) + ' |')
        lines += ['', '## Original explanations and source evidence', '']
        for row in report['prediction_audit']:
            f = row['prediction']
            lines += [f"### {table_cell(f['id'])}: {table_cell(f['title'])}", '', 'Original model explanation:', *quoted_lines(f['explanation']), '', f"Overall quotation status: {f['status']}."]
            for e in f['evidence']:
                lines += ['', f"Page {e['page']}; {e['verification_status']}; occurrences: {e['match_count']}; failure: {e['failure_reason'] or 'none'}.", *quoted_lines(e['quote'])]
            lines += ['', 'Credited ground-truth provisions: ' + ', '.join(f"Section {e['section']} (page {e['page']})" for e in row['supporting_provisions']), '']
        lines += ['## Missed issues', '', '| Ground truth | Sections | Reason |', '| --- | --- | --- |']
        for item in report['missed_issues']:
            i = item['issue']
            lines.append('| ' + ' | '.join(table_cell(v) for v in (i['id'] + ': ' + i['description'], ', '.join(i['sections']), item['reason'])) + ' |')
        for item in report['missed_issues']:
            i = item['issue']
            lines += ['', 'Missed issue ' + i['id'] + ':']
            for e in i['evidence']:
                lines += ['', f"Page {e['page']}, Section {e['section']}:", *quoted_lines(e['quote']), '']
        lines += ['', '## Human adjudication and verification failures', '',
                  'Uncertain predictions: ' + (', '.join(report['uncertain_prediction_ids']) or 'None.'),
                  'Verification failures: ' + json.dumps(report['verification_failures'], ensure_ascii=False)]
    lines += ['', '## Limitations', '']
    lines += ['- ' + text for text in report.get('limitations', LIMITATIONS)]
    lines += ['', '## Reproducibility', '', '```json', json.dumps(report.get('provenance', {}), indent=2), '```', '']
    return '\n'.join(lines)


def write_reports(ai, summary, directory=RESULTS):
    paths = []
    Path(directory).mkdir(parents=True, exist_ok=True)
    stems = [f"ai_evaluation_{ai['provenance']['run_id']}", f"combined_evaluation_{ai['provenance']['run_id']}"]
    if any((Path(directory) / (stem + suffix)).exists() for stem in stems for suffix in ('.json', '.md')):
        raise FileExistsError('Reports already exist. Use a new --output-dir; originals will not be overwritten.')
    # Exclusive writes: never overwrite any existing report or original capture.
    for stem, report in ((f"ai_evaluation_{ai['provenance']['run_id']}", ai),
                         (f"combined_evaluation_{ai['provenance']['run_id']}", summary)):
        for suffix, text in (('.json', json.dumps(report, indent=2, ensure_ascii=False) + '\n'), ('.md', render_report(report))):
            path = Path(directory) / (stem + suffix)
            with path.open('x', encoding='utf-8') as stream:
                stream.write(text)
            paths.append(path)
    return paths


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default=RUN_ID)
    parser.add_argument('--output-dir', type=Path, default=RESULTS)
    args = parser.parse_args()
    ai, summary = evaluate_saved(args.run_id)
    for path in write_reports(ai, summary, args.output_dir):
        print(path)
    print(json.dumps({'metadata': ai['response_metadata'], 'ai': ai['overall'], 'combined': summary['overall']}, indent=2))
