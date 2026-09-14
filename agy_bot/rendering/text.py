"""
Text utilities: ANSI stripping, text splitting, chat authorization.
"""

import re
from typing import List

from agy_bot.config import ALLOWED_CHAT_IDS


def chat_allowed(chat_id: int) -> bool:
    return (
        ALLOWED_CHAT_IDS is None
        or chat_id in ALLOWED_CHAT_IDS
    )


def strip_ansi(text: str) -> str:
    ansi = re.compile(
        r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])"
    )
    return ansi.sub("", text or "")


def split_text(
    text: str,
    max_len: int = 3500,
) -> List[str]:

    if len(text) <= max_len:
        return [text]

    chunks = []
    remaining = text

    while len(remaining) > max_len:

        cut = remaining.rfind(
            "\n",
            0,
            max_len,
        )

        if cut < max_len // 2:

            cut = remaining.rfind(
                " ",
                0,
                max_len,
            )

        if cut < max_len // 2:
            cut = max_len

        chunks.append(
            remaining[:cut].rstrip()
        )

        remaining = (
            remaining[cut:]
            .lstrip()
        )

    if remaining:
        chunks.append(remaining)

    return chunks
