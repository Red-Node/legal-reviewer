# Legal Reviewer

A minimal PDF text reader built with Python, FastAPI, PyMuPDF, and plain HTML,
CSS, and JavaScript. It extracts text by page and uses deterministic rules to
detect numbered section headings and explicit section references.

## Files

- `main.py`: serves the webpage and handles PDF uploads and text extraction.
- `detection.py`: identifies section headings and explicit references using text patterns.
- `index.html`: contains the upload form, styling, and JavaScript that displays results.
- `test_detection.py`: tests synthetic contract text and checks that PDF uploads still work.
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
as headings. A missing target such as 9.4 is simply listed; this version does
not check whether a referenced section exists.

To run the automated tests, activate your virtual environment and run this
command from the project folder:

```sh
python -m unittest -v
```

The tests create sample PDF data in memory; no test documents are stored.

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
  are kept, and referenced targets are not validated.

There is no AI, legal analysis, editing, database, or external API integration.
