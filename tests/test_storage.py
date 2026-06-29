import json
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
            storage._record_line_delivery(
                "2026-06-08",
                ["123"],
                {"messages": [{"text": "https://pubmed.ncbi.nlm.nih.gov/123/"}]},
            )
            self.assertIn("123", storage.known_pmids())

    def test_known_pmids_tracks_line_deliveries_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "digest.sqlite3")
            storage.mark_pmids_delivered(["999"], "2026-06-08")
            self.assertNotIn("999", storage.known_pmids())
            storage._record_line_delivery(
                "2026-06-08",
                ["999"],
                {"messages": [{"text": "https://pubmed.ncbi.nlm.nih.gov/999/"}]},
            )
            self.assertIn("999", storage.known_pmids())

    def test_already_delivered_pmids(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "digest.sqlite3")
            storage._record_line_delivery(
                "2026-06-08",
                ["123"],
                {"messages": [{"text": "https://pubmed.ncbi.nlm.nih.gov/123/"}]},
            )
            self.assertEqual(storage.already_delivered_pmids(["123", "456"]), ["123"])

    def test_extract_pmids_from_run(self):
        pmids = Storage.extract_pmids_from_run(
            {
                "papers": [{"pmid": "123"}],
                "line_payload": json.dumps(
                    {"messages": [{"text": "https://pubmed.ncbi.nlm.nih.gov/456/"}]}
                ),
            }
        )
        self.assertEqual(pmids, ["123"])

    def test_known_pmids_always_excludes_same_day_deliveries(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "digest.sqlite3")
            storage.mark_pmids_delivered(["123", "456"], "2026-06-07")
            storage._record_line_delivery(
                "2026-06-07",
                ["123"],
                {"messages": [{"text": "https://pubmed.ncbi.nlm.nih.gov/123/"}]},
            )
            storage._record_line_delivery(
                "2026-06-08",
                ["789"],
                {"messages": [{"text": "https://pubmed.ncbi.nlm.nih.gov/789/"}]},
            )
            known = storage.known_pmids()
            self.assertIn("123", known)
            self.assertIn("789", known)

    def test_arthroplasty_deliveries_in_month_counts_delivered_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "digest.sqlite3")
            storage.upsert_run("2026-06-10", "delivered", False)
            storage.save_candidates(
                "2026-06-10",
                [
                    Paper(
                        pmid="111",
                        title="Reverse total shoulder arthroplasty outcomes",
                        abstract="Patients underwent RTSA. " * 4,
                    )
                ],
            )
            storage._record_line_delivery(
                "2026-06-10",
                ["111"],
                {"messages": [{"text": "https://pubmed.ncbi.nlm.nih.gov/111/"}]},
            )

            storage.upsert_run("2026-06-12", "delivered", False)
            storage.save_candidates(
                "2026-06-12",
                [
                    Paper(
                        pmid="222",
                        title="Scapular dyskinesis rehabilitation protocol",
                        abstract="Physical therapy and range of motion exercises. " * 4,
                    )
                ],
            )
            storage._record_line_delivery(
                "2026-06-12",
                ["222"],
                {"messages": [{"text": "https://pubmed.ncbi.nlm.nih.gov/222/"}]},
            )

            self.assertEqual(storage.arthroplasty_deliveries_in_month("2026-06-15"), 1)
            self.assertEqual(storage.arthroplasty_deliveries_in_month("2026-07-01"), 0)


if __name__ == "__main__":
    unittest.main()

