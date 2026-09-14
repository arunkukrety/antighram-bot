"""
Directory browser markup builder.
"""

import html
import os
from typing import Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from agy_bot.workspace.browse_token import get_browse_token


def build_browse_markup(
    current_path: str,
    nav_history: Dict[int, List[str]],
    chat_id: Optional[int] = None,
) -> Tuple[str, InlineKeyboardMarkup]:

    current_path = os.path.abspath(
        os.path.expanduser(current_path)
    )
    parent_path = os.path.dirname(current_path)

    curr_token = get_browse_token(current_path)
    parent_token = get_browse_token(parent_path)

    subdirs = []
    try:
        entries = sorted(
            os.scandir(current_path),
            key=lambda e: e.name.lower(),
        )
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if (
                        entry.name.startswith(".")
                        and entry.name not in (".config", ".gemini")
                    ):
                        continue
                    subdirs.append(entry.name)
            except (PermissionError, OSError):
                continue
    except Exception as exc:
        return (
            f"⚠️ Could not read directory: {html.escape(str(exc))}",
            InlineKeyboardMarkup([]),
        )

    buttons = []

    # Row 1: Navigation controls (Up, Down/Prev, Set Active)
    control_row = []
    if parent_path and parent_path != current_path:
        control_row.append(
            InlineKeyboardButton(
                "⬆️ Up",
                callback_data=f"br:nav:{parent_token}",
            )
        )

    # Down / Previous Directory Button (from navigation history)
    prev_path = None
    if chat_id and chat_id in nav_history:
        for p in reversed(nav_history[chat_id]):
            if p != current_path and os.path.isdir(p):
                prev_path = p
                break

    if prev_path:
        prev_token = get_browse_token(prev_path)
        prev_name = (
            os.path.basename(prev_path.rstrip("/"))
            or "Prev"
        )
        control_row.append(
            InlineKeyboardButton(
                f"⬇️ {prev_name[:12]}",
                callback_data=f"br:back:{prev_token}",
            )
        )

    control_row.append(
        InlineKeyboardButton(
            "🎯 Set Active",
            callback_data=f"br:sel:{curr_token}",
        )
    )
    buttons.append(control_row)

    # Row 2: Action buttons
    action_row = [
        InlineKeyboardButton(
            "🚀 Launch agy",
            callback_data=f"br:agy:{curr_token}",
        ),
        InlineKeyboardButton(
            "💾 Volumes",
            callback_data="br:vols:all",
        ),
        InlineKeyboardButton(
            "⭐ Set Default",
            callback_data=f"br:def:{curr_token}",
        ),
    ]
    buttons.append(action_row)

    # Row 3+: Subdirectories (2 per row)
    subdir_rows = []
    current_row = []
    for sub in subdirs[:24]:
        sub_path = os.path.join(current_path, sub)
        sub_token = get_browse_token(sub_path)
        current_row.append(
            InlineKeyboardButton(
                f"📁 {sub[:18]}",
                callback_data=f"br:nav:{sub_token}",
            )
        )
        if len(current_row) == 2:
            subdir_rows.append(current_row)
            current_row = []
    if current_row:
        subdir_rows.append(current_row)

    buttons.extend(subdir_rows)

    text = (
        f"📂 <b>Directory Browser</b>\n\n"
        f"📍 <code>{html.escape(current_path)}</code>\n\n"
        f"Subdirectories: {len(subdirs)}\n"
        f"<i>Tap a folder to navigate, or tap an action button above:</i>"
    )

    return text, InlineKeyboardMarkup(buttons)
