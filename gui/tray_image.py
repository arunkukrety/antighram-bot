"""
gui/tray_image.py — Programmatic system-tray icon rendering (no image files).
"""

from PIL import Image, ImageDraw


def make_tray_image(running: bool, size: int = 64) -> Image.Image:
    """
    Renders a circular tray icon programmatically.
    Green  = server running
    Gray   = server stopped
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer glow ring
    glow_color = (34, 197, 94, 80) if running else (107, 114, 128, 60)
    draw.ellipse([2, 2, size - 2, size - 2], fill=glow_color)

    # Main circle
    fill = (34, 197, 94, 255) if running else (75, 85, 99, 255)
    pad = 8
    draw.ellipse([pad, pad, size - pad, size - pad], fill=fill)

    # Inner "A" letter (rough approximation as a white triangle + bar)
    cx, cy = size // 2, size // 2
    r = size // 2 - pad - 4
    # Triangle lines for the "A" shape
    pts = [
        (cx, cy - r + 2),
        (cx - r + 2, cy + r - 2),
        (cx + r - 2, cy + r - 2),
    ]
    draw.polygon(pts, fill=(255, 255, 255, 200))
    # Crossbar
    bar_y = cy + 2
    bar_x1 = cx - r // 2 + 3
    bar_x2 = cx + r // 2 - 3
    bar_w = max(2, size // 18)
    draw.rectangle([bar_x1, bar_y, bar_x2, bar_y + bar_w], fill=fill)

    return img
