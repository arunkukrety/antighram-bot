"""
Maps agy stream-json events to human-readable status strings.
"""

import html
import os
from typing import Optional


def status_from_event(
    event: dict,
) -> Optional[str]:

    event_type = event.get("event")

    if event_type == "init":
        return "🚀 <b>Starting agy…</b>"

    if event_type == "step_update":
        step = event.get("step_update", {})
        state = step.get("state")
        step_type = step.get("step_type", "")

        # ------------------------------------------------------------
        # Active / Running steps (agy uses state == "ACTIVE")
        # ------------------------------------------------------------
        if state in ("ACTIVE", "RUNNING"):
            if step_type == "tool":
                tool_name = step.get("tool_name") or step.get("tool_info", {}).get("name") or ""
                params = step.get("tool_info", {}).get("parameters", {})

                if tool_name == "run_command":
                    cmd = params.get("CommandLine", "").strip()
                    if cmd:
                        short_cmd = cmd[:55] + ("…" if len(cmd) > 55 else "")
                        return f"⚡ <b>Running:</b> <code>{html.escape(short_cmd)}</code>"
                    return "⚡ <b>Running command…</b>"

                if tool_name in ("view_file", "read_file"):
                    path = params.get("AbsolutePath") or params.get("TargetFile") or ""
                    fname = os.path.basename(path) if path else ""
                    if fname:
                        return f"📖 <b>Reading:</b> <code>{html.escape(fname)}</code>"
                    return "📖 <b>Reading file…</b>"

                if tool_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
                    path = params.get("TargetFile") or ""
                    fname = os.path.basename(path) if path else ""
                    if fname:
                        return f"✏️ <b>Editing:</b> <code>{html.escape(fname)}</code>"
                    return "✏️ <b>Writing file…</b>"

                if tool_name in ("search_web", "grep_search"):
                    q = params.get("query") or params.get("Query") or ""
                    if q:
                        short_q = q[:40] + ("…" if len(q) > 40 else "")
                        return f"🔍 <b>Searching:</b> <i>{html.escape(short_q)}</i>"
                    return "🔍 <b>Searching…</b>"

                if tool_name:
                    readable = tool_name.replace("_", " ").strip().title()
                    return f"⚙️ <b>Tool:</b> {html.escape(readable)}…"

                return "⚙️ <b>Running tool…</b>"

            if step_type in ("user_input", "user"):
                return "🧠 <b>Processing your request…</b>"

            if step_type in ("agent_response", "response"):
                return "✍️ <b>Generating response…</b>"

            if step_type:
                readable = step_type.replace("_", " ").strip().title()
                return f"⚙️ <b>{html.escape(readable)}…</b>"

            return "🧠 <b>Working…</b>"

        # ------------------------------------------------------------
        # Step completed
        # ------------------------------------------------------------
        if state == "DONE":
            if step_type == "tool":
                tool_name = step.get("tool_name") or step.get("tool_info", {}).get("name") or ""
                if tool_name == "run_command":
                    return "⚡ <b>Command finished</b>"
                return None

            if step_type in ("user_input", "user"):
                return "🔎 <b>Analyzing request…</b>"

            if step_type in ("agent_response", "response"):
                return "✍️ <b>Finishing up…</b>"

        if state == "ERROR":
            if step_type == "tool":
                tool_name = step.get("tool_name") or ""
                return f"⚠️ <b>Tool error:</b> {html.escape(tool_name or 'command')}"

    if event_type == "result":
        return "✅ <b>Finished</b>"

    return None

