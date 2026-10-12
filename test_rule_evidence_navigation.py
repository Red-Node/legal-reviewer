"""Offline navigation tests using actual detector output and the benchmark PDF."""
import json
from pathlib import Path
import unittest

import pymupdf
from detection import detect_sections_and_references, validate_references
import test_review


class RuleEvidenceNavigationTests(unittest.TestCase):
    run_js = test_review.ReviewDashboardTests.run_js

    def test_real_benchmark_page_five_reference_and_visible_highlight(self):
        with pymupdf.open(Path(__file__).parent / 'benchmark/fictional_services_agreement.pdf') as pdf:
            pages = [{'number': i + 1, 'text': page.get_text()} for i, page in enumerate(pdf)]
        detected = detect_sections_and_references(pages)
        reference = next(item for item in validate_references(**detected)['broken_references']
                         if item['number'] == '16.9')
        self.assertEqual(reference['page'], 5)
        self.assertTrue(reference['excerpt'].startswith('…'))
        self.run_js('upload.pages=' + json.dumps(pages) + ';\n' +
                    'upload.broken_references=' + json.dumps([reference]) + r''';
await uploadFile();
const finding=state()[0];
assert.equal(findQuoteMatches(upload.pages[4].text, finding.evidence[0].quote).length,0);
const right=elements.get('findings-scroll'); right.scrollTop=315;
const left=elements.get('document-scroll'); left.scrollTop=2300;
vm.runInContext('viewEvidence(reviewState.findings()[0].evidence[0], "rules")',context);
const page=vm.runInContext('pageElements.get(5)',context);
const marks=page.text.children.filter(item=>item.tagName==='mark');
assert.equal(marks.length,1); assert.equal(marks[0].textContent,'Section 16.9');
assert.equal(page.text.textContent,upload.pages[4].text);
const rect=marks[0].getClientRects()[0], viewport=left.getBoundingClientRect();
assert(rect.top>=viewport.top && rect.bottom<=viewport.top+left.clientHeight);
assert.equal(right.scrollTop,315);
''', ui=True)

    def test_normal_quote_remains_exact(self):
        self.run_js("assert.deepEqual(findEvidenceMatches('Notice promptly.',{quote:'Notice promptly.'},'real'),[{start:0,end:16}]);")

    def test_ai_truncation_and_invented_quotes_never_use_rule_fallback(self):
        self.run_js(r'''
const evidence={quote:'…invented sentence',displayExcerpt:true,referenceText:'Section 16.9',referenceNumber:'16.9'};
for(const source of ['real','demo',undefined])
  assert.equal(findEvidenceMatches('See Section 16.9.',evidence,source).length,0);
assert.equal(findQuoteMatches('See Section 16.9.',evidence.quote).length,0);
''')

    def test_repeated_references_all_returned_with_next_previous(self):
        self.run_js(r'''
upload.pages=[{number:1,text:'See Section 16.9. Again, see Section 16.9.'}];
upload.broken_references=[{number:'16.9',text:'Section 16.9',page:1,excerpt:'…missing context',explanation:'Missing.'}];
await uploadFile();
vm.runInContext('viewEvidence(reviewState.findings()[0].evidence[0], "rules")',context);
assert.equal(elements.get('evidence-match-controls').hidden,false);
assert(elements.get('document-navigation-status').textContent.includes('does not identify a unique location'));
elements.get('evidence-next').listeners.click();
assert.equal(elements.get('evidence-match-position').textContent,'Match 2 of 2');
elements.get('evidence-previous').listeners.click();
assert.equal(elements.get('evidence-match-position').textContent,'Match 1 of 2');
''',ui=True)

    def test_context_distinguishes_repeated_reference(self):
        self.run_js(r'''
const text='See Section 16.9. The termination-dispute referral process is specified in Section 16.9. A dispute entry shall identify the notice.';
const evidence={quote:'…ermination-dispute referral process is specified in Section 16.9. A dispute entry shall identify the',displayExcerpt:true,referenceText:'Section 16.9',referenceNumber:'16.9'};
const matches=findEvidenceMatches(text,evidence,'rules');
assert.equal(matches.length,1); assert.equal(matches[0].start,text.lastIndexOf('Section 16.9'));
''')

    def test_exact_number_not_prefix(self):
        self.run_js(r'''
const evidence={quote:'…missing context',displayExcerpt:true,referenceText:'Section 2.1',referenceNumber:'2.1'};
assert.equal(findEvidenceMatches('Section 2.10. Section 2.1(a). Section 2.1b.',evidence,'rules').length,0);
assert.equal(findEvidenceMatches('See Section 2.1.',evidence,'rules').length,1);
''')

    def test_distinctive_truncated_term_context_with_both_ellipses(self):
        self.run_js(r'''
const text='The Supplier shall record the Delivery Window in the monthly register before enabling access to users.';
const evidence={quote:'…plier shall record the Delivery Window in the monthly register before enabling acc…',displayExcerpt:true};
const matches=findEvidenceMatches(text,evidence,'rules');
assert.equal(matches.length,1);
assert.equal(text.slice(matches[0].start,matches[0].end),'shall record the Delivery Window in the monthly register before enabling');
assert.equal(findEvidenceMatches(text,{quote:'…Delivery Window…',displayExcerpt:true},'rules').length,0);
''')

    def test_missing_reference_no_movement(self):
        self.run_js(r'''
upload.pages=[{number:1,text:'Unrelated source text.'}]; await uploadFile();
const left=elements.get('document-scroll'); left.scrollTop=800;
vm.runInContext('viewEvidence({page:1,quote:"…missing context",displayExcerpt:true,referenceText:"Section 16.9",referenceNumber:"16.9"},"rules")',context);
assert.equal(left.scrollTop,800); assert.equal(elements.get('evidence-match-controls').hidden,true);
assert(elements.get('document-navigation-status').textContent.includes('Cannot locate'));
''',ui=True)

    def test_docx_reference_keeps_original_location(self):
        self.run_js(r'''
const evidence={locationId:'paragraph-2',locationLabel:'Paragraph 2',quote:'…missing context',displayExcerpt:true,referenceText:'Section 16.9',referenceNumber:'16.9'};
assert.equal(findEvidenceMatches('See Section\n16.9.',evidence,'rules').length,1);
assert(!Object.hasOwn(evidence,'page'));
''')


if __name__ == '__main__':
    unittest.main()
