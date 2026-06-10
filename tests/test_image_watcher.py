import tempfile
import time
import unittest
from pathlib import Path

from shoulder_digest.image_watcher import ImageWatcher


class ImageWatcherTests(unittest.TestCase):
    def test_newest_after_finds_new_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            watcher = ImageWatcher(directory)
            before = watcher.snapshot()
            started_at = time.time()
            image = directory / "digest.png"
            image.write_bytes(b"png")
            found = watcher.newest_after(before, started_at, wait_seconds=2)
            self.assertEqual(found, image.resolve())

    def test_newest_after_finds_image_in_generated_turn_subdirectory(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            watcher = ImageWatcher(directory)
            before = watcher.snapshot()
            started_at = time.time()
            turn_dir = directory / "turn-id"
            turn_dir.mkdir()
            image = turn_dir / "digest.webp"
            image.write_bytes(b"webp")
            found = watcher.newest_after(before, started_at, wait_seconds=2)
            self.assertEqual(found, image.resolve())


if __name__ == "__main__":
    unittest.main()
