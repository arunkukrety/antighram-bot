"""
agy_bot/health/health.py — Service, host system, and agy AI engine health check.
"""

import html
import os
import platform
import resource
import shutil
import time
from typing import Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agy_bot.config import (
    log,
    AGY_BIN,
    BOT_START_TIME,
)
from agy_bot.rendering.text import chat_allowed
from agy_bot.session import SESSIONS, ChatSession
from agy_bot.workspace.resolver import get_default_workspace


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m {sec:02d}s"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h {minutes:02d}m"


def probe_system_health() -> dict:
    """Gather host system and process health metrics."""
    now = time.time()
    uptime_sec = max(0.0, now - BOT_START_TIME)

    # Process Memory RSS (Linux maxrss in KB)
    try:
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        rss_mb = round(rusage.ru_maxrss / 1024.0, 1)
    except Exception:
        rss_mb = 0.0

    # CPU Load Average
    try:
        load1, load5, load15 = os.getloadavg()
    except Exception:
        load1, load5, load15 = 0.0, 0.0, 0.0

    # Disk Space (Root filesystem)
    try:
        usage = shutil.disk_usage("/")
        free_gb = round(usage.free / (1024**3), 1)
        total_gb = round(usage.total / (1024**3), 1)
        used_pct = round((usage.used / usage.total) * 100, 1)
    except Exception:
        free_gb, total_gb, used_pct = 0.0, 0.0, 0.0

    # agy CLI status
    agy_path = shutil.which(AGY_BIN) or AGY_BIN
    agy_available = shutil.which(AGY_BIN) is not None

    return {
        "uptime_formatted": format_duration(uptime_sec),
        "uptime_sec": uptime_sec,
        "pid": os.getpid(),
        "rss_mb": rss_mb,
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "free_gb": free_gb,
        "total_gb": total_gb,
        "used_pct": used_pct,
        "agy_bin": AGY_BIN,
        "agy_path": agy_path,
        "agy_available": agy_available,
        "python_version": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "node": platform.node(),
    }


def build_health_display(
    session: Optional[ChatSession] = None,
) -> Tuple[str, InlineKeyboardMarkup]:
    """Build formatted HTML report and inline keyboard markup for /health."""
    sys_health = probe_system_health()

    bot_status_badge = "🟢 <b>HEALTHY</b>"
    agy_badge = (
        "🟢 <b>AVAILABLE</b>"
        if sys_health.get("agy_available")
        else "⚠️ <b>NOT FOUND</b>"
    )

    lines = [
        "🩺 <b>Antigravity Service Health</b>",
        "──────────────────────",
        f"🤖 <b>Bot Service:</b> {bot_status_badge}",
        f"• Uptime: <code>{sys_health['uptime_formatted']}</code> (PID <code>{sys_health['pid']}</code>)",
        f"• Memory RSS: <code>{sys_health['rss_mb']} MB</code>",
        f"• System Load: <code>{sys_health['load1']:.2f}, {sys_health['load5']:.2f}, {sys_health['load15']:.2f}</code>",
        f"• Python: <code>{sys_health['python_version']}</code> on <code>{html.escape(sys_health['platform'])}</code>",
        "",
        f"🧠 <b>AI Engine (agy):</b> {agy_badge}",
        f"• Binary: <code>{html.escape(sys_health['agy_path'])}</code>",
    ]

    # Workspace & Sessions
    current_ws = session.workspace if session else get_default_workspace()
    session_mode = (session.mode if session else "print").upper()
    session_model = session.model if (session and session.model) else "default"

    lines.extend([
        "",
        "💾 <b>Storage & Workspace:</b>",
        f"• Active Folder: <code>{html.escape(current_ws)}</code>",
        f"• Disk Space: <code>{sys_health['free_gb']} GB free</code> / <code>{sys_health['total_gb']} GB</code> ({sys_health['used_pct']}% used)",
        f"• Active Sessions: <code>{len(SESSIONS)}</code> (Mode: <b>{session_mode}</b>, Model: <code>{html.escape(session_model)}</code>)",
    ])

    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Health", callback_data="health:refresh"),
            InlineKeyboardButton("🤖 Models", callback_data="hact:models"),
        ],
        [
            InlineKeyboardButton("📊 Usage", callback_data="hact:usage"),
            InlineKeyboardButton("💬 New Chat", callback_data="hact:new"),
            InlineKeyboardButton("📍 PWD", callback_data="hact:pwd"),
        ],
    ])

    return "\n".join(lines), markup


async def cmd_health(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Handler for /health command."""
    chat_id = update.effective_chat.id

    if not chat_allowed(chat_id):
        return

    session = SESSIONS.get(chat_id)
    text, markup = build_health_display(session=session)

    target_msg = update.effective_message or update.message
    await target_msg.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def on_health_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Handler for health inline keyboard callbacks."""
    query = update.callback_query
    if not query:
        return

    chat_id = update.effective_chat.id
    if not chat_allowed(chat_id):
        await query.answer("Not authorized", show_alert=True)
        return

    await query.answer("Health status refreshed")
    session = SESSIONS.get(chat_id)
    text, markup = build_health_display(session=session)

    try:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except Exception as exc:
        if "message is not modified" not in str(exc).lower():
            log.warning("Could not update health message: %s", exc)
