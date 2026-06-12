import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shoulder_digest.app import ShoulderDigestApp
from shoulder_digest.config import Settings
from shoulder_digest.models import Paper
from shoulder_digest.server import render_setup


class FakePubMed:
    def search_recent(self, run_date, retmax=80, lookback_days=1):
        self.last_lookback = lookback_days
        return ["1", "2", "3"]

    def fetch_details(self, pmids):
        papers = []
        for pmid in pmids:
            papers.append(
                Paper(
                    pmid=pmid,
                    title=f"Rotator cuff shoulder study {pmid}",
                    abstract="Patients with rotator cuff tears were randomized in a rehabilitation trial with clinical outcomes. " * 4,
                    journal="J Shoulder",
                    publication_date="2026-06-08",
                    pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    article_types=["Randomized Controlled Trial"],
                    topics=["rotator cuff", "shoulder", "rehabilitation"],
                    relevance_score=10,
                    evidence_type="Randomized Controlled Trial",
                )
            )
        return papers


class FakeLine:
    def __init__(self):
        self.calls = []

    def push(self, to, messages, dry_run=False):
        self.calls.append((to, messages, dry_run))
        return {"status": "sent", "payload": {"to": to, "messages": messages}}


class AppFlowTests(unittest.TestCase):
    def test_dry_run_flow_without_external_services(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "digest.sqlite3", mock_ai=True)
            app = ShoulderDigestApp(settings)
            app.pubmed = FakePubMed()
            result = app.run_daily("2026-06-08", dry_run=True)
            self.assertEqual(result["status"], "ready_for_approval")
            run = app.get_run("2026-06-08")
            self.assertEqual(len(run["papers"]), 1)

            app.storage.set_setting("line_group_id", "C123")
            send = app.approve_send("2026-06-08", dry_run=True)
            self.assertTrue(send["dryRun"])
            self.assertEqual(send["payload"]["to"], "C123")

    def test_auto_send_after_daily_run_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "digest.sqlite3",
                mock_ai=True,
                auto_send=True,
                line_group_id="C123",
                line_channel_access_token="token",
                line_channel_secret="secret",
                public_base_url="https://example.com",
            )
            app = ShoulderDigestApp(settings)
            app.pubmed = FakePubMed()
            fake_line = FakeLine()
            app.line = fake_line
            generated = Path(tmp) / "generated.png"
            generated.write_bytes(b"png")
            with patch("shoulder_digest.app.generate_image_with_codex", return_value=generated):
                result = app.run_daily("2026-06-08", dry_run=False)
            self.assertEqual(result["status"], "delivered")
            self.assertEqual(len(fake_line.calls), 1)
            self.assertEqual(fake_line.calls[0][0], "C123")

    def test_rerun_after_delivered_picks_next_paper(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(db_path=Path(tmp) / "digest.sqlite3", mock_ai=True)
            app = ShoulderDigestApp(settings)
            app.pubmed = FakePubMed()
            app.run_daily("2026-06-08", dry_run=True)
            app.storage.upsert_run("2026-06-08", "delivered", True)
            result = app.run_daily("2026-06-08", dry_run=True)
            self.assertEqual(result["status"], "ready_for_approval")
            run = app.get_run("2026-06-08")
            self.assertNotEqual(run["papers"][0]["pmid"], "1")

    def test_resend_after_delivered(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                db_path=Path(tmp) / "digest.sqlite3",
                mock_ai=True,
                line_group_id="C123",
                line_channel_access_token="token",
                line_channel_secret="secret",
                public_base_url="https://example.com",
            )
            app = ShoulderDigestApp(settings)
            app.pubmed = FakePubMed()
            fake_line = FakeLine()
            app.line = fake_line
            app.run_daily("2026-06-08", dry_run=True)
            with app.storage.session() as conn:
                conn.execute(
                    "UPDATE runs SET image_url = ? WHERE run_date = ?",
                    ("https://example.com/test.png", "2026-06-08"),
                )
            app.storage.upsert_run("2026-06-08", "delivered", True)
            result = app.approve_send("2026-06-08", dry_run=False)
            self.assertEqual(result["status"], "sent")
            self.assertEqual(len(fake_line.calls), 1)

    def test_render_setup_contains_status_rows(self):
        html = render_setup(
            {
                "setup_items": [{"label": "Codex", "ok": True, "detail": "installed"}],
                "ready_for_mock_dry_run": True,
                "ready_for_real_digest": False,
                "ready_for_notion_archive": False,
                "ready_for_line_delivery": False,
                "ready_for_end_to_end": False,
                "codex_login_ok": True,
                "line_token": False,
                "line_secret": False,
                "line_group_id": False,
                "line_image_delivery_ready": False,
            }
        )
        self.assertIn("Setup Status", html)
        self.assertIn("Codex", html)
        self.assertIn("Mock dry-run", html)
        self.assertIn("Next Steps", html)
        self.assertIn("LINE_CHANNEL_ACCESS_TOKEN", html)
        self.assertIn('/setup/line-group', html)


if __name__ == "__main__":
    unittest.main()
