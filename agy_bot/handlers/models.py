"""
agy_bot/handlers/models.py — Model selection: /model, /models and callbacks.
"""

import asyncio
import time

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from agy_bot.session import SESSIONS, ChatSession
from agy_bot.rendering.text import chat_allowed
from agy_bot.state import DEFAULT_WORKSPACE
from agy_bot.models.models import (
    MODELS_CACHE,
    fetch_available_models,
    render_model_groups_markup,
    render_reasoning_markup,
)


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
