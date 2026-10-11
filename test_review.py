"""Offline tests of the actual browser-memory JavaScript; requires Node.js."""

import json
from pathlib import Path
import shutil
import subprocess
import unittest


BASE_DIR = Path(__file__).resolve().parent
NODE = shutil.which("node")
JS_SETUP = """
const assert = require('node:assert/strict');
const {createReview, ruleFindings, aiFindings, canAccept} = require(REVIEW_PATH);
const review = createReview();
review.reset();
const candidate = (status = 'verified') => ({
  category: 'ambiguity', title: 'Unclear notice', explanation: 'Promptly is unclear.',
  verificationStatus: status,
  evidence: [{quote: 'Notice promptly.', page: 1, verificationStatus: status}],
});
const add = (source = 'demo', status = 'verified') => {
  review.replaceSource(source, [candidate(status)], review.token());
  return review.findings().find(f => f.source === source).id;
};
"""

# Small DOM stand-in: execute the existing HTML script and its event handlers,
# rather than contacting a browser, local server, or external API in tests.
UI_SETUP = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(INDEX_PATH, 'utf8');
class Element {
  constructor() { this.children = []; this.textContent = ''; this.hidden = false;
    this.disabled = false; this.listeners = {}; this.files = []; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute() {}
  addEventListener(event, handler) { this.listeners[event] = handler; }
}
const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(m => [m[1], new Element()]));
const upload = {filename: 'sample.pdf', total_pages: 1, pages: [{number: 1, text: 'Sample'}],
  sections: [], references: [], broken_references: [], defined_terms: [], candidate_term_uses: [],
  potentially_undefined_terms: [], validation_warning: null, term_validation_warning: null};
const calls = [];
let demoResponse = {mode: 'mock', message: 'Mock only', findings: [{id: 'D1', category: 'ambiguity',
  title: 'Unclear notice', explanation: 'Potential ambiguity.', status: 'verified', failure_reasons: [],
  evidence: [{quote: 'Notice promptly.', page: 1, verification_status: 'verified', match_count: 1, failure_reason: null}]}]};
let delayedDemo = null;
const context = vm.createContext({
  ReviewDashboard: {createReview, ruleFindings, aiFindings, canAccept},
  document: {getElementById: id => elements.get(id), createElement: () => new Element()},
  location: {hostname: '127.0.0.1'}, window: {confirm: () => false},
  AbortController, FormData: class {append() {}},
  fetch: async url => {
    calls.push(url);
    if (url === '/ai-review-demo' && delayedDemo) return delayedDemo;
    return {ok: true, json: async () => url === '/analyze' ? upload :
      url === '/ai-review-demo' ? demoResponse : {enabled: false, max_input_bytes: 20000, max_output_tokens: 2048}};
  },
});
const inline = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
vm.runInContext(inline, context);
const state = () => vm.runInContext('reviewState.findings()', context);
const uploadFile = async () => {
  elements.get('pdf-file').files = [{name: 'sample.pdf', size: 100}];
  await elements.get('upload-form').listeners.submit({preventDefault() {}});
};
"""


class ReviewDashboardTests(unittest.TestCase):
    def run_js(self, code, ui=False):
        if not NODE:
            self.fail("Node.js is required for the offline browser-state tests. Install Node.js and rerun.")
        setup = JS_SETUP.replace("REVIEW_PATH", json.dumps(str(BASE_DIR / "review.js")))
        if ui:
            setup += UI_SETUP.replace("INDEX_PATH", json.dumps(str(BASE_DIR / "index.html")))
        script = setup + "\n(async () => {\n" + code + "\n})().catch(() => { process.stderr.write('JavaScript review test failed.'); process.exitCode = 1; });"
        result = subprocess.run([NODE, "-"], input=script, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_findings_default_to_pending(self):
        self.run_js("add('rules'); add('demo'); add('real'); assert(review.findings().every(f => f.decision === 'pending'));")

    def test_accept_reject_and_change_decision(self):
        self.run_js("""
const id = add();
for (const decision of ['accepted', 'rejected', 'accepted', 'pending']) {
  assert.equal(review.decide(id, decision), true);
  assert.equal(review.findings()[0].decision, decision);
}
""")

    def test_failed_evidence_cannot_be_accepted_but_can_be_rejected(self):
        self.run_js("""
