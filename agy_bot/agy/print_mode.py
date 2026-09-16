"""
Print mode: run agy via stream-json and stream status updates to Telegram.
"""

import asyncio
import html
import json
import time
from typing import List, Optional

import pexpect
from telegram import error as tg_error
from telegram.ext import Application
from telegram.constants import ChatAction, ParseMode

from agy_bot.config import log, AGY_BIN, PRINT_TIMEOUT
from agy_bot.session import ChatSession
from agy_bot.rendering.text import strip_ansi, split_text
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
    streamed_text = ""
    current_status = "🚀 <b>Starting agy…</b>"

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
        nonlocal status_message, streamed_text, current_status

        last_rendered_text = None
        last_edit_time = 0.0

        while True:
            try:
                event = await asyncio.wait_for(
                    event_queue.get(),
                    timeout=0.3,
                )
                events = [event]
                while not event_queue.empty():
                    try:
                        events.append(event_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                for ev in events:
                    new_st = status_from_event(ev)
                    if new_st:
                        current_status = new_st

                    step = ev.get("step_update", {})
                    delta = step.get("text_delta")
                    if delta:
                        streamed_text += delta
            except asyncio.TimeoutError:
                pass

            now = time.monotonic()
            # Enforce at least 1.0s interval between Telegram message edits
            if now - last_edit_time < 1.0:
                continue

            if streamed_text.strip():
                clean = streamed_text.strip()
                if len(clean) > 900:
                    preview = "… " + clean[-900:]
                else:
                    preview = clean
                display_text = (
                    f"{current_status}\n\n"
                    f"<blockquote>{html.escape(preview)}</blockquote>"
                )
            else:
                display_text = current_status

            if display_text == last_rendered_text:
                continue

            try:
                if status_message is None:
                    status_message = await app.bot.send_message(
                        session.chat_id,
                        display_text,
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await app.bot.edit_message_text(
                        chat_id=session.chat_id,
                        message_id=status_message.message_id,
                        text=display_text,
                        parse_mode=ParseMode.HTML,
                    )
                last_rendered_text = display_text
                last_edit_time = now
            except tg_error.RetryAfter as exc:
                last_edit_time = now + exc.retry_after
                log.debug("Status update rate limited: sleeping %s s", exc.retry_after)
            except Exception as exc:
                log.debug("Status update edit failed: %s", exc)

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

        # Cancel status worker before deleting message
        status_task.cancel()
        try:
            await status_task
        except asyncio.CancelledError:
            pass

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

            status_message = None

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

        try:
            await send_final_response(
                app,
                session.chat_id,
                str(response),
                str(model),
                duration,
                images=images,
            )
        except Exception as send_exc:
            log.exception(
                "send_final_response failed, attempting emergency raw text delivery: %s",
                send_exc,
            )
            raw_resp = str(response).strip() or "⚠️ (empty response from agy)"
            for chunk in split_text(raw_resp, 3500):
                await app.bot.send_message(
                    chat_id=session.chat_id,
                    text=chunk,
                    parse_mode=None,
                    disable_web_page_preview=True,
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
