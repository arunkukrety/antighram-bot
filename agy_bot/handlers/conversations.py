"""
agy_bot/handlers/conversations.py — /conversations list & resume.
"""

import html
import os

from telegram import Update, error as tg_error
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agy_bot.config import log
from agy_bot.session import SESSIONS, ChatSession
from agy_bot.rendering.text import chat_allowed
from agy_bot.workspace.resolver import get_default_workspace
from agy_bot.conversation.history import (
    render_conversations_markup,
    load_conversations,
)


async def cmd_conversations(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(chat_id)
    current_conv_id = session.conversation_id if session else None

    text, markup = render_conversations_markup(
        chat_id=chat_id,
        current_conv_id=current_conv_id,
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def on_conversation_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if not query:
        return

    chat_id = update.effective_chat.id
    if not chat_allowed(chat_id):
        await query.answer("Unauthorized", show_alert=True)
        return

    session = SESSIONS.get(chat_id)
    if not session:
        session = ChatSession(
            chat_id=chat_id,
            workspace=get_default_workspace(),
        )
        SESSIONS[chat_id] = session

    data = query.data

    if data == "conv_new":
        if session.conversation_id is None:
            await query.answer("Already in a fresh chat context!")
            return
        await query.answer("Started new chat!")

        if session.interactive:
            from agy_bot.session import teardown_session
            teardown_session(session)
            session.interactive = None
            session.mode = "print"
        session.conversation_id = None

        text, markup = render_conversations_markup(
            chat_id=chat_id,
            current_conv_id=None,
        )
        try:
            await query.edit_message_text(
                text + "\n\n✨ <i>New chat activated! Next message will start fresh.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except tg_error.BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                log.warning(f"Failed to edit message in conv_new: {exc}")
        except Exception as exc:
            log.warning(f"Unexpected error in conv_new: {exc}")
        return

    if data == "conv_refresh":
        await query.answer("Refreshed!")
        text, markup = render_conversations_markup(
            chat_id=chat_id,
            current_conv_id=session.conversation_id,
        )
        try:
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except tg_error.BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                log.warning(f"Failed to edit message in conv_refresh: {exc}")
        except Exception as exc:
            log.warning(f"Unexpected error in conv_refresh: {exc}")
        return

    if data.startswith("conv:"):
        conv_id = data.split(":", 1)[1].strip()
        if session.conversation_id == conv_id:
            await query.answer("This conversation is already active!")
            return

        session.conversation_id = conv_id
        await query.answer("Active conversation switched!")

        # Switch workspace if recorded and valid
        convos = load_conversations()
        matched = next((c for c in convos if c.get("id") == conv_id), None)
        ws_info = ""
        if matched and matched.get("workspace") and os.path.isdir(matched["workspace"]):
            session.workspace = matched["workspace"]
            ws_info = f"\n📂 Workspace: <code>{html.escape(session.workspace)}</code>"

        text, markup = render_conversations_markup(
            chat_id=chat_id,
            current_conv_id=session.conversation_id,
        )
        try:
            await query.edit_message_text(
                text + f"\n\n✅ <b>Active conversation switched!</b>{ws_info}",
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except tg_error.BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                log.warning(f"Failed to edit message in conv select: {exc}")
        except Exception as exc:
            log.warning(f"Unexpected error in conv select: {exc}")
        return
