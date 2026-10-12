"""One-request runner tests use fake credentials, mocked streams, and blocked networking."""

from contextlib import redirect_stdout
from io import StringIO
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from anthropic import APITimeoutError, APIConnectionError, AuthenticationError, RateLimitError
import httpx2

from ai_reviewer import CONTRACT_SYSTEM_PROMPT, format_document_pages, get_real_review_settings
from benchmark import run_real_ai as runner


FAKE_KEY = "sk-ant-test-only-secret-never-real-123456"
VALID = json.dumps({"findings": [{"id": "F1", "category": "ambiguity", "title": "Support timing",
    "explanation": "Please clarify the response timeframe.", "status": "unverified",
    "evidence": [{"quote": "The Supplier shall respond to priority support requests promptly.", "page": 3}]}]})


def events(text=VALID, stop="end_turn", completed=True):
    stream = [NS(type="message_start", message=NS(model="claude-sonnet-5-5", id="msg_mock",
                    usage=NS(input_tokens=6000, output_tokens=0, cache_read_input_tokens=0))),
              NS(type="content_block_start", index=0, content_block=NS(type="text", text="")),
              NS(type="content_block_delta", index=0, delta=NS(type="text_delta", text=text)),
              NS(type="message_delta", delta=NS(stop_reason=stop), usage=NS(output_tokens=2100))]
    if completed:
        stream.append(NS(type="message_stop"))
    return stream


class RealBenchmarkRunnerTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"ANTHROPIC_API_KEY": FAKE_KEY,
            "ANTHROPIC_MODEL": "claude-sonnet-5-5", "PUBLIC_DEMO_ONLY": "false", "ENABLE_REAL_AI": "false"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        dotenv = patch("ai_reviewer.load_dotenv")
        dotenv.start()
        self.addCleanup(dotenv.stop)
        production_sdk = patch("ai_reviewer.Anthropic", side_effect=AssertionError("Production SDK must not be called."))
        production_sdk.start()
        self.addCleanup(production_sdk.stop)
        network = patch("socket.socket.connect", side_effect=AssertionError("No real network calls are allowed."))
        network.start()
        self.addCleanup(network.stop)
        sdk = patch("benchmark.run_real_ai.Anthropic")
        self.sdk = sdk.start()
        self.addCleanup(sdk.stop)
        transport = patch("benchmark.run_real_ai.DefaultHttpxClient")
        self.transport = transport.start()
        self.addCleanup(transport.stop)
        terminal = patch("sys.stdin.isatty", return_value=True)
        self.terminal = terminal.start()
        self.addCleanup(terminal.stop)
        self.client = self.sdk.return_value.__enter__.return_value
        self.create = self.client.messages.create
        self.create.return_value.__enter__.return_value = events()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name).resolve() / "runs"
        self.messages = []

    def invoke(self, dry=False, confirmation=runner.CONFIRMATION):
        return runner.run(dry_run=dry, directory=self.directory,
                          input_fn=lambda _: confirmation, output_fn=self.messages.append)

    def results(self):
        return sorted(self.directory.glob("*/raw.json"))

    def test_dry_run_checks_complete_input_without_client_confirmation_or_outputs(self):
        confirmation = lambda _: self.fail("Dry run must not ask for paid confirmation")
        self.assertEqual(runner.run(dry_run=True, directory=self.directory, input_fn=confirmation, output_fn=self.messages.append), 0)
        self.sdk.assert_not_called()
        self.transport.assert_not_called()
        self.assertFalse(self.directory.exists())
        summary = json.loads(self.messages[0])
        prepared = runner.prepare(self.directory)
        self.assertEqual(summary["document_input_bytes"], len(format_document_pages(prepared.pages).encode("utf-8")))
        self.assertEqual(summary["model"], "claude-sonnet-5-5")
        self.assertEqual(summary["max_output_tokens"], 8192)
        self.assertEqual(summary["timeout_seconds"], 120)
        self.assertEqual(summary["automatic_retries"], 0)
        self.assertIn("Estimate", summary["estimated_cost"]["label"])
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))
        self.assertNotIn(FAKE_KEY, repr(prepared))

    def test_all_confirmation_variants_cancel_without_request(self):
        for response in ["", "yes", "RUN ONE PAID REQUEST ", " RUN ONE PAID REQUEST", "run one paid request", True, None]:
            with self.subTest(response=response):
                self.assertEqual(self.invoke(confirmation=response), 1)
        self.sdk.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_eof_or_keyboard_interrupt_in_confirmation_cancels(self):
        for error in [EOFError(), KeyboardInterrupt()]:
            with self.subTest(error=type(error).__name__):
                def interrupt(_):
                    raise error
                self.assertEqual(runner.run(directory=self.directory, input_fn=interrupt, output_fn=self.messages.append), 1)
        self.sdk.assert_not_called()

    def test_noninteractive_confirmation_cannot_be_piped(self):
        self.terminal.return_value = False
        self.assertEqual(self.invoke(), 1)
        self.sdk.assert_not_called()

    def test_public_demo_mode_blocks_even_with_enabled_paid_flag(self):
        os.environ["PUBLIC_DEMO_ONLY"] = "true"
        os.environ["ENABLE_REAL_AI"] = "true"
        self.assertEqual(self.invoke(), 2)
        self.assertEqual(self.invoke(dry=True), 2)
        self.sdk.assert_not_called()

    def test_railway_environment_is_blocked_even_with_public_flag_false(self):
        for marker in runner.HOSTED_MARKERS:
            with self.subTest(marker=marker), patch.dict(os.environ, {marker: "hosted"}):
                self.assertEqual(self.invoke(), 2)
        self.sdk.assert_not_called()

    def test_missing_or_placeholder_key_blocks_request(self):
        for key in ["", "  ", "your_key_here"]:
            with self.subTest(key=key), patch.dict(os.environ, {"ANTHROPIC_API_KEY": key}):
                self.assertEqual(self.invoke(dry=True), 2)
        self.sdk.assert_not_called()

    def test_unknown_model_is_rejected_without_printing_its_value(self):
        os.environ["ANTHROPIC_MODEL"] = FAKE_KEY
        self.assertEqual(self.invoke(dry=True), 2)
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))
        self.sdk.assert_not_called()

    def test_input_limit_rejects_oversized_documents_without_truncation(self):
        pages = [{"number": i, "text": "x" * 5000} for i in range(1, 7)]
        with patch("benchmark.run_real_ai.analyze_document", return_value={"pages": pages}):
            self.assertEqual(self.invoke(), 2)
        self.sdk.assert_not_called()
        self.assertIn("Nothing was truncated", self.messages[-1])

    def test_byte_limit_counts_utf8_and_page_markers_at_exact_boundary(self):
        # Six page markers/separators contribute 64 bytes, not six characters.
        text_bytes = 25000 - 64
        pages = [{"number": i, "text": "x"} for i in range(1, 7)]
        pages[0]["text"] = "é" + "x" * (text_bytes - 7)
        with patch("benchmark.run_real_ai.analyze_document", return_value={"pages": pages}):
            self.assertEqual(runner.prepare(self.directory).input_bytes, 25000)
            pages[0]["text"] += "x"
            with self.assertRaisesRegex(runner.RunnerError, "25000-byte"):
                runner.prepare(self.directory)
        self.sdk.assert_not_called()

    def test_wrong_page_count_or_bad_pdf_is_rejected(self):
        with patch("benchmark.run_real_ai.analyze_document", return_value={"pages": [{"number": 1, "text": "Other"}]}):
            self.assertEqual(self.invoke(dry=True), 2)
        with patch("benchmark.run_real_ai.analyze_document", side_effect=ValueError(FAKE_KEY)):
            self.assertEqual(self.invoke(dry=True), 2)
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))
        self.sdk.assert_not_called()

    def test_storage_failure_or_symlink_is_blocked_before_request(self):
        with patch("benchmark.run_real_ai.tempfile.TemporaryFile", side_effect=OSError(FAKE_KEY)):
            self.assertEqual(self.invoke(dry=True), 2)
        self.directory.symlink_to(self.directory.parent, target_is_directory=True)
        self.assertEqual(self.invoke(), 2)
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))
        self.sdk.assert_not_called()

    def test_success_uses_one_streaming_request_and_only_production_prompt_and_pages(self):
        prepared = runner.prepare(self.directory)
        os.environ["ANTHROPIC_BASE_URL"] = "https://untrusted.invalid"
        self.assertEqual(self.invoke(), 0)
        self.sdk.assert_called_once_with(api_key=FAKE_KEY, base_url="https://api.anthropic.com",
            max_retries=0, timeout=120.0, http_client=self.transport.return_value.__enter__.return_value)
        self.transport.assert_called_once_with(follow_redirects=False, timeout=120.0)
        self.create.assert_called_once_with(model="claude-sonnet-5-5", max_tokens=8192, system=CONTRACT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": format_document_pages(prepared.pages)}], stream=True)
        self.assertEqual(len(prepared.pages), 6)
        for name in ["preflight.json", "raw.json", "parsed.json", "verified.json"]:
            self.assertTrue((self.results()[0].parent / name).exists())
        raw = json.loads(self.results()[0].read_text())
        self.assertEqual(raw["raw_text"], VALID)
        self.assertEqual(raw["request_attempts"], 1)
        self.assertEqual(raw["response_model"], "claude-sonnet-5-5")
        self.assertEqual(raw["usage"]["input_tokens"], 6000)
        self.assertEqual(raw["usage"]["output_tokens"], 2100)
        self.assertEqual(raw["stop_reason"], "end_turn")
        self.assertIn("+00:00", raw["finished_at_utc"])
        verified = json.loads((self.results()[0].parent / "verified.json").read_text())
        self.assertEqual(verified["findings"][0]["status"], "verified")

    def test_ground_truth_files_are_never_read_for_request_preparation(self):
        original = Path.read_text
        def guarded(path, *args, **kwargs):
            if path.name in ["answer_key.json", "contract_source.json"]:
                self.fail("Ground truth must never be read by the runner")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", guarded):
            self.assertEqual(self.invoke(), 0)
        sent = self.create.call_args.kwargs
        self.assertEqual(sent["system"], CONTRACT_SYSTEM_PROMPT)
        self.assertNotIn("BR01", sent["messages"][0]["content"])
        self.assertNotIn("UT01", sent["messages"][0]["content"])

    def test_raw_file_is_saved_before_parsing_or_verification(self):
        parser = runner.parse_analysis_response
        verifier = runner.verify_findings
        def check_parse(*args):
            self.assertEqual(json.loads(self.results()[0].read_text())["raw_text"], VALID)
            return parser(*args)
        def check_verify(*args):
            self.assertTrue((self.results()[0].parent / "parsed.json").exists())
            return verifier(*args)
        with patch("benchmark.run_real_ai.parse_analysis_response", side_effect=check_parse), \
             patch("benchmark.run_real_ai.verify_findings", side_effect=check_verify):
            self.assertEqual(self.invoke(), 0)

    def test_invented_quotes_remain_available_as_verification_failed(self):
        value = json.loads(VALID)
        value["findings"][0]["evidence"][0]["quote"] = "The supplier guarantees an invented entitlement."
        self.create.return_value.__enter__.return_value = events(json.dumps(value))
        self.assertEqual(self.invoke(), 0)
        verified = json.loads((self.results()[0].parent / "verified.json").read_text())
        finding = verified["findings"][0]
        self.assertEqual(finding["status"], "verification_failed")
        self.assertTrue(finding["failure_reasons"])
        self.create.assert_called_once()

    def test_malformed_or_wrong_page_response_saved_without_retry(self):
        for text in ["not-json", VALID.replace('"page": 3', '"page": 999')]:
            with self.subTest(text=text):
                self.create.reset_mock()
                self.create.return_value.__enter__.return_value = events(text)
                self.assertEqual(self.invoke(), 2)
                self.create.assert_called_once()
                run = self.results()[-1].parent
                self.assertEqual(json.loads((run / "raw.json").read_text())["raw_text"], text)
                self.assertTrue((run / "processing_error.json").exists())
                self.assertFalse((run / "verified.json").exists())

    def test_truncated_response_saved_and_never_parsed_or_retried(self):
        self.create.return_value.__enter__.return_value = events(VALID, stop="max_tokens")
        with patch("benchmark.run_real_ai.parse_analysis_response") as parser:
            self.assertEqual(self.invoke(), 2)
            parser.assert_not_called()
        raw = json.loads(self.results()[0].read_text())
        self.assertEqual(raw["raw_text"], VALID)
        self.assertEqual(raw["stop_reason"], "max_tokens")
        self.assertTrue(raw["errors"])
        self.create.assert_called_once()

    def test_ended_stream_without_message_stop_is_incomplete(self):
        self.create.return_value.__enter__.return_value = events(VALID, completed=False)
        self.assertEqual(self.invoke(), 2)
        self.assertFalse((self.results()[0].parent / "parsed.json").exists())
        self.assertFalse(json.loads(self.results()[0].read_text())["stream_completed"])
        self.create.assert_called_once()

    def test_timeout_preserves_available_partial_text_and_safe_error(self):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        def partial():
            yield from events(text='{"findings": [', completed=False)[:3]
            raise APITimeoutError(request=request)
        self.create.return_value.__enter__.return_value = partial()
        self.assertEqual(self.invoke(), 2)
        raw = json.loads(self.results()[0].read_text())
        self.assertEqual(raw["raw_text"], '{"findings": [')
        self.assertEqual(raw["errors"][0]["type"], "timeout")
        self.assertIn("Charges may apply", raw["errors"][0]["message"])
        self.create.assert_called_once()

    def test_interrupt_during_response_preserves_partial_text_without_retry(self):
        def partial():
            yield from events(text="partial", completed=False)[:3]
            raise KeyboardInterrupt()
        self.create.return_value.__enter__.return_value = partial()
        self.assertEqual(self.invoke(), 130)
        self.assertEqual(json.loads(self.results()[0].read_text())["raw_text"], "partial")
        self.create.assert_called_once()

    def test_auth_rate_limit_connection_and_unknown_errors_do_not_leak_or_retry(self):
        response = httpx2.Response(401, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
        errors = [AuthenticationError(FAKE_KEY, response=response, body={"key": FAKE_KEY}),
                  RateLimitError(FAKE_KEY, response=response, body={"key": FAKE_KEY}),
                  APIConnectionError(message=FAKE_KEY, request=response.request), RuntimeError(FAKE_KEY)]
        for error in errors:
            with self.subTest(error=type(error).__name__):
                self.create.reset_mock()
                self.create.side_effect = error
                self.assertEqual(self.invoke(), 2)
                self.create.assert_called_once()
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))
        for file in self.directory.rglob("*.json"):
            self.assertNotIn(FAKE_KEY, file.read_text())

    def test_provider_echoed_credentials_are_redacted_from_all_saved_files(self):
        value = json.loads(VALID)
        value["findings"][0]["title"] = FAKE_KEY
        self.create.return_value.__enter__.return_value = events(json.dumps(value))
        self.assertEqual(self.invoke(), 0)
        for file in self.directory.rglob("*.json"):
            self.assertNotIn(FAKE_KEY, file.read_text())
        self.assertIn("[REDACTED]", self.results()[0].read_text())
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))

    def test_two_invocations_create_unique_files_without_overwriting(self):
        self.assertEqual(self.invoke(), 0)
        first = self.results()[0]
        original = first.read_bytes()
        self.assertEqual(self.invoke(), 0)
        self.assertEqual(len(self.results()), 2)
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(self.create.call_count, 2)  # Exactly one per separately confirmed invocation.
        self.assertNotEqual(self.results()[0].parent.name, self.results()[1].parent.name)

    def test_exclusive_raw_file_creation_never_replaces_existing_content(self):
        file = self.directory.parent / "raw.json"
        file.write_text("original")
        with self.assertRaises(FileExistsError):
            runner.write_json_once(file, {"raw_text": "replacement"}, FAKE_KEY)
        self.assertEqual(file.read_text(), "original")

    def test_result_files_and_run_directories_have_private_permissions(self):
        self.assertEqual(self.invoke(), 0)
        run = self.results()[0].parent
        self.assertEqual(run.stat().st_mode & 0o777, 0o700)
        for file in run.glob("*.json"):
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_production_defaults_and_web_paid_flag_are_unchanged(self):
        before = dict(os.environ)
        self.assertEqual(self.invoke(), 0)
        settings = get_real_review_settings()
        self.assertEqual(settings["max_input_bytes"], 20000)
        self.assertEqual(settings["max_output_tokens"], 2048)
        self.assertEqual(settings["timeout_seconds"], 30)
        self.assertFalse(settings["enabled"])
        self.assertEqual(dict(os.environ), before)

    def test_public_flag_is_rechecked_after_confirmation(self):
        def confirm(_):
            os.environ["PUBLIC_DEMO_ONLY"] = "true"
            return runner.CONFIRMATION
        code = runner.run(directory=self.directory, input_fn=confirm, output_fn=self.messages.append)
        self.assertEqual(code, 2)
        self.sdk.assert_not_called()
        self.assertEqual(json.loads(self.results()[0].read_text())["request_attempts"], 0)

    def test_transport_logging_is_suppressed_and_restored(self):
        logger = logging.getLogger("anthropic")
        before = (logger.handlers, logger.propagate, logger.disabled)
        captured = StringIO()
        with redirect_stdout(captured):
            with runner.quiet_transport_logs():
                logger.debug(FAKE_KEY)
                self.assertTrue(logger.disabled)
        self.assertEqual(captured.getvalue(), "")
        self.assertEqual((logger.handlers, logger.propagate, logger.disabled), before)

    def test_local_captures_are_git_ignored_without_ignoring_baseline_reports(self):
        paths = ["benchmark/results/real_ai_runs/example/raw.json", "benchmark/results/rule_based_baseline.json"]
        result = subprocess.run(["git", "check-ignore", "--no-index", "--stdin"],
            cwd=runner.PDF.parent.parent, input="\n".join(paths) + "\n", text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.splitlines(), paths[:1])


    def test_credential_in_pdf_is_rejected_before_prompt_or_request(self):
        pages = [{"number": i, "text": "Synthetic page"} for i in range(1, 7)]
        pages[0]["text"] += " " + FAKE_KEY
        with patch("benchmark.run_real_ai.analyze_document", return_value={"pages": pages}):
            self.assertEqual(self.invoke(dry=True), 2)
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))
        self.sdk.assert_not_called()

    def test_run_reservation_failure_happens_before_paid_call(self):
        with patch("benchmark.run_real_ai.allocate_run", side_effect=FileExistsError(FAKE_KEY)):
            self.assertEqual(self.invoke(), 2)
        self.sdk.assert_not_called()
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))

    def test_preflight_write_failure_prevents_request(self):
        with patch("benchmark.run_real_ai.write_json_once", side_effect=OSError(FAKE_KEY)):
            self.assertEqual(self.invoke(), 2)
        self.sdk.assert_not_called()
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))

    def test_raw_save_failure_never_parses_or_retries(self):
        writer = runner.write_json_once
        def fail_raw(path, value, key):
            if path.name == "raw.json":
                raise OSError(FAKE_KEY)
            return writer(path, value, key)
        with patch("benchmark.run_real_ai.write_json_once", side_effect=fail_raw), \
             patch("benchmark.run_real_ai.parse_analysis_response") as parser:
            self.assertEqual(self.invoke(), 2)
            parser.assert_not_called()
        self.create.assert_called_once()
        self.assertIn("may have been charged", self.messages[-1])
        self.assertNotIn(FAKE_KEY, "\n".join(self.messages))

    def test_verification_error_keeps_raw_and_parsed_files_without_retry(self):
        with patch("benchmark.run_real_ai.verify_findings", side_effect=ValueError(FAKE_KEY)):
            self.assertEqual(self.invoke(), 2)
        run = self.results()[0].parent
        self.assertTrue((run / "raw.json").exists())
        self.assertTrue((run / "parsed.json").exists())
        self.assertFalse((run / "verified.json").exists())
        error = json.loads((run / "processing_error.json").read_text())
        self.assertEqual(error["stage"], "verification_or_saving")
        self.assertNotIn(FAKE_KEY, (run / "processing_error.json").read_text())
        self.create.assert_called_once()

    def test_multiple_text_blocks_join_like_production_and_ignore_thinking_text(self):
        split = VALID.index("[") + 1
        stream = events()[:1] + [
            NS(type="content_block_start", index=0, content_block=NS(type="thinking", thinking=FAKE_KEY)),
            NS(type="content_block_delta", index=0, delta=NS(type="thinking_delta", thinking=FAKE_KEY)),
            NS(type="content_block_start", index=2, content_block=NS(type="text", text=VALID[:split])),
            NS(type="content_block_start", index=4, content_block=NS(type="text", text="")),
            NS(type="content_block_delta", index=4, delta=NS(type="text_delta", text=VALID[split:])),
        ] + events()[-2:]
        self.create.return_value.__enter__.return_value = stream
        self.assertEqual(self.invoke(), 0)
        raw = json.loads(self.results()[0].read_text())
        self.assertEqual(raw["raw_text"], VALID[:split] + "\n" + VALID[split:])
        self.assertNotIn(FAKE_KEY, self.results()[0].read_text())
        self.create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
