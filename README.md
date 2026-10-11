# Legal Reviewer

A minimal PDF text reader built with Python, FastAPI, PyMuPDF, and plain HTML,
CSS, and JavaScript. It extracts text by page and uses deterministic rules to
detect numbered section headings and explicit section references, then flag
references whose targets were not found among recognized headings. It also detects
explicit term definitions and candidate uses of capitalized multi-word terms,
then flags potential issues when a complete term's definition was not found.
The browser review dashboard combines rule-based and AI findings for explicit
human Accept / Reject decisions and wording edits, kept in memory for the current
review only. Accepted findings can be turned into an editable plain-text draft
of questions for counsel without any AI call or automatic email sending.

## Files

- `main.py`: serves the webpage, handles PDF uploads, generates the demo PDF, and exposes the mock-only review endpoint.
- `detection.py`: identifies headings and references, then compares exact section numbers.
- `terms.py`: detects definitions and candidate uses, then checks for potential missing definitions.
- `ai_reviewer.py`: prepares real Claude analysis (inactive), and provides the synthetic mock review using the existing JSON parser and quote verifier.
- `quote_verifier.py`: independently checks evidence quotes against their claimed original pages, entirely offline.
- `.env.example`: shows the local configuration variable names without a real key.
- `index.html`: contains the upload form, styling, and JavaScript that displays results.
- `review.js`: manages unified finding IDs, human decisions, wording edits, evidence acceptance checks, counters, exact quote matching, and counsel letter drafts in browser memory.
- `test_review.py`: runs offline JavaScript state and UI event-handler tests using Node.js.
- `test_detection.py`: tests detection, potential broken references, and existing PDF uploads.
- `test_terms.py`: tests term detection, validation, and integration with existing PDF results.
- `test_ai_reviewer.py`: tests configuration, contract analysis, and response validation with a mocked client.
- `test_quote_verifier.py`: tests exact quote presence, failures, whitespace, and repeated occurrences.
- `test_demo_review.py`: tests the demo endpoints, sample PDF upload, and guards against all real AI calls.
- `test_real_review.py`: tests disabled real-review safeguards and future permitted requests with fake credentials and a mocked SDK.
- `requirements.txt`: lists the Python packages needed to run the app.
- `.gitignore`: excludes local files such as `.env` and `.venv` from Git.

## Run locally on macOS

Use Python 3.10 or newer. Open Terminal in the folder containing your cloned
`legal-reviewer` repository, then run the commands below. The first command
opens the project folder. If Terminal is already inside that folder (where
`main.py` and `requirements.txt` are), skip the `cd legal-reviewer` line.

```sh
cd legal-reviewer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The virtual environment (`.venv`) keeps this project's Python packages separate
from other projects. Open http://127.0.0.1:8000 in your browser. Keep Terminal
running while you use the app. Press **Control+C** in Terminal to stop it.

On later runs, open Terminal in the folder containing the cloned repository
and run the following. Again, skip the first line if you are already inside
the project folder:

```sh
cd legal-reviewer
source .venv/bin/activate
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## Test in your browser

1. Choose a PDF with selectable text and click **Analyze Document**.
2. Check that its original filename and page count appear above the results.
3. Try a multipage PDF and check that each page has its own heading.
4. Submit without selecting a file to see the missing-file error.
5. Try an invalid PDF (for example, a text file renamed to `.pdf`).
6. Try a scanned or blank PDF with no selectable text.
7. Try a PDF larger than 10 MB to see the size error.

You can create a text PDF on your Mac by typing a few paragraphs in TextEdit,
then choosing **File → Print → PDF → Save as PDF**.

## Test section and reference detection

Create a PDF from the following text, keeping each heading on its own line:

```text
Section 2.1 — Payment Terms
See Section 9.4.
2.2 Investor Obligations
Pursuant to Section 2.1, the investor must pay.
Section 3.4: Confidentiality
As described in Sections 3.1 and 3.2, information is confidential.
The fee is 2.2 million dollars and the interest rate is 3.5%.
```

Upload it and click **Analyze Document**. Below the extracted pages, you should
see three **Detected Sections** (2.1, 2.2, 3.4) and four **Section References**
(9.4, 2.1, 3.1, 3.2). Each result includes its PDF page number. The heading labels
themselves should not appear as references, and the amounts should not appear
as headings. **Potential Broken References** should list 9.4, 3.1, and 3.2
with their page numbers, original text excerpts, a “Not found” status, and an
explanation. These are potential errors because a heading may have been missed.

## Test potential broken references

The app first collects headings from **all pages**, then checks each reference.
Section numbers must match exactly: 2.1 does not match 2.10, 2.01, or 2.
Repeated missing references are listed separately to preserve every page location.

Try these variations of the sample PDF:

1. Add standalone headings `Section 9.4 General Terms`, `Section 3.1 Disclosure`,
   and `Section 3.2 Permitted Uses`. Upload the new PDF. You should see
   “No broken references detected among recognized sections.”
