"""
agy_bot/main.py — Application entrypoint.

Wires all handlers together and builds the Telegram Application.
"""

import asyncio
import html
import os
import re
import time
from typing import Dict, List, Optional

import pyte
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    error as tg_error,
)
from telegram.constants import ParseMode, ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from agy_bot.config import (
    log, BOT_TOKEN,
)
from agy_bot.session import (
    SESSIONS, ChatSession, InteractiveState, teardown_session,
)
from agy_bot.rendering.text import chat_allowed, split_text
from agy_bot.rendering.images import find_involved_images, send_images
from agy_bot.workspace.history import remember_workspace, forget_workspace, get_recent_workspaces
from agy_bot.workspace.resolver import get_default_workspace, set_default_workspace, resolve_target_workspace
from agy_bot.workspace.browse_token import BROWSE_CACHE, get_browse_token
from agy_bot.workspace.volumes import build_volumes_markup
from agy_bot.workspace.markup import build_workspace_markup
from agy_bot.browse.markup import build_browse_markup
from agy_bot.agy.print_mode import handle_print_message
from agy_bot.agy.interactive_mode import (
    spawn_interactive_agy, interactive_reader_loop, render_screen_text,
)
from agy_bot.models.models import (
    MODELS_CACHE, fetch_available_models,
    render_model_groups_markup, render_reasoning_markup,
)
from agy_bot.usage.usage import fetch_usage_data, render_usage_display
from agy_bot.conversation.history import (
    render_conversations_markup,
    load_conversations,
)

# Navigation history for the directory browser (chat_id -> list of paths)
NAV_HISTORY: Dict[int, List[str]] = {}

# Initialise default workspace on startup
DEFAULT_WORKSPACE = get_default_workspace()
os.makedirs(DEFAULT_WORKSPACE, exist_ok=True)


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
# /WORKSPACES
# ============================================================================

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


# ============================================================================
# WORKSPACE CALLBACK
# ============================================================================

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


# ============================================================================
# /PWD
# ============================================================================

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


# ============================================================================
# /CD
# ============================================================================

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


# ============================================================================
# /DEFAULT & /SET_DEFAULT
# ============================================================================

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


# ============================================================================
# /SH (DESKTOP SHELL EXECUTION)
# ============================================================================

