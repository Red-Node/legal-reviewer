"""Local-only, explicitly confirmed, single-request synthetic Claude benchmark.

Prepare without any API traffic: python -m benchmark.run_real_ai --dry-run
No ground-truth files are read, and production request defaults are not changed.
"""

import argparse
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

from anthropic import (Anthropic, DefaultHttpxClient, APIConnectionError, APITimeoutError,
                       APIStatusError, AuthenticationError, RateLimitError)
from fastapi import UploadFile

from ai_reviewer import (CONTRACT_SYSTEM_PROMPT, DEFAULT_MODEL, format_document_pages,
                         is_public_demo_only, parse_analysis_response)
from main import analyze_document
from quote_verifier import verify_findings


PDF = Path(__file__).resolve().parent / "fictional_services_agreement.pdf"
OUTPUT = Path(__file__).resolve().parent / "results" / "real_ai_runs"
MAX_INPUT_BYTES = 25000
MAX_OUTPUT_TOKENS = 8192
TIMEOUT_SECONDS = 120.0
CONFIRMATION = "RUN ONE PAID REQUEST"
COST_ESTIMATE = {"currency": "USD", "minimum": 0.03, "maximum": 0.12,
                 "label": "Estimate only; actual tokens, thinking, and charges may vary."}
HOSTED_MARKERS = ("RAILWAY_PROJECT_ID", "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_ID", "RAILWAY_DEPLOYMENT_ID")


class RunnerError(ValueError):
    """Static, non-sensitive error suitable for the command line."""


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def ensure_local():
    if any(os.getenv(name) for name in HOSTED_MARKERS):
        raise RunnerError("This tool is local only. Railway environments are blocked.")
    if is_public_demo_only():
        raise RunnerError("PUBLIC_DEMO_ONLY blocks this runner. No Anthropic request was made.")


@dataclass
class Prepared:
    pages: list = field(repr=False)
    text: str = field(repr=False)
    api_key: str = field(repr=False)
    model: str
    input_bytes: int
    pdf_sha256: str

    def summary(self):
        return {"pdf_filename": PDF.name, "document_input_bytes": self.input_bytes,
                "maximum_document_bytes": MAX_INPUT_BYTES, "model": self.model,
                "max_output_tokens": MAX_OUTPUT_TOKENS, "timeout_seconds": TIMEOUT_SECONDS,
                "automatic_retries": 0, "estimated_cost": COST_ESTIMATE,
                "api_key_configured": True,
                "configuration_note": "Key presence checked offline; validity, model access, and credit balance are not checked."}


def check_storage(directory):
    """Check local storage before charging, without creating a run in dry-run mode."""
    directory = Path(directory)
    for path in [directory, *directory.parents]:
        if path.is_symlink():
            raise RunnerError("Result directories must not use symbolic links.")
    parent = directory
    while not parent.exists():
        parent = parent.parent
    if not parent.is_dir():
        raise RunnerError("Result location is not a directory.")
    try:
        with tempfile.TemporaryFile(dir=parent) as probe:
            probe.write(b"write-check")
            probe.flush()
    except OSError:
        raise RunnerError("Result location is not writable. Nothing was sent.") from None


def prepare(directory=OUTPUT):
    ensure_local()  # Existing .env is loaded read-only; explicit environment values take priority.
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key or key == "your_key_here":
        raise RunnerError("A local ANTHROPIC_API_KEY is required. No value is displayed or saved.")
    model = os.getenv("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
    if model != "claude-sonnet-5-5":
        raise RunnerError("This cost-bounded benchmark runner supports claude-sonnet-5-5 only.")
    try:
        with PDF.open("rb") as stream:
            analysis = analyze_document(UploadFile(file=stream, filename=PDF.name))
    except Exception:
        raise RunnerError("The fixed synthetic benchmark PDF could not be extracted safely.") from None
    pages = analysis["pages"]
    if len(pages) != 6:
        raise RunnerError("Expected the complete six-page synthetic benchmark PDF.")
    text = format_document_pages(pages)
    if key in text or key in CONTRACT_SYSTEM_PROMPT or re.search(r"sk-ant-[A-Za-z0-9_-]+", text):
        raise RunnerError("Credential-looking content detected in benchmark input. Nothing was sent.")
    size = len(text.encode("utf-8"))
    if size > MAX_INPUT_BYTES:
        raise RunnerError(f"Benchmark input is {size} bytes, above the 25000-byte limit. Nothing was truncated or sent.")
    check_storage(directory)
    return Prepared(pages, text, key, model, size, hashlib.sha256(PDF.read_bytes()).hexdigest())


def redact(text, key):
    text = text.replace(key, "[REDACTED]")
    return re.sub(r"sk-ant-[A-Za-z0-9_-]+", "[REDACTED]", text)


def write_json_once(path, value, key):
    """Owner-readable, exclusive creation. Never replace an existing result file."""
    # JSON-escaped replacement also covers unusual characters in a configured key.
    content = json.dumps(value, indent=2, ensure_ascii=False)
    content = content.replace(json.dumps(key, ensure_ascii=False)[1:-1], "[REDACTED]")
    content = redact(content, key)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content + "\n")
        output.flush()
        os.fsync(output.fileno())


