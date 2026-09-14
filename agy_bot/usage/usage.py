"""
Usage data fetching and display rendering.
"""

import asyncio
import html
import json
from typing import Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from agy_bot.config import AGY_BIN


def make_progress_bar(
    fraction: float,
    length: int = 10,
) -> str:
    fraction = max(
        0.0,
        min(1.0, fraction),
    )
    filled = int(
        round(fraction * length)
    )
    empty = length - filled
    return "█" * filled + "░" * empty


def render_usage_display(
    data: dict,
) -> Tuple[str, InlineKeyboardMarkup]:

    lines = [
        "📊 <b>Model Quota & Usage</b>\n",
    ]

    groups = data.get(
        "groups",
        [],
    )

    if not groups:
        raw_text = data.get(
            "raw_text",
            "No quota data returned.",
        )
        lines.append(
            f"<pre>{html.escape(raw_text)}</pre>"
        )
    else:
        for group in groups:
            g_name = group.get(
                "name",
                "Models",
            )
            g_desc = group.get(
                "description",
                "",
            )
            lines.append(
                f"<b>{html.escape(g_name)}</b>"
            )
            if g_desc:
                lines.append(
                    f"<i>{html.escape(g_desc)}</i>"
                )
            lines.append("")

            for b in group.get(
                "buckets",
                [],
            ):
                b_name = b.get(
                    "name",
                    "Limit",
                )
                frac = b.get(
                    "remaining_fraction",
                    0.0,
                )
                pct = int(
                    round(frac * 100)
                )
                bar = make_progress_bar(
                    frac
                )
                b_desc = b.get(
                    "description",
                    "",
                )

                refresh_info = ""
                if "refresh in" in b_desc:
                    refresh_info = b_desc.split(
                        "refresh in",
                        1,
                    )[1].rstrip(".")
                    refresh_info = (
                        f" • Refreshes in{refresh_info}"
                    )
                elif frac >= 0.999:
                    refresh_info = (
                        " • Fully available"
                    )

                emoji = (
                    "🟢"
                    if pct >= 50
                    else (
                        "🟡"
                        if pct >= 20
                        else "🔴"
                    )
                )

                lines.append(
                    f"{emoji} <b>{html.escape(b_name)}:</b> {pct}%"
                )
                lines.append(
                    f"<code>[{bar}]</code>{html.escape(refresh_info)}"
                )
                lines.append("")

            lines.append(
                "─────────────────────────\n"
            )

        if (
            lines
            and lines[-1].startswith("────")
        ):
            lines.pop()

    buttons = [
        [
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data="usage:refresh",
            ),
            InlineKeyboardButton(
                "🤖 Switch Model",
                callback_data="usage:models",
            ),
        ]
    ]

    return (
        "\n".join(lines).strip(),
        InlineKeyboardMarkup(buttons),
    )


async def fetch_usage_data(
    workspace: str,
) -> dict:

    proc = await asyncio.create_subprocess_exec(
        AGY_BIN,
        "-p",
        "/usage",
        "--output-format",
        "stream-json",
        cwd=workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(
            "Timed out querying agy usage"
        )

    out = stdout.decode(
        "utf-8",
        errors="replace",
    )

    raw_lines = []

    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            if ev.get("event") == "command_result":
                cmd = ev.get(
                    "command",
                    {},
                )
                if (
                    cmd.get("name") == "usage"
                    and "data" in cmd
                ):
                    return cmd["data"]
            elif ev.get("event") == "result":
                resp = ev.get(
                    "result",
                    {},
                ).get("response")
                if resp:
                    raw_lines.append(resp)
        except Exception:
            raw_lines.append(line)

    err = stderr.decode(
        "utf-8",
        errors="replace",
    ).strip()

    return {
        "raw_text": (
            "\n".join(raw_lines).strip()
            or err
            or "No usage data returned."
        )
    }
