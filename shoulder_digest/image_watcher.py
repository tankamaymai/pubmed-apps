from __future__ import annotations

import time
from pathlib import Path

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class ImageWatcher:
    def __init__(self, directory: Path):
        self.directory = directory

    def snapshot(self) -> set[Path]:
        if not self.directory.exists():
            return set()
        return {path.resolve() for path in self.directory.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS}

    def newest_after(self, before: set[Path], started_at: float, wait_seconds: int = 30) -> Path | None:
        deadline = time.monotonic() + wait_seconds
        newest: Path | None = None
        while time.monotonic() < deadline:
            candidates = []
            for path in self.snapshot() - before:
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    continue
                if stat.st_mtime >= started_at - 1:
                    candidates.append((stat.st_mtime, path))
            if candidates:
                newest = max(candidates, key=lambda item: item[0])[1]
                if _looks_stable(newest):
                    return newest
            time.sleep(0.5)
        return newest


def _looks_stable(path: Path) -> bool:
    try:
        first = path.stat().st_size
        time.sleep(0.8)
        second = path.stat().st_size
    except FileNotFoundError:
        return False
    return first > 0 and first == second
