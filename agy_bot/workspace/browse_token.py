"""
Browse token cache: short random tokens mapped to filesystem paths.
"""

import os
import secrets
from typing import Dict

BROWSE_CACHE: Dict[str, str] = {}


def get_browse_token(path: str) -> str:
    path = os.path.abspath(
        os.path.expanduser(path)
    )
    for token, p in list(
        BROWSE_CACHE.items()
    ):
        if p == path:
            return token
    if len(BROWSE_CACHE) > 500:
        BROWSE_CACHE.clear()
    token = secrets.token_hex(4)
    BROWSE_CACHE[token] = path
    return token
