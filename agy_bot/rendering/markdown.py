"""
Markdown → Telegram HTML rendering.
"""

import html
import re
from typing import Optional


def markdown_to_html(
    text: str,
) -> str:
    """
    Convert common LLM Markdown to Telegram-safe HTML.

    We intentionally use private-use Unicode placeholders rather than
    strings like __PLACEHOLDER__, because those can themselves be
    interpreted as Markdown/HTML.

    Supported:
      # headings
      **bold**
      *italic*
      _italic_
      `inline code`
      ```code blocks```
      [links](https://...)
      - bullets
      1. numbered lists

    Everything else is safely escaped.
    """

    if not text:
        return ""

    text = (
        text.replace(
            "\r\n",
            "\n",
        )
        .replace(
            "\r",
            "\n",
        )
    )

    placeholders = {}

    def put_placeholder(
        value: str,
    ) -> str:

        index = len(
            placeholders
        )

        key = chr(
            0xE000 + index
        )

        placeholders[key] = value

        return key

    # ------------------------------------------------------------------
    # Fenced code blocks
    # ------------------------------------------------------------------

    def fenced_code(
        match,
    ):

        language = (
            match.group(1)
            or ""
        ).strip()

        code = (
            match.group(2)
            or ""
        ).strip("\n")

        escaped = html.escape(
            code,
            quote=False,
        )

        if language:

            lang = html.escape(
                language,
                quote=False,
            )

            value = (
                f"<b>{lang}</b>\n"
                f"<pre>{escaped}</pre>"
            )

        else:

            value = (
                f"<pre>{escaped}</pre>"
            )

        return put_placeholder(
            value
        )

    text = re.sub(
        r"```([^\n]*)\n(.*?)```",
        fenced_code,
        text,
        flags=re.DOTALL,
    )

    # ------------------------------------------------------------------
    # Inline code
    # ------------------------------------------------------------------

    def inline_code(
        match,
    ):

        code = html.escape(
            match.group(1),
            quote=False,
        )

        return put_placeholder(
            f"<code>{code}</code>"
        )

    text = re.sub(
        r"`([^`\n]+)`",
        inline_code,
        text,
    )

    # ------------------------------------------------------------------
    # Markdown links
    # ------------------------------------------------------------------

    def markdown_link(
        match,
    ):

        label = html.escape(
            match.group(1),
            quote=False,
        )

        url = html.escape(
            match.group(2),
            quote=True,
        )

        return put_placeholder(
            f'<a href="{url}">{label}</a>'
        )

    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        markdown_link,
        text,
    )

    # ------------------------------------------------------------------
    # Escape the remaining raw text.
    # ------------------------------------------------------------------

    text = html.escape(
        text,
        quote=False,
    )

    # ------------------------------------------------------------------
    # Headings
    # ------------------------------------------------------------------

    text = re.sub(
        r"(?m)^[ \t]*#{1,6}[ \t]+(.+?)$",
        r"<b>\1</b>",
        text,
    )

    # ------------------------------------------------------------------
    # Bold
    # ------------------------------------------------------------------

    text = re.sub(
        r"\*\*(.+?)\*\*",
        r"<b>\1</b>",
        text,
        flags=re.DOTALL,
    )

    # ------------------------------------------------------------------
    # Italic
    # ------------------------------------------------------------------

    text = re.sub(
        r"(?<!\*)\*([^*\n]+)\*(?!\*)",
        r"<i>\1</i>",
        text,
    )

    text = re.sub(
        r"(?<!_)_([^_\n]+)_(?!_)",
        r"<i>\1</i>",
        text,
    )

    # ------------------------------------------------------------------
    # Bullets
    # ------------------------------------------------------------------

    text = re.sub(
        r"(?m)^[ \t]*[-*][ \t]+",
        "• ",
        text,
    )

    # ------------------------------------------------------------------
    # Restore protected blocks.
    # ------------------------------------------------------------------

    for key, value in placeholders.items():

        text = text.replace(
            key,
            value,
        )

    return text


def format_footer(
    model: Optional[str],
    duration: Optional[float],
) -> str:
    """Render the standard agy response footer."""
    model_text = html.escape(
        model or "default",
        quote=False,
    )
    duration_text = (
        f"{duration:.2f}s"
        if duration is not None
        else "unknown"
    )
    return (
        "──────────────\n"
        f"🤖 <code>{model_text}</code>\n"
        f"⏱ <code>{duration_text}</code>"
    )


def response_html(
    response: str,
    model: Optional[str],
    duration: Optional[float],
) -> str:

    body = markdown_to_html(
        response.strip()
    )

    return (
        "<b>agy</b>\n\n"
        + body
        + "\n\n"
        + format_footer(model, duration)
    )
