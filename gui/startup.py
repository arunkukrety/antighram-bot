"""
gui/startup.py — "Start on system startup" registration.

Windows: HKCU\\...\\Run registry value.  Linux: XDG autostart .desktop file.
"""

import sys
from pathlib import Path

from gui.constants import APP_ID, APP_NAME, IS_LINUX, IS_WINDOWS
from gui.paths import APP_DIR, IS_FROZEN, PROJECT_DIR


def _gui_launch_cmd() -> str:
    """The command that launches this app (frozen: the binary itself)."""
    if IS_FROZEN:
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{APP_DIR / "gui_app.py"}"'


def get_startup_enabled() -> bool:
    """Return True if the app is registered for system startup."""
    if IS_WINDOWS:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            )
            winreg.QueryValueEx(key, APP_ID)
            winreg.CloseKey(key)
            return True
        except (FileNotFoundError, OSError):
            return False
    elif IS_LINUX:
        desktop = Path.home() / ".config" / "autostart" / f"{APP_ID}.desktop"
        if not desktop.exists():
            return False
        content = desktop.read_text(encoding="utf-8")
        return "X-GNOME-Autostart-enabled=true" in content
    return False


def set_startup_enabled(enabled: bool) -> None:
    """Register or deregister the app for system startup."""
    if IS_WINDOWS:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE,
            )
            if enabled:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, _gui_launch_cmd())
            else:
                try:
                    winreg.DeleteValue(key, APP_ID)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[startup] Windows registry error: {e}")

    elif IS_LINUX:
        desktop_dir = Path.home() / ".config" / "autostart"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        desktop_file = desktop_dir / f"{APP_ID}.desktop"
        if enabled:
            content = (
                "[Desktop Entry]\n"
                f"Name={APP_NAME}\n"
                f"Exec={_gui_launch_cmd()}\n"
                "Type=Application\n"
                "Categories=Utility;\n"
                "Comment=Antighram Bot Control Center\n"
                "X-GNOME-Autostart-enabled=true\n"
                f"Icon={PROJECT_DIR / 'assets' / 'icon.png'}\n"
            )
            desktop_file.write_text(content, encoding="utf-8")
        else:
            if desktop_file.exists():
                desktop_file.unlink()
