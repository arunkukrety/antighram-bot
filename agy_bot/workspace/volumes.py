"""
System volume and external drive detection + markup building.
"""

import html
import json
import os
import subprocess
from typing import List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from agy_bot.config import log
from agy_bot.workspace.browse_token import get_browse_token
from agy_bot.workspace.resolver import get_default_workspace


def find_system_volumes() -> List[dict]:
    """
    Detects external/secondary drives, removable devices, and non-root volumes
    (e.g., /run/media/$USER/*, /media/*, /mnt/*, and NTFS/FAT partitions).
    """
    volumes = []
    seen_paths = set()

    user = os.environ.get("USER", "arun")
    candidate_dirs = [
        f"/run/media/{user}",
        f"/media/{user}",
        "/run/media",
        "/media",
        "/mnt",
    ]

    for cdir in candidate_dirs:
        if os.path.isdir(cdir):
            try:
                for entry in os.scandir(cdir):
                    if entry.is_dir(follow_symlinks=True):
                        p = os.path.abspath(entry.path)
                        if (
                            p in seen_paths
                            or p in (
                                f"/run/media/{user}",
                                f"/media/{user}",
                                "/run/media",
                                "/media",
                                "/mnt",
                            )
                        ):
                            continue
                        try:
                            os.listdir(p)
                            seen_paths.add(p)
                            volumes.append(
                                {
                                    "name": entry.name,
                                    "path": p,
                                    "device": None,
                                    "fstype": "mounted",
                                    "size": "",
                                    "mounted": True,
                                }
                            )
                        except Exception:
                            pass
            except Exception:
                pass

    try:
        out = subprocess.check_output(
            [
                "lsblk",
                "-J",
                "-o",
                "NAME,PATH,MOUNTPOINT,FSTYPE,SIZE,LABEL",
            ],
            text=True,
            timeout=5,
        )
        data = json.loads(out)

        def process_dev(dev):
            name = dev.get("name") or ""
            dev_path = dev.get("path") or f"/dev/{name}"
            mp = dev.get("mountpoint")
            fstype = dev.get("fstype")
            size = dev.get("size", "")
            label = dev.get("label") or name

            if name.startswith("loop") or (
                mp and mp.startswith("/snap")
            ):
                return
            if mp in (
                "/",
                "/boot",
                "/boot/efi",
                "[SWAP]",
            ):
                return

            if mp:
                if mp not in seen_paths:
                    seen_paths.add(mp)
                    volumes.append(
                        {
                            "name": label or os.path.basename(mp),
                            "path": mp,
                            "device": dev_path,
                            "fstype": fstype or "",
                            "size": size,
                            "mounted": True,
                        }
                    )
                else:
                    for v in volumes:
                        if v.get("path") == mp:
                            v["device"] = dev_path
                            v["fstype"] = (
                                fstype
                                or v["fstype"]
                            )
                            v["size"] = size
                            if label and label != name:
                                v["name"] = label
            elif not mp and fstype and fstype not in ("swap",):
                volumes.append(
                    {
                        "name": label or name,
                        "path": None,
                        "device": dev_path,
                        "fstype": fstype,
                        "size": size,
                        "mounted": False,
                    }
                )

            for c in dev.get("children", []):
                process_dev(c)

        for d in data.get("blockdevices", []):
            process_dev(d)

    except Exception as exc:
        log.warning(
            "Could not query lsblk: %s",
            exc,
        )

    return volumes


def build_volumes_markup(
    sessions: dict,
    chat_id: Optional[int] = None,
) -> Tuple[str, InlineKeyboardMarkup]:

    vols = find_system_volumes()
    mounted = [v for v in vols if v["mounted"]]
    unmounted = [v for v in vols if not v["mounted"]]

    lines = [
        "💾 <b>Connected Volumes & Storage</b>\n",
        "External drives, media, and partitions not in root:\n",
    ]

    buttons = []

    if mounted:
        lines.append("<b>Mounted Volumes:</b>")
        for v in mounted:
            v_name = v["name"]
            v_path = v["path"]
            v_size = f" ({v['size']})" if v.get("size") else ""
            v_fs = f" • {v['fstype']}" if v.get("fstype") else ""
            lines.append(
                f"• <b>{html.escape(v_name)}</b>{v_size}{v_fs}\n"
                f"  <code>{html.escape(v_path)}</code>"
            )

            token = get_browse_token(v_path)
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"📂 Browse: {v_name[:18]}{v_size}",
                        callback_data=f"br:nav:{token}",
                    ),
                    InlineKeyboardButton(
                        "🎯 Set Active",
                        callback_data=f"br:sel:{token}",
                    ),
                ]
            )
        lines.append("")

    if unmounted:
        lines.append("<b>Available External / Unmounted Disks:</b>")
        for v in unmounted:
            dev = v.get("device") or ""
            label = v["name"]
            size = f" ({v['size']})" if v.get("size") else ""
            fs = f" • {v['fstype']}" if v.get("fstype") else ""
            lines.append(
                f"• <b>{html.escape(label)}</b>{size}{fs}\n"
                f"  <code>{html.escape(dev)}</code>"
            )

            dev_token = get_browse_token(dev)
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"🔌 Mount & Open: {label[:16]}{size}",
                        callback_data=f"br:mnt:{dev_token}",
                    )
                ]
            )
        lines.append("")

    if not mounted and not unmounted:
        lines.append(
            "<i>No external or secondary storage volumes detected.</i>\n"
        )

    session = sessions.get(chat_id) if chat_id else None
    back_target = (
        session.workspace
        if session
        else get_default_workspace()
    )
    back_token = get_browse_token(back_target)
    buttons.append(
        [
            InlineKeyboardButton(
                "📂 Return to File Browser",
                callback_data=f"br:nav:{back_token}",
            )
        ]
    )

    return "\n".join(lines), InlineKeyboardMarkup(buttons)