2. Put those added headings on a later page. References to them should still pass.
3. Replace `Section 9.4 General Terms` with `Section 9.40 General Terms`.
   The reference to 9.4 should show “Not found” because the numbers differ.
4. Repeat `See Section 9.4.` on two pages while its heading is absent.
   Both page locations should appear in the potential broken references list.
5. Remove all numbered headings but keep the reference sentences. You should
   see a warning that validation is unreliable, with no references labeled broken.
   The existing **Section References** list should still show the references.

After editing the PDF, upload the updated file and click **Analyze Document** again.

## Test defined terms and candidate uses

Create a PDF from this text:

```text
Section 2.1 Definitions
"Investor" means any person who subscribes for Interests.
“Closing Date” shall mean the date specified in the notice.
"Business Day" means a day other than Saturday or Sunday.
The Closing Date must be a Business Day.
Payment is due on the Closing Date.
See Section 2.1.
```

Upload it and click **Analyze Document**. The new **Defined Terms** list should
show Investor, Closing Date, and Business Day. **Candidate Term Uses** should show
Closing Date twice and Business Day once. Each result includes its page number
and a short excerpt. The quoted definition labels themselves are excluded from
candidate uses; uses of other terms inside a definition's body can still be listed.

Move the usage sentences to a second page to check page numbers. You can also
add `The Notice Period ends tomorrow.` to see a candidate that has no detected
definition. It should also appear as a potential issue in **Potentially Undefined
Terms**, with the status “Definition not found”. Existing section and cross-reference
results remain visible.

## Test potentially undefined terms

Create a PDF from this text:

```text
Section 2.1 Payment Terms
“Closing Date” shall mean the date specified in the notice.
The Closing Date is tomorrow.
The Final Closing Date may change.
The Notice Period ends tomorrow.
Refer To Section 2.1 for details.
```

After uploading, **Potentially Undefined Terms** should show Final Closing Date
and Notice Period, each with its page, original excerpt, and “Definition not found”
status. Closing Date matches its definition exactly. The recognized Payment Terms
heading and the numbered section reference should not become term findings, though
they may remain in the **Candidate Term Uses** list.

Try these variations:

1. Add `"Final Closing Date" means the amended date.` and
   `"Notice Period" means the time allowed for notice.` on a later page.
   You should see “No potentially undefined terms detected among recognized terms.”
2. Repeat `The Notice Period ends tomorrow.` on multiple pages while its
   definition is absent. Every detected occurrence and page should be retained.
3. Remove all definitions but keep the usage sentences. The app should warn that
   validation is unreliable and avoid automatically flagging candidates.
4. Upload a PDF containing only `"Investor" means a subscriber.`. You should
   see “No candidate term uses to validate.”

Complete names are compared case-sensitively after extra whitespace and surrounding
straight/curly double quotes are removed. Final Closing Date does not match Closing
Date, and Business Days does not match Business Day. A definition on any page counts.
Every finding is a **potential issue**, because the limited detector may miss a
definition. The app does not establish that a term is definitively undefined.

## Run automated tests

To run the automated tests, activate your virtual environment and run this
command from the project folder. The review dashboard tests also require Node.js
18 or newer installed locally (`node --version` checks this). Node.js is needed
only to run these JavaScript tests; the application still runs with Python and
plain browser JavaScript:

```sh
python -m unittest -v
```

The tests create sample PDF data in memory; no test documents are stored.
Claude tests use fake credentials and a mocked SDK client, ignore your local
`.env`, and block network connections. The tests run offline with no paid requests.

## Claude preparation (Milestone 4A)

