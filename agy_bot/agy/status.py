"""
Maps agy stream-json events to human-readable status strings.
"""

from typing import Optional


def status_from_event(
    event: dict,
) -> Optional[str]:

    event_type = event.get(
        "event"
    )

    if event_type == "init":

        return (
            "🚀 Starting agy…"
        )

    if event_type == "step_update":

        step = event.get(
            "step_update",
            {},
        )

        state = step.get(
            "state"
        )

        step_type = step.get(
            "step_type",
            "",
        )

        if state == "RUNNING":

            if step_type in (
                "user_input",
                "user",
            ):
                return (
                    "🧠 Processing your request…"
                )

            if step_type in (
                "agent_response",
                "response",
            ):
                return (
                    "✍️ Preparing the response…"
                )

            if step_type:

                readable = (
                    step_type
                    .replace(
                        "_",
                        " ",
                    )
                    .strip()
                    .capitalize()
                )

                return (
                    f"⚙️ {readable}…"
                )

            return (
                "🧠 Working…"
            )

        if state == "DONE":

            if step_type in (
                "user_input",
                "user",
            ):
                return (
                    "🔎 Working on it…"
                )

            if step_type in (
                "agent_response",
                "response",
            ):
                return (
                    "✍️ Finalizing response…"
                )

    if event_type == "result":

        return (
            "✅ Finished"
        )

    return None
