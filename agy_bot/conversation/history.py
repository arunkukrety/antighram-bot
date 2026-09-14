"""
Conversation tracking, persistence, and Telegram inline markup.
"""

import html
import json
import os
import re
import time
from typing import Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from agy_bot.config import log


CONVERSATION_HISTORY_FILE = os.path.expanduser("~/.agy-telegram-conversations.json")
BRAIN_DIR = os.path.expanduser("~/.gemini/antigravity-ide/brain")


def clean_prompt_preview(text: str, max_len: int = 35) -> str:
    """Clean prompt string for display as a button label or preview snippet."""
    if not text:
        return "Untitled Conversation"

    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = " ".join(cleaned.split()).strip()

    if not cleaned:
        return "Untitled Conversation"

    if len(cleaned) > max_len:
        return cleaned[: max_len - 1] + "…"
    return cleaned


def load_conversations() -> List[dict]:
    """Load conversation records from JSON file."""
    if not os.path.exists(CONVERSATION_HISTORY_FILE):
        return []

    try:
        with open(CONVERSATION_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        log.warning(f"Failed to load conversations from {CONVERSATION_HISTORY_FILE}: {e}")

    return []


def save_conversations(convos: List[dict]) -> None:
    """Save conversation records to JSON file."""
    try:
        tmp_file = f"{CONVERSATION_HISTORY_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(convos[:50], f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, CONVERSATION_HISTORY_FILE)
    except Exception as e:
        log.warning(f"Failed to save conversations to {CONVERSATION_HISTORY_FILE}: {e}")


def record_conversation(
    chat_id: int,
    conv_id: str,
    prompt: str,
    workspace: str,
    model: Optional[str] = None,
) -> None:
    """Record or update a conversation in the persistent history store."""
    if not conv_id:
        return

    convos = load_conversations()
    now = time.time()

    existing_idx = None
    for idx, c in enumerate(convos):
        if c.get("id") == conv_id:
            existing_idx = idx
            break

    if existing_idx is not None:
        entry = convos.pop(existing_idx)
        entry["updated_at"] = now
        entry["workspace"] = workspace
        if model:
            entry["model"] = model
        if not entry.get("title") or entry.get("title") == "Untitled Conversation":
            entry["title"] = clean_prompt_preview(prompt)
        convos.insert(0, entry)
    else:
        entry = {
            "id": conv_id,
            "chat_id": chat_id,
            "title": clean_prompt_preview(prompt),
            "workspace": workspace,
            "model": model,
            "created_at": now,
            "updated_at": now,
        }
        convos.insert(0, entry)

    save_conversations(convos)


def discover_brain_conversations(limit: int = 10) -> List[dict]:
    """Scan local brain directory for existing agy conversations."""
    if not os.path.exists(BRAIN_DIR) or not os.path.isdir(BRAIN_DIR):
        return []

    discovered = []
    try:
        entries = []
        for name in os.listdir(BRAIN_DIR):
            full_path = os.path.join(BRAIN_DIR, name)
            if os.path.isdir(full_path) and not name.startswith("."):
                try:
                    mtime = os.path.getmtime(full_path)
                    entries.append((mtime, name, full_path))
                except OSError:
                    continue

        entries.sort(key=lambda x: x[0], reverse=True)

        for mtime, conv_id, path in entries[:limit]:
            transcript_path = os.path.join(path, ".system_generated", "logs", "transcript.jsonl")
            prompt_preview = "Untitled Conversation"
            if os.path.exists(transcript_path):
                try:
                    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            row = json.loads(line)
                            if row.get("type") == "USER_INPUT":
                                prompt_preview = clean_prompt_preview(row.get("content", ""))
                                break
                except Exception:
                    pass

            discovered.append(
                {
                    "id": conv_id,
                    "title": prompt_preview,
                    "workspace": "",
                    "model": None,
                    "created_at": mtime,
                    "updated_at": mtime,
                }
            )
    except Exception as e:
        log.warning(f"Error discovering brain conversations: {e}")

    return discovered


def get_recent_conversations(chat_id: Optional[int] = None, limit: int = 8) -> List[dict]:
    """Get recent conversations, falling back to disk discovery if needed."""
    saved = load_conversations()

    filtered = [c for c in saved if chat_id is None or c.get("chat_id") == chat_id]
    if not filtered and saved:
        filtered = saved

    existing_ids = {c.get("id") for c in filtered}

    if len(filtered) < limit:
        discovered = discover_brain_conversations(limit=limit)
        for disc in discovered:
            if disc["id"] not in existing_ids:
                filtered.append(disc)
                existing_ids.add(disc["id"])
                if len(filtered) >= limit:
                    break

    return filtered[:limit]


def render_conversations_markup(
    chat_id: int,
    current_conv_id: Optional[str] = None,
) -> Tuple[str, InlineKeyboardMarkup]:
    """Render conversation list and inline keyboard buttons."""
    convos = get_recent_conversations(chat_id=chat_id, limit=8)

    buttons = []
    for c in convos:
        c_id = c.get("id", "")
        title = c.get("title") or c_id[:8]
        is_active = bool(current_conv_id and current_conv_id == c_id)

        ws = c.get("workspace")
        ws_name = os.path.basename(ws.rstrip("/")) if ws else ""
        prefix = f"[{ws_name}] " if ws_name else ""

        max_title_len = 22 if is_active else 30
        if len(title) > max_title_len:
            title_display = title[: max_title_len - 1] + "…"
        else:
            title_display = title

        if is_active:
            btn_label = f"• {prefix}{title_display} [active]"
        else:
            btn_label = f"{prefix}{title_display}"

        buttons.append([InlineKeyboardButton(btn_label, callback_data=f"conv:{c_id}")])

    control_row = [
        InlineKeyboardButton("➕ New Chat", callback_data="conv_new"),
        InlineKeyboardButton("🔄 Refresh", callback_data="conv_refresh"),
    ]
    buttons.append(control_row)

    active_display = (
        f"<code>{html.escape(current_conv_id)}</code>"
        if current_conv_id
        else "<i>None (next prompt will start fresh)</i>"
    )

    text = (
        "<b>Conversations</b>\n\n"
        f"Active ID: {active_display}\n\n"
        "<i>Select a previous conversation to resume, or tap <b>➕ New Chat</b>:</i>"
    )

    return text, InlineKeyboardMarkup(buttons)
