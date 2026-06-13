import tempfile
import unittest
from pathlib import Path

from shoulder_digest.models import Paper
from shoulder_digest.storage import Storage


class StorageTests(unittest.TestCase):
    def test_known_pmids_only_counts_delivered_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "digest.sqlite3")
            storage.upsert_run("2026-06-08", "running", True)
            storage.save_candidates(
                "2026-06-08",
                [Paper(pmid="123", title="Shoulder paper", abstract="A" * 100)],
            )
            self.assertNotIn("123", storage.known_pmids())

            storage.upsert_run("2026-06-08", "delivered", True)
            storage.mark_pmids_delivered(["123"], "2026-06-08")
            self.assertIn("123", storage.known_pmids())
            self.assertNotIn("123", storage.known_pmids("2026-06-08"))

    def test_known_pmids_exclude_run_date_allows_rerun_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "digest.sqlite3")
            storage.mark_pmids_delivered(["123", "456"], "2026-06-07")
            storage.mark_pmids_delivered(["789"], "2026-06-08")
            self.assertIn("123", storage.known_pmids("2026-06-08"))
            self.assertNotIn("789", storage.known_pmids("2026-06-08"))


if __name__ == "__main__":
    unittest.main()

