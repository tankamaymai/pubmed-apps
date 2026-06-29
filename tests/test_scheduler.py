import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from shoulder_digest.app import ShoulderDigestApp
from shoulder_digest.config import Settings
from shoulder_digest.server import run_scheduled_daily_if_needed, should_run_scheduled_daily
from shoulder_digest.storage import Storage


class SchedulerTests(unittest.TestCase):
    def test_should_not_run_before_daily_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "digest.sqlite3")
            app = ShoulderDigestApp(settings)
            now = datetime(2026, 6, 12, 6, 30, 0)
            self.assertFalse(should_run_scheduled_daily(app, "07:00", now=now))

    def test_should_run_after_daily_time_if_not_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "digest.sqlite3")
            app = ShoulderDigestApp(settings)
            now = datetime(2026, 6, 12, 8, 0, 0)
            self.assertTrue(should_run_scheduled_daily(app, "07:00", now=now))

    def test_should_not_run_again_after_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "digest.sqlite3")
            app = ShoulderDigestApp(settings)
            Storage(settings.db_path).upsert_run("2026-06-12", "delivered", dry_run=False)
            now = datetime(2026, 6, 12, 8, 0, 0)
            self.assertFalse(should_run_scheduled_daily(app, "07:00", now=now))

    def test_auto_send_when_ready_for_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "digest.sqlite3",
                auto_send=True,
                line_group_id="C123",
                line_channel_access_token="token",
                line_channel_secret="secret",
                public_base_url="https://example.com",
            )
            app = ShoulderDigestApp(settings)
            storage = Storage(settings.db_path)
            storage.upsert_run("2026-06-12", "ready_for_approval", dry_run=False)
            with storage.session() as conn:
                conn.execute(
                    "UPDATE runs SET image_url = ?, digest_summary = ? WHERE run_date = ?",
                    ("https://example.com/test.png", "summary", "2026-06-12"),
                )
            sent = {"count": 0}

            def fake_send(run_date, dry_run=False):
                sent["count"] += 1
                return {"status": "sent"}

            app.approve_send = fake_send  # type: ignore[method-assign]
            now = datetime(2026, 6, 12, 8, 0, 0)
            self.assertTrue(run_scheduled_daily_if_needed(app, "07:00", now=now))
            self.assertEqual(sent["count"], 1)


if __name__ == "__main__":
    unittest.main()
