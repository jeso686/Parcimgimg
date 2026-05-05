from __future__ import annotations

import asyncio
from pathlib import Path

import streamlit as st

from parser import DownloadedImage, HumanLikeImageParser


st.set_page_config(page_title="Elegant Image Parser", page_icon="🖼️", layout="wide")

# Общий стиль для современного интерфейса.
st.markdown(
    """
    <style>
        .main > div {padding-top: 1rem;}
        .stButton button {
            border-radius: 12px;
            border: 1px solid #6a5acd;
            background: linear-gradient(90deg, #6a5acd, #7b68ee);
            color: white;
            font-weight: 600;
            padding: 0.55rem 1.2rem;
        }
        .glass {
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(200,200,255,0.2);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 12px;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🖼️ Elegant Human-Like Image Parser")
st.caption("Парсер извлекает изображения с сайта, имитирует поведение человека и сохраняет лучшие по разрешению версии.")

with st.sidebar:
    st.header("⚙️ Settings")
    url = st.text_input("Target URL", placeholder="https://example.com/gallery")
    download_dir = st.text_input("Download folder", value="downloads")
    max_images = st.slider("Max unique images", min_value=5, max_value=500, value=80, step=5)
    min_width = st.number_input("Min width", min_value=32, max_value=8000, value=700, step=50)
    min_height = st.number_input("Min height", min_value=32, max_value=8000, value=500, step=50)
    timeout_sec = st.slider("Network timeout (sec)", min_value=5, max_value=120, value=30, step=5)
    upscale_small = st.checkbox("Upscale smaller images", value=False)
    upscale_factor = st.slider("Upscale factor", min_value=1.1, max_value=4.0, value=1.8, step=0.1)

left, right = st.columns([1.2, 1])

with left:
    st.subheader("Control Panel")
    start = st.button("Start Parsing", use_container_width=True)
    stop_note = st.info("Остановку можно выполнить закрытием вкладки или перезапуском с новыми параметрами.")

with right:
    st.subheader("Live Status")
    progress_bar = st.progress(0.0)
    counter = st.empty()

log_box = st.empty()
log_lines: list[str] = []


def add_log(message: str) -> None:
    # Лог обновляется в реальном времени для интерактивного наблюдения.
    log_lines.append(message)
    log_box.markdown("<div class='glass'><pre>" + "\n".join(log_lines[-120:]) + "</pre></div>", unsafe_allow_html=True)


def set_progress(current: int, total: int) -> None:
    value = 0.0 if total == 0 else min(max(current / total, 0.0), 1.0)
    progress_bar.progress(value)
    counter.metric("Downloaded / Selected", f"{current}/{total}")


def render_gallery(images: list[DownloadedImage]) -> None:
    st.subheader("Downloaded Gallery")
    if not images:
        st.warning("Нет изображений для отображения.")
        return

    cols = st.columns(3)
    for idx, image in enumerate(images):
        with cols[idx % 3]:
            st.image(str(image.file_path), caption=f"{image.file_path.name}\n{image.width}x{image.height}")
            st.caption(f"Source: {image.url}")
            st.caption(f"Size: {round(image.byte_size / 1024, 2)} KB")


if start:
    if not url.strip().startswith(("http://", "https://")):
        st.error("Введите корректный URL (http/https).")
    else:
        add_log(f"Старт задачи для: {url}")
        parser = HumanLikeImageParser(
            target_url=url.strip(),
            download_dir=Path(download_dir.strip() or "downloads"),
            max_images=int(max_images),
            min_width=int(min_width),
            min_height=int(min_height),
            timeout_sec=int(timeout_sec),
            upscale_small=bool(upscale_small),
            upscale_factor=float(upscale_factor),
        )

        try:
            results = asyncio.run(parser.run(add_log, set_progress))
            add_log("Парсинг завершён.")
            st.success(f"Готово! Сохранено {len(results)} изображений в: {Path(download_dir).resolve()}")
            render_gallery(results)
        except Exception as error:
            st.exception(error)
            add_log(f"Критическая ошибка: {error}")
else:
    st.info("Укажите URL и параметры в меню Settings, затем нажмите Start Parsing.")
