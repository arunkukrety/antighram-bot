"""
Shared workspace list markup builder — eliminates duplication between
cmd_workspaces and on_workspace_callback.
"""

import html
from typing import List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from agy_bot.workspace.browse_token import get_browse_token


def build_workspace_markup(
    workspaces: List[dict],
) -> tuple:
    """
    Returns (text: str, markup: InlineKeyboardMarkup) for a workspace list.
    Used by both cmd_workspaces and on_workspace_callback error recovery.
    """
    buttons = []
    for item in workspaces[:10]:
        name = item.get("name") or item.get("path")
        token = get_browse_token(item["path"])
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📂 {name[:50]}",
                    callback_data=f"workspace:{token}",
                )
            ]
        )

    lines = [
        "📂 <b>Recent workspaces</b>",
        "",
    ]

    for index, item in enumerate(
        workspaces[:10],
        start=1,
    ):
        name = html.escape(
            item.get("name", "workspace"),
            quote=False,
        )
        path = html.escape(
            item.get("path", ""),
            quote=False,
        )
        lines.append(
            f"<b>{index}.</b> {name}\n"
            f"<code>{path}</code>"
        )

    return "\n".join(lines), InlineKeyboardMarkup(buttons)
