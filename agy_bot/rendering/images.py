"""
Image detection, deduplication, and sending.
"""

import hashlib
import os
import re
import urllib.parse
from typing import List, Optional

from telegram.ext import Application
from telegram.constants import ParseMode

from agy_bot.rendering.markdown import markdown_to_html, format_footer
from agy_bot.rendering.text import split_text


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def get_image_file_hash(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read(1024 * 1024)).hexdigest()
    except Exception:
        return None


def find_involved_images(
    text_content: str,
    workspace: str,
    started_at: Optional[float] = None,
    conversation_id: Optional[str] = None,
    events: Optional[List[dict]] = None,
) -> List[str]:
    """
    Detect image / screenshot files produced or referenced during an agy run.
    Prioritizes explicit references in text/events, and falls back to
    filesystem scan only if nothing was explicitly referenced.
    Deduplicates images by canonical path AND content hash so duplicate
    copies in nested folders are never sent multiple times.
    """
    found_paths: List[str] = []
    seen_canonical = set()
    seen_hashes = set()

    def add_if_valid(candidate: str) -> bool:
        if not candidate:
            return False
        candidate = candidate.strip().strip("'\"`<>")
        if candidate.startswith("file://"):
            candidate = candidate[7:]
        candidate = urllib.parse.unquote(candidate)
        candidate = os.path.expanduser(candidate)

        if os.path.isabs(candidate):
            p = os.path.abspath(candidate)
        else:
            p = os.path.abspath(os.path.join(workspace, candidate))

        if os.path.isfile(p):
            ext = os.path.splitext(p)[1].lower()
            if ext in IMAGE_EXTENSIONS:
                try:
                    if os.path.getsize(p) > 0:
                        real = os.path.realpath(p)
                        if real not in seen_canonical:
                            fhash = get_image_file_hash(real)
                            if fhash and fhash in seen_hashes:
                                return False
                            if fhash:
                                seen_hashes.add(fhash)
                            seen_canonical.add(real)
                            found_paths.append(real)
                            return True
                except OSError:
                    pass
        return False

    # 1. Regex for markdown images and links
    md_matches = re.findall(r'!\[.*?\]\((?:file://)?([^\s\)]+)\)', text_content or "")
    for m in md_matches:
        add_if_valid(m)

    link_matches = re.findall(r'\[.*?\]\((?:file://)?([^\s\)]+\.(?:png|jpg|jpeg|webp|gif))\)', text_content or "", re.IGNORECASE)
    for m in link_matches:
        add_if_valid(m)

    # 2. General path mentions in text
    path_matches = re.findall(r'(?:file://)?([a-zA-Z0-9_\-\.\\/~]+\.(?:png|jpg|jpeg|webp|gif))', text_content or "", re.IGNORECASE)
    for m in path_matches:
        add_if_valid(m)

    # 3. Tool events inspection
    if events:
        def scan_obj(obj):
            if isinstance(obj, str):
                for match in re.findall(r'(?:file://)?([a-zA-Z0-9_\-\.\\/~]+\.(?:png|jpg|jpeg|webp|gif))', obj, re.IGNORECASE):
                    add_if_valid(match)
            elif isinstance(obj, dict):
                for v in obj.values():
                    scan_obj(v)
            elif isinstance(obj, list):
                for v in obj:
                    scan_obj(v)

        for ev in events:
            scan_obj(ev)

    # If explicit images were found in the text response or tool events, return them immediately.
    # This prevents scouring the disk and sending duplicate copies or intermediate debug screenshots.
    if found_paths:
        return found_paths

    # 4. Fallback: Check for newly created images on disk (only if nothing was explicitly mentioned in text)
    if started_at is not None:
        threshold = started_at - 3.0
        dirs_to_check = [workspace]

        if conversation_id:
            brain_conv_dir = os.path.expanduser(f"~/.gemini/antigravity-ide/brain/{conversation_id}")
            if os.path.isdir(brain_conv_dir):
                dirs_to_check.append(brain_conv_dir)

        for base_dir in dirs_to_check:
            if not os.path.isdir(base_dir):
                continue
            for root, dirs, files in os.walk(base_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", ".venv", "__pycache__")]
                rel_depth = os.path.relpath(root, base_dir).count(os.sep)
                if rel_depth > 3:
                    dirs.clear()

                for fname in files:
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in IMAGE_EXTENSIONS:
                        fpath = os.path.join(root, fname)
                        try:
                            if os.path.getmtime(fpath) >= threshold:
                                add_if_valid(fpath)
                        except OSError:
                            pass

    return found_paths


import asyncio
from telegram import error as tg_error

async def send_images(
    app: Application,
    chat_id: int,
    image_paths: List[str],
):
    from agy_bot.config import log

    for img_path in image_paths:
        if not os.path.exists(img_path):
            continue

        basename = os.path.basename(img_path)
        max_retries = 3

        for attempt in range(max_retries):
            try:
                size = os.path.getsize(img_path)
                if size <= 10 * 1024 * 1024:
                    with open(img_path, "rb") as f:
                        await app.bot.send_photo(
                            chat_id=chat_id,
                            photo=f,
                            caption=basename,
                        )
                else:
                    with open(img_path, "rb") as f:
                        await app.bot.send_document(
                            chat_id=chat_id,
                            document=f,
                            caption=f"{basename} (full resolution)",
                        )
                break
            except tg_error.RetryAfter as exc:
                log.warning("Rate limited sending image %s; sleeping %s s", img_path, exc.retry_after)
                await asyncio.sleep(exc.retry_after + 0.5)
            except (tg_error.TimedOut, tg_error.NetworkError) as exc:
                if attempt < max_retries - 1:
                    backoff = 2.0 * (attempt + 1)
                    log.warning(
                        "Transient error sending image %s (%s); retrying in %.1fs (attempt %d/%d)",
                        img_path,
                        exc,
                        backoff,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(backoff)
                else:
                    log.warning("Could not send image %s after %d attempts: %s", img_path, max_retries, exc)
            except Exception as exc:
                log.warning("Could not send image %s: %s", img_path, exc)
                break


async def send_final_response(
    app: Application,
    chat_id: int,
    response: str,
    model: Optional[str],
    duration: Optional[float],
    images: Optional[List[str]] = None,
):
    from agy_bot.rendering.markdown import response_html
    from agy_bot.config import log

    chunks = split_text(
        response.strip(),
        3500,
    )

    async def _safe_send(formatted_html: str, raw_text: str):
        html_sent = False
        max_retries = 3

        for attempt in range(max_retries):
            try:
                await app.bot.send_message(
                    chat_id,
                    formatted_html,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                html_sent = True
                break
            except tg_error.RetryAfter as exc:
                log.warning("Rate limited sending HTML message; sleeping %s s", exc.retry_after)
                await asyncio.sleep(exc.retry_after + 0.5)
            except (tg_error.TimedOut, tg_error.NetworkError) as exc:
                if attempt < max_retries - 1:
                    backoff = 1.5 * (attempt + 1)
                    log.warning(
                        "Telegram HTML send transient network error (%s); retrying in %.1fs (attempt %d/%d)",
                        exc,
                        backoff,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(backoff)
                else:
                    log.warning(
                        "Telegram HTML send timed out/failed after %d attempts (%s); falling back to plain text",
                        max_retries,
                        exc,
                    )
                    break
            except tg_error.BadRequest as exc:
                log.warning("Telegram HTML parse/formatting error (%s); falling back to plain text", exc)
                break
            except Exception as exc:
                log.warning("Telegram HTML send unexpected error (%s); falling back to plain text", exc)
                break

        if html_sent:
            return

        for attempt in range(max_retries):
            try:
                await app.bot.send_message(
                    chat_id,
                    raw_text,
                    parse_mode=None,
                    disable_web_page_preview=True,
                )
                return
            except tg_error.RetryAfter as exc:
                log.warning("Rate limited sending plain text message; sleeping %s s", exc.retry_after)
                await asyncio.sleep(exc.retry_after + 0.5)
            except (tg_error.TimedOut, tg_error.NetworkError) as exc:
                if attempt < max_retries - 1:
                    backoff = 1.5 * (attempt + 1)
                    log.warning(
                        "Telegram plain text send transient network error (%s); retrying in %.1fs (attempt %d/%d)",
                        exc,
                        backoff,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(backoff)
                else:
                    log.error(
                        "Telegram plain text send failed after %d attempts: %s",
                        max_retries,
                        exc,
                    )
                    raise
            except Exception as exc:
                log.error("Telegram plain text send failed: %s", exc)
                raise

    # Normal case.
    if len(chunks) == 1:
        formatted = response_html(
            response,
            model,
            duration,
        )

        raw_with_footer = response.strip()
        if model or duration:
            footer = f"\n\n— {model or 'default'}"
            if duration:
                footer += f" ({duration:.1f}s)"
            raw_with_footer += footer

        await _safe_send(formatted, raw_with_footer)
        if images:
            await send_images(app, chat_id, images)
        return

    # Long response.
    for index, chunk in enumerate(chunks):
        formatted = markdown_to_html(chunk)
        raw_chunk = chunk

        if index == len(chunks) - 1:
            formatted += (
                "\n\n"
                + format_footer(model, duration)
            )
            if model or duration:
                raw_chunk += f"\n\n— {model or 'default'}"
                if duration:
                    raw_chunk += f" ({duration:.1f}s)"

        await _safe_send(formatted, raw_chunk)

    if images:
        await send_images(app, chat_id, images)

