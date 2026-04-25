from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ImageCandidate:
    url: str
    width: int
    height: int
    content_type: str | None = None

    @property
    def pixels(self) -> int:
        """Возвращает количество пикселей как метрику качества."""
        return self.width * self.height


@dataclass(slots=True)
class DownloadResult:
    source_url: str
    saved_path: Path
    width: int
    height: int
    upscaled: bool