def allocate_run(directory, prepared):
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    run = root / run_id
    run.mkdir(mode=0o700)  # A collision aborts before the API call; it is never reused.
    metadata = {**prepared.summary(), "run_id": run_id, "started_at_utc": utc_now(),
                "pdf_sha256": prepared.pdf_sha256,
                "document_sha256": hashlib.sha256(prepared.text.encode("utf-8")).hexdigest(),
                "system_prompt_sha256": hashlib.sha256(CONTRACT_SYSTEM_PROMPT.encode("utf-8")).hexdigest()}
    write_json_once(run / "preflight.json", metadata, prepared.api_key)
    return run, metadata


@contextmanager
def quiet_transport_logs():
    saved = []
    for name in ("anthropic", "httpx2", "httpcore2", "httpx", "httpcore"):
        logger = logging.getLogger(name)
        saved.append((logger, logger.handlers, logger.propagate, logger.disabled))
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        logger.disabled = True
    try:
        yield
    finally:
        for logger, handlers, propagate, disabled in saved:
            logger.handlers, logger.propagate, logger.disabled = handlers, propagate, disabled


def usage_values(usage):
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return {key: value for key, value in usage.model_dump(mode="json").items() if value is not None}
    return {key: value for key, value in vars(usage).items() if value is not None}


def request_error(error):
    # Never serialize str(error), repr(error), request headers, or provider error bodies.
    if isinstance(error, KeyboardInterrupt):
        kind, message = "interrupted", "Interrupted. Partial text retained; no retry. Charges may apply."
    elif isinstance(error, APITimeoutError):
        kind, message = "timeout", "Timed out. Partial text retained when available; no retry. Charges may apply."
    elif isinstance(error, AuthenticationError):
        kind, message = "authentication", "Authentication failed. No retry. Check local credentials privately."
    elif isinstance(error, RateLimitError):
        kind, message = "rate_limit", "Rate limited. No retry."
    elif isinstance(error, APIConnectionError):
        kind, message = "connection", "Connection failed. No retry; check account usage before another invocation."
    elif isinstance(error, APIStatusError):
        kind, message = "api_status", "API error or unavailable model access. No retry."
    else:
        kind, message = "request_error", "Request failed. No retry; charges may apply."
    return {"stage": "request", "type": kind, "message": message}


