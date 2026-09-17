"""
agy_bot/main.py — Application entrypoint.

Builds the Telegram Application and wires command/callback handlers.
All handler logic lives in agy_bot/handlers/*, grouped by feature:

    session_cmds.py    /start /new /stop /sleep + text router
    workspace.py       /workspaces /pwd /cd /default /set_default
    browse.py          /browse /volumes + br:* callbacks
    shell.py           /sh desktop shell execution
    modes.py           /help /interactive /plain /debug + permission buttons
    models.py          /model /models + model pickers
    usage.py           /usage quota panel
    conversations.py   /conversations + resume
    routing.py         callback router + global error handler
"""

from telegram import BotCommand
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from agy_bot.config import log, BOT_TOKEN, get_notification_chat_ids
from agy_bot.handlers import (
    browse,
    conversations,
    modes,
    models,
    routing,
    session_cmds,
    shell,
    usage,
    workspace,
)
from agy_bot.health.health import cmd_health

# Touch `state` so the default workspace is created at startup
import agy_bot.state  # noqa: F401


# ============================================================================
# BOT COMMANDS REGISTRATION & ENTRYPOINT
# ============================================================================

BOT_COMMANDS = [
    BotCommand("health", "Service & system health diagnostics"),
    BotCommand("new", "Start fresh chat & reset context"),
    BotCommand("conversations", "List recent chats & resume"),
    BotCommand("pwd", "Show current & default workspace"),
    BotCommand("cd", "Change directory: /cd <path>"),
    BotCommand("default", "View or set permanent default workspace"),
    BotCommand("browse", "Interactive visual folder browser"),
    BotCommand("volumes", "External drives & storage"),
    BotCommand("workspaces", "Switch recent workspaces"),
    BotCommand("sh", "Run command in desktop shell: /sh <cmd>"),
    BotCommand("models", "List & select AI models"),
    BotCommand("model", "Set active model: /model <name>"),
    BotCommand("usage", "Check quotas & reset timers"),
    BotCommand("interactive", "Live approval mode for agy"),
    BotCommand("plain", "Streaming print mode"),
    BotCommand("stop", "Interrupt active command or session"),
    BotCommand("sleep", "Put laptop to sleep (suspend)"),
    BotCommand("help", "Show all commands & usage guide"),
]


async def post_init(application: Application) -> None:
    try:
        await application.bot.set_my_commands(BOT_COMMANDS)
        log.info("Registered Telegram bot commands via set_my_commands.")
    except Exception as exc:
        log.warning(f"Could not register bot commands: {exc}")

    target_chats = get_notification_chat_ids()
    online_text = (
        "🟢 <b>Antigravity Bot is Online</b>\n\n"
        "💻 Server is up and ready for commands.\n"
        "Type /help to see commands or tap <b>[/]</b> to browse."
    )
    for chat_id in target_chats:
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=online_text,
                parse_mode="HTML",
            )
        except Exception as exc:
            log.warning(f"Could not send online alert to {chat_id}: {exc}")


async def post_stop(application: Application) -> None:
    target_chats = get_notification_chat_ids()
    offline_text = (
        "🔴 <b>Antigravity Bot is Going Offline</b>\n\n"
        "💤 The bot server process is stopping.\n"
        "Commands are paused until the server starts back up."
    )
    for chat_id in target_chats:
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=offline_text,
                parse_mode="HTML",
            )
        except Exception as exc:
            log.warning(f"Could not send offline alert to {chat_id}: {exc}")


def main():

    request = HTTPXRequest(
        connection_pool_size=100,
        connect_timeout=20.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=10.0,
    )
    get_updates_request = HTTPXRequest(
        connection_pool_size=10,
        connect_timeout=20.0,
        read_timeout=30.0,
        write_timeout=20.0,
        pool_timeout=10.0,
    )

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(request)
        .get_updates_request(get_updates_request)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )

    app.add_error_handler(routing.on_error)

    app.add_handler(CommandHandler("start", session_cmds.cmd_start))
    app.add_handler(CommandHandler("help", modes.cmd_help))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("new", session_cmds.cmd_new))
    app.add_handler(CommandHandler("newchat", session_cmds.cmd_new))
    app.add_handler(CommandHandler("conversations", conversations.cmd_conversations))
    app.add_handler(CommandHandler("history", conversations.cmd_conversations))
    app.add_handler(CommandHandler("pwd", workspace.cmd_pwd))
    app.add_handler(CommandHandler("cd", workspace.cmd_cd))
    app.add_handler(CommandHandler("default", workspace.cmd_default))
    app.add_handler(CommandHandler("set_default", workspace.cmd_set_default))
    app.add_handler(CommandHandler("browse", browse.cmd_browse))
    app.add_handler(CommandHandler("sh", shell.cmd_sh))
    app.add_handler(CommandHandler("volumes", browse.cmd_volumes))
    app.add_handler(CommandHandler("workspaces", workspace.cmd_workspaces))
    app.add_handler(CommandHandler("interactive", modes.cmd_interactive))
    app.add_handler(CommandHandler("plain", modes.cmd_plain))
    app.add_handler(CommandHandler("model", models.cmd_model))
    app.add_handler(CommandHandler("models", models.cmd_models))
    app.add_handler(CommandHandler("usage", usage.cmd_usage))
    app.add_handler(CommandHandler("debug", modes.cmd_debug))
    app.add_handler(CommandHandler("stop", session_cmds.cmd_stop))
    app.add_handler(CommandHandler("sleep", session_cmds.cmd_sleep))
    app.add_handler(CallbackQueryHandler(routing.on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, session_cmds.on_text))

    log.info("Starting Telegram agy bot...")

    app.run_polling()


if __name__ == "__main__":
    main()
