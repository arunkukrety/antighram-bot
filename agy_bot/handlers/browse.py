"""
agy_bot/handlers/browse.py — Interactive directory browser and volumes.

/browse, /volumes and the br:* callback router.
"""

import asyncio
import html
import os
import re
from typing import Dict, List

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agy_bot.session import SESSIONS, ChatSession, teardown_session
from agy_bot.rendering.text import chat_allowed
from agy_bot.workspace.history import remember_workspace
from agy_bot.workspace.resolver import get_default_workspace, set_default_workspace
from agy_bot.workspace.browse_token import BROWSE_CACHE
from agy_bot.workspace.volumes import build_volumes_markup
from agy_bot.browse.markup import build_browse_markup

# Navigation history for the directory browser (chat_id -> list of paths)
NAV_HISTORY: Dict[int, List[str]] = {}


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