The [official Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
and `python-dotenv` are included in `requirements.txt`. If you already have the
app installed, update its packages from the project folder:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
```

An API key is **optional for this milestone**. The PDF app and all tests work
without one. No Claude calls are connected to the webpage or PDF uploads.

To prepare local configuration:

1. If you do not already have a `.env` file, run `cp .env.example .env` in the
   project folder. Skip this command if `.env` already exists so you keep its settings.
2. Open `.env` in your local text editor. Replace `your_key_here` with your own
   Anthropic API key. Keep the key private; do not paste it into chat, screenshots,
   source code, or the README.
3. Leave the model setting as `ANTHROPIC_MODEL=claude-sonnet-5-5`, or change it
   later if you choose a different model.

The example file contains:

```dotenv
ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_MODEL=claude-sonnet-5-5
```

`.env` is excluded by `.gitignore`; `.env.example` contains only a placeholder.
Existing environment variables take priority over `.env` settings. A missing or
blank model setting defaults to `claude-sonnet-5-5`. Missing, blank, and placeholder
keys are treated as unconfigured.

Check configuration safely with:

```sh
python -c "from ai_reviewer import get_configuration_status; print(get_configuration_status())"
```

This prints only `api_key_configured` (True or False) and the model name. It never
prints the key or contacts Anthropic. True means a key value is present; it does
not verify the key, account balance, or model availability. Those are not tested
in this milestone.

`send_text_to_claude()` is a small function prepared for a future milestone.
**Do not call it with a real key yet:** doing so would send its supplied text to
Anthropic and could incur charges. Only mocked tests exercise it here. There is
no active AI analysis, and the browser results stay
the same. You can upload a PDF as before to check the existing features.

## Contract analysis preparation (Milestone 4B)

This milestone prepares analysis of **potential contradictions** between clauses
and **ambiguities** in terms or obligations. It runs only in offline tests with
mocked Claude responses. Milestone 4D-1 below adds a **demo-only** review button; no uploaded
document is sent to Anthropic.

The proposed flow is:

1. `analyze_contract(pages)` accepts the page dictionaries already produced by
   the PDF reader: each contains `number` and `text`.
2. `format_document_pages()` adds markers such as `[Page 1]` and `[Page 2]`.
   It keeps the extracted text unchanged, including blank pages in readable documents.
3. A separate system prompt asks Claude to act as a document quality-control
   assistant, not legal counsel. It limits analysis to the supplied contract,
   requests verbatim supporting quotes, and instructs Claude to treat document
   content as untrusted data rather than instructions. It asks for no findings
   when evidence is insufficient. The system prompt uses the separate `system`
   parameter described in the [Anthropic Messages API documentation](https://platform.claude.com/docs/en/api/messages/create).
4. Claude would return JSON with a `findings` list. Each finding has an id,
   category, title, cautious explanation, evidence quotes with page numbers,
   and an `unverified` status. Contradictions need at least two evidence items;
   ambiguities need at least one.
5. `parse_analysis_response()` checks the response structure. It rejects malformed
   JSON, duplicate JSON fields or finding ids, unknown categories, missing or empty
   fields, insufficient evidence, and invalid or nonexistent page numbers. Any
   invalid finding rejects the entire response with `ValueError`. It does not
   silently turn invalid output into “no findings”.

Example response for a synthetic contract with different payment deadlines:

```json
{
  "findings": [
    {
      "id": "F1",
      "category": "contradiction",
      "title": "Potentially inconsistent payment deadlines",
      "explanation": "These clauses may specify different deadlines for the same payment.",
      "evidence": [
        {"quote": "Payment is due within 10 days.", "page": 1},
        {"quote": "Payment is due within 30 days.", "page": 2}
      ],
      "status": "unverified"
    }
  ]
}
```

No findings is represented as `{"findings": []}`. That means the response
reported no supported potential issues; it does not establish that the contract
has no problems.

**The AI parser leaves all findings unverified.** A valid JSON shape or an existing page number
does not prove that a quote appears on that page, that two quotes are from distinct
clauses, or that an interpretation is correct. A fabricated quote or a quote
assigned to the wrong existing page can still pass structure validation. Quote
verification is a separate offline step implemented in Milestone 4C below.
Prompt instructions alone cannot guarantee model accuracy or resistance to
instructions embedded in a document.

To test this preparation safely, use the existing test command:

```sh
source .venv/bin/activate
python -m unittest -v
```

The analysis tests replace the Anthropic client with a mock and use synthetic
text, fake credentials, and a network block. No real key is needed. The previous
PDF, section, term, and configuration tests are included.

**Do not invoke `analyze_contract()` or `send_text_to_claude()` with real credentials
in this milestone.** These callable functions are future API entry points and
would make a paid request if called with a real key. The model defaults to
`claude-sonnet-5-5`, as in Milestone 4A. Real model behavior and availability have
not been tested. The preparation sends a whole document in one request and has
no long-document splitting; response output is capped at 2048 tokens. Large
contracts or truncated responses may fail, and JSON validation does not assess
completeness. There are no automatic legal conclusions or recommendations.

## Independent quote verification (Milestone 4C)

`quote_verifier.py` checks whether evidence actually occurs on the claimed page
of the **original extracted PDF text**. It needs no API key and has no network
or Anthropic dependencies. Milestone 4D-1 below connects it to the mock review panel.

Pass the parsed analysis and the original `pages` list to:

```python
from quote_verifier import verify_findings

verified_analysis = verify_findings(parsed_analysis, pages)
```

This call does not run AI analysis. For offline testing, `parsed_analysis` can
come from `parse_analysis_response()` applied to a synthetic JSON response.
Use the original page texts, not the prompt text with added page markers.

For example, a quote `Payment is due within 10 days.` passes when page 1 contains
`Payment is due\nwithin   10 days.`. The same quote fails if assigned to page 2
when it appears only on page 1. Changing `10` to `30` or removing punctuation
also fails.

The verifier collapses runs of whitespace (including line breaks and tabs) into
single spaces and trims surrounding whitespace. It never changes words, case,
punctuation, or numbers. Matching is literal, with boundaries to avoid finding
quoted words or numbers inside longer words or numbers. It never searches other
pages to repair a wrong page assignment or combines text across pages.

It returns an annotated **copy** of the analysis; it does not change the inputs:

- Each evidence item keeps its original `quote` and `page`, and gains
  `verification_status`, `failure_reason` (null when successful), and `match_count`.
- A finding's `status` becomes `verified` only when all its evidence items pass.
  Contradictions require at least two items; ambiguities require at least one.
- Any failed item or insufficient evidence makes the finding's status
  `verification_failed`. `failure_reasons` explains the problems, and the finding
  stays in the returned list in its original order.
- Repeated quotes report their number of matches on the claimed page, including
  overlapping matches. No unique position or original PDF coordinate is claimed.

**Verified means quote presence only.** It does not mean a contradiction is real,
an ambiguity is legally significant, or a human has approved the finding. Any
existing human review fields are preserved without being changed. Two evidence
items quoting the same passage may both pass; this does not establish that they
refer to different clauses.

Known limits: verification relies on extracted text, whose layout or reading
order may differ from the visible PDF. Hyphenated line breaks, different straight
or curly quotes, OCR errors, and other character differences are not repaired and
can cause a failed match. No fuzzy matching or semantic comparison is used.

Run all offline tests, including the previous milestones, from the project folder:

```sh
source .venv/bin/activate
python -m unittest -v
```

No real API calls or document transfers are involved. The AI entry points remain
inactive in the app; do not call them with real credentials in this milestone.

## Mock AI review in the browser (Milestone 4D-1)

This is **Demo Mode — No Anthropic API calls**. The new button shows predefined
mock AI responses, not newly generated analysis. No API key is required. There
is no browser paid-mode toggle. Milestone 4D-2A adds a separate real-AI endpoint
that remains disabled by default on the server.

From Terminal in your cloned repository folder, run:

```sh
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Then test this exact flow:

1. Open http://127.0.0.1:8000/ and reload if the app was already open.
2. Click **Download the synthetic demo contract** above the upload button. This
   downloads `legal-reviewer-demo.pdf`, generated in memory by the local server.
3. Choose that downloaded PDF and click **Analyze Document**. The extracted page
   and all previous section and term checks should remain visible under
   **Rule-based Checks**. The **AI Review Findings** panel and **Analyze with AI
   (Demo)** button appear only after a successful upload.
4. Click **Analyze with AI (Demo)**. Expect three mock findings:
   - A potential contradiction comparing the 10-day and 30-day payment clauses.
     Both quotes and the overall finding are green and marked `verified`.
   - An ambiguity about “promptly”. Its quote and overall status are `verified`.
   - An intentionally invented quote about cancellation. Its quote and overall
     status are red and marked `verification_failed`; a failure reason and zero
     matches are displayed. This is a demonstration of rejecting fabricated evidence.
5. Check that each result includes its category, title, explanation, quotes,
   claimed pages, individual verification statuses, and overall status. The
   panel explains that verified evidence does not establish a legal conclusion.
6. Select a different readable PDF and process it. Previous demo results clear.
   Clicking the demo button should return no findings and explain that the
   document does not match the synthetic fixture. This does **not** mean the
   document has no issues; no AI analysis was performed.
7. To test a connection failure, stop the server with **Control+C** after an
   upload, then click the demo button. The panel should show a connection error
   while keeping the extracted text and rule-based results. Restart the server
   with the command above and try the demo button again.

The fixture is one page containing exactly this text:

```text
Legal Reviewer Demo Contract
Section 1.1 Payment
Payment is due within 10 days.
Section 1.2 Payment Deadline
Payment is due within 30 days.
Section 1.3 Notice
Notice must be sent promptly.
```

The backend compares the **entire extracted document**, including its one-page
layout, against this fixture, allowing whitespace differences only. Matching
filenames or a few matching quotes are insufficient. Changed words, extra clauses,
page headers, or extra pages receive an empty mock result. A different PDF with
exactly the same extracted page text is equivalent for this demo.

The browser sends the extracted pages to the local `/ai-review-demo` endpoint.
It calls `review_contract_demo()`, which selects the fixture response or an empty
response, then reuses `parse_analysis_response()` and `verify_findings()`. It
never calls the Anthropic client or the real analysis functions, even with an API
key configured. Malformed mock output or processing errors return a generic error
without document contents or credentials. There is no fallback to real AI.

Page text is kept in browser memory for the current flow and in server memory
only for each request. A new file selection, new upload, or page reload clears
the demo state. There is no server document cache, localStorage, database, or
application save to disk. Upload and demo responses use `Cache-Control: no-store`;
the app does not log document text. The existing PDF upload may use temporary
multipart files, which are closed and cleaned up as described below. The sample
download is a synthetic file you intentionally save, not a saved upload.

Run the offline suite:

```sh
python -m unittest -v
```

The demo tests block network connections and assert that the SDK client, real AI
entry points, and credential loader are never invoked. They cover the sample
download → PDF extraction → mock review → quote verification flow, unrelated
documents, invalid input, oversized requests, malformed mock output, processing
errors, and independent requests. Demo JSON requests have a 10 MB size limit.

Limitations: the mock results are fixed, so this does not test Claude's reasoning
or analyze arbitrary contracts. Verification still confirms quote presence only,
with the whitespace and extraction limitations described above. Milestones 5A
and 5B below add human decisions, wording edits, and evidence highlighting.

## Real Claude preparation, disabled by default (Milestone 4D-2A)

**No paid requests are authorized or performed in this milestone.** Real review
is gated by a server-only flag, `ENABLE_REAL_AI`. If absent or not `true`, all real
API entry points refuse execution before creating an Anthropic client. Browser
requests cannot enable this flag, supply an API key, or increase the output cap.
The example configuration keeps it disabled:

```dotenv
ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_MODEL=claude-sonnet-5-5
ENABLE_REAL_AI=false
AI_MAX_INPUT_BYTES=20000
```

`AI_MAX_INPUT_BYTES` is the maximum UTF-8 byte length of the complete document
text with page markers; it defaults to 20,000. Oversized text is rejected before
any API client is created, rather than silently truncating the contract. This is
a byte limit, not an estimate of tokens or cost. Output is capped at 2,048 tokens,
SDK timeout is 30 seconds, and `max_retries=0` disables SDK retries as documented
in the [official Anthropic SDK guidance](https://github.com/anthropics/skills/blob/main/skills/claude-api/python/claude-api/README.md).
SDK/transport logs are suppressed during calls so debug logging does not expose
document text or credentials. Do not add logging of documents or API errors.

After a successful PDF upload on localhost, a separate **Analyze with Claude
(Real AI)** button appears under **Claude Review Findings (Real AI)**. It does not
run on page load, upload, or demo review. The adjacent configuration message shows
whether server execution is enabled; reading configuration never contacts Claude
or exposes the API key. Before submitting, the button opens a confirmation dialog
explaining document transfer to Anthropic and possible charges. Cancel sends
nothing. Confirming while the server is disabled still returns a disabled message
without contacting Anthropic. The free demo button is unaffected.

The server permits the real controls only for loopback clients and local hostnames.
The real endpoint also requires the matching local Origin header and a literal
`confirmed: true`. These are development safeguards, not production authentication:
do not expose this app publicly or enable paid mode behind a reverse proxy.

For a future permitted request, `review_contract_real()` reuses `analyze_contract()`
and the structured parser, then passes every quote to `verify_findings()` before
returning results. Failed quotes remain visible. Real results are shown in their
own panel and never replace the demo or rule-based results. Missing keys, rejected
credentials, unavailable models, rate limits, connection failures, timeouts,
truncated or malformed responses, and other failures produce safe messages without
raw API error text or credentials. There is no automatic retry or fallback.

Safe testing now:

1. Keep `ENABLE_REAL_AI=false` (or leave it unset) and run the local app as above.
2. Upload the synthetic demo PDF and confirm the free demo still works.
3. Check the real panel says **Server execution: disabled**.
4. Click the real button and choose **Cancel**; no real-review submission occurs.
5. You may also confirm while the server is disabled: expect the disabled message,
   with no Anthropic request. Do not change the flag during this milestone.
6. Run `python -m unittest -v`. Tests ignore `.env`, use only fake credentials,
   mock the SDK, and block network access. Enabled-mode cases exist only in isolated
   mocked test environments, never as activation of your running server.

Before the **first paid test**, wait for explicit approval. Then, in a future
authorized step:

1. Stop the local server. Use a small synthetic contract whose text you are
   authorized to send, and decide your spending limit in advance. The token cap
   does not impose an account-level spending limit.
2. Configure your own key privately in `.env`, confirm your Anthropic account has
   access to `claude-sonnet-5-5`, and choose an appropriate `AI_MAX_INPUT_BYTES`.
   Keep `.env` excluded from Git. Never paste the key into chat or the browser.
3. Only after approval, change the local `.env` line to `ENABLE_REAL_AI=true`.
   Existing shell environment variables override `.env`; make sure you understand
   those settings. This README describes activation; this milestone does not do it.
4. Start the server bound to loopback:
   `python -m uvicorn main:app --host 127.0.0.1 --port 8000`.
   Upload the small synthetic PDF and check the real panel reports enabled.
5. Click the real button once, read the disclosure, and confirm once. Inspect the
   returned quote verification and your Anthropic usage before submitting again.
6. Stop the server, restore `ENABLE_REAL_AI=false`, and restart it. Check the panel
   reports disabled again.

Limitations: a timeout, browser cancellation, file change, or page reload does not
guarantee cancellation of a request already accepted by Anthropic; charges may
still apply. The timeout is an SDK timeout, not a guarantee of a strict overall
wall-clock deadline. There is no persistent document storage, but a future
approved real request will disclose text to Anthropic. Real model behavior, model
availability, and costs have not been tested here. Quote presence does not establish
legal correctness. Milestones 5A and 5B below add human decisions, wording edits,
and evidence highlighting.

## Human review dashboard (Milestone 5A)

After a successful upload, **Review Findings** appears above the extracted pages.
It combines potential broken references, potentially undefined terms, and AI
contradiction/ambiguity findings after you explicitly run an AI review. Existing
result sections remain visible. Each item shows a stable ID for this review, its
source (rule-based, synthetic demo AI, or real Claude), category, title, explanation,
page numbers, supporting text, and evidence verification where applicable.

All findings start **pending**. Click **Accept** or **Reject** to record your own
decision. You can change that decision, or use **Mark pending** to return an item
to the review queue. The **Total findings**, **To review**, **Accepted**, and
**Rejected** counters update immediately. No decision is sent to a server, and
clicking a decision button never calls Claude.

AI evidence verification and human review are separate. AI findings with failed
or unverified evidence cannot be accepted; the Accept button is disabled with an
explanation, and the JavaScript decision function also rejects acceptance. They
remain available for rejection or further review. Rule-based findings show that
quote verification was not applied; they remain potential issues for your judgment.
A verified quote alone never accepts a finding or establishes legal correctness.

**Everything is kept in browser memory only.** Reloading the page, selecting
another file, or starting a new upload clears all findings and decisions, even
when reuploading the same PDF. Old AI responses are ignored after a new review
starts. IDs are unique and stable within the current review, not permanent IDs.
Rerunning the same AI mode replaces its batch without accumulating duplicates:
identical findings retain their IDs and decisions, while changed findings become
new pending items. Demo and real results have independent decisions. A failed
rerun leaves the last successful batch in the dashboard.

Test without spending API credits:

1. Start the app with real AI disabled for this process (this does not edit `.env`):

   ```sh
   source .venv/bin/activate
   ENABLE_REAL_AI=false python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

2. Open http://127.0.0.1:8000/ and reload to load the new frontend. Download and
   upload the synthetic demo PDF, then click **Analyze with AI (Demo)**.
3. Scroll to **Review Findings**. Expect three pending items and counters
   **Total: 3**, **To review: 3**, **Accepted: 0**, **Rejected: 0**.
4. Accept the payment contradiction and reject the intentionally invented-evidence
   finding. Expect **To review: 1**, **Accepted: 1**, **Rejected: 1**. The invented
   evidence item's Accept button remains disabled, even after rejection.
5. Reject the previously accepted item, then accept it again or mark it pending.
   Confirm the ID stays the same and the counters follow your decisions.
6. Run the demo again. Unchanged findings keep their IDs and decisions, and the
   total stays three. No real Claude button is needed for this test.
7. To test rule-based review, create a PDF with this text using TextEdit → Print
   → PDF → Save as PDF, then upload it:

   ```text
   Section 1.1 Payment
   "Business Day" means a day other than Saturday or Sunday.
   The Notice Period ends tomorrow.
   See Section 9.4.
   ```

   The dashboard should show two new pending rule-based issues (Section 9.4 and
   Notice Period). Prior demo findings and decisions must be gone. These entries
   can be accepted or rejected, with their original excerpts and pages visible.
8. Reload the page to confirm that decisions and uploaded results disappear.

Run all automated tests with Node.js 18+ available and the Python environment active:

```sh
node --version
python -m unittest -v
```

`test_review.py` runs the actual JavaScript module and HTML event handlers with
synthetic data, a small DOM stand-in, and mocked fetch responses. No server or
external network is needed for these tests; existing Anthropic tests remain mocked.

Limitations: decisions have no permanent storage or audit history, and independent
tabs do not share them. Milestones 5B and 6 below add wording edits, evidence highlighting, and
plain-text counsel drafts. No automatic email sending is implemented. Accepted demo findings are still synthetic test results. Findings from
different sources are kept separate, so related rule and AI issues may appear
more than once. IDs and decisions are not suitable for permanent records yet.

## Editing findings and highlighting evidence (Milestone 5B)

In **Review Findings**, click **Edit** to change only a finding's title and
explanation. **Save** updates the wording immediately; **Cancel** discards the
unfinished draft. Both fields must contain text. You can edit one finding at a
time. While editing, that finding's decision buttons are disabled until you save
or cancel.

Saving an accepted finding returns it to **pending**, even if you save the same
wording, so you explicitly approve the final wording. Pending and rejected
findings retain their decision. Changed wording is labeled **Human-edited wording**;
expand **Original AI-generated wording** (or **Original rule-based wording**) to
compare it with the original. Source quotes, page numbers, verification results,
and finding IDs cannot be edited. Failed evidence still blocks acceptance.

Each nonempty supporting quote has a **View in document** button. It searches
only the claimed extracted page, scrolls there, and highlights the exact source
text in yellow. Whitespace and PDF line breaks may differ, but words, numbers,
punctuation, and capitalization must match. All matching occurrences on that
page are highlighted; multiple matches are explicitly reported without claiming
a unique location. If no match exists, a message explains that nothing was
highlighted. The previous highlight is cleared when another quote is selected.
Highlighting never searches an AI explanation or edited wording.

### Safe browser test

1. From your repository folder, activate the existing environment and start the
   server with paid execution disabled for this session:

   ```sh
   source .venv/bin/activate
   ENABLE_REAL_AI=false python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

   If the server is already running, stop it with Control-C first, then run the
   command above. Open http://127.0.0.1:8000/ and reload the page.
2. Download the synthetic demo contract using the link on the webpage, upload
   it, click **Analyze Document**, then **Analyze with AI (Demo)**. These steps
   make no Anthropic requests.
3. In **Review Findings**, accept the payment contradiction. Click **Edit**,
   change its title and explanation, and click **Save**. Confirm the new wording
   appears, the ID and evidence are unchanged, **Accepted** returns to zero,
   and **To review** returns to three. Expand the original wording to compare.
4. Accept the revised finding, edit it again, and click **Cancel**. Confirm the
   saved wording and acceptance remain unchanged.
5. Click **View in document** for each payment quote. Expect Page 1 to scroll
   into view with the selected 10-day or 30-day sentence highlighted. The page
   text itself stays unchanged.
6. Click **View in document** for the intentionally invented quote. Expect a
   clear no-match message and no highlight. Edit and save that finding; its
   Accept button must remain disabled.
7. To test repeated text, make a PDF in TextEdit with the following text using
   Print → PDF → Save as PDF, then upload it:

   ```text
   Section 1.1 Payment
   See Section 9.4.
   See Section 9.4.
   ```

   Click **View in document** on either broken-reference finding. Both matching
   excerpts should be highlighted, with a message that the quote does not
   identify a unique location. Old demo findings, edits, and decisions disappear.
8. Reload to confirm all findings, decisions, edits, and highlights disappear.

### Offline automated tests

With the Python environment active and Node.js 18+ available:

```sh
python -m unittest -v
```

Milestone 5B added **17 tests** for saving and
canceling edits, preserving original wording and evidence, resetting acceptance,
failed-evidence protection, page navigation, exact and repeated quote matching,
safe plain-text rendering, and clearing state for another upload. The Anthropic
responses and frontend requests used by tests are mocked; tests make no real API
requests.

Limitations: edits and decisions live only in this browser tab's memory and are
lost on reload or a new upload. There is no edit history, export, or permanent
record. Unchanged AI reruns preserve saved edits and decisions; changed results
become new pending findings. Human edits appear in the unified dashboard; the
older source-specific result lists continue to show the original generated
wording. Highlighting uses extracted text, not the PDF's visual layout. A
truncated rule-based excerpt or altered punctuation/hyphenation may not match;
there is no fuzzy matching or cross-page search. Overlapping matches share one
highlighted span, while the occurrence count reports all matches. Quote presence
does not establish a correct legal interpretation or human acceptance.

## Draft questions for counsel (Milestone 6)

In **Review Findings**, click **Draft Questions for Counsel** after accepting the
findings you want counsel to review. The app builds a draft entirely in JavaScript,
without another Claude request. It includes the specified subject, greeting,
introduction, one numbered clarification question per eligible accepted finding,
a brief thank-you, and the closing **Best regards, Document Review Team**.
Milestone 6A polishes the email template without changing eligibility or draft
controls. The subject is **Questions Regarding Draft Agreement**. Each issue
shows the saved title and explanation, source quotations with page references,
and a concise, category-specific question. The template does not infer deadlines,
legal conclusions, section numbers, or answers.

Only accepted findings are eligible. Pending and rejected findings are excluded.
The latest saved title and explanation are used; unfinished finding edits must
be saved or canceled first. Explanations and source evidence remain separate
internally; email quotations use quotation marks and page references. Technical
labels and provenance stay in the dashboard and internal review state, rather
than appearing in the email. AI evidence must have
passed verification, and its quotes are checked again on their claimed extracted
pages before inclusion. Contradictions require at least two passing quotes.
Failed, unverified, incomplete, or unsupported AI findings are excluded even if
their decision is changed to accepted outside the normal UI. Rule-based findings
retain their original pages and excerpts. Their internal verification status
remains separate from AI evidence verification. Section references appear when present in the
finding wording or source excerpt; the generator does not infer extra sections.
Demo findings remain identified in the dashboard; the email omits demo and
verification labels, so use the demo contract only for testing.

You can edit the complete email in **Editable draft email**. **Copy to Clipboard**
copies the current text, including your manual edits. **Download .txt** saves the
same text as `counsel-questions.txt`. No email is sent, and no email service is
connected. If clipboard permission is unavailable, select the text and copy it
manually with Command-C (Mac) or Control-C.

When any saved finding or review decision changes, an existing draft is marked
**Potentially outdated**. Copy and download are disabled until you regenerate.
Manual draft edits are retained. Newly accepted findings are never silently
added. Click **Draft Questions for Counsel** again to explicitly replace the
current draft, including manual edits, with the latest eligible accepted findings.
If none are eligible, a clear message appears and any previous draft is retained
for inspection rather than replaced by an empty letter. Uploading/selecting a
new PDF or reloading clears the draft along with the current review.

### Safe browser test

1. In your repository folder, activate the environment and start the server with
   real AI execution disabled for this session. Stop an existing server with
   Control-C first if necessary:

   ```sh
   source .venv/bin/activate
   ENABLE_REAL_AI=false python -m uvicorn main:app --host 127.0.0.1 --port 8000
   ```

2. Open http://127.0.0.1:8000/ and reload. Download/upload the synthetic demo
   contract, click **Analyze Document**, then **Analyze with AI (Demo)**.
3. Click **Draft Questions for Counsel** before accepting anything. Expect a
   message explaining that there are no accepted, eligible findings.
4. Edit and save the payment finding's title or explanation, then accept it.
   Reject the invented-evidence finding and leave the notice finding pending.
5. Draft again. Expect exactly one numbered question with your saved wording and
   both payment quotes on Page 1. Neither rejected nor pending findings belongs
   in the draft. Confirm the professional closing and absence of technical
   labels such as Demo AI or Reviewer-approved explanation in the email.
6. Add a manual note in the draft textarea. Copy or download it and confirm your
   note is present. The downloaded file should be plain text, not HTML.
7. Accept the notice finding. Confirm the existing draft and your note remain
   unchanged, the outdated warning appears, and copy/download are disabled.
8. Draft again. Expect two numbered questions; your manual note is replaced only
   by this explicit regeneration action. Editing an accepted finding likewise
   marks the draft outdated and requires saving, accepting, and regenerating.
9. Upload another PDF or reload. Confirm the old draft is gone. The entire test
   uses only the free mock mode; do not click the real-Claude button.

### Offline tests and limitations

With the Python environment active and Node.js 18+ available:

```sh
python -m unittest -v
```

All **184 tests pass**, including the **16 counsel-draft tests** and **2 new
Milestone 6A template tests** for accepted-only
selection, latest saved edits, numbering and structure, original evidence,
failed/unverified AI exclusions, quote rechecks, manual copy/download content,
outdated drafts, new uploads, clipboard failures, and plain-text injection safety.
The template tests also check dynamic issue wording, preservation of internal
evidence and provenance, category-specific questions, and removal of internal
labels. Tests mock browser requests, clipboard/download operations, and
Anthropic calls.

This is a deterministic template, so questions are generic clarification requests.
It does not decide legal validity, invent answers, or assess the legal meaning of
reviewer wording. You must review the final email before sharing it. Manual email
edits are not automatically checked against findings or quotes. Drafts, findings,
and decisions have no database, permanent record, or audit history. A .txt download
is an explicit local export; no draft is otherwise saved to files or localStorage.
Browser clipboard access may depend on permissions. Quote checks retain the
existing PDF extraction and whitespace-matching limitations. Demo findings are
for testing and should not be used as substantive counsel questions.

Browser verification confirmed generation, editing, and outdated-draft behavior.
The embedded browser did not confirm a downloaded file during this milestone's
UI check. The .txt content and filename passed offline tests; please confirm the
actual download in your regular Mac browser using the steps above.

## Limits and document handling

- The size limit is 10 × 1024 × 1024 bytes and is checked in both the browser and server.
- Password-protected PDFs must be unlocked before upload.
- Image-only PDFs cannot be read because this version does not include OCR.
- A blank page in an otherwise readable PDF is still shown with a message.
- Uploads are read for extraction and closed after each request. FastAPI may
  temporarily spool larger uploads to disk; these temporary files are cleaned up
  when closed. Documents and extracted text are not saved by the application.
- Text is displayed in a basic reading order; complex PDF layouts may not keep
  their original formatting.
- Headings must occupy a single extracted line with a short title in title case
  or uppercase. Lowercase connecting words such as “of” and “and” are allowed.
  Bare headings require dotted numbers (such as 2.2); an explicit “Section” label
  also allows whole numbers. Wrapped headings and sentence-style titles may be missed.
- References require the word “Section” or “Sections”. Plural lists joined by
  commas, “and”, “or”, or “&” are supported, including line breaks within a page.
  Lettered subsections, numeric ranges, and references split across pages are not supported.
- Detection uses text patterns, not PDF font sizes or legal meaning. Ambiguous
  text and table-of-contents entries can resemble headings. Repeated occurrences
  are kept. Validation only checks targets against recognized headings; it does
  not prove that a reference is legally correct or incorrect. Missed headings can
  cause false warnings, and unrelated or table-of-contents headings may hide a
  missing target. If no headings are recognized, validation is skipped with a warning.
- Definitions must use matching straight or curly double quotes followed by
  “means” or “shall mean” and some definition text. Other wording such as “is
  defined as”, single quotation marks, and term names containing numbers are not supported.
- Candidate uses contain two to six consecutive capitalized words on one extracted
  line. Common prefixes such as “The” are removed. Single-word uses such as Investor,
  lowercase uses, and phrases with lowercase connecting words may be missed.
- Proper names and headings can resemble candidate terms. Recognized numbered
  headings and identifiable numbered section-reference phrases are excluded from
  term findings; unrecognized headings and proper names may still cause false warnings.
  Repeated occurrences are kept. Definition meanings and scope are not checked;
  definitions using other patterns or in another document may be missed. With no
  detected definitions, validation is skipped with a warning. PDF formatting and
  page breaks can affect detection. Excerpts keep
  original words and punctuation while joining whitespace and truncating long context.

Real Claude integration is disabled by default. The application uses deterministic
rules and a local mock AI demo. Only a future explicitly enabled and confirmed
real request would send document text to Anthropic. There is no document editing
or database storage.
