"""Rebuild static/pwa/*.png from engine.brand with headless Chrome.

Run once after changing the logo: python scripts/generate_pwa_icons.py
Then bump CACHE_NAME in static/pwa/sw.js so installed apps pick the icons up.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.brand import BRAND_VIOLET, BRAND_VIOLET_LIGHT, logo_mark  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PWA = ROOT / "static" / "pwa"

# Maskable and Apple icons get cropped by the OS, so they are a full-bleed
# violet square with a white wave instead of the bubble-shaped mark.
FULL_BLEED = (
    '<svg viewBox="0 0 120 120" width="{s}" height="{s}" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
    f'<stop offset="0" stop-color="{BRAND_VIOLET_LIGHT}"/><stop offset="1" stop-color="{BRAND_VIOLET}"/>'
    '</linearGradient></defs><rect width="120" height="120" fill="url(#g)"/>'
    '<polyline points="26,60 34,60 40,44 48,78 56,36 64,84 72,48 80,68 86,60 94,60" fill="none" '
    'stroke="#fff" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


def render(svg: str, size: int, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "icon.html"
        shot = Path(tmp) / "icon.png"
        page.write_text(f'<!doctype html><body style="margin:0">{svg}</body>', encoding="utf-8")
        subprocess.run(
            [CHROME, "--headless=new", "--hide-scrollbars", "--default-background-color=00000000",
             f"--window-size={size},{size}", f"--screenshot={shot}", page.as_uri()],
            check=True, capture_output=True,
        )
        Image.open(shot).convert("RGBA").crop((0, 0, size, size)).save(out)
    print(out.name, size)


render(logo_mark(192), 192, PWA / "icon-192.png")
render(logo_mark(512), 512, PWA / "icon-512.png")
render(FULL_BLEED.format(s=512), 512, PWA / "icon-maskable-512.png")
render(FULL_BLEED.format(s=180), 180, PWA / "apple-touch-icon.png")
