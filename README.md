# Image Harvest Pro

Modern desktop GUI parser that:
- opens any user-provided URL in a real browser (Playwright),
- simulates human-like behavior (mouse moves, pauses, scrolling),
- detects image candidates from `img`, `srcset`, and CSS `background-image`,
- downloads image files and keeps only high-resolution results,
- displays logs and progress in real time with interactive previews.

## Features

- **Human emulation parser**
  - randomized pauses,
  - random mouse movement and wheel scrolling,
  - lazy-content triggering before extraction.
- **Only top resolution**
  - chooses largest entry from `srcset`,
  - sorts downloads by area,
  - keeps only high-resolution slice (>= 35% of maximum area).
- **Live UX**
  - real-time logging panel,
  - progress bar,
  - gallery previews of saved images.
- **Extra settings menu**
  - download folder,
  - headless mode,
  - delay ranges,
  - scroll count,
  - timeout.

## Install

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

- Some websites may block automated sessions or require login/cookies.
- Respect robots.txt, local laws, and website terms of service.
