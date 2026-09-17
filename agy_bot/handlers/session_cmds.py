"""
agy_bot/handlers/session_cmds.py — Session lifecycle commands.

/start, /new, /stop, /sleep and the plain-text message router.
"""

import asyncio
import html
import os
import sys
import time

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agy_bot.config import log
from agy_bot.session import SESSIONS, ChatSession, teardown_session
from agy_bot.rendering.text import chat_allowed
from agy_bot.workspace.history import remember_workspace
from agy_bot.workspace.resolver import get_default_workspace, resolve_target_workspace
from agy_bot.agy.print_mode import handle_print_message

IS_WINDOWS = sys.platform == "win32"


# ============================================================================
# /START
# ============================================================================

async def cmd_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):

        await update.message.reply_text(
            "Not authorized for this bot."
        )

        return

    args = context.args or []

    raw_ws = args[0] if args else None
    if raw_ws:
        resolved, _ = resolve_target_workspace(raw_ws, get_default_workspace())
        workspace = (
            resolved
            if resolved
            else os.path.abspath(os.path.expanduser(raw_ws))
        )
    else:
        workspace = get_default_workspace()

    model = (
        " ".join(
            args[1:]
        )
        if len(args) > 1
        else None
    )

    os.makedirs(
        workspace,
        exist_ok=True,
    )

    remember_workspace(
        workspace
    )

    # Stop previous interactive session.
    old = SESSIONS.get(
        chat_id
    )

    teardown_session(old)

    SESSIONS[chat_id] = ChatSession(
        chat_id=chat_id,
        workspace=workspace,
        model=model,
    )

    message = (
        "✅ <b>Session ready</b>\n\n"
        f"📂 <code>{html.escape(workspace)}</code>\n"
    )

    if model:

        message += (
            f"🤖 <code>{html.escape(model)}</code>\n"
        )

    message += (
        "\n"
        "Mode: <b>PRINT</b>\n"
        "Normal messages run through headless agy "
        "with automatic tool approval.\n\n"
        "• /new — Start a new chat context\n"
        "• /conversations — View & resume previous chats\n"
        "• /browse or /workspaces — Switch folders\n"
        "• /cd &lt;path&gt; &amp; /pwd — Directory navigation\n"
        "• /default — View or set default workspace\n"
        "• /sh &lt;cmd&gt; — Run desktop terminal commands\n"
        "• /interactive — Live approval mode\n"
        "• /help — Full command list"
    )

    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
    )


# ============================================================================
# /NEW (START NEW CONVERSATION)
# ============================================================================

async def cmd_new(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(chat_id)
    if not session:
        session = ChatSession(
            chat_id=chat_id,
            workspace=get_default_workspace(),
        )
        SESSIONS[chat_id] = session

    if session.interactive:
        teardown_session(session)
        session.interactive = None
        session.mode = "print"

    old_conv_id = session.conversation_id
    session.conversation_id = None

    text = (
        "✨ <b>New chat started!</b>\n\n"
        f"📂 Workspace: <code>{html.escape(session.workspace)}</code>\n"
    )
    if session.model:
        text += f"🤖 Model: <code>{html.escape(session.model)}</code>\n"
    if old_conv_id:
        text += f"Detached previous conversation: <code>{html.escape(old_conv_id[:8])}…</code>\n"

    text += "\n<i>Your next message will start a fresh conversation.</i>"

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


# ============================================================================
# /STOP
# ============================================================================

async def cmd_stop(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.pop(
        chat_id,
        None,
    )

    if not session:

        await update.message.reply_text(
            "No active session."
        )

        return

    teardown_session(session)

    await update.message.reply_text(
        "🛑 Session stopped."
    )


# ============================================================================
# /SLEEP
# ============================================================================

async def cmd_sleep(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    await update.message.reply_text(
        "💤 <b>Putting laptop to sleep...</b>\n\n"
        "⚠️ <i>Note: The Telegram bot will go offline while the laptop is suspended. "
        "To wake it back up, press the power button or open the laptop lid.</i>",
        parse_mode=ParseMode.HTML,
    )

    if IS_WINDOWS:
        suspend_cmd = [
            "rundll32.exe",
            "powrprof.dll,SetSuspendState",
            "0,1,0",
        ]
    else:
        suspend_cmd = ["systemctl", "suspend"]

    async def _do_suspend():
        await asyncio.sleep(1.2)
        try:
            proc = await asyncio.create_subprocess_exec(
                *suspend_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except Exception as e:
            log.error(f"Failed to put laptop to sleep: {e}")

    asyncio.create_task(_do_suspend())


# ============================================================================
# NORMAL TEXT
# ============================================================================

async def on_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(
        chat_id
    )

    if not session:

        await update.message.reply_text(
            "No session yet.\n\n"
            "Use /start first."
        )

        return

    text = (
        update.message.text
        or ""
    ).strip()

    if not text:
        return

    # ---------------------------------------------------------------
    # Interactive mode
    # ---------------------------------------------------------------

    if session.mode == "interactive":

        if (
            not session.interactive
            or not session.interactive.child
        ):

            await update.message.reply_text(
                "⚠️ Interactive session is not "
                "running. Use /interactive again."
            )

            return

        try:

            session.interactive.child.send(
                text + "\r"
            )

            session.interactive.dirty = True

            session.interactive.last_data_at = (
                time.time()
            )

        except Exception as exc:

            await update.message.reply_text(
                "⚠️ Could not send message "
                "to agy:\n"
                + str(exc)
            )

        return

    # ---------------------------------------------------------------
    # Print mode
    # ---------------------------------------------------------------

    if session.busy:

        await update.message.reply_text(
            "⏳ I'm still working on your "
            "previous request."
        )

        return

    remember_workspace(
        session.workspace
    )

    asyncio.create_task(
        handle_print_message(
            context.application,
            session,
            text,
        )
    )