const id = add('real', 'verification_failed');
assert.equal(review.decide(id, 'accepted'), false);
assert.equal(review.findings()[0].decision, 'pending');
assert.equal(review.decide(id, 'rejected'), true);
assert.equal(review.findings()[0].verificationStatus, 'verification_failed');
""")

    def test_unverified_evidence_and_inconsistent_status_block_acceptance(self):
        self.run_js("""
const c = candidate(); c.evidence[0].verificationStatus = 'verification_failed';
review.replaceSource('real', [c], review.token());
assert.equal(review.decide(review.findings()[0].id, 'accepted'), false);
const id = add('demo', 'unverified'); assert.equal(review.decide(id, 'accepted'), false);
""")

    def test_contradiction_requires_two_verified_evidence_items(self):
        self.run_js("""
const c = candidate(); c.category = 'contradiction';
review.replaceSource('real', [c], review.token());
assert.equal(canAccept(review.findings()[0]), false);
c.evidence.push({...c.evidence[0], quote: 'Other clause.'});
review.replaceSource('real', [c], review.token());
assert.equal(canAccept(review.findings()[0]), true);
""")

    def test_counters_follow_decisions(self):
        self.run_js("""
const a = add('rules'), b = add('demo'); add('real', 'verification_failed');
review.decide(a, 'accepted'); review.decide(b, 'rejected');
assert.deepEqual(review.counts(), {total: 3, pending: 1, accepted: 1, rejected: 1});
review.decide(a, 'rejected');
assert.deepEqual(review.counts(), {total: 3, pending: 1, accepted: 0, rejected: 2});
""")

    def test_new_document_clears_decisions_and_invalidates_old_ids(self):
        self.run_js("""
const old = add(); review.decide(old, 'accepted'); review.reset();
assert.deepEqual(review.counts(), {total: 0, pending: 0, accepted: 0, rejected: 0});
assert.equal(review.decide(old, 'accepted'), false);
const fresh = add(); assert.notEqual(old, fresh); assert.equal(review.findings()[0].decision, 'pending');
""")

    def test_late_results_from_previous_document_are_ignored(self):
        self.run_js("""
const token = review.token(); review.reset();
assert.equal(review.replaceSource('demo', [candidate()], token), false);
assert.equal(review.findings().length, 0);
""")

    def test_stable_ids_and_decisions_for_identical_ai_rerun(self):
        self.run_js("""
const id = add(); review.decide(id, 'accepted'); add();
assert.equal(review.findings().length, 1);
assert.equal(review.findings()[0].id, id); assert.equal(review.findings()[0].decision, 'accepted');
""")

    def test_changed_evidence_gets_new_pending_finding(self):
        self.run_js("""
const id = add(); review.decide(id, 'accepted'); add('demo', 'verification_failed');
assert.notEqual(review.findings()[0].id, id); assert.equal(review.findings()[0].decision, 'pending');
assert.equal(review.decide(id, 'accepted'), false);
""")

    def test_repeated_locations_have_unique_ids_and_separate_decisions(self):
        self.run_js("""
review.replaceSource('demo', [candidate(), candidate()], review.token());
const [a, b] = review.findings(); assert.notEqual(a.id, b.id);
review.decide(a.id, 'accepted'); assert.equal(review.findings()[1].decision, 'pending');
""")

    def test_rule_based_fields_and_page_locations_are_preserved(self):
        self.run_js("""
const data = {broken_references: [{number: '9.4', page: 2, excerpt: 'See Section 9.4.', explanation: 'Potential missing heading.'}],
  potentially_undefined_terms: [{term: 'Notice Period', page: 3, excerpt: 'The Notice Period ends.', explanation: 'Definition may be missing.'}]};
review.replaceSource('rules', ruleFindings(data), review.token());
assert.deepEqual(review.findings().map(f => f.evidence[0].page), [2, 3]);
assert.equal(review.findings()[0].evidence[0].quote, 'See Section 9.4.');
assert(review.findings().every(f => f.verificationStatus === 'not_applicable'));
""")

    def test_demo_and_real_sources_do_not_share_decisions(self):
        self.run_js("""
