# Legal Reviewer

A minimal PDF text reader built with Python, FastAPI, PyMuPDF, and plain HTML,
CSS, and JavaScript. This first version only extracts and displays text by page.

## Files

- `main.py`: serves the webpage and handles PDF uploads and text extraction.
- `index.html`: contains the upload form, styling, and JavaScript that displays results.
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

There is no AI, legal analysis, editing, database, or external API integration.
