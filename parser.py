from __future__ import annotations

import asyncio
import hashlib
import random
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image
from playwright.async_api import Browser, BrowserContext, Page, async_playwright


LOG_FN = Callable[[str], None]
PROGRESS_FN = Callable[[int, int], None]


@dataclass
class ImageCandidate:
    source_page: str
    original_url: str
    resolved_url: str
    width_hint: int | None = None
    height_hint: int | None = None


@dataclass
class DownloadedImage:
    url: str
    file_path: Path
    width: int
    height: int
    byte_size: int


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]


class HumanLikeImageParser:
    def __init__(
        self,
        target_url: str,
        download_dir: Path,
        max_images: int,
        min_width: int,
        min_height: int,
        timeout_sec: int,
        upscale_small: bool,
        upscale_factor: float,
    ) -> None:
        self.target_url = target_url
        self.download_dir = download_dir
        self.max_images = max_images
        self.min_width = min_width
        self.min_height = min_height
        self.timeout_sec = timeout_sec
        self.upscale_small = upscale_small
        self.upscale_factor = upscale_factor
        self.download_dir.mkdir(parents=True, exist_ok=True)

    async def run(self, log: LOG_FN, progress: PROGRESS_FN) -> list[DownloadedImage]:
        candidates = await self._collect_candidates(log)
        log(f"Найдено {len(candidates)} кандидатов изображений до фильтрации.")

        grouped = self._group_by_base(candidates)
        log(f"Сгруппировано в {len(grouped)} уникальных изображений.")

        selected = []
        for _, group in grouped.items():
            best = self._pick_highest_hint(group)
            selected.append(best)

        selected = selected[: self.max_images]
        log(f"Для скачивания выбрано {len(selected)} изображений.")

        downloads = await self._download_best_images(selected, log, progress)
        log(f"Завершено: сохранено {len(downloads)} файлов.")
        return downloads

    async def _collect_candidates(self, log: LOG_FN) -> list[ImageCandidate]:
        ua = random.choice(USER_AGENTS)
        log("Запуск браузера Playwright в режиме эмуляции пользователя...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await self._build_context(browser, ua)
            page = await context.new_page()

            await page.goto(self.target_url, wait_until="domcontentloaded", timeout=self.timeout_sec * 1000)
            await self._human_like_behavior(page, log)

            html = await page.content()
            candidates = self._extract_from_html(self.target_url, html)

            # Сбор URL картинок из динамически подгруженных элементов.
            dom_urls = await page.eval_on_selector_all(
                "img",
                """
                nodes => nodes.flatMap(n => {
                    const src = n.getAttribute('src');
                    const currentSrc = n.currentSrc;
                    const srcset = n.getAttribute('srcset');
                    return [src, currentSrc, srcset].filter(Boolean);
                })
                """,
            )
            for row in dom_urls:
                if "," in row or " " in row and "http" in row and row.count("http") > 1:
                    candidates.extend(self._parse_srcset(self.target_url, row))
                else:
                    resolved = urljoin(self.target_url, row)
                    candidates.append(
                        ImageCandidate(
                            source_page=self.target_url,
                            original_url=row,
                            resolved_url=resolved,
                        )
                    )

            await context.close()
            await browser.close()

        return self._clean_candidates(candidates)

    async def _build_context(self, browser: Browser, user_agent: str) -> BrowserContext:
        viewport = {"width": random.randint(1280, 1680), "height": random.randint(720, 1024)}
        context = await browser.new_context(user_agent=user_agent, viewport=viewport, locale="en-US")
        return context

    async def _human_like_behavior(self, page: Page, log: LOG_FN) -> None:
        # Имитация поведения живого пользователя: паузы, скролл, легкие движения.
        await asyncio.sleep(random.uniform(1.2, 2.4))
        for i in range(random.randint(4, 8)):
            scroll_by = random.randint(300, 900)
            await page.mouse.wheel(0, scroll_by)
            log(f"Скролл страницы: шаг {i + 1}, смещение {scroll_by}px")
            await asyncio.sleep(random.uniform(0.4, 1.3))

        for _ in range(random.randint(2, 5)):
            x = random.randint(60, 1000)
            y = random.randint(60, 700)
            await page.mouse.move(x, y, steps=random.randint(8, 20))
            await asyncio.sleep(random.uniform(0.2, 0.8))

        await page.wait_for_load_state("networkidle", timeout=self.timeout_sec * 1000)

    def _extract_from_html(self, page_url: str, html: str) -> list[ImageCandidate]:
        soup = BeautifulSoup(html, "lxml")
        results: list[ImageCandidate] = []

        for img in soup.select("img"):
            src = img.get("src")
            srcset = img.get("srcset")
            w = self._safe_int(img.get("width"))
            h = self._safe_int(img.get("height"))

            if src:
                results.append(
                    ImageCandidate(
                        source_page=page_url,
                        original_url=src,
                        resolved_url=urljoin(page_url, src),
                        width_hint=w,
                        height_hint=h,
                    )
                )

            if srcset:
                results.extend(self._parse_srcset(page_url, srcset, fallback_w=w, fallback_h=h))

        return results

    def _parse_srcset(
        self,
        page_url: str,
        srcset: str,
        fallback_w: int | None = None,
        fallback_h: int | None = None,
    ) -> list[ImageCandidate]:
        items: list[ImageCandidate] = []
        for part in srcset.split(","):
            piece = part.strip()
            if not piece:
                continue
            tokens = piece.split()
            url = tokens[0]
            width = None
            if len(tokens) > 1 and tokens[1].endswith("w"):
                width = self._safe_int(tokens[1][:-1])
            resolved = urljoin(page_url, url)
            items.append(
                ImageCandidate(
                    source_page=page_url,
                    original_url=url,
                    resolved_url=resolved,
                    width_hint=width or fallback_w,
                    height_hint=fallback_h,
                )
            )
        return items

    def _clean_candidates(self, candidates: Iterable[ImageCandidate]) -> list[ImageCandidate]:
        cleaned: list[ImageCandidate] = []
        seen: set[str] = set()

        for c in candidates:
            if not c.resolved_url.startswith(("http://", "https://")):
                continue
            if any(ext in c.resolved_url.lower() for ext in [".svg", ".gif", ".ico"]):
                continue
            key = c.resolved_url.split("#", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(c)

        return cleaned

    def _group_by_base(self, candidates: list[ImageCandidate]) -> dict[str, list[ImageCandidate]]:
        grouped: dict[str, list[ImageCandidate]] = {}
        for c in candidates:
            base = self._base_signature(c.resolved_url)
            grouped.setdefault(base, []).append(c)
        return grouped

    def _base_signature(self, url: str) -> str:
        parsed = urlparse(url)
        normalized = re.sub(r"(_\d+x\d+|[-_]small|[-_]thumb|[-_]large|[?&]w=\d+|[?&]h=\d+)", "", parsed.path)
        return f"{parsed.netloc}{normalized}"

    def _pick_highest_hint(self, group: list[ImageCandidate]) -> ImageCandidate:
        return sorted(group, key=lambda c: (c.width_hint or 0, c.height_hint or 0, len(c.resolved_url)), reverse=True)[0]

    async def _download_best_images(
        self,
        selected: list[ImageCandidate],
        log: LOG_FN,
        progress: PROGRESS_FN,
    ) -> list[DownloadedImage]:
        downloaded: list[DownloadedImage] = []
        headers = {"User-Agent": random.choice(USER_AGENTS)}

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=self.timeout_sec) as client:
            total = len(selected)
            for idx, candidate in enumerate(selected, 1):
                try:
                    response = await client.get(candidate.resolved_url)
                    response.raise_for_status()
                    content = response.content
                    image = Image.open(BytesIO(content)).convert("RGB")
                    width, height = image.size

                    if width < self.min_width or height < self.min_height:
                        log(f"Пропуск (маленькое): {candidate.resolved_url} -> {width}x{height}")
                        progress(idx, total)
                        continue

                    if self.upscale_small and (width < self.min_width * 2 or height < self.min_height * 2):
                        # Увеличиваем небольшие изображения, если включен режим upscaling.
                        new_w = int(width * self.upscale_factor)
                        new_h = int(height * self.upscale_factor)
                        image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        width, height = image.size
                        log(f"Upscale: {candidate.resolved_url} -> {width}x{height}")

                    filename = self._make_filename(candidate.resolved_url, idx)
                    out_path = self.download_dir / filename
                    image.save(out_path, format="JPEG", quality=95)

                    downloaded.append(
                        DownloadedImage(
                            url=candidate.resolved_url,
                            file_path=out_path,
                            width=width,
                            height=height,
                            byte_size=out_path.stat().st_size,
                        )
                    )
                    log(f"Сохранено: {out_path.name} ({width}x{height})")
                except Exception as exc:
                    log(f"Ошибка скачивания {candidate.resolved_url}: {exc}")
                finally:
                    progress(idx, total)
                    await asyncio.sleep(random.uniform(0.1, 0.6))

        return downloaded

    def _make_filename(self, url: str, idx: int) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
        return f"image_{idx:04d}_{digest}.jpg"

    @staticmethod
    def _safe_int(value: str | int | None) -> int | None:
        try:
            return int(str(value)) if value is not None else None
        except (TypeError, ValueError):
            return None
