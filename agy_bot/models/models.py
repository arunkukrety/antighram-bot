"""
Model group building and markup rendering for the hierarchical model selector.
"""

import html
import re
import time
import asyncio
from typing import Dict, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from agy_bot.config import AGY_BIN
from agy_bot.workspace.resolver import get_default_workspace


MODELS_CACHE: Dict[str, object] = {
    "timestamp": 0.0,
    "raw_models": [],
    "groups": {},
    "group_order": [],
}


def extract_model_group_and_variant(m_id: str, m_name: str) -> Tuple[str, str]:
    """
    Extract base model family name and reasoning/variant effort.
    e.g. 'Gemini 3.8 Flash (High)' -> ('Gemini 3.8 Flash', 'High')
    e.g. 'Claude Sonnet 4.6 (Thinking)' -> ('Claude Sonnet 4.6', 'Thinking')
    """
    if " (" in m_name and m_name.endswith(")"):
        base, var = m_name.rsplit(" (", 1)
        return base.strip(), var[:-1].strip()
    return m_name.strip(), "Default"


def get_model_icon(name: str) -> str:
    return ""


def get_variant_display_label(variant: str) -> str:
    v_lower = variant.lower()
    if "high" in v_lower:
        return "High Reasoning"
    elif "medium" in v_lower or "med" in v_lower:
        return "Medium Reasoning"
    elif "low" in v_lower:
        return "Low Reasoning"
    elif "thinking" in v_lower:
        return "Thinking"
    elif variant == "Default":
        return "Standard"
    else:
        return variant


def slugify_model_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return slug or "model"


def build_model_groups(
    raw_models: List[Tuple[str, str]]
) -> Tuple[Dict[str, dict], List[str]]:
    groups: Dict[str, dict] = {}
    order: List[str] = []

    for m_id, m_name in raw_models:
        base_name, variant = extract_model_group_and_variant(m_id, m_name)
        slug = slugify_model_name(base_name)

        if slug not in groups:
            groups[slug] = {
                "slug": slug,
                "name": base_name,
                "variants": [],
            }
            order.append(slug)

        groups[slug]["variants"].append(
            {
                "id": m_id,
                "variant": variant,
                "label": get_variant_display_label(variant),
                "full_name": m_name,
            }
        )

    return groups, order


async def fetch_available_models(
    force: bool = False,
) -> Tuple[Dict[str, dict], List[str]]:
    now = time.time()
    if (
        not force
        and MODELS_CACHE["groups"]
        and (now - MODELS_CACHE["timestamp"] < 600)
    ):
        return MODELS_CACHE["groups"], MODELS_CACHE["group_order"]

    workspace = get_default_workspace()
    proc = await asyncio.create_subprocess_exec(
        AGY_BIN,
        "models",
        cwd=workspace,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = (
        stdout.decode("utf-8", errors="replace").strip()
        or stderr.decode("utf-8", errors="replace").strip()
    )
    if not output:
        return {}, []

    raw_models = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            parts = line.split("\t", 1)
            m_id = parts[0].strip()
            m_name = parts[1].strip()
        else:
            parts = line.split(None, 1)
            m_id = parts[0].strip()
            m_name = (
                parts[1].strip() if len(parts) > 1 else m_id
            )
        raw_models.append((m_id, m_name))

    groups, order = build_model_groups(raw_models)
    MODELS_CACHE["timestamp"] = now
    MODELS_CACHE["raw_models"] = raw_models
    MODELS_CACHE["groups"] = groups
    MODELS_CACHE["group_order"] = order
    return groups, order


def render_model_groups_markup(
    sessions: dict,
    chat_id: int,
    groups: Dict[str, dict],
    order: List[str],
) -> Tuple[str, InlineKeyboardMarkup]:
    session = sessions.get(chat_id)
    current_model = session.model if session else None

    buttons = []
    for slug in order:
        grp = groups[slug]
        active_variant = None
        for v in grp["variants"]:
            if current_model and (
                current_model == v["id"] or current_model == v["full_name"]
            ):
                active_variant = v["variant"]
                break

        if active_variant:
            label = f"{grp['name']} ({active_variant}) [active]"
        else:
            label = grp["name"]

        buttons.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"mgrp:{slug}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "Refresh List",
                callback_data="mrefresh",
            )
        ]
    )

    text = (
        "<b>Available Models</b>\n\n"
        f"Current model: <code>{html.escape(current_model or '(agy default)')}</code>\n\n"
        "<i>Tap a model family below to choose reasoning effort:</i>"
    )
    return text, InlineKeyboardMarkup(buttons)


def render_reasoning_markup(
    sessions: dict,
    chat_id: int,
    group: dict,
) -> Tuple[str, InlineKeyboardMarkup]:
    session = sessions.get(chat_id)
    current_model = session.model if session else None

    buttons = []
    for v in group["variants"]:
        is_active = bool(
            current_model
            and (current_model == v["id"] or current_model == v["full_name"])
        )
        suffix = " [active]" if is_active else ""
        label = f"{v['label']}{suffix}"
        buttons.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"model:{v['id']}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "Back to Models",
                callback_data="mhome",
            )
        ]
    )

    text = (
        f"<b>{html.escape(group['name'])}</b>\n\n"
        f"Current model: <code>{html.escape(current_model or '(agy default)')}</code>\n\n"
        "<i>Select reasoning effort level:</i>"
    )
    return text, InlineKeyboardMarkup(buttons)
