from __future__ import annotations

import asyncio
import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import aiohttp
import customtkinter as ctk

from src.downloader import download_image
from src.models import DownloadResult
from src.parser import collect_best_images
from src.settings import AppSettings


class ImageParserApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Elegant Image Harvester")
        self.geometry("1180x760")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # Очередь нужна для безопасного обмена между потоками и UI.
        self.event_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None

        self._build_ui()
        self.after(120, self._poll_events)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=1)

        self.main_panel = ctk.CTkFrame(self, corner_radius=16)
        self.main_panel.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
        self.main_panel.grid_rowconfigure(4, weight=1)
        self.main_panel.grid_columnconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, corner_radius=16)
        self.sidebar.grid(row=0, column=1, padx=(0, 16), pady=16, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            self.main_panel,
            text="🖼️ Elegant Image Harvester",
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        self.title_label.grid(row=0, column=0, padx=22, pady=(20, 10), sticky="w")

        self.url_entry = ctk.CTkEntry(
            self.main_panel,
            placeholder_text="Вставьте URL страницы для анализа...",
            height=42,
            corner_radius=12,
            font=ctk.CTkFont(size=14),
        )
        self.url_entry.grid(row=1, column=0, padx=22, pady=8, sticky="ew")

        self.controls = ctk.CTkFrame(self.main_panel, fg_color="transparent")
        self.controls.grid(row=2, column=0, padx=22, pady=(6, 10), sticky="ew")
        self.controls.grid_columnconfigure((0, 1), weight=1)

        self.start_button = ctk.CTkButton(
            self.controls,
            text="Start Parsing",
            height=40,
            corner_radius=12,
            command=self.start_job,
        )
        self.start_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.clear_button = ctk.CTkButton(
            self.controls,
            text="Clear Log",
            height=40,
            corner_radius=12,
            fg_color="#444",
            hover_color="#555",
            command=self._clear_log,
        )
        self.clear_button.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self.main_panel)
        self.progress_bar.grid(row=3, column=0, padx=22, pady=(2, 8), sticky="ew")
        self.progress_bar.set(0.0)

        self.log_box = ctk.CTkTextbox(self.main_panel, corner_radius=12)
        self.log_box.grid(row=4, column=0, padx=22, pady=(8, 20), sticky="nsew")

        self.settings_title = ctk.CTkLabel(
            self.sidebar,
            text="Settings",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        self.settings_title.grid(row=0, column=0, padx=20, pady=(18, 12), sticky="w")

        self.output_dir_var = ctk.StringVar(value=str(Path.cwd() / "downloads"))
        self.max_images_var = ctk.IntVar(value=20)
        self.only_largest_var = ctk.BooleanVar(value=True)
        self.upscale_var = ctk.DoubleVar(value=1.0)
        self.timeout_var = ctk.IntVar(value=45)
        self.headless_var = ctk.BooleanVar(value=True)

        self._build_settings_widgets()

    def _build_settings_widgets(self) -> None:
        container = ctk.CTkScrollableFrame(self.sidebar, corner_radius=12)
        container.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(1, weight=1)

        row = 0

        ctk.CTkLabel(container, text="Output folder").grid(row=row, column=0, sticky="w", pady=(10, 6))
        row += 1

        output_frame = ctk.CTkFrame(container, fg_color="transparent")
        output_frame.grid(row=row, column=0, sticky="ew")
        output_frame.grid_columnconfigure(0, weight=1)

        self.output_entry = ctk.CTkEntry(output_frame, textvariable=self.output_dir_var)
        self.output_entry.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        browse_button = ctk.CTkButton(output_frame, text="Browse", width=90, command=self._pick_output_folder)
        browse_button.grid(row=0, column=1, sticky="e")
        row += 1

        ctk.CTkSwitch(container, text="Only single largest image", variable=self.only_largest_var).grid(
            row=row, column=0, sticky="w", pady=(14, 6)
        )
        row += 1

        ctk.CTkLabel(container, text="Max images (if not single mode)").grid(row=row, column=0, sticky="w", pady=(10, 6))
        row += 1
        ctk.CTkSlider(container, from_=1, to=100, number_of_steps=99, variable=self.max_images_var).grid(
            row=row, column=0, sticky="ew"
        )
        row += 1
        ctk.CTkLabel(container, textvariable=self.max_images_var).grid(row=row, column=0, sticky="e")
        row += 1

        ctk.CTkLabel(container, text="Upscale factor (1.0–4.0)").grid(row=row, column=0, sticky="w", pady=(10, 6))
        row += 1
        ctk.CTkSlider(container, from_=1.0, to=4.0, number_of_steps=30, variable=self.upscale_var).grid(
            row=row, column=0, sticky="ew"
        )
        row += 1
        self.upscale_value_label = ctk.CTkLabel(container, text=f"{self.upscale_var.get():.1f}x")
        self.upscale_value_label.grid(row=row, column=0, sticky="e")
        self.upscale_var.trace_add("write", lambda *_: self.upscale_value_label.configure(text=f"{self.upscale_var.get():.1f}x"))
        row += 1

        ctk.CTkLabel(container, text="Navigation timeout (seconds)").grid(row=row, column=0, sticky="w", pady=(10, 6))
        row += 1
        ctk.CTkSlider(container, from_=10, to=180, number_of_steps=170, variable=self.timeout_var).grid(
            row=row, column=0, sticky="ew"
        )
        row += 1
        ctk.CTkLabel(container, textvariable=self.timeout_var).grid(row=row, column=0, sticky="e")
        row += 1

        ctk.CTkSwitch(container, text="Headless browser", variable=self.headless_var).grid(
            row=row, column=0, sticky="w", pady=(14, 14)
        )

    def _pick_output_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if selected:
            self.output_dir_var.set(selected)

    def _clear_log(self) -> None:
        self.log_box.delete("1.0", "end")

    def _log(self, message: str) -> None:
        self.log_box.insert("end", f"{message}\n")
        self.log_box.see("end")

    def _set_busy(self, busy: bool) -> None:
        self.start_button.configure(state="disabled" if busy else "normal")

    def _build_settings(self) -> AppSettings | None:
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("Validation", "Please provide a valid URL.")
            return None

        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        return AppSettings(
            url=url,
            output_dir=Path(self.output_dir_var.get()),
            max_images=int(self.max_images_var.get()),
            only_single_largest=bool(self.only_largest_var.get()),
            upscale_factor=float(self.upscale_var.get()),
            timeout_seconds=int(self.timeout_var.get()),
            headless=bool(self.headless_var.get()),
        )

    def start_job(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("Busy", "Parser is already running.")
            return

        settings = self._build_settings()
        if settings is None:
            return

        self._set_busy(True)
        self.progress_bar.set(0.06)
        self._log("Запуск фоновой задачи парсинга...")

        def runner() -> None:
            asyncio.run(self._run_job(settings))

        self.worker_thread = threading.Thread(target=runner, daemon=True)
        self.worker_thread.start()

    async def _run_job(self, settings: AppSettings) -> None:
        def report(text: str) -> None:
            self.event_queue.put(("log", text))

        try:
            candidates = await collect_best_images(settings, report)
            self.event_queue.put(("progress", "0.62"))

            if not candidates:
                self.event_queue.put(("log", "Изображения не найдены."))
                self.event_queue.put(("done", "completed"))
                return

            self.event_queue.put(("log", f"К скачиванию: {len(candidates)}"))

            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                results: list[DownloadResult] = []

                for index, candidate in enumerate(candidates, start=1):
                    self.event_queue.put(("log", f"Скачиваю {index}/{len(candidates)}: {candidate.url}"))
                    result = await download_image(
                        session=session,
                        candidate=candidate,
                        output_dir=settings.normalized_output_dir(),
                        index=index,
                        upscale_factor=settings.upscale_factor,
                    )
                    results.append(result)
                    progress_value = 0.62 + (0.35 * (index / max(1, len(candidates))))
                    self.event_queue.put(("progress", f"{progress_value:.3f}"))

            for item in results:
                marker = "[UPSCALED]" if item.upscaled else "[ORIGINAL]"
                self.event_queue.put(
                    (
                        "log",
                        f"{marker} {item.saved_path.name} -> {item.width}x{item.height} ({item.saved_path})",
                    )
                )

            self.event_queue.put(("log", "Готово. Обработка завершена успешно."))
        except Exception as exc:
            self.event_queue.put(("log", f"Ошибка: {exc}"))
        finally:
            self.event_queue.put(("progress", "1.0"))
            self.event_queue.put(("done", "completed"))

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.event_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress_bar.set(float(payload))
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass
        finally:
            self.after(120, self._poll_events)


if __name__ == "__main__":
    app = ImageParserApp()
    app.mainloop()