def capture_once(prepared, metadata):
    """One streaming Messages request, no redirects/retries, with partial-text capture."""
    record = {**metadata, "request_attempts": 0, "raw_text": "", "response_model": None,
              "usage": {}, "stop_reason": None, "message_id": None,
              "stream_completed": False, "errors": []}
    blocks = {}
    try:
        ensure_local()  # Recheck after confirmation and storage allocation.
        with quiet_transport_logs(), DefaultHttpxClient(follow_redirects=False, timeout=TIMEOUT_SECONDS) as transport:
            with Anthropic(api_key=prepared.api_key, base_url="https://api.anthropic.com",
                           max_retries=0, timeout=TIMEOUT_SECONDS, http_client=transport) as client:
                record["request_attempts"] = 1
                # This is the only API request site. No API token counting or model lookup occurs.
                with client.messages.create(model=prepared.model, max_tokens=MAX_OUTPUT_TOKENS,
                        system=CONTRACT_SYSTEM_PROMPT, messages=[{"role": "user", "content": prepared.text}],
                        stream=True) as events:
                    for event in events:
                        if event.type == "message_start":
                            record["response_model"] = event.message.model
                            record["message_id"] = event.message.id
                            record["usage"].update(usage_values(event.message.usage))
                        elif event.type == "content_block_start" and event.content_block.type == "text":
                            blocks[event.index] = event.content_block.text
                        elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                            blocks[event.index] = blocks.get(event.index, "") + event.delta.text
                        elif event.type == "message_delta":
                            record["stop_reason"] = event.delta.stop_reason
                            record["usage"].update(usage_values(event.usage))
                        elif event.type == "message_stop":
                            record["stream_completed"] = True
                        elif event.type == "error":
                            raise RunnerError("Stream error")
    except (Exception, KeyboardInterrupt) as error:
        record["errors"].append(request_error(error))
    record["raw_text"] = "\n".join(blocks[index] for index in sorted(blocks))
    if not record["errors"] and (not record["stream_completed"] or record["stop_reason"] != "end_turn"):
        record["errors"].append({"stage": "response", "type": "incomplete_response",
            "message": "Response incomplete or stopped without end_turn. Raw text retained; no parsing or retry."})
    record["finished_at_utc"] = utc_now()
    return record


def run(*, dry_run=False, directory=OUTPUT, input_fn=input, output_fn=print):
    try:
        prepared = prepare(directory)
    except (RunnerError, OSError):
        # Print only the static error, never exception/provider details or credentials.
        error = sys.exc_info()[1]
        output_fn(str(error) if isinstance(error, RunnerError) else "Local configuration check failed. Nothing was sent.")
        return 2
    output_fn(redact(json.dumps(prepared.summary(), indent=2), prepared.api_key))
    if dry_run:
        output_fn("Dry run passed. No API client created, no request made, and no run results written.")
        return 0
    if not sys.stdin.isatty():
        output_fn("Cancelled: interactive terminal confirmation is required. Nothing was sent.")
        return 1
    try:
        confirmation = input_fn(f"Type exactly {CONFIRMATION}: ")
    except (EOFError, KeyboardInterrupt):
        confirmation = None
    if confirmation != CONFIRMATION:
        output_fn("Cancelled. Nothing was sent.")
        return 1
    try:
        run_path, metadata = allocate_run(directory, prepared)
    except OSError:
        output_fn("Could not reserve a new result directory. Nothing was sent.")
        return 2
    record = capture_once(prepared, metadata)
    try:
        # Save the full text and API outcome before any parser or quote verifier runs.
        write_json_once(run_path / "raw.json", record, prepared.api_key)
    except OSError:
        output_fn("Raw result could not be saved. A request may have been charged. Do not retry automatically.")
        return 2
    if record["errors"]:
        output_fn(f"Raw/partial result saved in run {metadata['run_id']}. Request was not retried.")
        return 130 if record["errors"][0]["type"] == "interrupted" else 2
    try:
        parsed = parse_analysis_response(record["raw_text"], [page["number"] for page in prepared.pages])
        write_json_once(run_path / "parsed.json", parsed, prepared.api_key)
    except (ValueError, OSError):
        processing = {"stage": "parsing_or_saving", "message": "Structured response could not be parsed or saved. Raw result retained; no retry."}
    else:
        try:
            verified = verify_findings(parsed, prepared.pages)
            write_json_once(run_path / "verified.json", verified, prepared.api_key)
        except (ValueError, OSError):
            processing = {"stage": "verification_or_saving", "message": "Verification could not be completed or saved. Raw/parsed results retained; no retry."}
        else:
            output_fn(f"Raw, parsed, and independently verified results saved in run {metadata['run_id']}. No grading was performed.")
            return 0
    try:
        write_json_once(run_path / "processing_error.json", processing, prepared.api_key)
    except OSError:
        output_fn("Processing error could not be saved. Raw result retained. No retry.")
    output_fn(f"Processing failed for run {metadata['run_id']}. Inspect local files; no retry was made.")
    return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Validate input/settings/storage offline; never create an API client.")
    arguments = parser.parse_args()
    sys.exit(run(dry_run=arguments.dry_run))
