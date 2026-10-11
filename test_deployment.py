"""Offline Railway preparation tests. No credentials, hosting, or AI networking."""

from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import pymupdf

import ai_reviewer
from main import app, MAX_FILE_SIZE


BASE_DIR = Path(__file__).resolve().parent


class PublicDemoTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"PUBLIC_DEMO_ONLY": "true", "ENABLE_REAL_AI": "true"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        dotenv = patch("ai_reviewer.load_dotenv")
        dotenv.start()
        self.addCleanup(dotenv.stop)
        sdk = patch("ai_reviewer.Anthropic", side_effect=AssertionError("Paid API client must never be created."))
        self.sdk = sdk.start()
        self.addCleanup(sdk.stop)
        network = patch("socket.socket.connect", side_effect=AssertionError("Network forbidden in offline tests."))
        network.start()
        self.addCleanup(network.stop)
        self.client = TestClient(app, base_url="https://legal-reviewer.example", client=("192.0.2.1", 50000))
        self.addCleanup(self.client.close)
        self.pages = [{"number": 1, "text": ai_reviewer.DEMO_CONTRACT_TEXT}]

    def tearDown(self):
        self.sdk.assert_not_called()

    def test_health_is_non_sensitive_and_independent_of_ai_settings(self):
        os.environ["ANTHROPIC_API_KEY"] = "fake-secret-never-use"
        os.environ["AI_MAX_INPUT_BYTES"] = "invalid"
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("fake-secret", response.text)

    def test_public_flag_overrides_paid_flag_without_credentials(self):
        self.assertNotIn("ANTHROPIC_API_KEY", os.environ)
        self.assertFalse(ai_reviewer.get_real_review_settings()["enabled"])
        self.assertTrue(ai_reviewer.is_public_demo_only())

    def test_public_flag_normalization_and_invalid_values_fail_closed(self):
        for flag in ["true", " TRUE ", "yes", "1", "", "typo"]:
            with self.subTest(flag=flag):
                os.environ["PUBLIC_DEMO_ONLY"] = flag
                self.assertTrue(ai_reviewer.is_public_demo_only())
                self.assertFalse(ai_reviewer.get_real_review_settings()["enabled"])
        os.environ["PUBLIC_DEMO_ONLY"] = "false"
        self.assertFalse(ai_reviewer.is_public_demo_only())
        self.assertTrue(ai_reviewer.get_real_review_settings()["enabled"])

    def test_all_real_python_entry_points_block_before_sdk_creation(self):
        os.environ["ANTHROPIC_API_KEY"] = "fake-secret-never-use"
        os.environ["AI_MAX_INPUT_BYTES"] = "invalid"
        calls = [lambda: ai_reviewer.send_text_to_claude("Synthetic text"),
                 lambda: ai_reviewer.analyze_contract(self.pages),
                 lambda: ai_reviewer.review_contract_real(self.pages, confirmed=True)]
        for call in calls:
            with self.assertRaisesRegex(ai_reviewer.ReviewError, "public demo mode"):
                call()

    def test_sdk_boundary_blocks_even_if_real_settings_are_overridden(self):
        with patch("ai_reviewer.get_real_review_settings", return_value={"enabled": True}):
            with self.assertRaisesRegex(ai_reviewer.ReviewError, "public demo mode"):
                ai_reviewer.send_text_to_claude("Synthetic text")

    def test_direct_local_endpoint_cannot_bypass_public_flag(self):
        os.environ["ANTHROPIC_API_KEY"] = "fake-secret-never-use"
        with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as local:
            with patch("main.review_contract_real") as real, patch("main.get_real_review_settings") as settings:
                response = local.post("/ai-review-real", headers={"Origin": "http://127.0.0.1:8000"},
                    json={"pages": self.pages, "confirmed": True, "PUBLIC_DEMO_ONLY": False})
                self.assertEqual(response.status_code, 403)
                self.assertIn("public demo mode", response.json()["detail"])
                self.assertNotIn("fake-secret", response.text)
                real.assert_not_called()
                settings.assert_not_called()

    def test_public_real_endpoint_rejects_even_malformed_body(self):
        response = self.client.post("/ai-review-real", content="not-json")
        self.assertEqual(response.status_code, 403)
        self.assertIn("public demo mode", response.json()["detail"])

    def test_real_configuration_is_blocked_in_public_mode_including_local_hosts(self):
        self.assertEqual(self.client.get("/ai-review-config").status_code, 403)
        with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as local:
            self.assertEqual(local.get("/ai-review-config").status_code, 403)

    def test_public_demo_works_without_key_even_with_invalid_real_settings(self):
        os.environ["AI_MAX_INPUT_BYTES"] = "invalid"
        response = self.client.post("/ai-review-demo", json={"pages": self.pages})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "mock")
        self.assertEqual([f["status"] for f in response.json()["findings"]],
                         ["verified", "verified", "verification_failed"])
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_unrelated_public_pdf_text_receives_no_mock_findings(self):
        response = self.client.post("/ai-review-demo", json={"pages": [{"number": 1, "text": "Other contract."}]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["findings"], [])

    def test_public_upload_retains_pdf_and_rule_checks(self):
        with pymupdf.open() as pdf:
            page = pdf.new_page()
            page.insert_text((72, 72), 'Section 1.1 Payment\n"Business Day" means a weekday.\nThe Notice Period ends tomorrow.\nSee Section 9.4.')
            contents = pdf.tobytes()
        response = self.client.post("/analyze", files={"file": ("sample.pdf", BytesIO(contents), "application/pdf")})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_pages"], 1)
        self.assertEqual(data["sections"][0]["number"], "1.1")
        self.assertEqual(data["broken_references"][0]["number"], "9.4")
        self.assertEqual(data["potentially_undefined_terms"][0]["term"], "Notice Period")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_public_upload_type_size_and_invalid_pdf_limits_remain(self):
        for filename, contents, expected in [
            ("sample.txt", b"not a pdf", 400),
            ("sample.pdf", b"not a pdf", 400),
            ("large.pdf", b"x" * (MAX_FILE_SIZE + 1), 413),
        ]:
            with self.subTest(filename=filename):
                response = self.client.post("/analyze", files={"file": (filename, contents, "application/pdf")})
                self.assertEqual(response.status_code, expected)

    def test_public_warning_assets_and_secret_paths(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn('id="prototype-warning"', home.text)
        self.assertIn("Do not upload confidential or personal legal documents", home.text)
        self.assertEqual(self.client.get("/review.js").status_code, 200)
        self.assertEqual(self.client.get("/demo-contract.pdf").status_code, 200)
        for path in ["/.env", "/.env.production", "/.git/config", "/ai_reviewer.py"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class RailwayConfigurationTests(unittest.TestCase):
    def test_start_command_uses_platform_port_and_forces_demo_mode(self):
        config = json.loads((BASE_DIR / "railway.json").read_text())
        self.assertEqual(config["build"]["builder"], "RAILPACK")
        self.assertEqual(config["deploy"]["healthcheckPath"], "/health")
        self.assertEqual(config["deploy"]["healthcheckTimeout"], 60)
        # Execute the real shell command against a fake python executable: no server/network.
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / "python"
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$PUBLIC_DEMO_ONLY" "$@"\n')
            python.chmod(0o700)
            result = subprocess.run(["/bin/sh", "-c", config["deploy"]["startCommand"]],
                env={"PATH": directory, "PORT": "43210", "PUBLIC_DEMO_ONLY": "false", "ENABLE_REAL_AI": "true"},
                text=True, capture_output=True, timeout=10, check=True)
        self.assertEqual(result.stdout.splitlines(), ["true", "-m", "uvicorn", "main:app",
            "--host", "0.0.0.0", "--port", "43210", "--no-access-log"])

    def test_python_version_and_production_dependencies_are_declared(self):
        self.assertEqual((BASE_DIR / ".python-version").read_text().strip(), "3.13")
        dependencies = {line.split("==")[0].lower() for line in (BASE_DIR / "requirements.txt").read_text().splitlines() if line.strip()}
        self.assertTrue({"fastapi", "uvicorn", "pymupdf", "python-multipart", "anthropic", "python-dotenv"} <= dependencies)

    def test_git_and_cli_deployment_ignore_real_environment_files(self):
        paths = [".env", ".env.local", ".env.production", ".venv/secret.txt"]
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(["git", "init", "--quiet", directory], check=True, capture_output=True, timeout=10)
            for ignore in [".gitignore", ".railwayignore"]:
                # Evaluate each file independently, without real credentials or the other ignore file.
                result = subprocess.run(["git", "-c", f"core.excludesFile={BASE_DIR / ignore}",
                    "check-ignore", "--no-index", "--stdin"], cwd=directory,
                    input="\n".join(paths + [".env.example"]) + "\n", text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(set(result.stdout.splitlines()), set(paths))
        tracked = subprocess.run(["git", "ls-files", ".env", ".env.*"], cwd=BASE_DIR,
            text=True, capture_output=True, timeout=10, check=True)
        self.assertEqual(tracked.stdout.splitlines(), [".env.example"])


if __name__ == "__main__":
    unittest.main()
