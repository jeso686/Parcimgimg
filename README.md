# Elegant Human-Like Image Parser

Modern GUI parser that:

- accepts a user-provided URL;
- simulates human browsing behavior (scroll, pauses, mouse movement);
- finds images across static and dynamic page content;
- groups duplicates and keeps only the highest-resolution candidate;
- optionally upscales smaller images;
- shows real-time logs/progress and a visual gallery.

## Tech stack

- Python 3.11+
- Streamlit (interactive GUI)
- Playwright (browser automation)
- httpx + BeautifulSoup + Pillow

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
streamlit run app.py
```

## Notes

- Use only websites where you are authorized to scrape media.
- Some websites have anti-bot protection and legal restrictions.