async def cmd_sh(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    command = " ".join(context.args or []).strip()

    if not command:
        await update.message.reply_text(
            "💻 <b>Desktop Terminal</b>\n\n"
            "Usage: <code>/sh &lt;command&gt;</code>\n"
            "Example: <code>/sh git status</code>\n"
            "Example: <code>/sh ls -la</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    session = SESSIONS.get(chat_id)
    cwd = (
        session.workspace
        if session
        else get_default_workspace()
    )

    trimmed = command.strip()
    if trimmed == "cd" or trimmed.startswith("cd "):
        target = trimmed[3:].strip() or "~"
        await update.message.reply_text(
            f"💡 <i>Tip:</i> Running <code>cd</code> in a subshell won't persist.\n"
            f"Use <code>/cd {html.escape(target)}</code> to change the bot workspace!",
            parse_mode=ParseMode.HTML,
        )

    await context.bot.send_chat_action(
        chat_id,
        ChatAction.TYPING,
    )

    started_wall_clock = time.time()

    try:

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable="/bin/bash",
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await update.message.reply_text(
                "⏱️ Command timed out after 60 seconds."
            )
            return

        out_str = stdout.decode(
            "utf-8",
            errors="replace",
        ).strip()

        err_str = stderr.decode(
            "utf-8",
            errors="replace",
        ).strip()

        combined = []
        if out_str:
            combined.append(out_str)
        if err_str:
            combined.append(f"[stderr]\n{err_str}")

        output = "\n\n".join(combined).strip() or "(no output)"
        status_icon = (
            "✅"
            if proc.returncode == 0
            else f"⚠️ (exit {proc.returncode})"
        )

        header = (
            f"{status_icon} <code>$ {html.escape(command)}</code>\n"
            f"📂 <code>{html.escape(cwd)}</code>\n\n"
        )

        chunks = split_text(output, max_len=3500)

        if chunks:
            await update.message.reply_text(
                header + f"<pre>{html.escape(chunks[0])}</pre>",
                parse_mode=ParseMode.HTML,
            )
            for chunk in chunks[1:]:
                await update.message.reply_text(
                    f"<pre>{html.escape(chunk)}</pre>",
                    parse_mode=ParseMode.HTML,
                )

        sh_images = find_involved_images(
            text_content=output,
            workspace=cwd,
            started_at=started_wall_clock,
        )
        if sh_images:
            await send_images(context.application, chat_id, sh_images)

    except Exception as exc:

        await update.message.reply_text(
            f"⚠️ Error executing command:\n{html.escape(str(exc))}",
            parse_mode=ParseMode.HTML,
        )


# ============================================================================
# /VOLUMES
# ============================================================================

async def cmd_volumes(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    text, markup = build_volumes_markup(sessions=SESSIONS, chat_id=chat_id)

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


# ============================================================================
# /BROWSE & DIRECTORY BROWSER
# ============================================================================

async def cmd_browse(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    args = context.args or []
    target = " ".join(args).strip()

    session = SESSIONS.get(chat_id)
    if target:
        start_path = os.path.abspath(
            os.path.expanduser(target)
        )
    elif session and session.workspace:
        start_path = session.workspace
    else:
        start_path = get_default_workspace()

    if not os.path.isdir(start_path):
        await update.message.reply_text(
            f"⚠️ Path is not a valid directory:\n<code>{html.escape(start_path)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    text, markup = build_browse_markup(
        start_path,
        nav_history=NAV_HISTORY,
        chat_id=chat_id,
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def on_browse_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query
    await query.answer()

    if not query.data or not query.data.startswith("br:"):
        return

    parts = query.data.split(":")
    if len(parts) != 3:
        return

    action, token = parts[1], parts[2]
    chat_id = query.message.chat_id

    if not chat_allowed(chat_id):
        return

    # 1. View external storage volumes
    if action == "vols":
        text, markup = build_volumes_markup(sessions=SESSIONS, chat_id=chat_id)
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
        return

    path = BROWSE_CACHE.get(token)

    if not path:
        await query.answer(
            "Path reference expired",
            show_alert=True,
        )
        return

    # 2. Mount external disk partition via udisksctl
    if action == "mnt":
        dev_path = path
        await query.answer(
            "Mounting volume...",
            show_alert=False,
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "udisksctl",
                "mount",
                "-b",
                dev_path,
                "--no-user-interaction",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            out = stdout.decode("utf-8", errors="replace").strip()
            mp = None
            if " at " in out:
                mp = out.split(" at ", 1)[1].strip().rstrip(".")

            if mp and os.path.isdir(mp):
                text, markup = build_browse_markup(
                    mp,
                    nav_history=NAV_HISTORY,
                    chat_id=chat_id,
                )
                await query.edit_message_text(
                    text=(
                        f"✅ <b>Volume mounted at:</b>\n<code>{html.escape(mp)}</code>\n\n"
                        + text
                    ),
                    parse_mode=ParseMode.HTML,
                    reply_markup=markup,
                )
                return
            else:
                err = (
                    stderr.decode("utf-8", errors="replace").strip()
                    or out
                )
                await query.message.reply_text(
                    f"⚠️ Mount response:\n<code>{html.escape(err or 'Could not detect mountpoint')}</code>",
                    parse_mode=ParseMode.HTML,
                )
        except Exception as exc:
            await query.message.reply_text(
                f"⚠️ Error mounting volume:\n{html.escape(str(exc))}",
                parse_mode=ParseMode.HTML,
            )
        return

    if not os.path.exists(path):
        await query.answer(
            "Folder no longer accessible",
            show_alert=True,
        )
        return

    # 3. Navigate forward into directory
    if action == "nav":
        m = re.search(
            r"📍 <code>(.*?)</code>",
            query.message.text or "",
        )
        if m:
            src_path = m.group(1).strip()
            if (
                src_path
                and os.path.isdir(src_path)
                and src_path != path
            ):
                hist = NAV_HISTORY.setdefault(chat_id, [])
                if not hist or hist[-1] != src_path:
                    hist.append(src_path)
                    if len(hist) > 20:
                        NAV_HISTORY[chat_id] = hist[-20:]

        text, markup = build_browse_markup(
            path,
            nav_history=NAV_HISTORY,
            chat_id=chat_id,
        )
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    # 4. Return to previous directory
    elif action == "back":
        if chat_id in NAV_HISTORY and NAV_HISTORY[chat_id]:
            if NAV_HISTORY[chat_id][-1] == path:
                NAV_HISTORY[chat_id].pop()

        text, markup = build_browse_markup(
            path,
            nav_history=NAV_HISTORY,
            chat_id=chat_id,
        )
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    # 5. Set active workspace
    elif action == "sel":
        session = SESSIONS.get(chat_id)
        model = session.model if session else None

        teardown_session(session)

        SESSIONS[chat_id] = ChatSession(
            chat_id=chat_id,
            workspace=path,
            model=model,
        )
        remember_workspace(path)
        await query.answer(
            "Active workspace updated!",
            show_alert=False,
        )
        await query.message.reply_text(
            f"✅ <b>Active workspace set to:</b>\n<code>{html.escape(path)}</code>\n\n"
            f"Ready! Send any prompt to run print mode, or use /interactive.",
            parse_mode=ParseMode.HTML,
        )

    # 6. Set permanent default workspace
    elif action == "def":
        resolved = set_default_workspace(path)
        await query.answer(
            "Saved as default workspace!",
            show_alert=True,
        )
        await query.message.reply_text(
            f"⭐ <b>Default workspace saved:</b>\n<code>{html.escape(resolved)}</code>\n\n"
            f"All future sessions and fallback commands will use this directory.",
            parse_mode=ParseMode.HTML,
        )

    # 7. Launch agy session here
    elif action == "agy":
        session = SESSIONS.get(chat_id)
        model = session.model if session else None

        teardown_session(session)

        SESSIONS[chat_id] = ChatSession(
            chat_id=chat_id,
            workspace=path,
            model=model,
        )
        remember_workspace(path)
        await query.answer(
            "Session initialized!",
            show_alert=False,
        )
        await query.message.reply_text(
            f"🚀 <b>Antigravity session launched in:</b>\n<code>{html.escape(path)}</code>\n\n"
            f"Ready! Send any prompt to run print mode, or use /interactive.",
            parse_mode=ParseMode.HTML,
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
            InlineKeyboardButton("💬 /new", callback_data="hact:new"),
            InlineKeyboardButton("📜 /history", callback_data="hact:history"),
            InlineKeyboardButton("📍 /pwd", callback_data="hact:pwd"),
        ],
        [
            InlineKeyboardButton("📂 /workspaces", callback_data="hact:workspaces"),
            InlineKeyboardButton("🤖 /models", callback_data="hact:models"),
            InlineKeyboardButton("📊 /usage", callback_data="hact:usage"),
        ],
        [
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
# /MODEL
# ============================================================================

async def cmd_model(
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
            "No active session. Use /start first."
        )

        return

    model = " ".join(
        context.args or []
    ).strip()

    if not model:

        await update.message.reply_text(
            "Current model: "
            + (
                session.model
                or "(agy default)"
            )
        )

        return

    session.model = model

    if (
        session.mode == "interactive"
        and session.interactive
    ):

        try:

            session.interactive.child.send(
                f"/model {model}\r"
            )

        except Exception:
            pass

    await update.message.reply_text(
        f"✅ Model set to: {model}"
    )


# ============================================================================
# /MODELS (HIERARCHICAL: BASE MODEL -> REASONING EFFORT)
# ============================================================================

async def cmd_models(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    # Check if this was called from a callback button (e.g. from /usage)
    is_callback = bool(update.callback_query)
    target_msg = update.callback_query.message if is_callback else update.message

    # Check if cache is already populated
    if (
        MODELS_CACHE["groups"]
        and (time.time() - MODELS_CACHE["timestamp"] < 600)
    ):
        text, markup = render_model_groups_markup(
            SESSIONS,
            chat_id,
            MODELS_CACHE["groups"],
            MODELS_CACHE["group_order"],
        )
        if is_callback:
            await update.callback_query.answer()
            await target_msg.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        else:
            await target_msg.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        return

    status_msg = None
    stop_spinner = asyncio.Event()

    async def spinner_worker():
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        idx = 0
        while not stop_spinner.is_set():
            try:
                await context.bot.send_chat_action(
                    chat_id,
                    ChatAction.TYPING,
                )
                if status_msg:
                    await status_msg.edit_text(
                        f"<code>{frames[idx % len(frames)]}</code> Fetching available models…",
                        parse_mode=ParseMode.HTML,
                    )
                idx += 1
            except Exception:
                pass

            try:
                await asyncio.wait_for(
                    stop_spinner.wait(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                pass

    try:
        await context.bot.send_chat_action(
            chat_id,
            ChatAction.TYPING,
        )

        if is_callback:
            await update.callback_query.answer()
            status_msg = target_msg
            await status_msg.edit_text(
                "<code>⠋</code> Fetching available models…",
                parse_mode=ParseMode.HTML,
            )
        else:
            status_msg = await target_msg.reply_text(
                "<code>⠋</code> Fetching available models…",
                parse_mode=ParseMode.HTML,
            )

        spinner_task = asyncio.create_task(spinner_worker())

        groups, order = await fetch_available_models(force=True)

        stop_spinner.set()
        await spinner_task

        if not groups:
            await status_msg.edit_text("No models returned.")
            return

        text, markup = render_model_groups_markup(
            SESSIONS,
            chat_id,
            groups,
            order,
        )
        await status_msg.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )

    except Exception as exc:
        stop_spinner.set()
        error_msg = f"⚠️ Error running agy models:\n{exc}"
        if status_msg:
            try:
                await status_msg.edit_text(error_msg)
                return
            except Exception:
                pass
        if target_msg:
            await target_msg.reply_text(error_msg)


async def on_model_group_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    if not chat_allowed(chat_id):
        return

    if not query.data or not query.data.startswith("mgrp:"):
        return

    slug = query.data.split(":", 1)[1].strip()
    groups, order = await fetch_available_models(force=False)
    grp = groups.get(slug)

    if not grp:
        await query.answer("Model family not found. Try refreshing.", show_alert=True)
        return

    text, markup = render_reasoning_markup(SESSIONS, chat_id, grp)
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except Exception:
        pass


async def on_model_home_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    if not chat_allowed(chat_id):
        return

    groups, order = await fetch_available_models(force=False)
    text, markup = render_model_groups_markup(SESSIONS, chat_id, groups, order)
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except Exception:
        pass


async def on_model_refresh_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer("Refreshing models list...")

    chat_id = query.message.chat_id
    if not chat_allowed(chat_id):
        return

    groups, order = await fetch_available_models(force=True)
    text, markup = render_model_groups_markup(SESSIONS, chat_id, groups, order)
    try:
        await query.edit_message_text(
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except Exception:
        pass


async def on_model_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    if not query.data or not query.data.startswith("model:"):
        return

    model = query.data.split(":", 1)[1].strip()
    chat_id = query.message.chat_id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(chat_id)
    if not session:
        session = ChatSession(
            chat_id=chat_id,
            workspace=DEFAULT_WORKSPACE,
            model=model,
        )
        SESSIONS[chat_id] = session
    else:
        session.model = model

    if session.mode == "interactive" and session.interactive:
        try:
            session.interactive.child.send(f"/model {model}\r")
        except Exception:
            pass

    # Find which group this model belongs to and re-render reasoning markup
    groups, _ = await fetch_available_models(force=False)
    target_group = None
    for grp in groups.values():
        for v in grp["variants"]:
            if v["id"] == model:
                target_group = grp
                break
        if target_group:
            break

    if target_group and query.message:
        text, markup = render_reasoning_markup(SESSIONS, chat_id, target_group)
        try:
            await query.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
        except Exception:
            pass

    await query.message.reply_text(f"Model set to: {model}")


# ============================================================================
# /USAGE & MODEL QUOTA
# ============================================================================

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

    async def _do_suspend():
        await asyncio.sleep(1.2)
        try:
            proc = await asyncio.create_subprocess_exec(
                "systemctl", "suspend",
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
# /CONVERSATIONS
# ============================================================================

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


# ============================================================================
# CONVERSATION CALLBACK
# ============================================================================

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


# ============================================================================
# CALLBACK ROUTER
# ============================================================================

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

    if query.data.startswith(
        "workspace:"
    ):

        await on_workspace_callback(
            update,
            context,
        )

        return

    if query.data.startswith("mgrp:"):
        await on_model_group_callback(
            update,
            context,
        )
        return

    if query.data == "mhome":
        await on_model_home_callback(
            update,
            context,
        )
        return

    if query.data == "mrefresh":
        await on_model_refresh_callback(
            update,
            context,
        )
        return

    if query.data.startswith(
        "model:"
    ):

        await on_model_callback(
            update,
            context,
        )

        return

    if query.data.startswith(
        "br:"
    ):

        await on_browse_callback(
            update,
            context,
        )

        return

    if query.data.startswith(
        "perm:"
    ):

        await on_permission_callback(
            update,
            context,
        )

        return

    if query.data.startswith(
        "usage:"
    ):

        await on_usage_callback(
            update,
            context,
        )

        return

    if query.data.startswith("conv:") or query.data in ("conv_new", "conv_refresh"):
        await on_conversation_callback(
            update,
            context,
        )
        return


# ============================================================================
# ERROR HANDLER
# ============================================================================

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle uncaught errors and suppress verbose traces for transient network hiccups."""
    err = context.error
    if isinstance(err, (tg_error.NetworkError, tg_error.TimedOut)):
        log.warning(f"Telegram network transient error: {err}")
        return
    if isinstance(err, tg_error.BadRequest) and "message is not modified" in str(err).lower():
        return
    log.error(f"Telegram error in update {update}:", exc_info=err)


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

    if action == "new":
        await cmd_new(fake_update, context)
    elif action == "history":
        await cmd_conversations(fake_update, context)
    elif action == "pwd":
        await cmd_pwd(fake_update, context)
    elif action == "workspaces":
        await cmd_workspaces(fake_update, context)
    elif action == "models":
        await cmd_models(fake_update, context)
    elif action == "usage":
        await cmd_usage(fake_update, context)
    elif action == "stop":
        await cmd_stop(fake_update, context)
    elif action == "sleep":
        await cmd_sleep(fake_update, context)


# ============================================================================
# BOT COMMANDS REGISTRATION & ENTRYPOINT
# ============================================================================

BOT_COMMANDS = [
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


def main():

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_error_handler(on_error)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("newchat", cmd_new))
    app.add_handler(CommandHandler("conversations", cmd_conversations))
    app.add_handler(CommandHandler("history", cmd_conversations))
    app.add_handler(CommandHandler("pwd", cmd_pwd))
    app.add_handler(CommandHandler("cd", cmd_cd))
    app.add_handler(CommandHandler("default", cmd_default))
    app.add_handler(CommandHandler("set_default", cmd_set_default))
    app.add_handler(CommandHandler("browse", cmd_browse))
    app.add_handler(CommandHandler("sh", cmd_sh))
    app.add_handler(CommandHandler("volumes", cmd_volumes))
    app.add_handler(CommandHandler("workspaces", cmd_workspaces))
    app.add_handler(CommandHandler("interactive", cmd_interactive))
    app.add_handler(CommandHandler("plain", cmd_plain))
    app.add_handler(CommandHandler("model", cmd_model))
    app.add_handler(CommandHandler("models", cmd_models))
    app.add_handler(CommandHandler("usage", cmd_usage))
    app.add_handler(CommandHandler("debug", cmd_debug))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("sleep", cmd_sleep))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("Starting Telegram agy bot...")

    app.run_polling()


if __name__ == "__main__":
    main()
