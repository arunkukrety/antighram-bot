"""
gui/constants.py — App metadata, platform flags, theme palette, geometry.
"""

import sys

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

APP_NAME = "Antigravity Bot"
APP_ID = "agy-telegram-bot"               # used for startup entries
WINDOW_W, WINDOW_H = 500, 620
REFRESH_MS = 1500                         # status + log refresh interval

# ── Palette ────────────────────────────────────────────────────────────────
COLOR_GREEN      = "#22C55E"
COLOR_RED        = "#EF4444"
COLOR_AMBER      = "#F59E0B"
COLOR_BG_DARK    = "#111318"
COLOR_SURFACE    = "#1C1F26"
COLOR_BORDER     = "#2A2D35"
COLOR_TEXT_DIM   = "#6B7280"
COLOR_TEXT       = "#E5E7EB"
COLOR_ACCENT     = "#6366F1"              # indigo
COLOR_ACCENT_HVR = "#4F52D3"
COLOR_LOG_BG     = "#0D0F14"
COLOR_LOG_FG     = "#A3E635"             # lime green — terminal feel
