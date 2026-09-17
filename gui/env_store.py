"""
gui/env_store.py — Read/write access to the user's .env config file.
"""

from dotenv import dotenv_values, set_key

from gui.paths import ENV_FILE

PLACEHOLDER_TOKEN = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"


def read_env() -> dict[str, str]:
    """Return current .env contents as a dict (all values are strings)."""
    if not ENV_FILE.exists():
        return {}
    return dict(dotenv_values(ENV_FILE))


def write_env(key: str, value: str) -> None:
    """Write / update a single key in the .env file."""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Ensure the file exists
    if not ENV_FILE.exists():
        ENV_FILE.write_text("", encoding="utf-8")
    set_key(str(ENV_FILE), key, value, quote_mode="never")


def write_env_all(data: dict[str, str]) -> None:
    """Overwrite all tracked keys in .env atomically."""
    for k, v in data.items():
        write_env(k, v)


def has_token() -> bool:
    """Return True if a real Bot Token is already configured."""
    token = read_env().get("TELEGRAM_BOT_TOKEN", "").strip()
    return bool(token) and token != PLACEHOLDER_TOKEN
