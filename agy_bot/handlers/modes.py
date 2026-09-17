"""
agy_bot/handlers/modes.py — Mode switching: /help, /interactive, /plain,
/debug, and permission-button callbacks.
"""

import asyncio
import html
import time

import pyte
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agy_bot.config import log
from agy_bot.session import SESSIONS, InteractiveState
from agy_bot.rendering.text import chat_allowed, split_text
from agy_bot.agy.interactive_mode import (
    spawn_interactive_agy,
    interactive_reader_loop,
    render_screen_text,
)


# ============================================================================
# /HELP
# ============================================================================

async def cmd_help(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    text = (
        "🤖 <b>Antigravity Telegram Bot Commands</b>\n\n"
        "<b>System &amp; Health:</b>\n"
        "• /health — Check service, bot and system health\n\n"
        "<b>Chat &amp; Conversations:</b>\n"
        "• /new (or /newchat) — Start fresh chat &amp; reset context\n"
        "• /conversations (or /history) — List recent chats &amp; resume\n\n"
        "<b>Workspace &amp; Navigation:</b>\n"
        "• /pwd — Show current &amp; default workspace\n"
        "• /cd <code>&lt;path&gt;</code> — Change current workspace directory\n"
        "• /default <code>[path]</code> — View or set permanent default workspace\n"
        "• /set_default <code>&lt;path&gt;</code> — Save directory as permanent default\n"
        "• /browse <code>[path]</code> — Interactive visual folder browser\n"
        "• /volumes — External drives &amp; storage volumes\n"
        "• /workspaces — Switch recent workspaces with buttons\n\n"
        "<b>Terminal &amp; Control:</b>\n"
        "• /sh <code>&lt;cmd&gt;</code> — Run command in desktop shell\n"
        "• /interactive — Live approval mode for agy\n"
        "• /plain — Switch back to print/streaming mode\n"
        "• /stop — Interrupt current command or session\n"
        "• /sleep — Put laptop to sleep (suspend)\n\n"
        "<b>Model Management:</b>\n"
        "• /models — List and select models with one click\n"
        "• /model <code>&lt;name&gt;</code> — Set active AI model\n"
        "• /usage — Check model quotas, limits &amp; visual reset timers\n\n"
        "💡 <i>Tip: Tap the <b>[/]</b> button next to your chat bar (or type <code>/</code>) to auto-populate any command directly into your text box!</i>"
    )

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🩺 /health", callback_data="hact:health"),
            InlineKeyboardButton("💬 /new", callback_data="hact:new"),
            InlineKeyboardButton("📜 /history", callback_data="hact:history"),
        ],
        [
            InlineKeyboardButton("📍 /pwd", callback_data="hact:pwd"),
            InlineKeyboardButton("📂 /workspaces", callback_data="hact:workspaces"),
            InlineKeyboardButton("🤖 /models", callback_data="hact:models"),
        ],
        [
            InlineKeyboardButton("📊 /usage", callback_data="hact:usage"),
            InlineKeyboardButton("🛑 /stop", callback_data="hact:stop"),
            InlineKeyboardButton("💤 /sleep", callback_data="hact:sleep"),
        ],
    ])

    target_msg = update.effective_message or update.message
    await target_msg.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


# ============================================================================
# /INTERACTIVE
# ============================================================================

async def cmd_interactive(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    from agy_bot.config import PTY_ROWS, PTY_COLS

    session = SESSIONS.get(
        chat_id
    )

    if not session:

        await update.message.reply_text(
            "No session yet. Use /start first."
        )

        return

    if session.mode == "interactive":

        await update.message.reply_text(
            "Already in interactive mode."
        )

        return

    try:

        child = spawn_interactive_agy(
            session.workspace,
            session.model,
            resume=bool(
                session.conversation_id
            ),
        )

        screen = pyte.Screen(
            PTY_COLS,
            PTY_ROWS,
        )

        stream = pyte.Stream(
            screen
        )

        session.interactive = InteractiveState(
            child=child,
            screen=screen,
            stream=stream,
        )

        session.mode = "interactive"

        session.interactive.reader_task = (
            asyncio.create_task(
                interactive_reader_loop(
                    context.application,
                    session,
                )
            )
        )

        await update.message.reply_text(
            "🔐 <b>Interactive mode</b>\n\n"
            "agy is now running as a persistent "
            "terminal session.\n\n"
            "Permission requests will appear "
            "as Telegram buttons.\n\n"
            "Use /plain to return to print mode.",
            parse_mode=ParseMode.HTML,
        )

    except Exception as exc:

        log.exception(
            "Could not start interactive mode"
        )

        await update.message.reply_text(
            "⚠️ Could not start interactive mode:\n"
            + str(exc)
        )


# ============================================================================
# /PLAIN
# ============================================================================

async def cmd_plain(
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
            "No active session."
        )

        return

    if session.mode != "interactive":

        await update.message.reply_text(
            "Already in print mode."
        )

        return

    state = session.interactive

    if state:

        if state.reader_task:
            state.reader_task.cancel()

        try:
            state.child.close(
                force=True
            )
        except Exception:
            pass

    session.interactive = None
    session.mode = "print"

    await update.message.reply_text(
        "✅ Back to <b>print mode</b>.",
        parse_mode=ParseMode.HTML,
    )


# ============================================================================
# /DEBUG
# ============================================================================

async def cmd_debug(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(
        chat_id
    )

    if (
        not session
        or session.mode != "interactive"
        or not session.interactive
    ):

        await update.message.reply_text(
            "Debug is only available "
            "in interactive mode."
        )

        return

    text = "\n".join(
        render_screen_text(
            session.interactive.screen
        )
    )

    if not text:
        text = "(blank screen)"

    for chunk in split_text(
        text
    ):

        await update.message.reply_text(
            html.escape(chunk),
            parse_mode=ParseMode.HTML,
        )


# ============================================================================
# PERMISSION CALLBACK
# ============================================================================

async def on_permission_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    try:

        (
            _,
            chat_id_str,
            choice_str,
        ) = query.data.split(":")

        chat_id = int(
            chat_id_str
        )

        choice = int(
            choice_str
        )

    except (
        ValueError,
        AttributeError,
    ):

        return

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(
        chat_id
    )

    if (
        not session
        or session.mode != "interactive"
        or not session.interactive
        or not session.interactive.pending
    ):

        await query.edit_message_text(
            "This permission request "
            "is no longer active."
        )

        return

    pending = (
        session.interactive.pending
    )

    label = dict(
        pending.options
    ).get(
        choice,
        str(choice),
    )

    try:

        session.interactive.child.send(
            f"{choice}\r"
        )

        session.interactive.pending = None

        session.interactive.dirty = True

        session.interactive.last_data_at = (
            time.time()
        )

        await query.edit_message_text(
            f"✅ Selected: {choice}. {label}"
        )

    except Exception as exc:

        await query.edit_message_text(
            "⚠️ Could not send selection:\n"
            + str(exc)
        )
