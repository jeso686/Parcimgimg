from __future__ import annotations

import io
import re
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
from PIL import Image

from .models import DownloadResult, ImageCandidate


_INVALID_FILE_CHARS = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_file_name(url: str, index: int) -> str:
    """Генерирует безопасное имя файла из URL."""
    parsed = urlparse(url)
    name = Path(parsed.path).name or f"image_{index}.bin"
    cleaned = _INVALID_FILE_CHARS.sub("_", name)
    return cleaned[:120] or f"image_{index}.bin"


async def download_image(
    session: aiohttp.ClientSession,
    candidate: ImageCandidate,
    output_dir: Path,
    index: int,
    upscale_factor: float,
) -> DownloadResult:
    """Скачивает изображение и при необходимости увеличивает его размер."""
    async with session.get(candidate.url, timeout=aiohttp.ClientTimeout(total=120)) as response:
        response.raise_for_status()
        data = await response.read()

    output_dir.mkdir(parents=True, exist_ok=True)
    file_name = _safe_file_name(candidate.url, index)
    save_path = output_dir / file_name

    upscaled = False
    width = candidate.width
    height = candidate.height

    # Пытаемся работать через Pillow, чтобы корректно определить размеры.
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size

        if upscale_factor > 1.0:
            upscaled = True
            new_size = (
                max(1, int(width * upscale_factor)),
                max(1, int(height * upscale_factor)),
            )
            image = image.resize(new_size, Image.Resampling.LANCZOS)
            width, height = image.size

        image.save(save_path)
    except Exception:
        # Если это не формат картинки для Pillow, сохраняем как есть.
        with save_path.open("wb") as file:
            file.write(data)

    return DownloadResult(
        source_url=candidate.url,
        saved_path=save_path,
        width=width,
        height=height,
        upscaled=upscaled,
    )
