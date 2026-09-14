"""
Print mode: run agy via stream-json and stream status updates to Telegram.
"""

import asyncio
import json
import time
from typing import List, Optional

import pexpect
from telegram.ext import Application
from telegram.constants import ChatAction

from agy_bot.config import log, AGY_BIN, PRINT_TIMEOUT
from agy_bot.session import ChatSession
from agy_bot.rendering.text import strip_ansi
from agy_bot.rendering.images import find_involved_images, send_final_response
from agy_bot.agy.status import status_from_event
from agy_bot.conversation.history import record_conversation


def run_stream_print_mode_sync(
    session: ChatSession,
    prompt: str,
    event_callback=None,
):
    """
    Run agy using stream-json.

    event_callback receives each decoded event.
    """

    cmd = [
        AGY_BIN,
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
    ]

    if session.model:

        cmd += [
            "--model",
            session.model,
        ]

    if session.conversation_id:

        cmd += [
            "--conversation",
            session.conversation_id,
        ]

    cmd += [
        "-p",
        prompt,
    ]

    log.info(
        "Starting agy stream-json"
    )

    child = pexpect.spawn(
        cmd[0],
        args=cmd[1:],
        cwd=session.workspace,
        timeout=PRINT_TIMEOUT,
        encoding="utf-8",
        codec_errors="replace",
    )

    events = []

    buffer = ""

    try:

        while True:

            try:

                chunk = child.read_nonblocking(
                    size=65536,
                    timeout=PRINT_TIMEOUT,
                )

                if not chunk:
                    continue

                buffer += chunk

                while "\n" in buffer:

                    line, buffer = (
                        buffer.split(
                            "\n",
                            1,
                        )
                    )

                    line = (
                        strip_ansi(line)
                        .strip()
                    )

                    if not line:
                        continue

                    try:

                        event = json.loads(
                            line
                        )

                        events.append(
                            event
                        )

                        if event_callback:
                            event_callback(
                                event
                            )

                    except json.JSONDecodeError:

                        log.debug(
                            "Non-JSON agy output: %s",
                            line,
                        )

            except pexpect.TIMEOUT:

                raise

            except pexpect.EOF:

                break

    finally:

        # Handle a final line without newline.
        if buffer.strip():

            try:

                event = json.loads(
                    strip_ansi(
                        buffer
                    ).strip()
                )

                events.append(
                    event
                )

                if event_callback:
                    event_callback(
                        event
                    )

            except Exception:
                pass

        try:
            child.close(
                force=True
            )
        except Exception:
            pass

    return events


