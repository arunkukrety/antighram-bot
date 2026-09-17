"""
Interactive PTY mode: spawn, screen rendering, reader loop, quiet-screen handler.
"""

import asyncio
import html
import re
import time
from typing import List, Optional

from agy_bot import pty_compat
import pyte
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application
from telegram.constants import ParseMode

from agy_bot.config import log, AGY_BIN, PTY_ROWS, PTY_COLS, QUIET_SECONDS, POLL_TIMEOUT
from agy_bot.session import ChatSession, PendingPermission
from agy_bot.rendering.text import split_text


def spawn_interactive_agy(
    workspace: str,
    model: Optional[str],
    resume: bool,
):

    args = []

    if model:

        args += [
            "--model",
            model,
        ]

    if resume:

        args += [
            "--continue",
        ]

    return pty_compat.spawn(
        AGY_BIN,
        args=args,
        cwd=workspace,
        timeout=None,
        encoding="utf-8",
        codec_errors="replace",
        dimensions=(
            PTY_ROWS,
            PTY_COLS,
        ),
    )


def render_screen_text(
    screen: pyte.Screen,
) -> List[str]:

    lines = list(
        screen.display
    )

    while (
        lines
        and not lines[-1].strip()
    ):

        lines.pop()

    return lines


def find_new_lines(
    previous: List[str],
    current: List[str],
) -> List[str]:

    common = 0

    for a, b in zip(
        previous,
        current,
    ):

        if a == b:
            common += 1
        else:
            break

    return current[common:]


def parse_permission_prompt(
    lines: List[str],
) -> Optional[PendingPermission]:

    joined = "\n".join(
        lines
    )

    if not re.search(
        r"Do you want to proceed\?",
        joined,
        re.IGNORECASE,
    ):

        return None

    action = (
        "unknown action"
    )

    match = re.search(
        r"Requesting permission for:\s*(.+)",
        joined,
        re.IGNORECASE,
    )

    if match:
        action = match.group(1).strip()

    options = []

    for line in lines:

        match = re.match(
            r"^\s*[>\s]?\s*(\d+)\.\s+(.*\S)\s*$",
            line,
        )

        if match:

            options.append(
                (
                    int(
                        match.group(1)
                    ),
                    match.group(2).strip(),
                )
            )

    if not options:
        return None

    return PendingPermission(
        action=action,
        options=options,
    )


async def interactive_reader_loop(
    app: Application,
    session: ChatSession,
):

    loop = asyncio.get_running_loop()

    state = session.interactive

    if not state:
        return

    child = state.child

    try:

        while True:

            try:

                chunk = await loop.run_in_executor(
                    None,
                    child.read_nonblocking,
                    4096,
                    POLL_TIMEOUT,
                )

                if chunk:

                    state.stream.feed(
                        chunk
                    )

                    state.last_data_at = (
                        time.time()
                    )

                    state.dirty = True

            except pty_compat.TIMEOUT:
                pass

            except pty_compat.EOF:

                await app.bot.send_message(
                    session.chat_id,
                    "⚠️ agy process exited.\n"
                    "Use /interactive to relaunch.",
                )

                session.interactive = None
                session.mode = "print"

                return

            idle_for = (
                time.time()
                - state.last_data_at
            )

            if (
                state.dirty
                and idle_for >= QUIET_SECONDS
            ):

                await handle_quiet_screen(
                    app,
                    session,
                )

                state.dirty = False

    except asyncio.CancelledError:
        return

    except Exception:

        log.exception(
            "Interactive reader crashed"
        )


async def handle_quiet_screen(
    app: Application,
    session: ChatSession,
):

    state = session.interactive

    if not state:
        return

    current_lines = render_screen_text(
        state.screen
    )

    permission = parse_permission_prompt(
        current_lines
    )

    if (
        permission
        and state.pending is None
    ):

        state.pending = permission

        buttons = []

        for number, label in (
            permission.options
        ):

            buttons.append(
                [
                    InlineKeyboardButton(
                        f"{number}. {label[:50]}",
                        callback_data=(
                            f"perm:"
                            f"{session.chat_id}:"
                            f"{number}"
                        ),
                    )
                ]
            )

        await app.bot.send_message(
            session.chat_id,
            (
                "🔐 <b>agy wants to:</b>\n\n"
                + html.escape(
                    permission.action
                )
                + "\n\n"
                "Choose an option:"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
        )

        state.last_display_lines = (
            current_lines
        )

        return

    if (
        permission
        and state.pending is not None
    ):

        state.last_display_lines = (
            current_lines
        )

        return

    new_lines = find_new_lines(
        state.last_display_lines,
        current_lines,
    )

    state.last_display_lines = (
        current_lines
    )

    state.pending = None

    text = "\n".join(
        new_lines
    ).strip()

    if text:

        for chunk in split_text(
            text
        ):

            await app.bot.send_message(
                session.chat_id,
                html.escape(
                    chunk
                ),
                parse_mode=ParseMode.HTML,
            )
