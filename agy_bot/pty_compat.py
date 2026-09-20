"""
agy_bot/pty_compat.py

Cross-platform PTY spawn helper providing the small subset of the
pexpect.spawn API that this project uses:

    spawn(command, args=..., cwd=..., dimensions=..., timeout=..., encoding=...)
    child.read_nonblocking(size, timeout) -> str
    child.send(text)
    child.close(force=...)
    child.isalive()

On POSIX this delegates to real pexpect.  On Windows it uses
pywinpty (ConPTY) so interactive CLI tools such as `agy` get a
full pseudo-terminal without needing WSL.

TIMEOUT / EOF are the exact pexpect exception classes, so existing
``except pexpect.TIMEOUT`` style handlers keep working unchanged.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from typing import List, Optional

from pexpect.exceptions import EOF, TIMEOUT  # noqa: F401  (re-exported)

IS_WINDOWS = sys.platform == "win32"

__all__ = ["spawn", "TIMEOUT", "EOF"]


def spawn(
    command: str,
    args: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    dimensions=(24, 80),
    timeout: Optional[float] = None,
    encoding: str = "utf-8",
    codec_errors: str = "replace",
    env: Optional[dict] = None,
):
    """Return a pexpect-like child process object for the current platform."""
    if IS_WINDOWS:
        return _ConPTYChild(
            command,
            args=args,
            cwd=cwd,
            dimensions=dimensions,
            timeout=timeout,
            encoding=encoding,
            codec_errors=codec_errors,
            env=env,
        )
    import pexpect

    return pexpect.spawn(
        command,
        args=args,
        cwd=cwd,
        dimensions=dimensions,
        timeout=timeout,
        encoding=encoding,
        codec_errors=codec_errors,
        env=env,
    )


class _ConPTYChild:
    """ConPTY-backed stand-in for pexpect.spawn (Windows only)."""

    def __init__(
        self,
        command: str,
        args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        dimensions=(24, 80),
        timeout: Optional[float] = None,
        encoding: str = "utf-8",
        codec_errors: str = "replace",
        env: Optional[dict] = None,
    ) -> None:
        from winpty import PtyProcess

        argv = [command] + [str(a) for a in (args or [])]
        rows, cols = dimensions if len(dimensions) == 2 else (24, 80)
        self._proc = PtyProcess.spawn(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env or dict(os.environ),
            dimensions=(int(rows), int(cols)),
        )
        self._enc = encoding
        self._codec_errors = codec_errors
        self._default_timeout = timeout
        self._chunks: "queue.Queue[bytes]" = queue.Queue()
        self._eof = threading.Event()
        self._closed = False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    # ------------------------------------------------------------------
    @property
    def pid(self) -> int:
        return self._proc.pid

    def _read_loop(self) -> None:
        while not self._eof.is_set():
            try:
                data = self._proc.read(4096)
            except EOFError:
                # The pty/socket is genuinely closed - the child is gone.
                self._eof.set()
                return
            except Exception:
                # Transient read error. Only stop if the child has actually
                # exited; otherwise keep reading so we don't drop output.
                if not self.isalive():
                    self._eof.set()
                    return
                time.sleep(0.01)
                continue

            if isinstance(data, str):
                data = data.encode(self._enc, self._codec_errors)

            if not data:
                # winpty's read() can return an empty string without the
                # process having exited (e.g. its internal "0011Ignore"
                # sentinel). Treating that as EOF truncates the stream and
                # can drop the final `result` event, so only stop when the
                # child is really gone.
                if not self.isalive():
                    self._eof.set()
                    return
                time.sleep(0.005)
                continue

            self._chunks.put(data)

    def read_nonblocking(
        self,
        size: int = 1,
        timeout: Optional[float] = "timeout_not_set",  # type: ignore[assignment]
    ) -> str:
        if timeout == "timeout_not_set":  # sentinel mirroring pexpect
            timeout = self._default_timeout
        size = max(int(size), 1)
        if timeout is None:
            # Block until at least one byte arrives.
            try:
                data = self._chunks.get()
            except Exception:
                raise EOF("ConPTY stream closed")
            return data[:size].decode(self._enc, self._codec_errors)

        deadline = time.monotonic() + max(float(timeout), 0.0)
        parts: List[bytes] = []
        total = 0
        while total < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                chunk = self._chunks.get(timeout=min(remaining, 0.25))
            except queue.Empty:
                if self._eof.is_set() and self._chunks.empty():
                    break
                continue
            parts.append(chunk)
            total += len(chunk)

        if not parts:
            if self._eof.is_set():
                raise EOF("ConPTY stream closed (process exited)")
            raise TIMEOUT(f"read_nonblocking timed out after {timeout}s")
        return b"".join(parts)[:size].decode(self._enc, self._codec_errors)

    def send(self, data) -> None:
        text = data.decode(self._enc, self._codec_errors) if isinstance(data, bytes) else str(data)
        self._proc.write(text)

    def sendline(self, text: str = "") -> None:
        self.send(text + "\r")

    def isalive(self) -> bool:
        try:
            return bool(self._proc.isalive())
        except Exception:
            return False

    def close(self, force: bool = False) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.isalive():
                if force:
                    self._proc.terminate(force=True)
                else:
                    self._proc.terminate()
        except Exception:
            pass
        try:
            self._proc.close(force=force)
        except Exception:
            pass
        self._eof.set()

    def terminate(self, force: bool = False) -> None:
        self.close(force=True or force)

    def kill(self, sig: int = 9) -> None:
        self.close(force=True)

    def wait(self) -> Optional[int]:
        while self.isalive():
            time.sleep(0.05)
        try:
            return self._proc.exitstatus
        except Exception:
            return None
