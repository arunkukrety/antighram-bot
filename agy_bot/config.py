"""
Central configuration: env vars, paths, and timeouts.
"""

import os
import json
import logging
import secrets
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

log = logging.getLogger("agy-telegram-bot")

# ============================================================================
# CORE SETTINGS
# ============================================================================

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

AGY_BIN = os.environ.get(
    "AGY_BIN",
    "agy",
)

CONFIG_FILE = Path(
    os.path.expanduser(
        "~/.agy-telegram-config.json"
    )
)

WORKSPACE_HISTORY_FILE = Path(
    os.path.expanduser(
        "~/.agy-telegram-workspaces.json"
    )
)

_allowed_raw = os.environ.get(
    "TELEGRAM_ALLOWED_CHAT_IDS",
    "",
).strip()

ALLOWED_CHAT_IDS = (
    {
        int(x.strip())
        for x in _allowed_raw.split(",")
        if x.strip()
    }
    if _allowed_raw
    else None
)

if ALLOWED_CHAT_IDS is None:
    log.warning(
        "TELEGRAM_ALLOWED_CHAT_IDS is not set."
    )

PRINT_TIMEOUT = int(
    os.environ.get(
        "AGY_PRINT_TIMEOUT",
        "300",
    )
)

QUIET_SECONDS = 1.5
POLL_TIMEOUT = 0.3

PTY_ROWS = 400
PTY_COLS = 200

TELEGRAM_MAX_LEN = 3900

# ============================================================================
# CONFIG FILE I/O
# ============================================================================

def load_bot_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            with open(
                CONFIG_FILE,
                "r",
                encoding="utf-8",
            ) as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        log.exception(
            "Could not load bot config"
        )
    return {}


def save_bot_config(config: dict):
    try:
        CONFIG_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        tmp = CONFIG_FILE.with_suffix(
            ".tmp"
        )
        with open(
            tmp,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                config,
                f,
                indent=2,
            )
        tmp.replace(CONFIG_FILE)
    except Exception:
        log.exception(
            "Could not save bot config"
        )
