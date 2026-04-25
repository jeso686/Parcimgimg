from __future__ import annotations

import asyncio
import io
import random
import re
from collections.abc import Callable
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup
from PIL import Image
from playwright.async_api import async_playwright

from .models import ImageCandidate
from .settings import AppSettings

ProgressCallback = Callable[[str], None]


def _extract_srcset_candidates(base_url: str, srcset_value: str) -> list[str]:
    """Парсит srcset и возвращает список абсолютных ссылок на изображения."""
    urls: list[str] = []
    for part in srcset_value.split(","):
        piece = part.strip().split(" ")[0].strip()
        if not piece:
            continue
        urls.append(urljoin(base_url, piece))
    return urls


def _extract_css_backgrounds(base_url: str, html: str) -> list[str]:
    """Извлекает URL из CSS background-image конструкций."""
    found = re.findall(r"background(?:-image)?\s*:\s*url\(([^)]+)\)", html, flags=re.IGNORECASE)
    urls: list[str] = []
    for item in found:
        clean = item.strip("'\" ")
        if clean:
            urls.append(urljoin(base_url, clean))
    return urls


async def _human_like_actions(page, progress: ProgressCallback) -> None:
    """Эмулирует поведение человека: паузы, движение мыши, скролл."""
    progress("Имитация пользователя: естественные паузы.")
    await asyncio.sleep(random.uniform(0.6, 1.6))

    viewport = page.viewport_size or {"width": 1280, "height": 720}
    width, height = viewport["width"], viewport["height"]

    for _ in range(random.randint(2, 5)):
        x = random.randint(20, max(20, width - 20))
        y = random.randint(20, max(20, height - 20))
        await page.mouse.move(x, y, steps=random.randint(4, 14))
        await asyncio.sleep(random.uniform(0.2, 0.8))

    scroll_steps = random.randint(3, 8)
    progress(f"Имитация пользователя: прокрутка страницы ({scroll_steps} шагов).")
    for _ in range(scroll_steps):
        await page.mouse.wheel(0, random.randint(260, 760))
        await asyncio.sleep(random.uniform(0.25, 0.9))


async def _probe_dimensions(session: aiohttp.ClientSession, url: str) -> ImageCandidate | None:
    """Проверяет размер изображения по URL и возвращает кандидат."""
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=45)) as response:
            if response.status >= 400:
                return None
            content_type = response.headers.get("Content-Type", "")
            if "image" not in content_type.lower() and not any(
                url.lower().endswith(ext)
                for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".avif")
            ):
                return None

            blob = await response.read()

        image = Image.open(io.BytesIO(blob))
        width, height = image.size
        return ImageCandidate(url=url, width=width, height=height, content_type=content_type)
    except Exception:
        return None


async def collect_best_images(settings: AppSettings, progress: ProgressCallback) -> list[ImageCandidate]:
    """Собирает и ранжирует изображения по максимальному разрешению."""
    progress("Инициализация браузера Playwright.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.headless)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        progress(f"Открываю URL: {settings.url}")
        await page.goto(settings.url, timeout=settings.timeout_seconds * 1000, wait_until="domcontentloaded")

        await _human_like_actions(page, progress)
        await page.wait_for_timeout(1200)

        html = await page.content()
        base_url = page.url
        await context.close()
        await browser.close()

    progress("Разбор HTML и извлечение ссылок на изображения.")

    soup = BeautifulSoup(html, "html.parser")
    discovered_urls: set[str] = set()

    for img in soup.select("img"):
        src = img.get("src")
        if src:
            discovered_urls.add(urljoin(base_url, src))

        srcset = img.get("srcset")
        if srcset:
            discovered_urls.update(_extract_srcset_candidates(base_url, srcset))

    discovered_urls.update(_extract_css_backgrounds(base_url, html))

    progress(f"Найдено {len(discovered_urls)} уникальных кандидатов. Проверяю размеры.")

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [_probe_dimensions(session, url) for url in discovered_urls]
        raw_results = await asyncio.gather(*tasks)

    candidates = [item for item in raw_results if item is not None]
    candidates.sort(key=lambda c: c.pixels, reverse=True)

    progress(f"Валидных изображений: {len(candidates)}.")

    if settings.only_single_largest:
        return candidates[:1]
    return candidates[: settings.max_images]
