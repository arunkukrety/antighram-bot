"""
Workspace resolution: default workspace, set default, smart path resolution.
"""

import os
from typing import Optional, Tuple

from agy_bot.config import load_bot_config, save_bot_config
from agy_bot.workspace.history import load_workspace_history, remember_workspace


def get_default_workspace() -> str:
    cfg = load_bot_config()
    saved = cfg.get("default_workspace")
    if saved:
        exp = os.path.abspath(
            os.path.expanduser(saved)
        )
        if os.path.isdir(exp):
            return exp
    return os.path.abspath(
        os.path.expanduser(
            os.environ.get(
                "AGY_DEFAULT_WORKSPACE",
                "~/agy-server-workspace",
            )
        )
    )


def set_default_workspace(path: str) -> str:
    resolved = os.path.abspath(
        os.path.expanduser(path)
    )
    os.makedirs(
        resolved,
        exist_ok=True,
    )
    cfg = load_bot_config()
    cfg["default_workspace"] = resolved
    save_bot_config(cfg)
    try:
        remember_workspace(resolved)
    except Exception:
        pass
    return resolved


def resolve_target_workspace(
    target: str,
    current_ws: str,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Smartly resolves a workspace target path.
    Checks:
      1. Empty target -> default workspace
      2. If target already exists as an absolute path or expanded path (~/...)
      3. If target exists relative to current_ws
      4. If target exists in user home dir (~/<target>)
      5. If target matches the name of any recent workspace
    Returns:
      (resolved_path, None) on success, or
      (None, attempted_path) on failure.
    """
    if not target or not target.strip():
        return get_default_workspace(), None

    raw = target.strip()
    expanded = os.path.expanduser(raw)

    # 1. Direct absolute or user-expanded path
    if os.path.isabs(expanded) and os.path.exists(expanded):
        return os.path.abspath(expanded), None

    # 2. Relative to current workspace
    rel_path = os.path.abspath(os.path.join(current_ws, expanded))
    if os.path.exists(rel_path):
        return rel_path, None

    # 3. Relative to user home directory (~/<target>)
    home_path = os.path.abspath(os.path.expanduser(f"~/{raw}"))
    if os.path.exists(home_path):
        return home_path, None

    # 4. Matches recent workspace by directory name (case-insensitive)
    for item in load_workspace_history():
        p = item.get("path", "")
        n = item.get("name", "")
        if (n.lower() == raw.lower() or os.path.basename(p).lower() == raw.lower()) and os.path.isdir(p):
            return p, None

    # If it was an absolute path that didn't exist, report it
    if os.path.isabs(expanded):
        return None, expanded

    return None, rel_path
