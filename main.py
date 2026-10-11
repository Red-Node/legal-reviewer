from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from detection import detect_sections_and_references, validate_references

app = FastAPI(title="Legal Reviewer")
BASE_DIR = Path(__file__).resolve().parent
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB, matching the browser's limit.


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "index.html")


@app.post("/analyze")
def analyze_document(file: UploadFile | None = File(default=None)):
    if file is None:
        raise HTTPException(status_code=400, detail="Please choose a PDF file.")

    # FastAPI may use a temporary file for uploads. Always close it to clean up.
    try:
        filename = file.filename or ""
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Please upload a PDF file (.pdf).")

        # Read at most one byte beyond the limit, even if browser checks are bypassed.
        contents = file.file.read(MAX_FILE_SIZE + 1)
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="The file is too large. The maximum size is 10 MB.")
        if not contents:
            raise HTTPException(status_code=400, detail="This file is empty. Please choose a valid PDF.")

        try:
            # Open the uploaded bytes directly; never save a document to the project.
            with pymupdf.open(stream=contents, filetype="pdf") as document:
                if not document.is_pdf:
                    raise HTTPException(status_code=400, detail="This file is not a valid PDF.")
                if document.needs_pass:
                    raise HTTPException(status_code=400, detail="This PDF is password protected. Please upload an unlocked copy.")

                pages = [
                    {"number": number, "text": page.get_text("text", sort=True)}
                    for number, page in enumerate(document, start=1)
                ]
        except (RuntimeError, ValueError):
            raise HTTPException(status_code=400, detail="This PDF is invalid or damaged and could not be read.") from None

        if not any(page["text"].strip() for page in pages):
            raise HTTPException(
                status_code=400,
                detail="This PDF has no extractable text. It may contain scanned images. Please upload a PDF with selectable text.",
            )

        detections = detect_sections_and_references(pages)
        # Detect all pages first, so a reference can point to a later section.
        validation = validate_references(detections["sections"], detections["references"])
        return {
            "filename": filename,
            "total_pages": len(pages),
            "pages": pages,
            **detections,
            **validation,
        }
    finally:
        file.file.close()
