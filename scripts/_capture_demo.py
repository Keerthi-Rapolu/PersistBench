"""
Capture PersistBench dashboard screenshots and produce:
  - docs/gifs/persistbench_demo.gif   (~8-13s animated GIF)
  - docs/images/dashboard_hero.png    (static hero image)

Requires: pip install playwright pillow
          python -m playwright install chromium
Run with: python scripts/_capture_demo.py
Streamlit must be running at http://localhost:8501
"""
from __future__ import annotations

import io
import os
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_URL    = "http://localhost:8501"
VIEWPORT    = {"width": 1440, "height": 900}
GIF_WIDTH   = 960          # resize for smaller GIF file
GIF_HEIGHT  = 600
HERO_WIDTH  = 1440
HERO_HEIGHT = 900

ROOT = Path(__file__).resolve().parent.parent
OUT_IMAGES = ROOT / "docs" / "images"
OUT_GIFS   = ROOT / "docs" / "gifs"
OUT_IMAGES.mkdir(parents=True, exist_ok=True)
OUT_GIFS.mkdir(parents=True, exist_ok=True)

# (url_path, page_title, hold_ms, scroll_to)
PAGES = [
    ("/",                   "Overview",              2200, 400),
    ("/attack_evolution",   "Attack Evolution",      2200, 300),
    ("/memory_provenance",  "Memory & Provenance",   2200, 400),
    ("/defense_metrics",    "Defense & Metrics",     2000, 300),
    ("/cross_run",          "Cross-Run Comparison",  2000, 300),
    ("/artifacts_about",    "Artifacts & About",     1800, 200),
]

HERO_PAGE = "/memory_provenance"   # page to use for static hero


def take_screenshot(page, url: str, scroll_y: int = 0) -> bytes:
    """Navigate, wait for load, optional scroll, return PNG bytes."""
    page.goto(BASE_URL + url, wait_until="networkidle", timeout=20000)
    # Extra wait for Altair/Vega charts to render
    time.sleep(2.5)
    if scroll_y:
        page.evaluate(f"window.scrollTo(0, {scroll_y})")
        time.sleep(0.4)
    return page.screenshot(full_page=False)


def png_to_pil(png_bytes: bytes, width: int, height: int) -> Image.Image:
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    return img.resize((width, height), Image.LANCZOS)


def make_final_frame(width: int, height: int) -> Image.Image:
    """Dark final frame with centered text."""
    img = Image.new("RGB", (width, height), color=(18, 18, 24))
    draw = ImageDraw.Draw(img)

    # Try to use a clean system font, fall back to default
    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 52)
        font_sub   = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 28)
        font_url   = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub   = font_title
        font_url   = font_title

    cx = width // 2
    line1 = "PersistBench"
    line2 = "Persistent Agent Security Benchmark"
    line3 = "https://persistbench.streamlit.app/"

    # Accent bar
    bar_y = height // 2 - 90
    draw.rectangle([cx - 120, bar_y, cx + 120, bar_y + 3], fill=(88, 130, 210))

    # Title
    bbox = draw.textbbox((0, 0), line1, font=font_title)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, height // 2 - 70), line1,
              fill=(230, 235, 245), font=font_title)

    # Subtitle
    bbox = draw.textbbox((0, 0), line2, font=font_sub)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, height // 2 + 8), line2,
              fill=(160, 170, 190), font=font_sub)

    # Separator
    draw.rectangle([cx - 60, height // 2 + 58, cx + 60, height // 2 + 60],
                   fill=(60, 70, 90))

    # URL
    bbox = draw.textbbox((0, 0), line3, font=font_url)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, height // 2 + 74), line3,
              fill=(100, 140, 200), font=font_url)

    return img


def main():
    print("Launching headless browser...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        ctx = browser.new_context(
            viewport=VIEWPORT,
            color_scheme="dark",
        )
        page = ctx.new_page()

        frames: list[Image.Image] = []
        durations: list[int] = []
        hero_img = None

        print(f"Capturing {len(PAGES)} pages...")
        for url, title, hold_ms, scroll_y in PAGES:
            print(f"  {title} ({url})")
            try:
                png = take_screenshot(page, url, scroll_y)
            except Exception as e:
                print(f"    WARNING: {e} — skipping")
                continue

            img_gif  = png_to_pil(png, GIF_WIDTH, GIF_HEIGHT)
            img_full = png_to_pil(png, HERO_WIDTH, HERO_HEIGHT)
            frames.append(img_gif)
            durations.append(hold_ms)

            # Save individual page PNG
            img_full.save(OUT_IMAGES / f"page_{title.lower().replace(' ', '_').replace('&','and')}.png")

            if url == HERO_PAGE:
                hero_img = img_full

        browser.close()

    # Fallback hero
    if hero_img is None and frames:
        hero_img = frames[0].resize((HERO_WIDTH, HERO_HEIGHT), Image.LANCZOS)

    # Add final title frame
    final = make_final_frame(GIF_WIDTH, GIF_HEIGHT)
    frames.append(final)
    durations.append(3200)

    # --- Save hero PNG ---
    hero_path = OUT_IMAGES / "dashboard_hero.png"
    if hero_img:
        hero_img.save(hero_path, optimize=True)
        size_kb = hero_path.stat().st_size // 1024
        print(f"Hero image: {hero_path}  ({size_kb} KB)")

    # --- Save animated GIF ---
    gif_path = OUT_GIFS / "persistbench_demo.gif"
    print(f"Building GIF ({len(frames)} frames)...")
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    size_mb = gif_path.stat().st_size / 1_048_576
    print(f"GIF: {gif_path}  ({size_mb:.2f} MB)")
    if size_mb > 15:
        print("  WARNING: GIF exceeds 15 MB — consider reducing GIF_WIDTH or frame count")

    print("Done.")


if __name__ == "__main__":
    main()
