"""
gui/paths.py — Location resolution for frozen (PyInstaller) vs development runs.

When packaged as a standalone executable, config can't be stored next to the
binary (it may be in a read-only location), so the OS user-data directory is
used instead.
"""

import os
import sys
from pathlib import Path

IS_FROZEN = getattr(sys, "frozen", False)

if IS_FROZEN:
    # sys.executable = the .exe / Linux binary itself
    APP_DIR = Path(sys.executable).parent
    BUNDLE_DIR = Path(sys._MEIPASS)          # PyInstaller temp extraction dir
    if sys.platform == "win32":
        CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "AntighramBot"
    else:
        CONFIG_DIR = Path.home() / ".config" / "antighram-bot"
else:
    APP_DIR = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = APP_DIR
    CONFIG_DIR = APP_DIR

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
PROJECT_DIR = APP_DIR          # used for display / ProcessManager working dir
ENV_FILE = CONFIG_DIR / ".env"
