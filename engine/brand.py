"""
engine/brand.py — the VerbaShake logo, shared by the login gate, the launcher
and scripts/generate_pwa_icons.py. Same mark as the Instagram covers.
"""

BRAND_VIOLET = "#5B3BE6"
BRAND_VIOLET_LIGHT = "#8B6CFF"

_WAVE = "26,56 34,56 40,40 48,74 56,32 64,80 72,44 80,64 86,56 94,56"


def logo_mark(size: int) -> str:
    """Speech bubble with a voice wave, as an inline SVG."""
    gradient_id = f"vs-logo-{size}"
    return (
        f'<svg viewBox="0 0 120 120" width="{size}" height="{size}" '
        'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="VerbaShake">'
        f'<defs><linearGradient id="{gradient_id}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{BRAND_VIOLET_LIGHT}"/>'
        f'<stop offset="1" stop-color="{BRAND_VIOLET}"/></linearGradient></defs>'
        '<path d="M28 8h64a20 20 0 0 1 20 20v52a20 20 0 0 1-20 20H52l-22 16 '
        f'4-16h-6A20 20 0 0 1 8 80V28A20 20 0 0 1 28 8z" fill="url(#{gradient_id})"/>'
        f'<polyline points="{_WAVE}" fill="none" stroke="#fff" stroke-width="6" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def logo_lockup(mark_size: int = 64, font_size: int = 44) -> str:
    """Mark + wordmark on one line, centred. Uses the app's --mova-ink text colour."""
    return (
        '<div style="display:flex;align-items:center;justify-content:center;gap:12px;'
        f'padding:20px 0 12px;font-family:var(--mova-font-sans);font-weight:900;'
        f'font-size:{font_size}px;letter-spacing:-1px;color:var(--mova-ink)">'
        f"{logo_mark(mark_size)}VerbaShake</div>"
    )
