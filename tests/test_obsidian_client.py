import tempfile
import unittest
from pathlib import Path

from shoulder_digest.obsidian_client import ObsidianVaultWriter


class ObsidianClientTests(unittest.TestCase):
    def test_save_digest_writes_note_and_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            source_image = Path(tmp) / "sample.png"
            source_image.write_bytes(b"png")

            writer = ObsidianVaultWriter(vault, "PubMed肩関節")
            result = writer.save_digest(
                "2026-06-11",
                "今日の概要",
                "shoulder infographic prompt",
                [
                    {
                        "pmid": "123",
                        "title": "Rotator cuff study",
                        "japanese_title": "肩腱板RCTの新規研究",
                        "journal": "J Shoulder",
                        "publication_date": "2026-06-10",
                        "pubmed_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
                        "japanese_summary": "肩腱板のRCT研究",
                        "clinical_takeaway": "早期リハビリが重要",
                        "topics": ["rotator cuff"],
                        "evidence_type": "Randomized Controlled Trial",
                        "abstract": "Abstract text",
                    }
                ],
                source_image_path=str(source_image),
            )

            note_path = vault / "PubMed肩関節" / "肩腱板RCTの新規研究.md"
            image_path = vault / "PubMed肩関節" / "attachments" / "123-sample.png"
            self.assertTrue(note_path.exists())
            self.assertTrue(image_path.exists())
            content = note_path.read_text(encoding="utf-8")
            self.assertIn("run_date: 2026-06-11", content)
            self.assertIn("# 肩腱板RCTの新規研究", content)
            self.assertIn("![[attachments/123-sample.png]]", content)
            self.assertIn("肩腱板のRCT研究", content)
            self.assertEqual(result["note_path"], str(note_path))

    def test_mark_delivered_updates_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            writer = ObsidianVaultWriter(vault, "PubMed肩関節")
            writer.save_digest(
                "2026-06-11",
                "summary",
                "",
                [{"pmid": "123", "title": "Study", "japanese_title": "研究タイトル"}],
            )
            writer.mark_delivered("2026-06-11")
            content = (vault / "PubMed肩関節" / "研究タイトル.md").read_text(encoding="utf-8")
            self.assertIn("status: delivered", content)

    def test_validate_vault_reports_missing_path(self):
        writer = ObsidianVaultWriter(Path("/missing/vault"), "PubMed肩関節")
        validation = writer.validate_vault()
        self.assertFalse(validation["ok"])


if __name__ == "__main__":
    unittest.main()
