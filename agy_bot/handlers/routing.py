"""
agy_bot/handlers/routing.py — Callback-query router, help-action dispatcher,
and the global error handler.
"""

from telegram import Update
from telegram.ext import ContextTypes

from agy_bot.config import log
from agy_bot.rendering.text import chat_allowed
from agy_bot.handlers import browse, conversations, models, usage, workspace
from agy_bot.handlers import modes, session_cmds
from agy_bot.health.health import cmd_health, on_health_callback


async def on_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query.data:
        return

    if query.data.startswith("hact:"):
        await on_help_action_callback(
            update,
            context,
        )
        return

    if query.data.startswith("workspace:"):
        await workspace.on_workspace_callback(
            update,
            context,
        )
        return

    if query.data.startswith("mgrp:"):
        await models.on_model_group_callback(
            update,
            context,
        )
        return

    if query.data == "mhome":
        await models.on_model_home_callback(
            update,
            context,
        )
        return

    if query.data == "mrefresh":
        await models.on_model_refresh_callback(
            update,
            context,
        )
        return

    if query.data.startswith("model:"):
        await models.on_model_callback(
            update,
            context,
        )
        return

    if query.data.startswith("br:"):
        await browse.on_browse_callback(
            update,
            context,
        )
        return

    if query.data.startswith("perm:"):
        await modes.on_permission_callback(
            update,
            context,
        )
        return

    if query.data.startswith("usage:"):
        await usage.on_usage_callback(
            update,
            context,
        )
        return

    if query.data.startswith("health:"):
        await on_health_callback(
            update,
            context,
        )
        return

    if query.data.startswith("conv:") or query.data in ("conv_new", "conv_refresh"):
        await conversations.on_conversation_callback(
            update,
            context,
        )
        return


async def on_help_action_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    chat_id = update.effective_chat.id
    if not chat_allowed(chat_id):
        return

    action = query.data.split(":", 1)[1] if ":" in query.data else ""
    fake_update = Update(update_id=update.update_id, message=query.message)

    if action == "health":
        await cmd_health(fake_update, context)
    elif action == "new":
        await session_cmds.cmd_new(fake_update, context)
    elif action == "history":
        await conversations.cmd_conversations(fake_update, context)
    elif action == "pwd":
        await workspace.cmd_pwd(fake_update, context)
    elif action == "workspaces":
        await workspace.cmd_workspaces(fake_update, context)
    elif action == "models":
        await models.cmd_models(fake_update, context)
    elif action == "usage":
        await usage.cmd_usage(fake_update, context)
    elif action == "stop":
        await session_cmds.cmd_stop(fake_update, context)
    elif action == "sleep":
        await session_cmds.cmd_sleep(fake_update, context)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle uncaught errors and suppress verbose traces for transient network hiccups."""
    from telegram import error as tg_error

    err = context.error
    if isinstance(err, (tg_error.NetworkError, tg_error.TimedOut)):
        log.warning(f"Telegram network transient error: {err}")
        return
    if isinstance(err, tg_error.BadRequest) and "message is not modified" in str(err).lower():
        return
    log.error(f"Telegram error in update {update}:", exc_info=err)
