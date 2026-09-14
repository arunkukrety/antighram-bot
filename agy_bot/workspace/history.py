"""
Workspace history: load, save, remember, forget, get recent.
"""

import json
import os
import time
from typing import List

from agy_bot.config import log, WORKSPACE_HISTORY_FILE


def load_workspace_history() -> List[dict]:

    try:

        if not WORKSPACE_HISTORY_FILE.exists():
            return []

        with open(
            WORKSPACE_HISTORY_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception:

        log.exception(
            "Could not load workspace history"
        )

    return []


def save_workspace_history(
    history: List[dict],
):

    try:

        WORKSPACE_HISTORY_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        tmp = WORKSPACE_HISTORY_FILE.with_suffix(
            ".tmp"
        )

        with open(
            tmp,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                history[:30],
                f,
                indent=2,
            )

        tmp.replace(
            WORKSPACE_HISTORY_FILE
        )

    except Exception:

        log.exception(
            "Could not save workspace history"
        )


def remember_workspace(
    workspace: str,
):

    workspace = os.path.abspath(
        os.path.expanduser(
            workspace
        )
    )

    history = load_workspace_history()

    # Remove existing entry.
    history = [
        item
        for item in history
        if item.get("path") != workspace
    ]

    history.insert(
        0,
        {
            "path": workspace,
            "name": os.path.basename(
                workspace.rstrip("/")
            ) or workspace,
            "last_used": int(
                time.time()
            ),
        },
    )

    save_workspace_history(
        history
    )


def forget_workspace(
    workspace: str,
):
    workspace = os.path.abspath(
        os.path.expanduser(workspace)
    )
    history = load_workspace_history()
    new_history = [
        item for item in history
        if item.get("path") != workspace
    ]
    save_workspace_history(new_history)


def get_recent_workspaces() -> List[dict]:
    history = load_workspace_history()
    valid = []
    cleaned = []
    modified = False

    for item in history:
        path = item.get("path")
        if not path:
            modified = True
            continue

        # Check if the workspace directory actually exists on disk
        if os.path.isdir(path):
            valid.append(item)
            cleaned.append(item)
        else:
            # Stale directory (e.g. deleted or /tmp wiped on reboot)
            modified = True

    if modified:
        save_workspace_history(cleaned)

    return valid[:20]
