import json
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from ai_reviewer import DEMO_CONTRACT_TEXT, format_document_pages, review_contract_demo

from detection import detect_sections_and_references, validate_references
from terms import detect_terms, validate_terms

app = FastAPI(title="Legal Reviewer")
BASE_DIR = Path(__file__).resolve().parent
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB, matching the browser's limit.


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/demo-contract.pdf")
def download_demo_contract():
    """Generate the synthetic fixture in memory; no file is saved by the server."""
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 72), DEMO_CONTRACT_TEXT, fontsize=12)
        contents = pdf.tobytes()
    return Response(contents, media_type="application/pdf", headers={
        "Content-Disposition": 'attachment; filename="legal-reviewer-demo.pdf"',
        "Cache-Control": "no-store",
    })


@app.post("/ai-review-demo")
async def ai_review_demo(request: Request):
    """Stateless, local-only demo. Text lives in this request, not a server cache."""
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="Demo text request exceeds 10 MB.")
        body.extend(chunk)
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict) or set(payload) != {"pages"}:
            raise ValueError("Expected document pages only.")
        pages = payload["pages"]
        format_document_pages(pages)
    except (ValueError, TypeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Provide valid extracted document pages for the demo.") from None

    try:
        result = review_contract_demo(pages)
    except Exception:
        # Never include document text, mock response contents, or credentials in errors.
        raise HTTPException(status_code=500, detail="Demo review could not be processed. Please try again. No Anthropic API call was made.") from None
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/analyze")
def analyze_document(file: UploadFile | None = File(default=None), response: Response = None):
    if response is not None:
        response.headers["Cache-Control"] = "no-store"
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
        term_detections = detect_terms(pages)
        term_validation = validate_terms(
            term_detections["defined_terms"],
            term_detections["candidate_term_uses"],
            detections["sections"],
            detections["references"],
        )
        return {
            "filename": filename,
            "total_pages": len(pages),
            "pages": pages,
            **detections,
            **validation,
            **term_detections,
            **term_validation,
        }
    finally:
        file.file.close()
