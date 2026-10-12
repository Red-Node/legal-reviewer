# Legal Reviewer

**Find potential contract issues, check the quoted evidence, and put a human in control of the final questions to counsel.**

Legal Reviewer is a hackathon prototype for document quality control, built with
FastAPI and vanilla JavaScript. It helps reviewers work through broken section
references, potentially undefined terms, and potential contradictions or
ambiguities. It does **not** provide legal advice or determine enforceability.

**[Try the public demo](https://legal-reviewer-production.up.railway.app)** ·
[Repository](https://github.com/Red-Node/legal-reviewer) ·
[Security audit](docs/SECURITY_AUDIT.md)

> **Use fictional or public sample documents only. Do not upload confidential or
> personal legal documents.** Uploads are processed on the hosting server. The
> public deployment is demo-only: real Claude requests are blocked server-side.

## The problem

Reviewing an agreement involves more than spotting unusual language. A reviewer
must locate the relevant provisions, distinguish a real concern from a false
alarm, and explain the question clearly to counsel. Copying unsupported AI
conclusions into an email can make that work less reliable.

Legal Reviewer separates three steps: **detection**, **source-evidence checking**,
and **human decision**. A quotation that exists in the document is still not a
validated legal interpretation. A finding is never automatically accepted.

## What it does

- Reads selectable PDF text and Word DOCX body paragraphs/tables.
- Detects numbered section headings and explicit section references.
- Flags references whose exact target number was not recognized.
- Detects limited explicit-definition patterns and capitalized multi-word uses;
  flags potential missing definitions when definitions were recognized.
- Provides a clearly labeled, free synthetic AI demo for one matching PDF fixture.
- Supports optional **local-only PDF Claude review**, behind server gates and a
  confirmation about document transfer and possible charges.
- Independently checks each AI supporting quotation against its claimed PDF page.
- Lets a human Accept, Reject, and Edit findings, and navigate to supporting text.
- Builds an editable counsel email from **accepted, eligible findings only**.
  Copy and Download .txt are explicit actions; nothing is emailed automatically.

| Capability | PDF | DOCX |
| --- | --- | --- |
| Extracted locations | Original PDF pages | Body paragraphs and table-cell paragraphs |
| Sections, references, defined-term checks | Supported | Supported for extracted text and typed numbering |
| Review decisions, wording edits, highlighting, counsel draft | Supported | Supported for rule-based findings |
| Synthetic AI demo | Only the exact demo fixture; other PDFs get an explained empty result | Unavailable |
| Real Claude analysis | Optional local development only; blocked publicly | Unavailable |
| AI quotation verification | Exact text on the claimed PDF page | No DOCX AI findings; location-based offline helper is available |

DOCX paragraph/table identifiers are **not page numbers**. The server and UI do
not reinterpret them as PDF pages. Legacy `.doc` and macro-enabled `.docm` files
are unsupported.

## End-to-end workflow

1. Upload a fictional PDF or DOCX and click **Analyze Document**.
2. Read the extracted text and rule-based results, including validation warnings.
3. For the synthetic demo PDF, explicitly click **Analyze with AI (Demo)**.
   The demo returns three predefined findings, including a deliberately invented
   quotation. These are demonstration results, **not benchmark detection**.
4. Examine each finding and its source evidence. **View in document** highlights
   exact source text, reports repeated matches, or explains why no match was found.
5. Accept or reject each finding. Edit its title/explanation if needed. Saving an
   edit to an accepted finding returns it to pending for explicit reapproval.
6. Click **Draft Questions for Counsel**. Only accepted, eligible findings are
   included, using the latest saved wording and original evidence locations.
7. Edit the draft, then copy or download it. Changed findings mark an existing
   draft outdated; regeneration is explicit and never silently overwrites edits.

All decisions and drafts live in browser memory. Reloading the page or uploading
another document clears them. Failed or unverified AI evidence cannot be accepted
or included in the draft; evidence status and human decision remain separate.

## A five-minute judge demo

### Synthetic PDF AI flow

1. Open the [public demo](https://legal-reviewer-production.up.railway.app).
2. Click **Download the synthetic demo contract** and upload the downloaded PDF.
3. Click **Analyze Document**, then **Analyze with AI (Demo)**.
4. Check the verified payment/notice quotations and the intentionally failed
   invented quotation. Accept should be unavailable for the failed finding.
5. Edit and accept one eligible finding, then generate a counsel draft. Confirm
   it includes only your accepted finding and saved wording.

This flow needs no API key and makes no Anthropic request. The public demo does
not analyze arbitrary contracts with real AI.

### DOCX rule-based flow

Create a fictional Word document with these separate paragraphs. Type the
section number explicitly rather than using Word automatic numbering:

```text
Section 1.1 — Payment Terms
"Business Day" means Monday through Friday.
Use the Delivery Window pursuant to Section 9.9.
```

Add a table cell containing `See Section 1.1.` and save as **Word Document
(.docx)**. Upload it and click **Analyze Document**. Expect a potential missing
Section 9.9 and a potentially undefined Delivery Window, both at Paragraph 3.
The table reference to Section 1.1 should resolve. Test highlighting, review
edits, and a counsel draft with paragraph/table labels. DOCX AI controls are
unavailable with an explicit explanation.

For a PDF version, print the fictional text to PDF with selectable text. Do not
use confidential agreements to evaluate the prototype.

## Architecture and stack

| Component | Responsibility |
| --- | --- |
| `main.py` | FastAPI routes, bounded uploads, PDF extraction, response assembly, local/public AI guards |
| `docx_reader.py` | In-memory DOCX package validation and document-order paragraph/table extraction |
| `detection.py`, `terms.py` | Deterministic section/reference and term checks |
| `ai_reviewer.py` | Free synthetic demo, local Claude configuration, production prompt, structured response parser |
| `quote_verifier.py` | Independent exact-text evidence checks; no AI or semantic similarity |
| `index.html`, `review.js` | Plain browser UI and in-memory decisions, edits, highlighting, counsel drafts |
| `benchmark/` | Fictional contract, ground truth, reproducible offline evaluation tools and tests |
| `railway.json` | Public-demo start command and health-check configuration |

Python 3.13 is selected for Railway. Dependencies include FastAPI/Starlette, Uvicorn,
PyMuPDF, python-docx/lxml, python-multipart, the official Anthropic SDK, and
python-dotenv. There is no React build, database, account system, or email
integration. Node.js 18+ is needed **only for offline JavaScript tests**.

The server returns extracted text to the browser and keeps no document cache.
AI review submits the current PDF page text in a separate request. Only an
explicitly enabled and confirmed **local real-review** action transfers text to
Anthropic; the public demo cannot do this.

## What quotation verification means

The AI must provide structured findings with supporting quotes and original PDF
page numbers. The parser rejects malformed JSON, unsupported categories, missing
evidence, and invalid page references. Contradictions require at least two
evidence items.

The independent verifier collapses line breaks and repeated whitespace, then
looks for the exact quoted text on the claimed page. Words, punctuation, case,
and numbers are preserved; there is no fuzzy matching. Every evidence item must
pass for a finding to be marked `verified`. Repeated occurrences are counted
without claiming a unique location. Failed findings remain visible with reasons.

**Verified means text presence only.** It does not establish that two clauses
conflict, that an ambiguity matters legally, that extraction was complete, or
that the human has accepted the finding. A user can also alter browser state;
this is a review aid, not a tamper-proof audit trail.

## Run locally

From the folder containing your cloned repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
PUBLIC_DEMO_ONLY=true ENABLE_REAL_AI=false python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000/**. Leave that Terminal running; Control+C stops the
server. If the virtual environment already exists, activate it and skip creating
it again. The recommended command forces free demo mode even if local `.env`
settings previously enabled AI. `/health` returns only `{"status":"ok"}`.

On Windows, use `.venv\Scripts\activate` and set the two environment flags in
your shell before the equivalent Uvicorn command. Python 3.10+ meets the current
package minimums, but the deployment target and local audit used Python 3.13.

### Optional local AI configuration — not needed for the demo

| Setting | Purpose |
| --- | --- |
| `PUBLIC_DEMO_ONLY=true` | Blocks paid execution even when `ENABLE_REAL_AI=true`; required for public hosting |
| `ENABLE_REAL_AI=false` | Default-off real review gate; keep false for demo/testing |
| `ANTHROPIC_API_KEY` | Local real-review credential only; never required publicly or sent to the browser |
| `ANTHROPIC_MODEL` | Project default: `claude-sonnet-5-5`; actual access depends on the account |
| `AI_MAX_INPUT_BYTES` | Web review default: 20,000 UTF-8 document bytes including page markers |
| `PORT` | Railway-provided production listening port |

Real PDF review additionally checks the local address, same-origin request,
explicit confirmation, and the public-demo flag at the SDK boundary. Production
output is capped at 2,048 tokens with a 30-second timeout and zero automatic
retries. Oversized input is rejected without truncation. A timeout can still
incur charges. Do not enable real review as part of judging or security testing.

`.env.example` contains placeholders; real `.env` variants are ignored by Git.
Keep credentials out of source code, commands, screenshots, and reports. See
[the archived setup reference](docs/MILESTONE_NOTES.md) for earlier activation
procedures; those paid commands require separate explicit authorization.

## Offline tests and dependency checks

With the virtual environment active and Node.js 18+ installed:

```bash
python -m unittest -v
python -m unittest test_security -v
python -m pip check
```

The Milestone 9A suite has **383 passing offline tests**, including PDF/DOCX,
mocked Claude responses, evidence checks, browser-state workflows, benchmark
integrity, and focused security regressions. Tests use synthetic documents and
mocks; no paid requests are needed. Tests that inspect saved real captures skip
in a fresh clone where those intentionally local files are absent.

## Synthetic benchmark: methodology and honest results

The six-page [fictional services agreement](benchmark/fictional_services_agreement.pdf)
contains exactly 20 planted issues. Its [answer key](benchmark/answer_key.json)
is validated against actual extracted quotes/pages, missing reference targets,
and absent explicit term definitions. It is never included in the Claude prompt
or exposed through the app's HTTP routes. Making this repository public will,
intentionally, make the answer key available to repository readers.

The rule-based baseline uses unchanged production extraction and detection.
The AI component grades **one previously completed real Claude run**, not the
predefined demo findings. Each true positive needs the same category and issue
identity, relevant source provisions, and independently verified supporting
quotations. Matching is one-to-one; extra/grouped warnings do not earn extra
credit. Uncertain matches are reserved for human adjudication.

| Component/category | Planted | Predictions | TP | FP | FN | Precision | Recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Rule-based broken references | 6 | 6 | 6 | 0 | 0 | 100% | 100% |
| Rule-based undefined terms | 5 | 11 | 5 | 6 | 0 | 45.45% | 100% |
| Claude contradictions | 5 | 5 | 5 | 0 | 0 | 100% | 100% |
| Claude ambiguities | 4 | 5 | 3 | 2 | 1 | 60% | 75% |
| **Initial combined evaluation** | **20** | **27** | **19** | **8** | **1** | **70.37%** | **95%** |

The AI run produced 10 findings with all 24 supporting quotes verified. It missed
AM03, the standard for reasonable transition expenses. Two grouped AI ambiguity
warnings concern undefined terms and broken references; they are genuine source
observations but receive no additional ambiguity credit under this answer key.
Components remain separate; the combined result does not deduplicate or
recategorize them into a better score.

> **This is one synthetic contract and one AI run, not generalized accuracy.**
> Semantic grading was performed by a **coding assistant**, not independently
> adjudicated by a legal expert. The benchmark is clean English text; strict
> full-quote matching can under-credit other valid evidence. Quote verification
> is not independent legal validation. No claim is made that the public mock
> demo detects 19 issues or that all real agreements achieve these results.

### Reproduce the offline benchmark work

Run from the repository root:

```bash
python benchmark/build.py --validate-only
python -m benchmark.evaluate --output-dir /tmp/legal-reviewer-rule-baseline
python -m unittest benchmark.test_benchmark benchmark.test_evaluation -v
```

To intentionally regenerate the fictional PDF/key, use `python benchmark/build.py`;
that command overwrites ground truth, so it is **not** part of normal evaluation.

Grading the saved AI run requires its original local capture directory, which is
excluded from Git. With those files present, use a fresh output directory:

```bash
python -m benchmark.grade_real_ai --output-dir /tmp/legal-reviewer-ai-grade
```

This reads existing captures and explicit semantic assessments, verifies source
fingerprints, and produces JSON/Markdown AI and combined reports without an API
call. It never overwrites original captures or existing reports. The run ID is
`20261012T073514543612Z_d5175dad358f430084ec7de3cb29d8b7`. A fresh clone can
reproduce rule-based grading; the local-only captures must be explicitly reviewed
and provided to reproduce the historical AI result. Do not request a new paid run
just to grade the old one.

The isolated benchmark runner has a safe `--dry-run` mode:

```bash
python -m benchmark.run_real_ai --dry-run
```

It checks local key presence without transmitting it, the entire input, and local
storage. It requires local mode and rejects Railway environments. A separate
paid invocation requires the exact interactive phrase `RUN ONE PAID REQUEST`,
uses 25,000 input bytes / 8,192 output tokens / 120 seconds / zero retries, and
saves unique raw, parsed, and verified captures. The recorded cost range is an
estimate, not a spending guarantee. **Do not execute that paid invocation during
the demo or this audit.** See [the detailed reference](docs/MILESTONE_NOTES.md).

## Security, privacy, and processing limits

This is a **prototype**, not a production-grade or fully secure legal service.

- Uploaded documents are sent to the hosting server for extraction. Files may
  temporarily spool to the OS temporary directory during multipart parsing and
  are closed afterward; there is no permanent upload storage or database.
  This is not a guarantee of secure erasure, log isolation, or data residency.
- Decisions/edits/drafts live only in browser memory. Copy and Download are
  user-directed exports; no mail integration is present.
- Real Anthropic execution is blocked publicly regardless of the paid flag.
  A public API key is unnecessary and should not be configured for the demo.
- Files are limited to **10 MB**. The raw HTTP body is limited to 10 MB plus
  64 KB multipart overhead **before file data is spooled**; streamed bytes are
  counted even without a trustworthy Content-Length header.
- PDFs are capped at **500 pages** and **2 MB extracted UTF-8 text**. DOCX is
  capped at **2 MB extracted text**, **10,000 locations**, **2,000 ZIP members**,
  **50 MB declared expanded ZIP contents**, and ten levels of table nesting.
  Oversized documents are rejected, not silently truncated.
- DOCX parsing rejects invalid/encrypted/duplicate-entry/macro packages and XML
  DTD/entity declarations. It does not unzip to project files or fetch external
  hyperlink targets. Invalid files return safe errors.
- Upload filenames, excerpts, model findings, and edits are rendered as plain
  text, not HTML. No permissive CORS middleware is configured; debug tracebacks
  are disabled. Health is non-sensitive; benchmark/config/source files are not
  exposed as static files. Public OpenAPI documentation describes routes only.
- Compatible browser headers disable MIME sniffing, framing, referrer disclosure,
  and camera/microphone/geolocation access. Responses default to `no-store`. No
  CSP blocks inline scripts or styles; clipboard copying and downloads remain
  supported. These local changes are not deployed automatically.
- These limits do **not** guarantee a hard CPU/memory/time bound. One parser call
  can allocate memory before text-size checks; many small/slow concurrent requests
  remain an abuse risk. There is no application rate limiter, authentication,
  worker isolation, or global concurrency quota. Use only fictional samples.

The [Milestone 9A audit](docs/SECURITY_AUDIT.md) records checks, high-severity fixes,
remaining warnings, dependency-check scope, and publication caveats. Local fixes
are not deployed automatically; the live deployment still needs a separately
approved release and verification.

## Railway deployment reference

The existing start command is:

```sh
PUBLIC_DEMO_ONLY=true exec python -m uvicorn main:app --host 0.0.0.0 --port $PORT --no-access-log
```

It forcibly enables public demo mode and uses Railway's port. The health check is
`/health`. No credentials, database, volume, frontend build, or Node runtime are
required in production. Uvicorn access logging is disabled. Do not place document
contents or credentials in application/platform logs.

For a **future authorized deployment**, connect the repository, retain Railpack
and this start command, set `PUBLIC_DEMO_ONLY=true` and `ENABLE_REAL_AI=false`,
omit `ANTHROPIC_API_KEY`, and verify health/demo/upload behavior after the build.
Review Git and CLI deployment exclusions beforehand. No variables were changed
and no deployment occurred for this audit. Linux wheel availability and local
checks do not replace testing the actual Railway build/runtime. Deployment budget,
proxy-level limits, logs, and runtime retention remain operator responsibilities.

## Known limitations and future work

- Scanned PDFs need OCR; password-protected files are unsupported. Text extraction
  can lose layout or miss content. Detection uses patterns, not legal meaning.
- Section detection prefers numbered, short title-style headings; references need
  explicit “Section” labels. Tables of contents, ranges, lettered subsections,
  wrapped text, or missing headings can produce false positives/negatives.
- Definitions use quoted names followed by “means” or “shall mean”. Other drafting
  conventions and single-word/lowercase uses may be missed. No recognized headings
  or definitions produces an unreliable-validation warning rather than mass errors.
- DOCX headers, footers, notes, text boxes, content controls, tracked revisions,
  fields, and automatic numbering may be omitted. Source row/cell order may differ
  from complex visual layouts. No DOCX AI review or rendered Word-page mapping.
- Claude can miss, misclassify, or misinterpret issues despite genuine quotes.
  Prompts treat documents as untrusted data but do not eliminate prompt injection.
  Output-token caps can reject incomplete structured responses.
- Review decisions are not permanent or tamper-proof. There is no authentication,
  counsel response workflow, legal-expert certification, or automated email.

Future priorities: independent legal-expert adjudication and broader benchmarks;
rate/concurrency controls and isolated parsing; supported dependency lock/upgrade
procedures; a tested CSP alongside the existing compatible browser headers; more robust DOCX numbering and
location-aware AI schemas; optional durable review history with explicit privacy
requirements. These are proposals, not implemented features.

Detailed historical setup and testing instructions are preserved in
[Milestone notes](docs/MILESTONE_NOTES.md); this README describes the current
hackathon submission.
