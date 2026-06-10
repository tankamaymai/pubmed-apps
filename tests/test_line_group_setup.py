import json
import os
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO

from shoulder_digest.__main__ import main
from shoulder_digest.app import ShoulderDigestApp
from shoulder_digest.config import Settings
from shoulder_digest.server import _make_handler


class LineGroupSetupTests(unittest.TestCase):
    def test_cli_set_line_group_persists_group_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings_path = Path(tmp) / ".env"
            settings_path.write_text(f"SHOULDER_DIGEST_DB={Path(tmp) / 'digest.sqlite3'}\n", encoding="utf-8")
            previous = Path.cwd()
            previous_db = os.environ.pop("SHOULDER_DIGEST_DB", None)
            try:
                os.chdir(tmp)
                with redirect_stdout(StringIO()) as out:
                    self.assertEqual(main(["set-line-group", "--group-id", "C123"]), 0)
                self.assertIn("C123", out.getvalue())
                app = ShoulderDigestApp(Settings.from_env())
                self.assertEqual(app.storage.get_setting("line_group_id"), "C123")
            finally:
                os.chdir(previous)
                if previous_db is not None:
                    os.environ["SHOULDER_DIGEST_DB"] = previous_db
                else:
                    os.environ.pop("SHOULDER_DIGEST_DB", None)

    def test_setup_form_saves_line_group_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "digest.sqlite3", mock_ai=True)
            app = ShoulderDigestApp(settings)
            server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(app, settings))
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                data = urllib.parse.urlencode({"groupId": "C456"}).encode("utf-8")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/setup/line-group",
                    data=data,
                    method="POST",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                payload = json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(app.storage.get_setting("line_group_id"), "C456")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
