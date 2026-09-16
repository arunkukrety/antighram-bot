"""
gui_app.py — Antigravity Telegram Bot Desktop Control Center

Cross-platform desktop tray application for Windows and Linux.
Manages the bot server process, live logs, and environment config
from a clean CustomTkinter UI that lives in the system tray.

Launch:
    python gui_app.py

The window starts hidden — the app lives in the system tray.
Left-click or "Open Control Panel" from the tray to show it.
"""

from __future__ import annotations

import os
import sys
import json
import time
import threading
import platform
import subprocess
from pathlib import Path
from typing import Optional

# ── Guard: friendly error if GUI deps are missing ──────────────────────────
_MISSING: list[str] = []
try:
    import customtkinter as ctk
except ImportError:
    _MISSING.append("customtkinter")
try:
    import pystray
    from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayItem
except ImportError:
    _MISSING.append("pystray")
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    _MISSING.append("pillow")

if _MISSING:
    print(
        f"\n[ERROR] Missing GUI dependencies: {', '.join(_MISSING)}\n"
        f"Install them with:\n"
        f"  pip install -r requirements-gui.txt\n"
    )
    sys.exit(1)

from dotenv import dotenv_values, set_key

# ── Frozen (PyInstaller) vs. development path resolution ──────────────────
# When packaged as a standalone exe, we can't store config next to the binary
# (it may be in a read-only location). Use the OS user-data directory instead.
if getattr(sys, 'frozen', False):
    # sys.executable = the .exe / Linux binary itself
    APP_DIR = Path(sys.executable).parent
    _BUNDLE_DIR = Path(sys._MEIPASS)          # PyInstaller temp extraction dir
    if IS_WINDOWS:
        CONFIG_DIR = Path(os.environ.get('APPDATA', Path.home())) / 'AntigravityBot'
    else:
        CONFIG_DIR = Path.home() / '.config' / 'agy-telegram-bot'
else:
    APP_DIR = Path(__file__).parent.resolve()
    _BUNDLE_DIR = APP_DIR
    CONFIG_DIR = APP_DIR

CONFIG_DIR.mkdir(parents=True, exist_ok=True)
PROJECT_DIR = APP_DIR          # used for display / ProcessManager working dir
ENV_FILE = CONFIG_DIR / '.env'

# Import after we know the project path
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(APP_DIR))
from agy_bot.process_manager import ProcessManager

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


# ══════════════════════════════════════════════════════════════════════════════
# Tray Icon Rendering (Pillow — no external image files needed)
# ══════════════════════════════════════════════════════════════════════════════

def _make_tray_image(running: bool, size: int = 64) -> "Image.Image":
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


# ══════════════════════════════════════════════════════════════════════════════
# .env helpers
# ══════════════════════════════════════════════════════════════════════════════

def read_env() -> dict[str, str]:
    """Return current .env contents as a dict (all values are strings)."""
    if not ENV_FILE.exists():
        return {}
    return dict(dotenv_values(ENV_FILE))


def write_env(key: str, value: str) -> None:
    """Write / update a single key in the .env file."""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Ensure the file exists
    if not ENV_FILE.exists():
        ENV_FILE.write_text("", encoding="utf-8")
    set_key(str(ENV_FILE), key, value, quote_mode="never")


def write_env_all(data: dict[str, str]) -> None:
    """Overwrite all tracked keys in .env atomically."""
    for k, v in data.items():
        write_env(k, v)


# ══════════════════════════════════════════════════════════════════════════════
# Startup Registration
# ══════════════════════════════════════════════════════════════════════════════

def _python_exe() -> str:
    return str(Path(sys.executable))


def _gui_launch_cmd() -> str:
    """The command that launches this GUI app."""
    return f'"{_python_exe()}" "{Path(__file__).resolve()}"'


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
                "Comment=Antigravity Telegram Bot Control Center\n"
                "X-GNOME-Autostart-enabled=true\n"
                f"Icon={PROJECT_DIR / 'assets' / 'icon.png'}\n"
            )
            desktop_file.write_text(content, encoding="utf-8")
        else:
            if desktop_file.exists():
                desktop_file.unlink()


