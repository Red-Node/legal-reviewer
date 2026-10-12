import json
from ipaddress import ip_address
from pathlib import Path

import pymupdf
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ai_reviewer import (DEMO_CONTRACT_TEXT, ReviewError, format_document_pages,
                         get_real_review_settings, is_public_demo_only,
                         review_contract_demo, review_contract_real)

from detection import detect_sections_and_references, validate_references
from terms import detect_terms, validate_terms
from docx_reader import DocxError, extract_docx, located_results

app = FastAPI(title="Legal Reviewer")
BASE_DIR = Path(__file__).resolve().parent
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB, matching the browser's limit.


@app.get("/health")
def health():
    """Readiness only: no document, environment, or credential information."""
    return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


@app.get("/")
def home():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/review.js")
def review_script():
    return FileResponse(BASE_DIR / "review.js", media_type="application/javascript")


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


def _reject_docx_ai_payload(payload):
    if not isinstance(payload, dict):
        return
    sources = payload.get("pages")
    if ("locations" in payload or payload.get("document_type") == "docx" or
            (isinstance(sources, list) and any(isinstance(source, dict) and "location_id" in source for source in sources))):
        raise HTTPException(status_code=400, detail="AI review is not supported for DOCX yet. Its paragraph/table locations cannot be represented as PDF evidence pages. No Anthropic request was made.")


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
        _reject_docx_ai_payload(payload)
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


def _require_local_development(request):
    # Check before trusting host/client addresses or reading any document content.
    if is_public_demo_only():
        raise HTTPException(status_code=403, detail="Real Claude review is blocked in public demo mode. No Anthropic request was made.")
    try:
        local = request.client is not None and ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    if not local or request.url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="Real Claude review controls are available only on local development addresses.")


@app.get("/ai-review-config")
def real_review_configuration(request: Request):
    _require_local_development(request)
    try:
        settings = get_real_review_settings()
    except ReviewError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    return JSONResponse(settings, headers={"Cache-Control": "no-store"})


@app.post("/ai-review-real")
async def real_review(request: Request):
    _require_local_development(request)
    if request.headers.get("origin") != str(request.base_url).rstrip("/"):
        raise HTTPException(status_code=403, detail="Real review must be requested from this local application page.")
    try:
        settings = get_real_review_settings()
    except ReviewError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    if not settings["enabled"]:
        raise HTTPException(status_code=403, detail="Real Claude review is disabled on the server. No Anthropic request was made.")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="Real review request exceeds 10 MB. Nothing was sent.")
        body.extend(chunk)
    try:
        payload = json.loads(body)
        _reject_docx_ai_payload(payload)
        if not isinstance(payload, dict) or set(payload) != {"pages", "confirmed"}:
            raise ValueError
        if payload["confirmed"] is not True:
            raise HTTPException(status_code=400, detail="Confirmation of document transfer and possible API charges is required.")
        pages = payload["pages"]
        format_document_pages(pages)
    except (ValueError, TypeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Provide valid document pages and explicit confirmation. Nothing was sent.") from None

    try:
        result = await run_in_threadpool(review_contract_real, pages, confirmed=True)
    except ReviewError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except Exception:
        raise HTTPException(status_code=502, detail="Claude review could not be processed safely. No automatic retry was made; check your account before trying again.") from None
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/analyze")
def analyze_document(file: UploadFile | None = File(default=None), response: Response = None):
    if response is not None:
        response.headers["Cache-Control"] = "no-store"
    if file is None:
        raise HTTPException(status_code=400, detail="Please choose a PDF or DOCX file.")

    # FastAPI may use a temporary file for uploads. Always close it to clean up.
    try:
        filename = file.filename or ""
        extension = Path(filename).suffix.lower()
        if extension == ".doc":
            raise HTTPException(status_code=400, detail="Legacy .doc files are not supported. Open the file in Word and save it as .docx.")
        if extension not in (".pdf", ".docx"):
            raise HTTPException(status_code=400, detail="Please upload a PDF or DOCX file (.pdf or .docx).")

        # Read at most one byte beyond the limit, even if browser checks are bypassed.
        contents = file.file.read(MAX_FILE_SIZE + 1)
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="The file is too large. The maximum size is 10 MB.")
        if not contents:
            raise HTTPException(status_code=400, detail="This file is empty. Please choose a valid PDF or DOCX.")

        locations = None
        if extension == ".docx":
            try:
                locations = extract_docx(contents)
            except DocxError as error:
                raise HTTPException(status_code=400, detail=str(error)) from None
            # Chunk ordinals are internal detector indices, never DOCX page numbers.
            pages = [{"number": index, "text": source["text"]}
                     for index, source in enumerate(locations, 1)]
        else:
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
        result = {
            "filename": filename,
            "total_pages": len(pages),
            "pages": pages,
            **detections,
            **validation,
            **term_detections,
            **term_validation,
        }
        if locations is not None:
            result.pop("pages")
            result.pop("total_pages")
            result = located_results(result, locations)
            result.update(document_type="docx", locations=locations, total_locations=len(locations),
                          ai_supported=False,
                          location_notice="DOCX locations identify body paragraphs and table cells, not rendered pages. Headers, footnotes, text boxes, tracked changes and automatic list numbers may be omitted. AI review is unavailable for DOCX; its current evidence format requires PDF pages.")
        return result
    finally:
        file.file.close()
