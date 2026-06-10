import unittest

from shoulder_digest.diagnostics import build_checks, doctor_exit_code, setup_items
from shoulder_digest.config import Settings
from shoulder_digest.storage import Storage
from pathlib import Path
import tempfile


class DiagnosticsTests(unittest.TestCase):
    def test_doctor_exit_code_requires_login_for_real_run(self):
        checks = {"codex_found": True, "codex_runnable": True, "codex_login_ok": False, "mock_ai": False}
        self.assertEqual(doctor_exit_code(checks), 3)
        checks["mock_ai"] = True
        self.assertEqual(doctor_exit_code(checks), 0)

    def test_setup_items_does_not_mark_login_ok_in_mock_mode(self):
        checks = {
            "codex_runnable": True,
            "codex_version": "codex-cli test",
            "codex_login_ok": False,
            "codex_login_status": "Not logged in",
            "mock_ai": True,
            "codex_schema_file_count": 1,
            "ncbi_api_key": True,
            "pubmed_eutilities_ready": True,
            "notion_validation": {"ok": True},
            "line_token": True,
            "line_secret": True,
            "line_group_id": True,
            "line_image_delivery_ready": True,
        }
        items = setup_items(checks)
        login = next(item for item in items if item["label"] == "Codex ChatGPT login")
        self.assertFalse(login["ok"])

    def test_setup_items_reports_line_requirements(self):
        checks = {
            "codex_runnable": True,
            "codex_version": "codex-cli test",
            "codex_login_ok": True,
            "codex_login_status": "Logged in",
            "mock_ai": False,
            "codex_schema_file_count": 1,
            "ncbi_api_key": True,
            "pubmed_eutilities_ready": True,
            "notion_validation": {"ok": True},
            "line_token": True,
            "line_secret": False,
            "line_group_id": True,
            "line_image_delivery_ready": False,
        }
        items = setup_items(checks)
        line = next(item for item in items if item["label"] == "LINE Messaging API")
        public_url = next(item for item in items if item["label"] == "Public image URL")
        self.assertFalse(line["ok"])
        self.assertFalse(public_url["ok"])

    def test_pubmed_item_is_ready_without_api_key(self):
        checks = {
            "codex_runnable": True,
            "codex_version": "codex-cli test",
            "codex_login_ok": True,
            "codex_login_status": "Logged in",
            "mock_ai": False,
            "codex_schema_file_count": 1,
            "ncbi_api_key": False,
            "pubmed_eutilities_ready": True,
            "notion_validation": {"ok": True},
            "line_token": True,
            "line_secret": True,
            "line_group_id": True,
            "line_image_delivery_ready": True,
        }
        items = setup_items(checks)
        pubmed = next(item for item in items if item["label"] == "PubMed E-utilities")
        self.assertTrue(pubmed["ok"])

    def test_build_checks_uses_stored_line_group_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "digest.sqlite3",
                mock_ai=True,
                line_channel_access_token="token",
                line_channel_secret="secret",
                public_base_url="https://example.com",
            )
            Storage(settings.db_path).set_setting("line_group_id", "C123")
            checks = build_checks(settings)
            self.assertTrue(checks["line_group_id"])
            self.assertEqual(checks["line_group_id_source"], "webhook_storage")
            self.assertEqual(checks["line_api_base_url"], "https://api.line.me")
            self.assertEqual(checks["notion_api_base_url"], "https://api.notion.com")


if __name__ == "__main__":
    unittest.main()
