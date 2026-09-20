#!/usr/bin/env python3
"""
build.py — Local PyInstaller build script for Antighram Bot.

Produces a single-file standalone executable for the current platform:
  Windows → dist/AntighramBot.exe
  Linux   → dist/AntighramBot-linux

Usage:
    python build.py              # build
    python build.py --clean      # remove dist/ and build/ directories
    python build.py --install    # install PyInstaller first, then build
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
from pathlib import Path

# ── Force UTF-8 output so the fancy banner doesn't crash on Windows
#    consoles (cp1252) or CI runners without PYTHONIOENCODING set. ──────────
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT  = Path(__file__).parent.resolve()
DIST  = ROOT / "dist"
BUILD = ROOT / "build"
SPEC  = ROOT / "antighram_bot.spec"

GREEN = "\033[32m"
RED   = "\033[31m"
CYAN  = "\033[36m"
DIM   = "\033[2m"
RESET = "\033[0m"

def banner():
    print(f"\n{CYAN}╔══════════════════════════════════════╗")
    print(f"║   Antighram Bot — PyInstaller Build  ║")
    print(f"╚══════════════════════════════════════╝{RESET}\n")

def step(msg: str):  print(f"{CYAN}==> {RESET}{msg}")
def ok(msg: str):    print(f"    {GREEN}✔{RESET}  {msg}")
def err(msg: str):   print(f"    {RED}✗{RESET}  {msg}"); sys.exit(1)

def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        ok(f"PyInstaller already installed")
    except ImportError:
        step("Installing PyInstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        ok("PyInstaller installed")

def ensure_gui_deps():
    step("Checking GUI dependencies...")
    result = subprocess.run(
        [sys.executable, "-c", "import customtkinter, pystray, PIL"],
        capture_output=True,
    )
    if result.returncode != 0:
        step("Installing GUI dependencies...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements-gui.txt")]
        )
    ok("GUI dependencies present")

def clean():
    for d in [DIST, BUILD]:
        if d.exists():
            shutil.rmtree(d)
            ok(f"Removed {d.name}/")
    # Remove cached .spec pyc
    for p in ROOT.glob("**/__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
    print(f"\n{GREEN}Clean complete.{RESET}\n")

def build():
    if not SPEC.exists():
        err(f"Spec file not found: {SPEC}")

    step(f"Building for {sys.platform}...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(SPEC),
    ]
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        err("PyInstaller failed — check output above for details.")

    # Locate output
    outputs = list(DIST.glob("AntighramBot*"))
    if not outputs:
        err(f"No output found in {DIST}")

    print()
    for f in outputs:
        size_mb = f.stat().st_size / (1024 * 1024)
        ok(f"Built: {f.relative_to(ROOT)}  ({size_mb:.1f} MB)")
        # Make Linux binary executable
        if sys.platform != "win32":
            os.chmod(f, 0o755)
            ok("Set executable bit (+x)")

    print(f"\n{GREEN}Build complete!{RESET}")
    print(f"\nRun it:")
    for f in outputs:
        print(f"  {CYAN}{f.relative_to(ROOT)}{RESET}")
    print()

def main():
    banner()

    if "--clean" in sys.argv:
        clean()
        return

    ensure_pyinstaller()
    ensure_gui_deps()
    build()

if __name__ == "__main__":
    main()
