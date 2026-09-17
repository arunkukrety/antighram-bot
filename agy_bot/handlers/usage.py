"""
agy_bot/handlers/usage.py — /usage quota display and refresh callback.
"""

import html

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from agy_bot.session import SESSIONS
from agy_bot.rendering.text import chat_allowed
from agy_bot.workspace.resolver import get_default_workspace
from agy_bot.usage.usage import fetch_usage_data, render_usage_display
from agy_bot.handlers.models import cmd_models


async def cmd_usage(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(chat_id)
    workspace = (
        session.workspace
        if session
        else get_default_workspace()
    )

    await context.bot.send_chat_action(
        chat_id,
        ChatAction.TYPING,
    )

    status_msg = await update.message.reply_text(
        "<code>⠋</code> Fetching model usage &amp; quota…",
        parse_mode=ParseMode.HTML,
    )

    try:
        data = await fetch_usage_data(
            workspace
        )
        text, markup = render_usage_display(
            data
        )
        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except Exception as exc:
        await status_msg.edit_text(
            f"⚠️ Error fetching usage:\n{html.escape(str(exc))}",
            parse_mode=ParseMode.HTML,
        )


async def on_usage_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    if not query.data or not query.data.startswith("usage:"):
        return

    action = query.data.split(":", 1)[1]
    chat_id = query.message.chat_id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(chat_id)
    workspace = (
        session.workspace
        if session
        else get_default_workspace()
    )

    if action == "refresh":
        await query.answer(
            "Refreshing quota...",
            show_alert=False,
        )
        try:
            data = await fetch_usage_data(
                workspace
            )
            text, markup = render_usage_display(
                data
            )
            await query.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except Exception as exc:
            await query.answer(
                f"Refresh failed: {exc}",
                show_alert=True,
            )

    elif action == "models":
        await cmd_models(
            update,
            context,
        )
