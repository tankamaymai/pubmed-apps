import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from shoulder_digest.__main__ import main
from shoulder_digest.config import Settings
from shoulder_digest.preflight import extract_enums, run_preflight, validate_codex_schema


class PreflightTests(unittest.TestCase):
    def test_extract_enums_finds_methods(self):
        schema = {
            "properties": {
                "method": {"enum": ["initialize", "thread/start", "plain"]},
                "nested": {"enum": ["turn/completed"]},
            }
        }
        self.assertEqual(extract_enums(schema), {"initialize", "thread/start", "turn/completed"})

    def test_validate_codex_schema_reports_required_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            schema_dir = Path(tmp)
            (schema_dir / "ClientRequest.json").write_text(
                json.dumps({"enum": ["initialize", "thread/start", "turn/start"]}),
                encoding="utf-8",
            )
            (schema_dir / "ServerNotification.json").write_text(
                json.dumps({"enum": ["thread/started", "turn/started", "turn/completed", "item/agentMessage/delta"]}),
                encoding="utf-8",
            )
            result = validate_codex_schema(schema_dir)
            self.assertTrue(result["ok"])

    def test_run_preflight_lists_external_missing_items(self):
        settings = Settings(mock_ai=True)
        result = run_preflight(settings, live_pubmed=False)
        self.assertFalse(result["ok"])
        self.assertTrue(any("codex login" in item for item in result["missing"]))

    def test_preflight_cli_allow_incomplete_returns_zero(self):
        with redirect_stdout(StringIO()) as out:
            self.assertEqual(main(["preflight", "--allow-incomplete"]), 0)
        payload = json.loads(out.getvalue())
        self.assertIn("missing", payload)


if __name__ == "__main__":
    unittest.main()

