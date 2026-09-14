"""
Session state: dataclasses and global SESSIONS registry.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pexpect
import pyte


@dataclass
class PendingPermission:
    action: str
    options: List[Tuple[int, str]]


@dataclass
class InteractiveState:
    child: pexpect.spawn
    screen: pyte.Screen
    stream: pyte.Stream

    last_data_at: float = field(
        default_factory=time.time
    )

    dirty: bool = True

    last_display_lines: List[str] = field(
        default_factory=list
    )

    pending: Optional[PendingPermission] = None

    reader_task: Optional[asyncio.Task] = None


@dataclass
class ChatSession:
    chat_id: int
    workspace: str

    mode: str = "print"

    model: Optional[str] = None

    conversation_id: Optional[str] = None

    busy: bool = False

    interactive: Optional[InteractiveState] = None


SESSIONS: Dict[int, ChatSession] = {}


def teardown_session(old: "ChatSession"):
    """Cancel reader task and close PTY child for an existing session."""
    if old and old.interactive:
        if old.interactive.reader_task:
            old.interactive.reader_task.cancel()
        try:
            old.interactive.child.close(force=True)
        except Exception:
            pass
