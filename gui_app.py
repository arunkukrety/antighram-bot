"""
gui_app.py — Antigravity Telegram Bot Desktop Control Center (entry point).

Cross-platform desktop tray application for Windows and Linux.
Manages the bot server process, live logs, and environment config
from a clean CustomTkinter UI that lives in the system tray.

Launch:
    python gui_app.py

The window starts hidden — the app lives in the system tray.
Left-click or "Open Control Panel" from the tray to show it.

GUI implementation lives in the gui/ package:
    gui/paths.py         config/bundle location (frozen vs dev)
    gui/env_store.py     .env read/write helpers
    gui/startup.py       login/startup registration
    gui/tray_image.py    programmatic tray icon rendering
    gui/setup_wizard.py  first-run credential wizard
    gui/app_window.py    AgyBotApp control panel + tray
"""

import sys
from pathlib import Path

# ── Guard: friendly error if GUI deps are missing ──────────────────────────
_MISSING: list[str] = []
try:
    import customtkinter  # noqa: F401
except ImportError:
    _MISSING.append("customtkinter")
try:
    import pystray  # noqa: F401
except ImportError:
    _MISSING.append("pystray")
try:
    import PIL  # noqa: F401
except ImportError:
    _MISSING.append("pillow")

if _MISSING:
    print(
        f"\n[ERROR] Missing GUI dependencies: {', '.join(_MISSING)}\n"
        f"Install them with:\n"
        f"  pip install -r requirements-gui.txt\n"
    )
    sys.exit(1)

# ── Dev mode: ensure project root is importable from any cwd ───────────────
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from gui.env_store import has_token  # noqa: E402
from gui.paths import ENV_FILE  # noqa: E402


def _run_bot_mode() -> None:
    """
    Headless entry-point: runs only the Telegram bot (no GUI).
    Called when the binary is launched with the ``--run-bot`` flag by
    ProcessManager so the single .exe acts as both GUI and bot subprocess.
    """
    # Load .env from the user config dir so the bot has credentials
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=str(ENV_FILE), override=True)
    # Static import — ensures PyInstaller bundles agy_bot.main
    from agy_bot.main import main as bot_main
    bot_main()


def main() -> None:
    # ── Bot-subprocess mode ────────────────────────────────────────────────
    if '--run-bot' in sys.argv:
        _run_bot_mode()
        return

    # ── First-run setup wizard ─────────────────────────────────────────────
    from gui.setup_wizard import SetupWizard
    from gui.app_window import AgyBotApp

    if not has_token():
        wizard = SetupWizard()
        completed = wizard.run()
        if not completed:
            # User closed without finishing — exit cleanly
            return

    # ── Launch main app ────────────────────────────────────────────────────
    app = AgyBotApp()
    app.run()


if __name__ == '__main__':
    main()
