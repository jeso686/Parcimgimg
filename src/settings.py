from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class AppSettings:
    url: str
    output_dir: Path
    max_images: int = 20
    only_single_largest: bool = True
    upscale_factor: float = 1.0
    timeout_seconds: int = 45
    headless: bool = True

    def normalized_output_dir(self) -> Path:
        """Возвращает безопасный путь папки для сохранения."""
        return self.output_dir.expanduser().resolve()
