"""Offline tests for redesign interactions without changing review/evidence state."""
from html.parser import HTMLParser
from pathlib import Path
import unittest
import test_review


class WorkspaceTests(unittest.TestCase):
    run_js = test_review.ReviewDashboardTests.run_js

    def seed(self):
        return '''
upload.pages[0].text='Notice promptly.';
await uploadFile();
await elements.get('ai-demo-button').listeners.click();
vm.runInContext('reviewState.replaceSource("rules", [{category:"Potential broken reference", title:"Section not found", explanation:"Missing target", verificationStatus:"not_applicable", evidence:[{quote:"Source",page:1,verificationStatus:"not_applicable"}]}], reviewState.token()); renderReviewDashboard()', context);
'''

    def test_filtering_never_changes_review_state(self):
        self.run_js(self.seed()+'''
const original = JSON.stringify(state());
for (const name of ['pending','accepted','rejected','all']) {
 elements.get('filter-'+name).listeners.click();
 assert.equal(JSON.stringify(state()), original);
}
assert.equal(elements.get('review-findings').children.length,2);
''',ui=True)

    def test_empty_filter_announced(self):
        self.run_js(self.seed()+'''
elements.get('filter-accepted').listeners.click();
assert.equal(elements.get('review-findings').children.length,0);
assert.equal(elements.get('filter-empty').hidden,false);
assert.equal(elements.get('review-empty').hidden,true);
elements.get('filter-all').listeners.click();
assert.equal(elements.get('filter-empty').hidden,true);
''',ui=True)

    def test_accept_from_pending_updates_filter_and_global_counts(self):
        self.run_js(self.seed()+'''
elements.get('filter-pending').listeners.click();
const card=elements.get('review-findings').children[0];
card.children.find(c=>c.className==='review-actions').children[0].listeners.click();
assert.equal(elements.get('review-findings').children.length,1);
assert(elements.get('review-counts').textContent.includes('Accepted: 1'));
assert(elements.get('review-counts').textContent.includes('Total findings: 2'));
elements.get('filter-accepted').listeners.click();
assert.equal(elements.get('review-findings').children.length,1);
''',ui=True)

    def test_rejected_findings_remain_accessible(self):
        self.run_js(self.seed()+'''
elements.get('review-findings').children[0].children.find(c=>c.className==='review-actions').children[1].listeners.click();
elements.get('filter-rejected').listeners.click();
assert.equal(elements.get('review-findings').children.length,1);
assert.equal(state().length,2);
''',ui=True)

    def test_disclosure_collapsed_by_default_and_keeps_quotes(self):
        self.run_js(self.seed()+'''
const first=elements.get('review-findings').children[0];
const evidence=first.children.find(c=>c.tagName==='ul');
assert.equal(evidence.hidden,true);
const before=JSON.stringify(state());
first.children.find(c=>c.className==='finding-toggle').listeners.click();
assert.equal(elements.get('review-findings').children[0].children.find(c=>c.tagName==='ul').hidden,false);
assert.equal(JSON.stringify(state()),before);
''',ui=True)

    def test_disclosure_preserved_after_decision(self):
        self.run_js(self.seed()+'''
const list=elements.get('review-findings');
list.children[0].children.find(c=>c.className==='finding-toggle').listeners.click();
list.children[0].children.find(c=>c.className==='review-actions').children[0].listeners.click();
assert.equal(list.children[0].children.find(c=>c.tagName==='ul').hidden,false);
''',ui=True)

    def test_filter_switch_during_edit_requires_save_or_cancel(self):
        self.run_js(self.seed()+'''
const list=elements.get('review-findings');
list.children[0].children.find(c=>c.className==='review-actions').children[3].listeners.click();
elements.get('filter-rejected').listeners.click();
assert.equal(list.children.length,2);
assert(list.children[0].children.some(c=>c.className==='finding-editor'));
assert(elements.get('review-decision-status').textContent.includes('Save or cancel'));
''',ui=True)

    def test_accepted_edit_resets_pending_and_draft_count(self):
        self.run_js(self.seed()+'''
const list=elements.get('review-findings');
const actions=()=>list.children[0].children.find(c=>c.className==='review-actions');
actions().children[0].listeners.click();
assert(elements.get('eligible-count').textContent.startsWith('1 accepted'));
actions().children[3].listeners.click();
const editor=list.children[0].children.find(c=>c.className==='finding-editor');
editor.children[1].value='Human title';editor.children[1].listeners.input();
editor.children[4].children[0].listeners.click();
assert.equal(state()[0].decision,'pending');
assert(elements.get('eligible-count').textContent.startsWith('0 accepted'));
''',ui=True)

    def test_failed_finding_visible_and_not_eligible(self):
        self.run_js('''
await uploadFile();demoResponse.findings[0].status='verification_failed';
demoResponse.findings[0].evidence[0].verification_status='verification_failed';
await elements.get('ai-demo-button').listeners.click();
const actions=elements.get('review-findings').children[0].children.find(c=>c.className==='review-actions');
assert.equal(actions.children[0].disabled,true);
assert(elements.get('eligible-count').textContent.startsWith('0 accepted'));
''',ui=True)

    def test_draft_uses_all_accepted_not_only_filtered_cards(self):
        self.run_js(self.seed()+'''
vm.runInContext('reviewState.decide(reviewState.findings()[0].id,"accepted");renderReviewDashboard()',context);
elements.get('filter-rejected').listeners.click();
assert.equal(elements.get('review-findings').children.length,0);
elements.get('draft-counsel-button').listeners.click();
assert(elements.get('counsel-letter').value.includes('Unclear notice'));
assert.equal(elements.get('counsel-panel').hidden,false);
assert(elements.get('stage-guidance').textContent.includes('Read the draft'));
''',ui=True)

    def test_filters_do_not_mark_draft_outdated(self):
        self.run_js(self.seed()+'''
vm.runInContext('reviewState.decide(reviewState.findings()[0].id,"accepted");renderReviewDashboard()',context);
elements.get('draft-counsel-button').listeners.click();
for(const name of ['pending','rejected','all'])elements.get('filter-'+name).listeners.click();
assert.equal(elements.get('counsel-outdated').hidden,true);
''',ui=True)

    def test_no_document_upload_has_clear_selected_state(self):
        self.run_js('''
elements.get('pdf-file').files=[{name:'sample.docx',size:100}];
elements.get('pdf-file').listeners.change();
assert.equal(elements.get('selected-filename').textContent,'sample.docx');
assert.equal(elements.get('current-document-name').textContent,'sample.docx');
assert(elements.get('stage-guidance').textContent.includes('Analyze Document'));
assert.equal(calls.length,0);
''',ui=True)

    def test_dropped_file_is_analyzed_without_automatic_request(self):
        self.run_js('''
const file={name:'dropped.docx',size:100};
elements.get('drop-zone').listeners.drop({preventDefault(){},dataTransfer:{files:[file]}});
assert.equal(elements.get('selected-filename').textContent,file.name);
assert.equal(calls.length,0);
await elements.get('upload-form').listeners.submit({preventDefault(){}});
assert(calls.includes('/analyze'));
''',ui=True)

    def test_multiple_dropped_files_rejected(self):
        self.run_js('''
elements.get('drop-zone').listeners.drop({preventDefault(){},dataTransfer:{files:[{name:'a.pdf'},{name:'b.pdf'}]}});
assert(elements.get('error').textContent.includes('one PDF or DOCX'));
assert.equal(calls.length,0);
''',ui=True)

    def test_invalid_drop_never_calls_endpoint(self):
        self.run_js('''
elements.get('drop-zone').listeners.drop({preventDefault(){},dataTransfer:{files:[{name:'bad.doc',size:100}]}});
await elements.get('upload-form').listeners.submit({preventDefault(){}});
assert.equal(calls.length,0);
assert(elements.get('error').textContent.includes('Legacy .doc'));
''',ui=True)

    def test_oversize_drop_never_calls_endpoint(self):
        self.run_js('''
elements.get('drop-zone').listeners.drop({preventDefault(){},dataTransfer:{files:[{name:'big.pdf',size:11*1024*1024}]}});
await elements.get('upload-form').listeners.submit({preventDefault(){}});
assert.equal(calls.length,0);
assert(elements.get('error').textContent.includes('10 MB'));
''',ui=True)

    def test_new_document_resets_filter_disclosure_and_draft(self):
        self.run_js(self.seed()+'''
elements.get('filter-accepted').listeners.click();
await uploadFile();await elements.get('ai-demo-button').listeners.click();
assert.equal(elements.get('review-findings').children.length,1);
assert.equal(elements.get('review-findings').children[0].children.find(c=>c.tagName==='ul').hidden,true);
assert.equal(elements.get('counsel-letter').value,'');
''',ui=True)

    def test_rendered_document_stays_literal(self):
        self.run_js(r'''
upload.pages=[{number:1,text:'  <script>alert(1)</script>\nExact  source text.'}];
await uploadFile();
assert.equal(elements.get('pages').children[0].children[2].textContent,upload.pages[0].text);
assert(!html.includes('innerHTML'));
''',ui=True)

    def test_validation_warnings_visible_without_opening_diagnostics(self):
        self.run_js("""
upload.validation_warning='No section headings; validation unreliable.';
upload.term_validation_warning='No definitions; validation unreliable.';
await uploadFile();
assert.equal(elements.get('check-warning').hidden,false);
assert(elements.get('check-warning').textContent.includes('No section headings'));
assert(elements.get('check-warning').textContent.includes('No definitions'));
""",ui=True)

    def test_empty_pdf_offers_ai_options_without_running_ai(self):
        self.run_js("""
await uploadFile();
assert.equal(elements.get('ai-options').open,true);
assert(!calls.includes('/ai-review-demo'));
assert(!calls.includes('/ai-review-real'));
assert(elements.get('stage-guidance').textContent.includes('Optional AI review'));
""",ui=True)

    def test_ai_completion_returns_to_unified_review_cards(self):
        self.run_js("""
await uploadFile();
elements.get('findings-scroll').scrollTop=400;
await elements.get('ai-demo-button').listeners.click();
assert.equal(elements.get('findings-scroll').scrollTop,0);
assert.equal(elements.get('review-heading').focused,true);
assert(elements.get('stage-guidance').textContent.includes('Inspect the evidence'));
""",ui=True)

    def test_blocked_real_configuration_has_clear_disabled_control(self):
        self.run_js("""
context.fetch=async url=>{
 calls.push(url);
 return url==='/analyze'?{ok:true,json:async()=>upload}:{ok:false,status:403,json:async()=>({detail:'Public demo gate'})};
};
await uploadFile();
await new Promise(resolve=>setImmediate(resolve));
assert.equal(elements.get('real-button').disabled,true);
assert(elements.get('real-config').textContent.includes('free demo remains available'));
assert(!calls.includes('/ai-review-real'));
""",ui=True)

    def test_html_structure_ids_and_responsive_rules(self):
        class Structure(HTMLParser):
            def __init__(self):super().__init__();self.ids=[];self.stack=[]
            def handle_starttag(self,tag,attrs):
                self.ids.extend(value for name,value in attrs if name=='id')
                if tag not in ('br','input','meta','link','path'):self.stack.append(tag)
            def handle_endtag(self,tag):
                if not self.stack or self.stack.pop()!=tag:raise AssertionError('Invalid HTML nesting')
            def handle_startendtag(self,tag,attrs):pass
        text=(Path(__file__).parent/'index.html').read_text()
        tree=Structure();tree.feed(text)
        self.assertFalse(tree.stack);self.assertEqual(len(tree.ids),len(set(tree.ids)))
        self.assertIn('grid-template-columns:minmax(0,1.35fr) minmax(0,1fr)',text)
        self.assertIn('@media(max-width:900px)',text)
        self.assertIn('prefers-reduced-motion',text)
        self.assertIn('aria-label="Scrollable document text"',text)
        self.assertIn('aria-label="Filter findings by human decision"',text)
