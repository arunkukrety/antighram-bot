"""
agy_bot/handlers/workspace.py — Workspace selection commands.

/workspaces, /pwd, /cd, /default, /set_default and their callbacks.
"""

import html
import os

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agy_bot.session import SESSIONS, ChatSession, teardown_session
from agy_bot.rendering.text import chat_allowed
from agy_bot.workspace.history import forget_workspace, get_recent_workspaces, remember_workspace
from agy_bot.workspace.resolver import (
    get_default_workspace,
    set_default_workspace,
    resolve_target_workspace,
)
from agy_bot.workspace.browse_token import BROWSE_CACHE, get_browse_token
from agy_bot.workspace.markup import build_workspace_markup


async def cmd_workspaces(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    workspaces = get_recent_workspaces()

    if not workspaces:
        await update.message.reply_text(
            "📂 No recent workspaces found.\n\n"
            "Use /start <workspace> or /cd <path> first."
        )
        return

    text, markup = build_workspace_markup(workspaces)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def on_workspace_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    raw = query.data.split(":", 1)[1].strip()
    workspace = None

    if raw in BROWSE_CACHE:
        workspace = BROWSE_CACHE[raw]
    elif raw.isdigit():
        idx = int(raw)
        ws_list = get_recent_workspaces()
        if 0 <= idx < len(ws_list):
            workspace = ws_list[idx]["path"]

    if not workspace or not os.path.isdir(workspace):
        if workspace:
            forget_workspace(workspace)
        await query.answer(
            "⚠️ That directory was not found on disk and was removed from recent workspaces.",
            show_alert=True,
        )
        workspaces = get_recent_workspaces()
        if not workspaces:
            await query.edit_message_text(
                "📂 No valid recent workspaces found.\n\n"
                "Use /start <workspace> or /cd <path> first."
            )
            return

        text, markup = build_workspace_markup(workspaces)
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    chat_id = query.message.chat_id
    old = SESSIONS.get(chat_id)
    model = old.model if old else None

    teardown_session(old)

    SESSIONS[chat_id] = ChatSession(
        chat_id=chat_id,
        workspace=workspace,
        model=model,
    )

    remember_workspace(workspace)

    await query.edit_message_text(
        "✅ <b>Workspace switched</b>\n\n"
        f"📂 <code>{html.escape(workspace)}</code>\n\n"
        "Mode: <b>PRINT</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_pwd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(chat_id)
    current_ws = session.workspace if session else None
    default_ws = get_default_workspace()

    lines = ["📍 <b>Workspace Status</b>\n"]

    if current_ws:
        lines.append(
            f"<b>Current Active Workspace:</b>\n<code>{html.escape(current_ws)}</code>\n"
        )
    else:
        lines.append(
            "<b>Current Active Workspace:</b> <i>(None active - use /start)</i>\n"
        )

    lines.append(
        f"<b>Default Workspace:</b>\n<code>{html.escape(default_ws)}</code>"
    )

    target = current_ws or default_ws
    token = get_browse_token(target)
    buttons = [
        [
            InlineKeyboardButton(
                "📂 Browse Folder",
                callback_data=f"br:nav:{token}",
            ),
            InlineKeyboardButton(
                "⭐ Make Default",
                callback_data=f"br:def:{token}",
            ),
        ]
    ]

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cmd_cd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    args = context.args or []
    target = " ".join(args).strip()

    session = SESSIONS.get(chat_id)
    current_ws = (
        session.workspace
        if session
        else get_default_workspace()
    )

    resolved, attempted = resolve_target_workspace(target, current_ws)

    if not resolved:
        await update.message.reply_text(
            f"⚠️ Directory does not exist:\n<code>{html.escape(attempted or target)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    target_path = resolved

    if not os.path.isdir(target_path):
        await update.message.reply_text(
            f"⚠️ Path is a file, not a directory:\n<code>{html.escape(target_path)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    model = session.model if session else None

    teardown_session(session)

    SESSIONS[chat_id] = ChatSession(
        chat_id=chat_id,
        workspace=target_path,
        model=model,
    )
    remember_workspace(target_path)

    token = get_browse_token(target_path)
    buttons = [
        [
            InlineKeyboardButton(
                "📂 Browse Here",
                callback_data=f"br:nav:{token}",
            ),
            InlineKeyboardButton(
                "⭐ Set as Default",
                callback_data=f"br:def:{token}",
            ),
        ]
    ]

    await update.message.reply_text(
        f"✅ <b>Workspace changed</b>\n\n"
        f"📂 <code>{html.escape(target_path)}</code>\n\n"
        f"Ready for your prompts or /interactive mode.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def cmd_default(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    args = context.args or []
    target = " ".join(args).strip()

    if target:
        resolved = set_default_workspace(target)
        await update.message.reply_text(
            f"⭐ <b>Default workspace saved!</b>\n\n"
            f"📂 <code>{html.escape(resolved)}</code>\n\n"
            f"All future sessions and fallback commands will use this directory.",
            parse_mode=ParseMode.HTML,
        )
        return

    session = SESSIONS.get(chat_id)
    current_default = get_default_workspace()
    lines = [
        "⭐ <b>Default Workspace Configuration</b>\n",
        f"Current Default:\n<code>{html.escape(current_default)}</code>\n",
    ]

    buttons = []
    if session and session.workspace and session.workspace != current_default:
        token = get_browse_token(session.workspace)
        buttons.append(
            [
                InlineKeyboardButton(
                    "⭐ Set Current Workspace as Default",
                    callback_data=f"br:def:{token}",
                )
            ]
        )
        lines.append(
            f"Current Active Workspace:\n<code>{html.escape(session.workspace)}</code>\n"
        )

    lines.append(
        "To change the default, type:\n<code>/default &lt;path&gt;</code> or <code>/set_default &lt;path&gt;</code>"
    )

    reply_markup = (
        InlineKeyboardMarkup(buttons)
        if buttons
        else None
    )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
    )


async def cmd_set_default(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    args = context.args or []
    target = " ".join(args).strip()

    session = SESSIONS.get(chat_id)

    if not target:
        if session and session.workspace:
            target = session.workspace
        else:
            await update.message.reply_text(
                "Usage: <code>/set_default &lt;path&gt;</code>",
                parse_mode=ParseMode.HTML,
            )
            return

    resolved = set_default_workspace(target)
    await update.message.reply_text(
        f"⭐ <b>Default workspace saved!</b>\n\n"
        f"📂 <code>{html.escape(resolved)}</code>\n\n"
        f"All future sessions and fallback commands will use this directory.",
        parse_mode=ParseMode.HTML,
    )
