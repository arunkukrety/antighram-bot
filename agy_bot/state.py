"""
agy_bot/state.py — Shared runtime state initialised at bot startup.

Lives here (rather than in main.py) so handler modules can use it
without importing main.py and creating a circular dependency.
"""

import os

from agy_bot.workspace.resolver import get_default_workspace

# Initialise default workspace on startup
DEFAULT_WORKSPACE = get_default_workspace()
os.makedirs(DEFAULT_WORKSPACE, exist_ok=True)
