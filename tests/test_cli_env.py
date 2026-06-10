import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from shoulder_digest.__main__ import init_env
from shoulder_digest.config import Settings


class CliEnvTests(unittest.TestCase):
    def test_init_env_writes_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            try:
                os.chdir(tmp)
                Path(".env.example").write_text("CODEX_BIN=\nNOTION_DATABASE_ID=\nNCBI_API_KEY=\n", encoding="utf-8")
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    self.assertEqual(init_env(), 0)
                text = Path(".env").read_text(encoding="utf-8")
                self.assertIn("NOTION_DATABASE_ID=c78096bc6401494999e598ed022e84a8", text)
                self.assertIn("CODEX_BIN=", text)
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    self.assertEqual(init_env(), 1)
            finally:
                os.chdir(previous)

    def test_settings_reads_pubmed_lookback_days(self):
        previous = os.environ.get("SHOULDER_DIGEST_PUBMED_LOOKBACK_DAYS")
        try:
            os.environ["SHOULDER_DIGEST_PUBMED_LOOKBACK_DAYS"] = "5"
            self.assertEqual(Settings.from_env().pubmed_lookback_days, 5)
            os.environ["SHOULDER_DIGEST_PUBMED_LOOKBACK_DAYS"] = "0"
            self.assertEqual(Settings.from_env().pubmed_lookback_days, 1)
        finally:
            if previous is None:
                os.environ.pop("SHOULDER_DIGEST_PUBMED_LOOKBACK_DAYS", None)
            else:
                os.environ["SHOULDER_DIGEST_PUBMED_LOOKBACK_DAYS"] = previous

    def test_settings_reads_api_base_urls(self):
        previous_notion = os.environ.get("NOTION_API_BASE_URL")
        previous_line = os.environ.get("LINE_API_BASE_URL")
        try:
            os.environ["NOTION_API_BASE_URL"] = "http://127.0.0.1:9001/"
            os.environ["LINE_API_BASE_URL"] = "http://127.0.0.1:9002/"
            settings = Settings.from_env()
            self.assertEqual(settings.notion_api_base_url, "http://127.0.0.1:9001")
            self.assertEqual(settings.line_api_base_url, "http://127.0.0.1:9002")
        finally:
            if previous_notion is None:
                os.environ.pop("NOTION_API_BASE_URL", None)
            else:
                os.environ["NOTION_API_BASE_URL"] = previous_notion
            if previous_line is None:
                os.environ.pop("LINE_API_BASE_URL", None)
            else:
                os.environ["LINE_API_BASE_URL"] = previous_line


if __name__ == "__main__":
    unittest.main()
