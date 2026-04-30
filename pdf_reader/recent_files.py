"""Recent files list backed by QSettings (Windows registry)."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings


_KEY = "recentFiles"
_MAX = 10


class RecentFiles:
    def __init__(self, org: str = "PdfReader", app: str = "App"):
        self.settings = QSettings(org, app)

    def list(self) -> list[str]:
        raw = self.settings.value(_KEY, [], type=list) or []
        out: list[str] = []
        for p in raw:
            if isinstance(p, str) and Path(p).exists() and p not in out:
                out.append(p)
        return out[:_MAX]

    def add(self, path: str) -> None:
        path = str(Path(path).resolve())
        items = [p for p in self.list() if p != path]
        items.insert(0, path)
        self.settings.setValue(_KEY, items[:_MAX])

    def clear(self) -> None:
        self.settings.remove(_KEY)
