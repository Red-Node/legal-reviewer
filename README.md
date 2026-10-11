# Legal Reviewer

A minimal PDF text reader built with Python, FastAPI, PyMuPDF, and plain HTML,
CSS, and JavaScript. It extracts text by page and uses deterministic rules to
detect numbered section headings and explicit section references, then flag
references whose targets were not found among recognized headings. It also detects
explicit term definitions and candidate uses of capitalized multi-word terms,
then flags potential issues when a complete term's definition was not found.

## Files

- `main.py`: serves the webpage and handles PDF uploads and text extraction.
- `detection.py`: identifies headings and references, then compares exact section numbers.
- `terms.py`: detects definitions and candidate uses, then checks for potential missing definitions.
- `ai_reviewer.py`: reads Claude configuration and prepares contract analysis with JSON validation; inactive in the app.
- `.env.example`: shows the local configuration variable names without a real key.
- `index.html`: contains the upload form, styling, and JavaScript that displays results.
- `test_detection.py`: tests detection, potential broken references, and existing PDF uploads.
- `test_terms.py`: tests term detection, validation, and integration with existing PDF results.
- `test_ai_reviewer.py`: tests configuration, contract analysis, and response validation with a mocked client.
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
command from the project folder:

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
mocked Claude responses. There is no **Analyze with AI** button, and no uploaded
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

**All findings remain unverified.** A valid JSON shape or an existing page number
does not prove that a quote appears on that page, that two quotes are from distinct
clauses, or that an interpretation is correct. A fabricated quote or a quote
assigned to the wrong existing page can still pass structure validation. Quote
verification belongs to Milestone 4C and is deliberately not implemented here.
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
no long-document splitting; response output is limited to 4096 tokens. Large
contracts or truncated responses may fail, and JSON validation does not assess
completeness. There are no automatic legal conclusions or recommendations.

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

Claude integration is prepared but inactive. The application uses deterministic
rules and sends no uploaded documents to external APIs. There is no AI analysis,
document editing, or database storage.