async def handle_print_message(
    app: Application,
    session: ChatSession,
    text: str,
):

    session.busy = True

    started = time.monotonic()
    started_wall_clock = time.time()

    status_message = None

    event_queue = asyncio.Queue()

    def event_callback(
        event
    ):
        try:
            event_queue.put_nowait(
                event
            )
        except Exception:
            pass

    async def status_worker():

        nonlocal status_message

        last_status = None

        while True:

            try:

                event = await asyncio.wait_for(
                    event_queue.get(),
                    timeout=0.5,
                )

            except asyncio.TimeoutError:
                continue

            status = status_from_event(
                event
            )

            if not status:
                continue

            if status == last_status:
                continue

            last_status = status

            try:

                if status_message is None:

                    status_message = (
                        await app.bot.send_message(
                            session.chat_id,
                            status,
                        )
                    )

                else:

                    await app.bot.edit_message_text(
                        chat_id=session.chat_id,
                        message_id=(
                            status_message.message_id
                        ),
                        text=status,
                    )

            except Exception as exc:

                log.debug(
                    "Status update failed: %s",
                    exc,
                )

    status_task = asyncio.create_task(
        status_worker()
    )

    try:

        await app.bot.send_chat_action(
            session.chat_id,
            ChatAction.TYPING,
        )

        loop = asyncio.get_running_loop()

        events = await loop.run_in_executor(
            None,
            run_stream_print_mode_sync,
            session,
            text,
            event_callback,
        )

        # Give queued events a moment to be consumed.
        await asyncio.sleep(
            0.1
        )

        # ---------------------------------------------------------------
        # Find final result.
        # ---------------------------------------------------------------

        result = None

        for event in reversed(
            events
        ):

            if event.get(
                "event"
            ) == "result":

                result = event.get(
                    "result"
                )

                break

        if not result:

            # Fallback: some versions may return the result-like
            # object directly.
            for event in reversed(
                events
            ):

                if (
                    event.get("response")
                    is not None
                ):

                    result = event
                    break

        local_duration = (
            time.monotonic()
            - started
        )

        if not result:

            if status_message:

                try:
                    await app.bot.edit_message_text(
                        chat_id=session.chat_id,
                        message_id=(
                            status_message.message_id
                        ),
                        text=(
                            "⚠️ agy finished, "
                            "but no result was returned."
                        ),
                    )
                except Exception:
                    pass

            log.warning(
                "No result event from agy."
            )

            return

        # ---------------------------------------------------------------
        # Conversation ID.
        # ---------------------------------------------------------------

        conversation_id = (
            result.get(
                "conversation_id"
            )
        )

        if conversation_id:
            session.conversation_id = conversation_id
            record_conversation(
                chat_id=session.chat_id,
                conv_id=conversation_id,
                prompt=text,
                workspace=session.workspace,
                model=session.model,
            )

        # ---------------------------------------------------------------
        # Response.
        # ---------------------------------------------------------------

        response = (
            result.get(
                "response"
            )
            or ""
        )

        # ---------------------------------------------------------------
        # Duration.
        # ---------------------------------------------------------------

        agy_duration = result.get(
            "duration_seconds"
        )

        try:

            duration = (
                float(agy_duration)
                if agy_duration is not None
                else local_duration
            )

        except (
            TypeError,
            ValueError,
        ):

            duration = local_duration

        # ---------------------------------------------------------------
        # Model.
        # ---------------------------------------------------------------

        model = (
            result.get("model")
            or result.get("model_name")
            or session.model
            or "default"
        )

        # ---------------------------------------------------------------
        # Empty response.
        # ---------------------------------------------------------------

        if not str(response).strip():

            denied = result.get(
                "denied_actions"
            )

            if denied:

                response = (
                    "agy completed the request, "
                    "but did not produce a final "
                    "text response.\n\n"
                    "Denied actions:\n"
                    + "\n".join(
                        f"- {item}"
                        for item in denied
                    )
                )

            else:

                response = (
                    "agy completed the request "
                    "but returned no response text."
                )

        # ---------------------------------------------------------------
        # Delete the temporary status message.
        # ---------------------------------------------------------------

        if status_message:

            try:

                await app.bot.delete_message(
                    chat_id=session.chat_id,
                    message_id=(
                        status_message.message_id
                    ),
                )

            except Exception:
                pass

        # ---------------------------------------------------------------
        # Detect any involved screenshots / images
        # ---------------------------------------------------------------

        images = find_involved_images(
            text_content=str(response),
            workspace=session.workspace,
            started_at=started_wall_clock,
            conversation_id=conversation_id,
            events=events,
        )

        # ---------------------------------------------------------------
        # Send final formatted response.
        # ---------------------------------------------------------------

        await send_final_response(
            app,
            session.chat_id,
            str(response),
            str(model),
            duration,
            images=images,
        )

    except pexpect.TIMEOUT:

        if status_message:

            try:

                await app.bot.edit_message_text(
                    chat_id=session.chat_id,
                    message_id=(
                        status_message.message_id
                    ),
                    text=(
                        "⏱ agy timed out after "
                        f"{PRINT_TIMEOUT} seconds."
                    ),
                )

            except Exception:
                pass

        else:

            await app.bot.send_message(
                session.chat_id,
                "⏱ agy timed out after "
                f"{PRINT_TIMEOUT} seconds.",
            )

    except Exception as exc:

        log.exception(
            "Print-mode request failed"
        )

        if status_message:

            try:

                await app.bot.edit_message_text(
                    chat_id=session.chat_id,
                    message_id=(
                        status_message.message_id
                    ),
                    text=(
                        "⚠️ agy error:\n"
                        + str(exc)
                    ),
                )

            except Exception:
                pass

        else:

            await app.bot.send_message(
                session.chat_id,
                "⚠️ agy error:\n"
                + str(exc),
            )

    finally:

        status_task.cancel()

        try:
            await status_task
        except asyncio.CancelledError:
            pass

        session.busy = False
