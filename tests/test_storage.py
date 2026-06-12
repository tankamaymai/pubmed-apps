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
            storage.mark_pmids_delivered(["123"])
            self.assertIn("123", storage.known_pmids())


if __name__ == "__main__":
    unittest.main()