# ══════════════════════════════════════════════════════════════════════════════
# Main Application
# ══════════════════════════════════════════════════════════════════════════════

class AgyBotApp:
    """
    Entry-point class.  Creates the hidden CTk root, the system tray icon,
    and all child widgets.  The root window only appears on user request.
    """

    def __init__(self) -> None:
        # ── Appearance ────────────────────────────────────────────────────
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # ── Hidden root window ────────────────────────────────────────────
        self.root = ctk.CTk()
        self.root.title(APP_NAME)
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.root.resizable(False, False)
        self.root.configure(fg_color=COLOR_BG_DARK)

        # Intercept the close button — hide to tray instead of quit
        self.root.protocol("WM_DELETE_WINDOW", self._hide_window)

        # Start hidden
        self.root.withdraw()

        # Set taskbar icon on Windows (best-effort)
        if IS_WINDOWS:
            try:
                self.root.iconbitmap(default="")
            except Exception:
                pass

        # ── Process manager ───────────────────────────────────────────────
        self._manager = ProcessManager(
            project_dir=PROJECT_DIR,
            on_status_change=self._on_status_change,
        )

        # ── Internal state ────────────────────────────────────────────────
        self._window_visible = False
        self._tray_icon: Optional[TrayIcon] = None
        self._last_status = "stopped"
        self._log_scroll_lock = False  # if user manually scrolled, pause auto-scroll

        # ── Build UI ──────────────────────────────────────────────────────
        self._build_ui()

        # ── System tray ───────────────────────────────────────────────────
        self._setup_tray()

        # ── Periodic refresh ──────────────────────────────────────────────
        self.root.after(REFRESH_MS, self._periodic_refresh)

    # ──────────────────────────────────────────────────────────────────────
    # Tray
    # ──────────────────────────────────────────────────────────────────────

    def _setup_tray(self) -> None:
        img_off = _make_tray_image(running=False)

        def on_left_click(icon, button):
            # pystray fires this for left-click via the default= mechanism
            self.root.after(0, self._toggle_window)

        self._tray_icon = TrayIcon(
            name=APP_ID,
            icon=img_off,
            title=APP_NAME,
            menu=TrayMenu(
                TrayItem("Status: Stopped", None, enabled=False),
                TrayMenu.SEPARATOR,
                TrayItem(
                    "Open Control Panel",
                    lambda icon, item: self.root.after(0, self._show_window),
                    default=True,          # bold; also the left-click default
                ),
                TrayMenu.SEPARATOR,
                TrayItem(
                    "Start Server",
                    lambda icon, item: self._tray_start(),
                    enabled=lambda item: self._last_status == "stopped",
                ),
                TrayItem(
                    "Stop Server",
                    lambda icon, item: self._tray_stop(),
                    enabled=lambda item: self._last_status == "running",
                ),
                TrayItem(
                    "Restart",
                    lambda icon, item: self._tray_restart(),
                    enabled=lambda item: self._last_status == "running",
                ),
                TrayMenu.SEPARATOR,
                TrayItem("Quit", lambda icon, item: self._quit()),
            ),
        )

        # Run tray on its own daemon thread so it doesn't block tkinter's mainloop
        t = threading.Thread(target=self._tray_icon.run, daemon=True)
        t.start()

    def _update_tray_icon(self, running: bool) -> None:
        if self._tray_icon is None:
            return
        label = "Running" if running else "Stopped"
        self._tray_icon.icon = _make_tray_image(running=running)
        self._tray_icon.title = f"{APP_NAME} — {label}"

    # ──────────────────────────────────────────────────────────────────────
    # Window visibility
    # ──────────────────────────────────────────────────────────────────────

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self._window_visible = True

    def _hide_window(self) -> None:
        self.root.withdraw()
        self._window_visible = False

    def _toggle_window(self) -> None:
        if self._window_visible:
            self._hide_window()
        else:
            self._show_window()

    # ──────────────────────────────────────────────────────────────────────
    # Tray action callbacks (safe to call from non-main threads)
    # ──────────────────────────────────────────────────────────────────────

    def _tray_start(self) -> None:
        threading.Thread(target=self._manager.start, daemon=True).start()

    def _tray_stop(self) -> None:
        threading.Thread(target=self._manager.stop, daemon=True).start()

    def _tray_restart(self) -> None:
        threading.Thread(target=self._manager.restart, daemon=True).start()

    def _quit(self) -> None:
        self._manager.stop()
        if self._tray_icon:
            self._tray_icon.stop()
        self.root.after(0, self.root.destroy)

    # ──────────────────────────────────────────────────────────────────────
    # Status change callback (called from ProcessManager thread)
    # ──────────────────────────────────────────────────────────────────────

    def _on_status_change(self, state: str) -> None:
        self._last_status = state
        # Schedule all UI updates on the main thread
        self.root.after(0, lambda: self._apply_status_ui(state))

    # ──────────────────────────────────────────────────────────────────────
    # Build UI
    # ──────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # ── Header bar ────────────────────────────────────────────────────
        header = ctk.CTkFrame(
            self.root, fg_color=COLOR_SURFACE, corner_radius=0, height=64
        )
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="✦ Antigravity Bot",
            font=ctk.CTkFont(family="Roboto", size=18, weight="bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left", padx=20)

        # Status pill in header
        self._header_status_lbl = ctk.CTkLabel(
            header,
            text="● STOPPED",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLOR_RED,
            fg_color=("#1A0808", "#1A0808"),
            corner_radius=10,
            padx=10,
            pady=4,
        )
        self._header_status_lbl.pack(side="right", padx=20, pady=18)

        # ── Tabview ───────────────────────────────────────────────────────
        self._tabs = ctk.CTkTabview(
            self.root,
            fg_color=COLOR_BG_DARK,
            segmented_button_fg_color=COLOR_SURFACE,
            segmented_button_selected_color=COLOR_ACCENT,
            segmented_button_selected_hover_color=COLOR_ACCENT_HVR,
            segmented_button_unselected_color=COLOR_SURFACE,
            segmented_button_unselected_hover_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            corner_radius=12,
        )
        self._tabs.pack(fill="both", expand=True, padx=12, pady=(6, 12))

        self._tabs.add("  Status  ")
        self._tabs.add("  Config  ")
        self._tabs.add("   Logs   ")

        self._build_status_tab(self._tabs.tab("  Status  "))
        self._build_config_tab(self._tabs.tab("  Config  "))
        self._build_logs_tab(self._tabs.tab("   Logs   "))

    # ── Status Tab ────────────────────────────────────────────────────────

    def _build_status_tab(self, parent) -> None:
        # Big status badge
        badge_frame = ctk.CTkFrame(parent, fg_color=COLOR_SURFACE, corner_radius=16)
        badge_frame.pack(fill="x", padx=20, pady=(28, 16))

        self._status_icon_lbl = ctk.CTkLabel(
            badge_frame,
            text="⬤",
            font=ctk.CTkFont(size=32),
            text_color=COLOR_RED,
        )
        self._status_icon_lbl.pack(pady=(20, 4))

        self._status_text_lbl = ctk.CTkLabel(
            badge_frame,
            text="STOPPED",
            font=ctk.CTkFont(family="Roboto", size=22, weight="bold"),
            text_color=COLOR_RED,
        )
        self._status_text_lbl.pack()

        self._pid_lbl = ctk.CTkLabel(
            badge_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
        )
        self._pid_lbl.pack(pady=(2, 20))

        # Toggle switch
        sw_frame = ctk.CTkFrame(parent, fg_color="transparent")
        sw_frame.pack(pady=8)

        ctk.CTkLabel(
            sw_frame,
            text="Server Power",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_TEXT_DIM,
        ).pack(side="left", padx=(0, 14))

        self._server_switch = ctk.CTkSwitch(
            sw_frame,
            text="",
            command=self._toggle_server,
            width=56,
            height=28,
            fg_color=COLOR_BORDER,
            progress_color=COLOR_GREEN,
            button_color="#FFFFFF",
            button_hover_color="#E5E7EB",
            switch_width=56,
            switch_height=28,
        )
        self._server_switch.pack(side="left")

        # Restart button
        self._restart_btn = ctk.CTkButton(
            parent,
            text="↺  Restart Server",
            command=lambda: threading.Thread(
                target=self._manager.restart, daemon=True
            ).start(),
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            border_color=COLOR_BORDER,
            border_width=1,
            text_color=COLOR_TEXT,
            corner_radius=10,
            height=38,
            state="disabled",
        )
        self._restart_btn.pack(fill="x", padx=20, pady=(16, 4))

        # Info box
        info = ctk.CTkFrame(parent, fg_color=COLOR_SURFACE, corner_radius=10)
        info.pack(fill="x", padx=20, pady=(20, 0))

        self._uptime_lbl = ctk.CTkLabel(
            info,
            text="Uptime: —",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
        )
        self._uptime_lbl.pack(fill="x", padx=16, pady=(10, 4))

        self._env_lbl = ctk.CTkLabel(
            info,
            text=f"Project: {PROJECT_DIR}",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM,
            anchor="w",
            wraplength=420,
        )
        self._env_lbl.pack(fill="x", padx=16, pady=(0, 10))

        self._start_time: Optional[float] = None

    # ── Config Tab ────────────────────────────────────────────────────────

    def _build_config_tab(self, parent) -> None:
        scroll = ctk.CTkScrollableFrame(
            parent,
            fg_color="transparent",
            scrollbar_button_color=COLOR_BORDER,
            scrollbar_button_hover_color=COLOR_ACCENT,
        )
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        env = read_env()

        def _section(label: str):
            ctk.CTkLabel(
                scroll,
                text=label.upper(),
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=COLOR_TEXT_DIM,
                anchor="w",
            ).pack(fill="x", padx=4, pady=(14, 4))

        def _field(label: str, key: str, *, masked: bool = False) -> ctk.CTkEntry:
            ctk.CTkLabel(
                scroll,
                text=label,
                font=ctk.CTkFont(size=13),
                text_color=COLOR_TEXT,
                anchor="w",
            ).pack(fill="x", padx=4, pady=(0, 2))
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=(0, 10))
            entry = ctk.CTkEntry(
                row,
                show="●" if masked else "",
                fg_color=COLOR_SURFACE,
                border_color=COLOR_BORDER,
                text_color=COLOR_TEXT,
                placeholder_text_color=COLOR_TEXT_DIM,
                corner_radius=8,
                height=36,
            )
            entry.pack(side="left", fill="x", expand=True)
            entry.insert(0, env.get(key, ""))
            if masked:
                eye_btn = ctk.CTkButton(
                    row,
                    text="👁",
                    width=36,
                    height=36,
                    fg_color=COLOR_SURFACE,
                    hover_color=COLOR_BORDER,
                    corner_radius=8,
                    command=lambda e=entry: _toggle_mask(e),
                )
                eye_btn.pack(side="left", padx=(6, 0))
            return entry

        def _toggle_mask(entry: ctk.CTkEntry):
            entry.configure(show="" if entry.cget("show") else "●")

        def _browse_field(entry: ctk.CTkEntry):
            from tkinter import filedialog
            chosen = filedialog.askdirectory(title="Select Directory")
            if chosen:
                entry.delete(0, "end")
                entry.insert(0, chosen)

        # ── Bot Credentials ───────────────────────────────────────────────
        _section("Bot Credentials")
        self._e_token = _field("Telegram Bot Token", "TELEGRAM_BOT_TOKEN", masked=True)
        self._e_chat_ids = _field("Allowed Chat IDs (comma-separated)", "TELEGRAM_ALLOWED_CHAT_IDS")

        # ── Runtime ───────────────────────────────────────────────────────
        _section("Runtime")
        self._e_agy_bin = _field("Agy CLI Binary", "AGY_BIN")

        ctk.CTkLabel(
            scroll,
            text="Default Workspace",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_TEXT,
            anchor="w",
        ).pack(fill="x", padx=4, pady=(0, 2))
        ws_row = ctk.CTkFrame(scroll, fg_color="transparent")
        ws_row.pack(fill="x", padx=4, pady=(0, 10))
        self._e_workspace = ctk.CTkEntry(
            ws_row,
            fg_color=COLOR_SURFACE,
            border_color=COLOR_BORDER,
            text_color=COLOR_TEXT,
            placeholder_text_color=COLOR_TEXT_DIM,
            corner_radius=8,
            height=36,
        )
        self._e_workspace.pack(side="left", fill="x", expand=True)
        self._e_workspace.insert(0, env.get("AGY_DEFAULT_WORKSPACE", ""))
        ctk.CTkButton(
            ws_row,
            text="Browse",
            width=68,
            height=36,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            corner_radius=8,
            command=lambda: _browse_field(self._e_workspace),
        ).pack(side="left", padx=(6, 0))

        self._e_timeout = _field("Print Timeout (seconds)", "AGY_PRINT_TIMEOUT")

        # ── Appearance ────────────────────────────────────────────────────
        _section("Appearance")
        ctk.CTkLabel(
            scroll,
            text="Theme",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_TEXT,
            anchor="w",
        ).pack(fill="x", padx=4, pady=(0, 2))
        self._theme_menu = ctk.CTkOptionMenu(
            scroll,
            values=["Dark", "Light", "System"],
            command=lambda v: ctk.set_appearance_mode(v.lower()),
            fg_color=COLOR_SURFACE,
            button_color=COLOR_ACCENT,
            button_hover_color=COLOR_ACCENT_HVR,
            text_color=COLOR_TEXT,
            dropdown_fg_color=COLOR_SURFACE,
            dropdown_hover_color=COLOR_BORDER,
            dropdown_text_color=COLOR_TEXT,
            corner_radius=8,
            height=36,
        )
        self._theme_menu.pack(fill="x", padx=4, pady=(0, 10))
        self._theme_menu.set("Dark")

        # ── System ────────────────────────────────────────────────────────
        _section("System")
        startup_row = ctk.CTkFrame(scroll, fg_color="transparent")
        startup_row.pack(fill="x", padx=4, pady=(0, 14))
        ctk.CTkLabel(
            startup_row,
            text="Start on system startup",
            font=ctk.CTkFont(size=13),
            text_color=COLOR_TEXT,
        ).pack(side="left")
        self._startup_switch = ctk.CTkSwitch(
            startup_row,
            text="",
            command=self._toggle_startup,
            width=50,
            height=26,
            fg_color=COLOR_BORDER,
            progress_color=COLOR_ACCENT,
            button_color="#FFFFFF",
            button_hover_color="#E5E7EB",
            switch_width=50,
            switch_height=26,
        )
        self._startup_switch.pack(side="right")
        if get_startup_enabled():
            self._startup_switch.select()

        # ── Save button ───────────────────────────────────────────────────
        self._save_feedback_lbl = ctk.CTkLabel(
            scroll,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=COLOR_GREEN,
        )
        self._save_feedback_lbl.pack(pady=(0, 4))

        ctk.CTkButton(
            scroll,
            text="💾  Save & Apply Changes",
            command=self._save_config,
            fg_color=COLOR_ACCENT,
            hover_color=COLOR_ACCENT_HVR,
            text_color="#FFFFFF",
            corner_radius=10,
            height=40,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(fill="x", padx=4, pady=(0, 24))

    # ── Logs Tab ──────────────────────────────────────────────────────────

    def _build_logs_tab(self, parent) -> None:
        btn_bar = ctk.CTkFrame(parent, fg_color="transparent")
        btn_bar.pack(fill="x", padx=4, pady=(4, 4))

        ctk.CTkLabel(
            btn_bar,
            text="Live Logs",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLOR_TEXT,
        ).pack(side="left")

        ctk.CTkButton(
            btn_bar,
            text="Clear",
            width=60,
            height=28,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            text_color=COLOR_TEXT_DIM,
            corner_radius=8,
            command=self._clear_logs,
        ).pack(side="right", padx=(4, 0))

        ctk.CTkButton(
            btn_bar,
            text="Copy",
            width=60,
            height=28,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_BORDER,
            text_color=COLOR_TEXT_DIM,
            corner_radius=8,
            command=self._copy_logs,
        ).pack(side="right", padx=(4, 0))

        self._log_box = ctk.CTkTextbox(
            parent,
            fg_color=COLOR_LOG_BG,
            border_color=COLOR_BORDER,
            border_width=1,
            text_color=COLOR_LOG_FG,
            font=ctk.CTkFont(family="Courier", size=11),
            corner_radius=10,
            wrap="word",
            state="disabled",
        )
        self._log_box.pack(fill="both", expand=True, padx=4, pady=(0, 4))

    # ──────────────────────────────────────────────────────────────────────
    # Actions
    # ──────────────────────────────────────────────────────────────────────

    def _toggle_server(self) -> None:
        is_on = self._server_switch.get()
        if is_on:
            threading.Thread(target=self._manager.start, daemon=True).start()
        else:
            threading.Thread(target=self._manager.stop, daemon=True).start()

    def _save_config(self) -> None:
        data = {
            "TELEGRAM_BOT_TOKEN": self._e_token.get().strip(),
            "TELEGRAM_ALLOWED_CHAT_IDS": self._e_chat_ids.get().strip(),
            "AGY_BIN": self._e_agy_bin.get().strip() or "agy",
            "AGY_DEFAULT_WORKSPACE": self._e_workspace.get().strip(),
            "AGY_PRINT_TIMEOUT": self._e_timeout.get().strip() or "300",
        }
        write_env_all(data)
        # Reload env into os.environ so ProcessManager picks it up on next start
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(ENV_FILE), override=True)

        self._save_feedback_lbl.configure(text="✔ Saved! Restart server to apply.")
        self.root.after(4000, lambda: self._save_feedback_lbl.configure(text=""))

        # Auto-restart if the server is running
        if self._last_status == "running":
            threading.Thread(target=self._manager.restart, daemon=True).start()

    def _toggle_startup(self) -> None:
        enabled = bool(self._startup_switch.get())
        try:
            set_startup_enabled(enabled)
        except Exception as e:
            print(f"[startup] Error: {e}")

    def _clear_logs(self) -> None:
        self._log_box.configure(state="normal")
        self._log_box.delete("0.0", "end")
        self._log_box.configure(state="disabled")

    def _copy_logs(self) -> None:
        text = self._log_box.get("0.0", "end")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    # ──────────────────────────────────────────────────────────────────────
    # UI state update helpers
    # ──────────────────────────────────────────────────────────────────────

    def _apply_status_ui(self, state: str) -> None:
        running = state == "running"
        color = COLOR_GREEN if running else COLOR_RED
        text = "RUNNING" if running else "STOPPED"
        dot = "⬤"
        pill_bg = ("#061A0E", "#061A0E") if running else ("#1A0808", "#1A0808")

        # Header pill
        self._header_status_lbl.configure(
            text=f"● {text}",
            text_color=color,
            fg_color=pill_bg,
        )
        # Status tab badge
        self._status_icon_lbl.configure(text=dot, text_color=color)
        self._status_text_lbl.configure(text=text, text_color=color)

        # PID label
        status = self._manager.status()
        pid_text = f"PID: {status['pid']}" if status.get("pid") else ""
        self._pid_lbl.configure(text=pid_text)

        # Toggle switch (sync without firing command)
        if running and not self._server_switch.get():
            self._server_switch.select()
        elif not running and self._server_switch.get():
            self._server_switch.deselect()

        # Restart button
        self._restart_btn.configure(state="normal" if running else "disabled")

        # Uptime
        if running and self._start_time is None:
            self._start_time = time.monotonic()
        elif not running:
            self._start_time = None
        if self._start_time and running:
            secs = int(time.monotonic() - self._start_time)
            h, rem = divmod(secs, 3600)
            m, s = divmod(rem, 60)
            self._uptime_lbl.configure(text=f"Uptime: {h:02d}:{m:02d}:{s:02d}")
        else:
            self._uptime_lbl.configure(text="Uptime: —")

        # Tray icon
        self._update_tray_icon(running)
        self._last_status = state

    # ──────────────────────────────────────────────────────────────────────
    # Periodic refresh (runs on main thread via root.after)
    # ──────────────────────────────────────────────────────────────────────

    def _periodic_refresh(self) -> None:
        # Status
        status = self._manager.status()
        current_state = status["state"]
        if current_state != self._last_status:
            self._apply_status_ui(current_state)
        elif current_state == "running" and self._start_time:
            # Keep uptime ticking even if state didn't change
            secs = int(time.monotonic() - self._start_time)
            h, rem = divmod(secs, 3600)
            m, s = divmod(rem, 60)
            self._uptime_lbl.configure(text=f"Uptime: {h:02d}:{m:02d}:{s:02d}")

        # Logs (only update if Logs tab is visible to save CPU)
        logs = self._manager.get_logs(last_n=300)
        log_text = "\n".join(logs)
        current = self._log_box.get("0.0", "end").rstrip("\n")
        if log_text != current:
            self._log_box.configure(state="normal")
            self._log_box.delete("0.0", "end")
            self._log_box.insert("end", log_text)
            self._log_box.configure(state="disabled")
            # Auto-scroll to bottom
            self._log_box.see("end")

        # Schedule next refresh
        self.root.after(REFRESH_MS, self._periodic_refresh)

    # ──────────────────────────────────────────────────────────────────────
    # Run
    # ──────────────────────────────────────────────────────────────────────

    def run(self) -> None:
        self.root.mainloop()


