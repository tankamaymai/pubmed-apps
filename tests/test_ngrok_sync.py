import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shoulder_digest.app import ShoulderDigestApp
from shoulder_digest.config import Settings
from shoulder_digest.ngrok_sync import (
    ENV_KEY,
    fetch_ngrok_https_url,
    rebuild_image_url,
    sync_public_base_url,
    update_env_file,
)


class NgrokSyncTests(unittest.TestCase):
    def test_fetch_ngrok_https_url_matches_port(self):
        payload = {
            "tunnels": [
                {
                    "public_url": "http://abc.ngrok-free.app",
                    "config": {"addr": "http://localhost:8765"},
                },
                {
                    "public_url": "https://7db9.ngrok-free.app",
                    "config": {"addr": "http://localhost:8765"},
                },
            ]
        }

        with patch("shoulder_digest.ngrok_sync.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
            self.assertEqual(fetch_ngrok_https_url(port=8765), "https://7db9.ngrok-free.app")

    def test_update_env_file_replaces_existing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text("FOO=1\nSHOULDER_DIGEST_PUBLIC_BASE_URL=https://old.example\n", encoding="utf-8")
            changed = update_env_file(env_path, ENV_KEY, "https://new.example")
            self.assertTrue(changed)
            text = env_path.read_text(encoding="utf-8")
            self.assertIn("SHOULDER_DIGEST_PUBLIC_BASE_URL=https://new.example", text)
            self.assertNotIn("https://old.example", text)

    def test_sync_public_base_url_writes_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            env_path.write_text(f"{ENV_KEY}=\n", encoding="utf-8")
            payload = {
                "tunnels": [
                    {
                        "public_url": "https://7db9.ngrok-free.app",
                        "config": {"addr": "http://localhost:8765"},
                    }
                ]
            }
            with patch("shoulder_digest.ngrok_sync.urllib.request.urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode("utf-8")
                result = sync_public_base_url(env_path, port=8765, max_attempts=1)
            self.assertTrue(result["ok"])
            self.assertEqual(result["url"], "https://7db9.ngrok-free.app")
            self.assertIn("https://7db9.ngrok-free.app", env_path.read_text(encoding="utf-8"))

    def test_rebuild_image_url(self):
        url = rebuild_image_url(
            "https://7db9.ngrok-free.app",
            ".pubmed_digest/images/2026-06-14-ig_test.png",
        )
        self.assertEqual(url, "https://7db9.ngrok-free.app/generated-images/2026-06-14-ig_test.png")

    def test_approve_send_refreshes_image_url_from_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "digest.sqlite3",
                mock_ai=True,
                line_group_id="C123",
                line_channel_access_token="token",
                line_channel_secret="secret",
                public_base_url="https://old.example",
            )
            app = ShoulderDigestApp(settings)
            app.run_daily("2026-06-08", dry_run=True)
            image_path = str(Path(tmp) / "2026-06-08-test.png")
            Path(image_path).write_bytes(b"png")
            with app.storage.session() as conn:
                conn.execute(
                    "UPDATE runs SET image_path = ?, image_url = ? WHERE run_date = ?",
                    (image_path, "https://old.example/generated-images/stale.png", "2026-06-08"),
                )

            class FakeLine:
                def push(self, to, messages, dry_run=False):
                    return {"status": "sent", "payload": {"to": to, "messages": messages}}

            app.line = FakeLine()
            with patch.object(app, "_sync_public_base_url", return_value={"ok": True, "url": "https://new.example"}):
                app.settings.public_base_url = "https://new.example"
                result = app.approve_send("2026-06-08", dry_run=True)

            image_message = result["payload"]["messages"][0]
            self.assertEqual(
                image_message["originalContentUrl"],
                "https://new.example/generated-images/2026-06-08-test.png",
            )


if __name__ == "__main__":
    unittest.main()
