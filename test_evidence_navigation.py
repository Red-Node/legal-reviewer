"""Geometry-based highlight navigation regressions, independent of page positions."""
import unittest
import test_review


class EvidenceNavigationTests(unittest.TestCase):
    run_js = test_review.ReviewDashboardTests.run_js

    def setup(self):
        return r'''
upload.pages=[{number:1,text:'Before Notice\n promptly. After'}, {number:6,text:'Last page source.'}];
await uploadFile();
const left=elements.get('document-scroll');
const right=elements.get('findings-scroll');
right.scrollTop=219;
left.scrollHeight=12000;
const page=vm.runInContext('pageElements.get(1)',context);
page.section.scrollIntoView=()=>{throw new Error('Must target the quote, not the page');};
page.section.getBoundingClientRect=()=>{throw new Error('Page geometry must not determine quote position');};
'''

    def test_highlight_not_page_at_27_point_5_percent(self):
        self.run_js(self.setup()+r'''
left.scrollTop=4500;
vm.runInContext('viewEvidence({page:1,quote:"Notice promptly."})',context);
const mark=page.text.children.find(c=>c.tagName==='mark');
const rect=mark.getClientRects()[0], viewport=left.getBoundingClientRect();
assert.equal(left.scrollTop,762.5);
assert.equal(rect.top-viewport.top, left.clientHeight*.275);
assert(rect.top>=viewport.top && rect.bottom<=viewport.top+left.clientHeight);
assert.equal(right.scrollTop,219);
assert.equal(page.section.scrolled,undefined);
assert.equal(mark.focused,true);
assert.equal(page.heading.focused,undefined);
assert.equal(left.lastScroll.behavior,'instant');
''',ui=True)

    def test_bottom_of_last_page_clamps_but_quote_is_visible(self):
        self.run_js(self.setup()+r'''
const create=context.document.createElement;
context.document.createElement=tag=>{const el=create(tag);if(tag==='mark')el.sourceOffset=11940;return el;};
upload.pages[1].text='Last page source.';
vm.runInContext('viewEvidence({page:6,quote:"Last page source."})',context);
const mark=vm.runInContext('pageElements.get(6).text.children.find(c=>c.tagName==="mark")',context);
assert.equal(left.scrollTop,left.scrollHeight-left.clientHeight);
const rect=mark.getClientRects()[0],view=left.getBoundingClientRect();
assert(rect.top>=view.top && rect.bottom<=view.top+left.clientHeight);
assert.equal(right.scrollTop,219);
''',ui=True)

    def test_quote_near_top_clamps_without_negative_scroll(self):
        self.run_js(self.setup()+r'''
const create=context.document.createElement;
context.document.createElement=tag=>{const el=create(tag);if(tag==='mark')el.sourceOffset=50;return el;};
left.scrollTop=2000;
vm.runInContext('viewEvidence({page:1,quote:"Notice promptly."})',context);
assert.equal(left.scrollTop,0);
assert.equal(right.scrollTop,219);
''',ui=True)

    def test_nested_scroll_and_client_border_offsets(self):
        self.run_js(self.setup()+r'''
left.rect={top:337,bottom:961,height:624,left:32,right:600,width:568};
left.clientTop=2;left.clientHeight=620;left.scrollTop=2900;left.scrollLeft=17;
vm.runInContext('viewEvidence({page:1,quote:"Notice promptly."})',context);
const mark=page.text.children.find(c=>c.tagName==='mark');
assert.equal(mark.getClientRects()[0].top,337+2+620*.275);
assert.equal(left.scrollLeft,17);
assert.equal(right.scrollTop,219);
''',ui=True)

    def test_layout_measured_after_rendering_frame(self):
        self.run_js(self.setup()+r'''
const frames=[];context.window.requestAnimationFrame=callback=>frames.push(callback);
left.scrollTop=111;
vm.runInContext('viewEvidence({page:1,quote:"Notice promptly."})',context);
assert.equal(left.scrollTop,111);
left.rect={top:260,bottom:684,height:424,left:0,right:600,width:600};
left.clientHeight=420;left.clientTop=2;
frames.shift()();
const mark=page.text.children.find(c=>c.tagName==='mark');
assert.equal(mark.getClientRects()[0].top,260+2+420*.275);
''',ui=True)

    def test_wrapped_quote_uses_first_inline_rect(self):
        self.run_js(self.setup()+r'''
const create=context.document.createElement;
context.document.createElement=tag=>{const el=create(tag);if(tag==='mark'){
 el.quoteHeight=650;
 const getLine=el.getClientRects.bind(el);
 el.getClientRects=()=>{const view=left.getBoundingClientRect();const top=view.top+left.clientTop+1300-left.scrollTop;
 return [{top,bottom:top+24,height:24},{top:top+24,bottom:top+48,height:24}];};
 el.getBoundingClientRect=()=>({top:-9999,bottom:9999,height:19998});
}return el;};
vm.runInContext('viewEvidence({page:1,quote:"Notice promptly."})',context);
const mark=page.text.children.find(c=>c.tagName==='mark');
assert.equal(left.scrollTop,1300-500*.275);
assert.equal(mark.getClientRects()[0].top,left.getBoundingClientRect().top+500*.275);
assert.equal(mark.textContent,'Notice\n promptly.');
''',ui=True)

    def test_missing_quote_no_unrelated_scrolling_or_right_mutation(self):
        self.run_js(self.setup()+r'''
left.scrollTop=1740;
elements.get('review-decision-status').textContent='Keep human decision announcement';
vm.runInContext('viewEvidence({page:1,quote:"Invented text"})',context);
assert.equal(left.scrollTop,1740);assert.equal(right.scrollTop,219);
assert.equal(elements.get('review-decision-status').textContent,'Keep human decision announcement');
assert.equal(elements.get('evidence-match-controls').hidden,true);
assert(elements.get('document-navigation-status').textContent.includes('Cannot locate'));
''',ui=True)

    def test_multiple_matches_default_first_and_cycle(self):
        self.run_js(self.setup()+r'''
page.sourceText='Notice promptly. Other text. Notice promptly.';
let markIndex=0;const create=context.document.createElement;
context.document.createElement=tag=>{const el=create(tag);if(tag==='mark')el.sourceOffset=[600,1900][markIndex++];return el;};
vm.runInContext('viewEvidence({page:1,quote:"Notice promptly."})',context);
assert.equal(left.scrollTop,600-500*.275);
assert.equal(elements.get('evidence-match-controls').hidden,false);
assert.equal(elements.get('evidence-match-position').textContent,'Match 1 of 2');
assert(elements.get('document-navigation-status').textContent.includes('does not identify a unique location'));
elements.get('evidence-next').listeners.click();
assert.equal(left.scrollTop,1900-500*.275);
assert.equal(elements.get('evidence-match-position').textContent,'Match 2 of 2');
elements.get('evidence-next').listeners.click();
assert.equal(elements.get('evidence-match-position').textContent,'Match 1 of 2');
elements.get('evidence-previous').listeners.click();
assert.equal(elements.get('evidence-match-position').textContent,'Match 2 of 2');
assert.equal(right.scrollTop,219);
''',ui=True)

    def test_pending_navigation_does_not_survive_document_reset(self):
        self.run_js(self.setup()+r'''
const frames=[];context.window.requestAnimationFrame=callback=>frames.push(callback);
vm.runInContext('viewEvidence({page:1,quote:"Notice promptly."})',context);
elements.get('pdf-file').listeners.change();
left.scrollTop=321;
for(const callback of frames)callback();
assert.equal(left.scrollTop,321);
assert.equal(elements.get('evidence-match-controls').hidden,true);
''',ui=True)

    def test_rapid_quote_changes_only_latest_frame_scrolls(self):
        self.run_js(self.setup()+r'''
const frames=[];context.window.requestAnimationFrame=callback=>frames.push(callback);
vm.runInContext('viewEvidence({page:1,quote:"Before"})',context);
const firstMark=page.text.children.find(c=>c.tagName==='mark');
vm.runInContext('viewEvidence({page:1,quote:"After"})',context);
frames[0]();assert.equal(left.lastScroll,undefined);
frames[1]();assert.equal(firstMark.focused,undefined);
assert.equal(page.text.children.find(c=>c.tagName==='mark').textContent,'After');
''',ui=True)

    def test_docx_location_uses_same_quote_geometry_not_fake_page(self):
        self.run_js(r'''
upload.document_type='docx';upload.locations=[{location_id:'docx-t1-r1-c1-p1',location_label:'Table 1, row 1, cell 1, Paragraph 1',text:'Notice promptly.'}];
upload.total_locations=1;upload.location_notice='DOCX locations, not pages';
await uploadFile();
const left=elements.get('document-scroll');left.scrollTop=2400;
vm.runInContext('viewEvidence({locationId:"docx-t1-r1-c1-p1", locationLabel:"Table 1, row 1, cell 1, Paragraph 1",quote:"Notice promptly."})',context);
assert.equal(left.scrollTop,762.5);
assert(elements.get('document-navigation-status').textContent.includes('Table 1'));
assert(!elements.get('document-navigation-status').textContent.includes('Page'));
''',ui=True)

    def test_overlapping_matches_are_labeled_as_shared_regions(self):
        self.run_js(self.setup()+r'''
page.sourceText='...';
vm.runInContext('viewEvidence({page:1,quote:".."})',context);
assert(elements.get('document-navigation-status').textContent.includes('2 matches'));
assert(elements.get('evidence-match-position').textContent.includes('overlapping source matches'));
assert.equal(elements.get('evidence-match-controls').hidden,true);
assert.equal(page.text.children.filter(c=>c.tagName==='mark').length,1);
''',ui=True)