const demo = add('demo'), real = add('real'); assert.notEqual(demo, real);
review.decide(demo, 'accepted'); assert.equal(review.findings().find(f => f.id === real).decision, 'pending');
review.replaceSource('demo', [], review.token()); assert.equal(review.findings()[0].source, 'real');
""")

    def test_snapshot_cannot_mutate_internal_decisions(self):
        self.run_js("const id = add(); review.findings()[0].decision = 'accepted'; assert.equal(review.findings()[0].decision, 'pending');")

    def test_actual_ui_upload_and_demo_do_not_automatically_request_real_ai(self):
        self.run_js("""
assert.equal(calls.length, 0);
await uploadFile(); await elements.get('ai-demo-button').listeners.click();
assert.equal(state()[0].decision, 'pending');
assert(calls.includes('/analyze')); assert(calls.includes('/ai-review-demo'));
assert(!calls.includes('/ai-review-real'));
await elements.get('real-button').listeners.click();
assert(!calls.includes('/ai-review-real')); // Confirmation cancelled.
""", ui=True)

    def test_actual_ui_buttons_change_decisions_and_counters(self):
        self.run_js("""
await uploadFile(); await elements.get('ai-demo-button').listeners.click();
const list = elements.get('review-findings');
let actions = list.children[0].children.find(child => child.className === 'review-actions');
actions.children[0].listeners.click(); assert.equal(state()[0].decision, 'accepted');
assert(elements.get('review-counts').textContent.includes('Accepted: 1'));
actions = list.children[0].children.find(child => child.className === 'review-actions');
actions.children[1].listeners.click(); assert.equal(state()[0].decision, 'rejected');
""", ui=True)

    def test_actual_ui_rule_findings_are_added_without_any_ai_request(self):
        self.run_js("""
upload.broken_references = [{number: '9.4', page: 1, excerpt: 'See Section 9.4.', explanation: 'Potential missing heading.'}];
upload.potentially_undefined_terms = [{term: 'Notice Period', page: 1, excerpt: 'The Notice Period ends.', explanation: 'Potential missing definition.'}];
await uploadFile();
assert.equal(state().length, 2); assert(state().every(f => f.source === 'rules' && f.decision === 'pending'));
assert(!calls.includes('/ai-review-demo')); assert(!calls.includes('/ai-review-real'));
""", ui=True)

    def test_actual_ui_another_document_resets_accepted_decisions(self):
        self.run_js("""
await uploadFile(); await elements.get('ai-demo-button').listeners.click();
let actions = elements.get('review-findings').children[0].children.find(child => child.className === 'review-actions');
actions.children[0].listeners.click(); const oldId = state()[0].id;
upload.filename = 'different.pdf'; upload.pages = [{number: 1, text: 'Different document'}];
upload.broken_references = [{number: '9.4', page: 1, excerpt: 'See Section 9.4.', explanation: 'Potential issue.'}];
await uploadFile();
assert.equal(state().length, 1); assert.equal(state()[0].source, 'rules');
assert.equal(state()[0].decision, 'pending'); assert.notEqual(state()[0].id, oldId);
assert.equal(elements.get('ai-findings').children.length, 0);
assert(elements.get('review-counts').textContent.includes('Accepted: 0'));
""", ui=True)

    def test_actual_ui_new_upload_rejects_late_demo_response(self):
        self.run_js("""
await uploadFile();
let resolveDemo;
delayedDemo = new Promise(resolve => {resolveDemo = resolve;});
const pending = elements.get('ai-demo-button').listeners.click();
elements.get('pdf-file').listeners.change();
await uploadFile();
resolveDemo({ok: true, json: async () => demoResponse}); await pending;
assert.equal(state().length, 0); assert.equal(elements.get('ai-findings').children.length, 0);
""", ui=True)

    def test_actual_ui_disables_accept_for_failed_evidence(self):
        self.run_js("""
demoResponse.findings[0].status = 'verification_failed';
demoResponse.findings[0].evidence[0].verification_status = 'verification_failed';
await uploadFile(); await elements.get('ai-demo-button').listeners.click();
const item = elements.get('review-findings').children[0];
const actions = item.children.find(child => child.className === 'review-actions');
assert.equal(actions.children[0].disabled, true);
actions.children[0].listeners.click(); assert.equal(state()[0].decision, 'pending');
actions.children[1].listeners.click(); assert.equal(state()[0].decision, 'rejected');
""", ui=True)


if __name__ == "__main__":
    unittest.main()
