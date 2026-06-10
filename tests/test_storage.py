import tempfile
import unittest
from pathlib import Path

from shoulder_digest.models import Paper
from shoulder_digest.storage import Storage


class StorageTests(unittest.TestCase):
    def test_known_pmids_can_exclude_current_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "digest.sqlite3")
            storage.upsert_run("2026-06-08", "running", True)
            storage.save_candidates(
                "2026-06-08",
                [Paper(pmid="123", title="Shoulder paper", abstract="A" * 100)],
            )
            self.assertIn("123", storage.known_pmids())
            self.assertNotIn("123", storage.known_pmids(exclude_run_date="2026-06-08"))


if __name__ == "__main__":
    unittest.main()

