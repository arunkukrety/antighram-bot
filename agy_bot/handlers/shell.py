"""
agy_bot/handlers/shell.py — /sh desktop shell execution.
"""

import asyncio
import html
import sys
import time

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from agy_bot.rendering.text import chat_allowed, split_text
from agy_bot.rendering.images import find_involved_images, send_images
from agy_bot.workspace.resolver import get_default_workspace
from agy_bot.session import SESSIONS

IS_WINDOWS = sys.platform == "win32"


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
            # Force bash only on POSIX; on Windows let the default shell handle it
            **({} if IS_WINDOWS else {"executable": "/bin/bash"}),
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
