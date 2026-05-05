import io
import os
import queue
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse, unquote

import requests
import tkinter as tk
from PIL import Image, ImageTk
from playwright.sync_api import sync_playwright
from tkinter import filedialog, messagebox, ttk


@dataclass
class ParserSettings:
    # Папка для сохранения результатов.
    download_dir: str = str(Path.cwd() / "downloads")
    # Запуск браузера без видимого окна.
    headless: bool = True
    # Минимальная задержка между действиями эмуляции.
    min_delay: float = 0.2
    # Максимальная задержка между действиями эмуляции.
    max_delay: float = 0.8
    # Количество прокруток страницы для подгрузки ленивых картинок.
    max_scrolls: int = 8
    # Таймаут загрузки страницы в миллисекундах.
    page_timeout_ms: int = 45_000


@dataclass
class ImageCandidate:
    # Ссылка на изображение.
    url: str
    # Источник обнаружения внутри страницы.
    source: str


@dataclass
class DownloadedImage:
    # Локальный путь после сохранения.
    path: Path
    # Ширина изображения.
    width: int
    # Высота изображения.
    height: int
    # URL изображения.
    url: str

    @property
    def area(self) -> int:
        return self.width * self.height


class ImageParserEngine:
    def __init__(self, settings: ParserSettings, logger: Callable[[str], None], progress: Callable[[int, int], None]):
        self.settings = settings
        self.log = logger
        self.progress = progress
        self.stop_requested = False

    def stop(self) -> None:
        self.stop_requested = True

    def _human_pause(self) -> None:
        # Небольшая случайная пауза для имитации человеческого поведения.
        time.sleep(random.uniform(self.settings.min_delay, self.settings.max_delay))

    def _extract_largest_from_srcset(self, srcset: str, base_url: str) -> list[str]:
        candidates = []
        for part in srcset.split(","):
            piece = part.strip()
            if not piece:
                continue
            items = piece.split()
            link = items[0]
            score = 0
            if len(items) > 1:
                token = items[1].strip().lower()
                if token.endswith("w"):
                    with_digits = re.sub(r"[^0-9]", "", token)
                    score = int(with_digits) if with_digits else 0
                elif token.endswith("x"):
                    try:
                        score = int(float(token[:-1]) * 1000)
                    except ValueError:
                        score = 0
            candidates.append((score, urljoin(base_url, link)))
        if not candidates:
            return []
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [candidates[0][1]]

    def _collect_candidates(self, page, target_url: str) -> list[ImageCandidate]:
        js = """
        () => {
          const out = [];
          for (const img of document.querySelectorAll('img')) {
            out.push({
              src: img.getAttribute('src') || '',
              currentSrc: img.currentSrc || '',
              srcset: img.getAttribute('srcset') || '',
              source: 'img'
            });
          }

          for (const node of document.querySelectorAll('*')) {
            const style = window.getComputedStyle(node);
            const bg = style.getPropertyValue('background-image');
            if (bg && bg.includes('url(')) {
              out.push({ src: bg, currentSrc: '', srcset: '', source: 'css-background' });
            }
          }
          return out;
        }
        """
        raw = page.evaluate(js)
        self.log(f"Found raw image entries: {len(raw)}")

        candidates: list[ImageCandidate] = []
        for item in raw:
            if self.stop_requested:
                break

            srcset = item.get("srcset", "").strip()
            if srcset:
                for url in self._extract_largest_from_srcset(srcset, target_url):
                    candidates.append(ImageCandidate(url=url, source=f"{item.get('source')} srcset"))

            for field_name in ("currentSrc", "src"):
                value = item.get(field_name, "").strip()
                if not value:
                    continue

                # Для CSS background-image вырезаем URL из url("...").
                if value.startswith("url("):
                    match = re.search(r"url\((['\"]?)(.*?)\1\)", value)
                    if match:
                        value = match.group(2)

                if value.startswith("data:"):
                    continue
                if not value:
                    continue
                candidates.append(ImageCandidate(url=urljoin(target_url, value), source=item.get("source", "unknown")))

        unique = {}
        for c in candidates:
            clean = c.url.strip()
            if not clean or clean.startswith("javascript:"):
                continue
            unique.setdefault(clean, c)

        final_candidates = list(unique.values())
        self.log(f"Unique candidate image URLs: {len(final_candidates)}")
        return final_candidates

    def _filename_from_url(self, url: str, index: int) -> str:
        path = urlparse(url).path
        name = unquote(Path(path).name)
        if not name or "." not in name:
            name = f"image_{index:05d}.jpg"
        return re.sub(r"[^a-zA-Z0-9._-]", "_", name)

    def run(self, target_url: str) -> list[DownloadedImage]:
        self.stop_requested = False
        Path(self.settings.download_dir).mkdir(parents=True, exist_ok=True)

        self.log("Starting browser and opening page...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.settings.headless)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            page.set_default_timeout(self.settings.page_timeout_ms)
            page.goto(target_url, wait_until="domcontentloaded")
            self._human_pause()

            # Эмуляция движений мыши и прокрутки для подгрузки контента.
            for i in range(self.settings.max_scrolls):
                if self.stop_requested:
                    break
                x = random.randint(100, 1200)
                y = random.randint(100, 700)
                page.mouse.move(x, y, steps=random.randint(5, 20))
                page.mouse.wheel(0, random.randint(400, 1400))
                self.log(f"Simulated human interaction step {i + 1}/{self.settings.max_scrolls}")
                self._human_pause()

            page.wait_for_timeout(1200)
            candidates = self._collect_candidates(page, target_url)

            context.close()
            browser.close()

        self.log("Downloading and selecting highest-resolution images...")

        downloaded: list[DownloadedImage] = []
        seen_hashes: set[str] = set()
        session = requests.Session()
        total = len(candidates)

        for idx, candidate in enumerate(candidates, start=1):
            if self.stop_requested:
                self.log("Stop requested by user.")
                break

            self.progress(idx, total)
            try:
                response = session.get(candidate.url, timeout=20)
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                if "image" not in content_type.lower():
                    continue

                data = response.content
                digest = str(hash(data))
                if digest in seen_hashes:
                    continue

                img = Image.open(io.BytesIO(data))
                width, height = img.size
                if width < 50 or height < 50:
                    continue

                filename = self._filename_from_url(candidate.url, idx)
                destination = Path(self.settings.download_dir) / filename

                # Не перезаписываем файл — добавляем суффикс при конфликте имени.
                counter = 1
                base_stem = destination.stem
                suffix = destination.suffix
                while destination.exists():
                    destination = destination.with_name(f"{base_stem}_{counter}{suffix}")
                    counter += 1

                destination.write_bytes(data)
                seen_hashes.add(digest)

                downloaded.append(
                    DownloadedImage(path=destination, width=width, height=height, url=candidate.url)
                )
                self.log(f"Saved {destination.name} ({width}x{height})")
            except Exception as exc:
                self.log(f"Skip {candidate.url} -> {exc}")

        downloaded.sort(key=lambda item: item.area, reverse=True)

        # Логический фильтр: оставляем только действительно крупные версии.
        if downloaded:
            max_area = downloaded[0].area
            threshold = int(max_area * 0.35)
            downloaded = [item for item in downloaded if item.area >= threshold]

        self.progress(total, total)
        self.log(f"Done. Kept {len(downloaded)} top-resolution images.")
        return downloaded


class SettingsDialog(tk.Toplevel):
    def __init__(self, master: tk.Tk, settings: ParserSettings):
        super().__init__(master)
        self.title("Parser Settings")
        self.settings = settings
        self.resizable(False, False)
        self.configure(bg="#0f172a")

        self.var_dir = tk.StringVar(value=settings.download_dir)
        self.var_headless = tk.BooleanVar(value=settings.headless)
        self.var_min_delay = tk.DoubleVar(value=settings.min_delay)
        self.var_max_delay = tk.DoubleVar(value=settings.max_delay)
        self.var_scrolls = tk.IntVar(value=settings.max_scrolls)
        self.var_timeout = tk.IntVar(value=settings.page_timeout_ms)

        frm = ttk.Frame(self, padding=14)
        frm.grid(sticky="nsew")

        ttk.Label(frm, text="Download folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_dir, width=52).grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(frm, text="Browse", command=self.pick_dir).grid(row=1, column=1)

        ttk.Checkbutton(frm, text="Headless browser", variable=self.var_headless).grid(row=2, column=0, sticky="w", pady=(8, 4))

        ttk.Label(frm, text="Min delay (sec)").grid(row=3, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_min_delay, width=12).grid(row=4, column=0, sticky="w")

        ttk.Label(frm, text="Max delay (sec)").grid(row=5, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_max_delay, width=12).grid(row=6, column=0, sticky="w")

        ttk.Label(frm, text="Scroll steps").grid(row=7, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_scrolls, width=12).grid(row=8, column=0, sticky="w")

        ttk.Label(frm, text="Page timeout (ms)").grid(row=9, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.var_timeout, width=12).grid(row=10, column=0, sticky="w")

        btn_bar = ttk.Frame(frm)
        btn_bar.grid(row=11, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(btn_bar, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(btn_bar, text="Save", command=self.save).grid(row=0, column=1, padx=4)

        self.grab_set()

    def pick_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.var_dir.get() or str(Path.cwd()))
        if chosen:
            self.var_dir.set(chosen)

    def save(self) -> None:
        min_delay = self.var_min_delay.get()
        max_delay = self.var_max_delay.get()
        if min_delay > max_delay:
            messagebox.showerror("Validation", "Min delay cannot be greater than max delay.")
            return

        self.settings.download_dir = self.var_dir.get().strip() or self.settings.download_dir
        self.settings.headless = self.var_headless.get()
        self.settings.min_delay = min_delay
        self.settings.max_delay = max_delay
        self.settings.max_scrolls = max(1, self.var_scrolls.get())
        self.settings.page_timeout_ms = max(5_000, self.var_timeout.get())
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Image Harvest Pro")
        self.geometry("1200x780")
        self.minsize(1000, 700)

        self.settings_data = ParserSettings()
        self.engine: ImageParserEngine | None = None
        self.worker: threading.Thread | None = None
        self.events = queue.Queue()
        self.preview_cache: list[ImageTk.PhotoImage] = []

        self._setup_style()
        self._build_ui()
        self.after(90, self._pump_events)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        self.configure(bg="#020617")
        style.configure("Root.TFrame", background="#020617")
        style.configure("Card.TFrame", background="#0b1220")
        style.configure("Title.TLabel", background="#020617", foreground="#e2e8f0", font=("Segoe UI", 14, "bold"))
        style.configure("Subtle.TLabel", background="#0b1220", foreground="#cbd5e1")
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, style="Root.TFrame", padding=14)
        root.pack(fill="both", expand=True)

        header = ttk.Frame(root, style="Root.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text="Image Harvest Pro", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Settings", command=self.open_settings).pack(side="right")

        controls = ttk.Frame(root, style="Card.TFrame", padding=12)
        controls.pack(fill="x", pady=(12, 8))
        ttk.Label(controls, text="Target URL", style="Subtle.TLabel").grid(row=0, column=0, sticky="w")

        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(controls, textvariable=self.url_var, width=110)
        self.url_entry.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(4, 8))

        self.btn_start = ttk.Button(controls, text="Start Parsing", style="Accent.TButton", command=self.start_parsing)
        self.btn_start.grid(row=2, column=0, sticky="w")
        self.btn_stop = ttk.Button(controls, text="Stop", command=self.stop_parsing)
        self.btn_stop.grid(row=2, column=1, sticky="w", padx=6)

        self.progress_var = tk.StringVar(value="Idle")
        ttk.Label(controls, textvariable=self.progress_var, style="Subtle.TLabel").grid(row=2, column=2, sticky="e")
        controls.columnconfigure(0, weight=1)

        self.pb = ttk.Progressbar(controls, mode="determinate")
        self.pb.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 2))

        body = ttk.Frame(root, style="Root.TFrame")
        body.pack(fill="both", expand=True, pady=(8, 0))

        logs_card = ttk.Frame(body, style="Card.TFrame", padding=12)
        logs_card.pack(side="left", fill="both", expand=True, padx=(0, 6))
        ttk.Label(logs_card, text="Live log", style="Subtle.TLabel").pack(anchor="w")

        self.logs = tk.Text(logs_card, height=20, bg="#020617", fg="#e2e8f0", insertbackground="#e2e8f0", relief="flat")
        self.logs.pack(fill="both", expand=True, pady=(6, 0))

        preview_card = ttk.Frame(body, style="Card.TFrame", padding=12)
        preview_card.pack(side="right", fill="both", expand=True)
        ttk.Label(preview_card, text="Downloaded previews", style="Subtle.TLabel").pack(anchor="w")

        self.preview_canvas = tk.Canvas(preview_card, bg="#020617", highlightthickness=0)
        self.preview_canvas.pack(side="left", fill="both", expand=True, pady=(8, 0))

        scroll = ttk.Scrollbar(preview_card, orient="vertical", command=self.preview_canvas.yview)
        scroll.pack(side="right", fill="y")
        self.preview_canvas.configure(yscrollcommand=scroll.set)

        self.preview_inner = ttk.Frame(self.preview_canvas)
        self.preview_canvas.create_window((0, 0), window=self.preview_inner, anchor="nw")
        self.preview_inner.bind("<Configure>", lambda e: self.preview_canvas.configure(scrollregion=self.preview_canvas.bbox("all")))

    def open_settings(self) -> None:
        SettingsDialog(self, self.settings_data)

    def log(self, text: str) -> None:
        self.events.put(("log", text))

    def report_progress(self, current: int, total: int) -> None:
        self.events.put(("progress", current, total))

    def start_parsing(self) -> None:
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Input", "Please provide URL.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showwarning("Busy", "Parser is already running.")
            return

        self.logs.delete("1.0", "end")
        self._clear_previews()
        self.pb.configure(value=0, maximum=100)
        self.progress_var.set("Starting...")

        self.engine = ImageParserEngine(self.settings_data, self.log, self.report_progress)
        self.worker = threading.Thread(target=self._run_worker, args=(url,), daemon=True)
        self.worker.start()

    def stop_parsing(self) -> None:
        if self.engine:
            self.engine.stop()
            self.log("Stop signal was sent.")

    def _run_worker(self, url: str) -> None:
        try:
            results = self.engine.run(url) if self.engine else []
            self.events.put(("done", results))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _clear_previews(self) -> None:
        self.preview_cache.clear()
        for child in self.preview_inner.winfo_children():
            child.destroy()

    def _render_previews(self, images: list[DownloadedImage]) -> None:
        self._clear_previews()
        for i, item in enumerate(images, start=1):
            frame = ttk.Frame(self.preview_inner, style="Card.TFrame", padding=8)
            frame.grid(row=i, column=0, sticky="ew", pady=5)

            img = Image.open(item.path)
            img.thumbnail((320, 220))
            tk_img = ImageTk.PhotoImage(img)
            self.preview_cache.append(tk_img)

            lbl_img = ttk.Label(frame, image=tk_img)
            lbl_img.grid(row=0, column=0, rowspan=3, padx=(0, 10))

            ttk.Label(frame, text=item.path.name, style="Subtle.TLabel").grid(row=0, column=1, sticky="w")
            ttk.Label(frame, text=f"{item.width} x {item.height}", style="Subtle.TLabel").grid(row=1, column=1, sticky="w")
            ttk.Label(frame, text=item.url[:95] + ("..." if len(item.url) > 95 else ""), style="Subtle.TLabel").grid(row=2, column=1, sticky="w")

    def _pump_events(self) -> None:
        while not self.events.empty():
            item = self.events.get_nowait()
            kind = item[0]

            if kind == "log":
                self.logs.insert("end", item[1] + "\n")
                self.logs.see("end")
            elif kind == "progress":
                current, total = item[1], max(item[2], 1)
                self.pb.configure(maximum=total, value=current)
                self.progress_var.set(f"Processing {current}/{total}")
            elif kind == "done":
                results = item[1]
                self.progress_var.set(f"Done: {len(results)} images")
                self._render_previews(results)
                self.log("Completed successfully.")
            elif kind == "error":
                self.progress_var.set("Error")
                messagebox.showerror("Error", item[1])

        self.after(90, self._pump_events)


if __name__ == "__main__":
    app = App()
    app.mainloop()
