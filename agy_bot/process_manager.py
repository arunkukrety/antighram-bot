"""
agy_bot/process_manager.py

Cross-platform, thread-safe manager for the Telegram bot subprocess.
Handles start / stop / restart / status / log capture cleanly on
both Windows and Linux without any external process supervisors.
"""

from __future__ import annotations

import os
import sys
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Deque, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_BUFFER_SIZE = 600          # max lines kept in memory
GRACEFUL_STOP_SECS = 4.0       # seconds before SIGKILL on Linux
POLL_INTERVAL = 0.1            # seconds between stdout reads
STARTUP_EMIT_DELAY = 0.2       # seconds to wait before declaring "started"

IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# ProcessManager
# ---------------------------------------------------------------------------

class ProcessManager:
    """
    Manages the lifecycle of `telegram_agy_bot.py` as a child subprocess.

    Thread-safety contract:
      All public methods acquire ``_lock`` before touching ``_proc`` or
      ``_log_buffer``.  The background reader thread also acquires the lock
      only for buffer appends, keeping contention minimal.
    """

    def __init__(
        self,
        project_dir: Path,
        python_exe: Optional[Path] = None,
        on_status_change: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._dir = Path(project_dir).resolve()
        self._python = python_exe or Path(sys.executable)
        self._on_status_change = on_status_change or (lambda s: None)

        self._proc: Optional[subprocess.Popen] = None
        self._log_buffer: Deque[str] = deque(maxlen=LOG_BUFFER_SIZE)
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        Start the bot subprocess.  Returns True if successfully started,
        False if it was already running.
        """
        with self._lock:
            if self._is_alive():
                return False
            self._proc = self._spawn()

        # Kick off background log reader (outside lock to avoid deadlock)
        t = threading.Thread(target=self._reader_loop, daemon=True)
        t.start()
        self._reader_thread = t

        time.sleep(STARTUP_EMIT_DELAY)
        self._on_status_change("running")
        return True

    def stop(self) -> bool:
        """
        Gracefully terminate the bot subprocess.  Returns True if
        it was running and has been stopped, False if already stopped.
        """
        with self._lock:
            if not self._is_alive():
                self._proc = None
                return False
            proc = self._proc
            self._proc = None

        self._terminate(proc)
        self._on_status_change("stopped")
        return True

    def restart(self) -> None:
        """Stop (if running) then start."""
        self.stop()
        time.sleep(0.5)
        self.start()

    def status(self) -> dict:
        """
        Return a dict with keys:
          ``state``  — "running" | "stopped"
          ``pid``    — int or None
        """
        with self._lock:
            alive = self._is_alive()
            pid = self._proc.pid if alive else None
        return {"state": "running" if alive else "stopped", "pid": pid}

    def get_logs(self, last_n: int = 200) -> list[str]:
        """Return the last *last_n* log lines."""
        with self._lock:
            return list(self._log_buffer)[-last_n:]

    def append_log(self, line: str) -> None:
        """Inject a UI-sourced message into the log buffer (e.g. status events)."""
        with self._lock:
            self._log_buffer.append(line)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_alive(self) -> bool:
        """Must be called with ``_lock`` held."""
        return self._proc is not None and self._proc.poll() is None

    def _spawn(self) -> subprocess.Popen:
        """Spawn the bot process. Called with ``_lock`` held."""
        env = os.environ.copy()

        if getattr(sys, 'frozen', False):
            # Running as a PyInstaller single-file binary.
            # Spawn ourselves with --run-bot flag — the binary acts as both
            # GUI and headless bot runner depending on the argument.
            cmd = [sys.executable, '--run-bot']
        else:
            script = self._dir / "telegram_agy_bot.py"
            cmd = [str(self._python), str(script)]

        kwargs: dict = dict(
            args=cmd,
            cwd=str(self._dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if IS_WINDOWS:
            # Prevent a console window from flashing on Windows
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | 0x00000008  # DETACHED_PROCESS flag (no console window)
            )
        else:
            kwargs["start_new_session"] = True  # detach from parent's session

        with self._lock:
            self._log_buffer.append(
                f"[GUI] Starting bot … ({self._python} {script})"
            )

        return subprocess.Popen(**kwargs)

    def _terminate(self, proc: subprocess.Popen) -> None:
        """Terminate a process gracefully, then forcefully."""
        try:
            if IS_WINDOWS:
                import ctypes
                # Send CTRL_BREAK to the process group for clean shutdown
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                except (OSError, AttributeError):
                    pass
                try:
                    proc.wait(timeout=GRACEFUL_STOP_SECS)
                except subprocess.TimeoutExpired:
                    # Force kill the entire process tree
                    subprocess.call(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    proc.wait(timeout=GRACEFUL_STOP_SECS)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                except ProcessLookupError:
                    pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

        with self._lock:
            self._log_buffer.append("[GUI] Bot process stopped.")

    def _reader_loop(self) -> None:
        """Background daemon thread: drain subprocess stdout into log buffer."""
        proc_ref: Optional[subprocess.Popen] = None
        with self._lock:
            proc_ref = self._proc

        if proc_ref is None or proc_ref.stdout is None:
            return

        try:
            for line in proc_ref.stdout:
                stripped = line.rstrip("\n\r")
                with self._lock:
                    self._log_buffer.append(stripped)
        except Exception:
            pass
        finally:
            # Process ended — update status if it died unexpectedly
            if proc_ref.poll() is not None:
                with self._lock:
                    if self._proc is proc_ref:
                        self._proc = None
                self._on_status_change("stopped")
