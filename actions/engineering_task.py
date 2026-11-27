from __future__ import annotations

from typing import Any


def engineering_task(
    parameters: dict[str, Any],
    player=None,
) -> str:
    request = str((parameters or {}).get("request") or "").strip()
    if not request:
        return "Please describe the project task or status question."

    agent = getattr(player, "engineering_agent", None)
    if agent is None:
        return "The shared engineering task engine is not available."

    result = agent.handle_text(request)
    if result is None:
        return (
            "The shared engineering task engine could not classify this request. "
            "No project operation was performed."
        )
    return str(result.get("message") or "The task returned no result text.")


TOOL = {
    "name": "engineering_task",
    "description": (
        "Route natural-language project scans, coding fixes, verification, project setup, "
        "VS Code extension installation, Windows software detection/installation, project "
        "opening in VS Code or Android Studio, and engineering task-status questions through "
        "NEBIX's shared task engine. It scans before scoped edits, asks for approval before "
        "source sharing, changes, software installs, and package installs, and verifies actual "
        "test/build results. Do not use this tool for Excel workbook operations; use "
        "excel_control for real workbooks."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "request": {
                "type": "STRING",
                "description": "The user's original engineering request, preserving its language and any project path.",
            },
        },
        "required": ["request"],
    },
    "handler": engineering_task,
}