# ══════════════════════════════════════════════════════════════════════════════
# Bot-mode runner  (used by the frozen exe when spawned with --run-bot)
# ══════════════════════════════════════════════════════════════════════════════

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


def _has_token() -> bool:
    """Return True if a Bot Token is already configured."""
    env = read_env()
    token = env.get('TELEGRAM_BOT_TOKEN', '').strip()
    return bool(token) and token != '123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ'


# ══════════════════════════════════════════════════════════════════════════════
# First-run Setup Wizard
# ══════════════════════════════════════════════════════════════════════════════

class SetupWizard:
    """
    Standalone CTk window shown on first launch when no valid token is found.
    Collects credentials, writes .env, then destroys itself so the main
    AgyBotApp can start normally.
    """

    def __init__(self) -> None:
        ctk.set_appearance_mode('dark')
        ctk.set_default_color_theme('blue')

        self._root = ctk.CTk()
        self._root.title('Antigravity Bot — First Run Setup')
        self._root.geometry('460x520')
        self._root.resizable(False, False)
        self._root.configure(fg_color=COLOR_BG_DARK)
        self._root.protocol('WM_DELETE_WINDOW', self._cancel)
        self._completed = False
        self._build()

    def _build(self) -> None:
        r = self._root

        # Branding
        ctk.CTkLabel(
            r, text='✦',
            font=ctk.CTkFont(size=48),
            text_color=COLOR_ACCENT,
        ).pack(pady=(36, 0))

        ctk.CTkLabel(
            r, text='Antigravity Bot',
            font=ctk.CTkFont(family='Roboto', size=22, weight='bold'),
            text_color=COLOR_TEXT,
        ).pack(pady=(4, 2))

        ctk.CTkLabel(
            r, text='Quick setup — takes 30 seconds',
            font=ctk.CTkFont(size=12),
            text_color=COLOR_TEXT_DIM,
        ).pack(pady=(0, 24))

        card = ctk.CTkFrame(r, fg_color=COLOR_SURFACE, corner_radius=14)
        card.pack(fill='x', padx=28)

        # Bot Token
        ctk.CTkLabel(
            card, text='Telegram Bot Token',
            font=ctk.CTkFont(size=13, weight='bold'),
            text_color=COLOR_TEXT, anchor='w',
        ).pack(fill='x', padx=16, pady=(16, 4))
        ctk.CTkLabel(
            card,
            text='Get yours from @BotFather on Telegram',
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM, anchor='w',
        ).pack(fill='x', padx=16, pady=(0, 4))
        self._e_token = ctk.CTkEntry(
            card, show='●',
            placeholder_text='1234567890:ABCdef...',
            fg_color=COLOR_BG_DARK, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, corner_radius=8, height=36,
        )
        self._e_token.pack(fill='x', padx=16, pady=(0, 14))

        # Chat IDs
        ctk.CTkLabel(
            card, text='Allowed Chat IDs  (optional)',
            font=ctk.CTkFont(size=13, weight='bold'),
            text_color=COLOR_TEXT, anchor='w',
        ).pack(fill='x', padx=16, pady=(0, 4))
        ctk.CTkLabel(
            card,
            text='Comma-separated. Get yours from @userinfobot',
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM, anchor='w',
        ).pack(fill='x', padx=16, pady=(0, 4))
        self._e_ids = ctk.CTkEntry(
            card,
            placeholder_text='123456789, 987654321',
            fg_color=COLOR_BG_DARK, border_color=COLOR_BORDER,
            text_color=COLOR_TEXT, corner_radius=8, height=36,
        )
        self._e_ids.pack(fill='x', padx=16, pady=(0, 16))

        # Error label
        self._err_lbl = ctk.CTkLabel(
            r, text='', font=ctk.CTkFont(size=12),
            text_color=COLOR_RED,
        )
        self._err_lbl.pack(pady=(10, 0))

        # Launch button
        ctk.CTkButton(
            r,
            text='Get Started  →',
            command=self._submit,
            fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HVR,
            text_color='#FFFFFF', corner_radius=10, height=42,
            font=ctk.CTkFont(size=15, weight='bold'),
        ).pack(fill='x', padx=28, pady=(16, 8))

        ctk.CTkLabel(
            r,
            text='You can change these later in Settings',
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_DIM,
        ).pack()

    def _submit(self) -> None:
        token = self._e_token.get().strip()
        if not token or ':' not in token:
            self._err_lbl.configure(text='⚠  Please enter a valid Bot Token')
            return
        chat_ids = self._e_ids.get().strip()
        write_env_all({
            'TELEGRAM_BOT_TOKEN': token,
            'TELEGRAM_ALLOWED_CHAT_IDS': chat_ids,
            'AGY_BIN': 'agy',
            'AGY_DEFAULT_WORKSPACE': str(Path.home() / 'agy-server-workspace'),
            'AGY_PRINT_TIMEOUT': '300',
        })
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=str(ENV_FILE), override=True)
        self._completed = True
        self._root.destroy()

    def _cancel(self) -> None:
        self._root.destroy()

    def run(self) -> bool:
        """Show the wizard; return True if user completed setup."""
        self._root.mainloop()
        return self._completed


# ══════════════════════════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    # ── Bot-subprocess mode ────────────────────────────────────────────────
    # When the frozen exe is spawned by ProcessManager with --run-bot,
    # skip all GUI code and just run the bot.
    if '--run-bot' in sys.argv:
        _run_bot_mode()
        return

    # ── First-run setup wizard ─────────────────────────────────────────────
    if not _has_token():
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
