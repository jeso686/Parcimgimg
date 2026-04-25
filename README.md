# Elegant Image Harvester

A modern desktop GUI parser that:
- opens any user-provided URL with a browser automation layer,
- emulates human behavior (random delays, scrolling, cursor movement),
- discovers image candidates (`img`, CSS background URLs, `srcset`),
- evaluates dimensions and keeps only the largest-resolution image(s),
- can optionally upscale downloaded images,
- displays live progress in a responsive interface.

## Features

- **Modern GUI** based on `CustomTkinter`.
- **Real-time log stream** with progress updates.
- **Settings panel**:
  - download folder,
  - max images,
  - single-largest-only mode,
  - upscale factor,
  - browser headless/headed mode,
  - timeout.
- **Human-like browser simulation** using Playwright:
  - randomized pause windows,
  - scrolling behavior,
  - lightweight pointer movement.

## Tech stack

- Python 3.11+
- Playwright
- CustomTkinter
- Pillow
- aiohttp
- BeautifulSoup4

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python app.py
```

## Notes

- Some websites block automation or require login.
- This app is intended for legal and ethical use only.
- Respect robots policies, copyrights, and terms of service.
