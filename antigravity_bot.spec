# antigravity_bot.spec
# PyInstaller spec file for building the Antigravity Bot standalone executable.
#
# Build with:  python build.py
# Or directly: pyinstaller antigravity_bot.spec

import sys
from pathlib import Path

# ── resolve paths ────────────────────────────────────────────────────────────
ROOT = Path(SPECPATH).resolve()
IS_WIN = sys.platform == "win32"

# ── customtkinter assets (themes, icons, etc.) ───────────────────────────────
try:
    import customtkinter as _ctk
    _ctk_dir = Path(_ctk.__file__).parent
    _ctk_datas = [
        (str(_ctk_dir / "assets"), "customtkinter/assets"),
    ]
except ImportError:
    _ctk_datas = []

# ── agy_bot package source files ─────────────────────────────────────────────
_agydatas = [
    (str(ROOT / "agy_bot"), "agy_bot"),
]

datas = _ctk_datas + _agydatas

# ── hidden imports PyInstaller may miss ─────────────────────────────────────
# pystray has platform-specific backend modules imported at runtime
hidden_imports = [
    # pystray backends
    "pystray._xorg",
    "pystray._gtk",
    "pystray._win32",
    "pystray._darwin",
    # PIL
    "PIL._tkinter_finder",
    "PIL.Image",
    "PIL.ImageDraw",
    # agy_bot internals (not directly imported by gui_app.py but needed for --run-bot)
    "agy_bot.main",
    "agy_bot.config",
    "agy_bot.session",
    # python-telegram-bot
    "telegram",
    "telegram.ext",
    "telegram.request",
    # fastapi / uvicorn
    "fastapi",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # pexpect (Linux) / pyte
    "pexpect",
    "pexpect.exceptions",
    "pyte",
    # ConPTY backend for Windows PTY support (agy_bot.pty_compat)
    "winpty",
    # dotenv
    "dotenv",
    "dotenv.main",
    # tkinter (must be present on build machine)
    "tkinter",
    "tkinter.filedialog",
]

# ── large packages we definitely don't need ──────────────────────────────────
excludes = [
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "PyQt5",
    "PyQt6",
    "wx",
    "jupyter",
    "IPython",
    "notebook",
    "sphinx",
    "pytest",
]

block_cipher = None

a = Analysis(
    [str(ROOT / "gui_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    # Output name differs by platform for clear GitHub Release filenames
    name="AntigravityBot" if IS_WIN else "AntigravityBot-linux",
    debug=False,
    bootloader_ignore_signals=False,
    strip=not IS_WIN,       # strip symbols on Linux to reduce size
    # NOTE: UPX is deliberately disabled — CI UPX 5.x hard-fails on random
    # .pyd files (e.g. _uuid.pyd) and compressed Tcl/Tk DLLs break at runtime.
    upx=False,
    runtime_tmpdir=None,
    # No console window — this is a GUI/tray app
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Icon: supply a .ico (Windows) or .icns (macOS); omit if none exists yet
    # icon="assets/icon.ico",
)
