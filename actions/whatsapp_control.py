from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

_WHATSAPP_PROCESS_NAMES = {"whatsapp.exe", "whatsapp.root.exe"}
_VOICE_CALL_NAMES = {"voice call", "audio call"}
_ACTIVE_CALL_SIGNALS = {
    "cancel call",
    "end call",
    "end voice call",
    "hang up",
    "in call",
    "calling",
    "connecting",
    "ringing",
}


def _inspect_whatsapp(
    *,
    process_iter: Callable[..., Any] | None = None,
    desktop_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    process_ids: set[int] = set()
    process_names: set[str] = set()
    try:
        if process_iter is None:
            import psutil

            process_iter = psutil.process_iter
        for process in process_iter(["pid", "name"]):
            info = process.info
            name = str(info.get("name") or "").strip()
            if name.casefold() in _WHATSAPP_PROCESS_NAMES:
                process_names.add(name)
                pid = info.get("pid")
                if isinstance(pid, int):
                    process_ids.add(pid)
    except Exception as exc:
        return {
            "running": False,
            "window": None,
            "controls": [],
            "error": (
                "WhatsApp process detection failed "
                f"({type(exc).__name__}: {exc})."
            ),
        }

    try:
        if desktop_factory is None:
            from pywinauto import Desktop

            desktop_factory = Desktop
        windows = desktop_factory(backend="uia").windows()
        matching_windows = []
        for window in windows:
            if not window.is_visible():
                continue
            title = window.window_text().strip()
            title_matches = "whatsapp" in title.casefold()
            try:
                process_matches = window.process_id() in process_ids
            except Exception:
                process_matches = False
            if title_matches or process_matches:
                matching_windows.append(window)
    except Exception as exc:
        return {
            "running": bool(process_names),
            "window": None,
            "controls": [],
            "error": (
                "WhatsApp UI Automation inspection failed "
                f"({type(exc).__name__}: {exc})."
            ),
        }

    running = bool(process_names or matching_windows)
    if len(matching_windows) != 1:
        return {
            "running": running,
            "window": None,
            "controls": [],
            "error": (
                "No visible WhatsApp window is exposed through UI Automation."
                if not matching_windows
                else "Multiple visible WhatsApp windows make the target ambiguous."
            ),
        }

    try:
        from actions.whatsapp_guard import _visible_controls

        window = matching_windows[0]
        controls = _visible_controls(window)
    except Exception as exc:
        return {
            "running": running,
            "window": None,
            "controls": [],
            "error": (
                "WhatsApp UI Automation controls could not be read "
                f"({type(exc).__name__}: {exc})."
            ),
        }
    return {
        "running": running,
        "window": window,
        "controls": controls,
        "error": "",
    }


def _voice_call_controls(
    controls: list[tuple[Any, str, str]],
) -> list[Any]:
    return [
        control
        for control, control_type, name in controls
        if control_type == "Button"
        and name.strip().casefold() in _VOICE_CALL_NAMES
        and control.is_enabled()
    ]


def _status_result(state: dict[str, Any]) -> str:
    if state["error"]:
        process_status = (
            "unknown"
            if state["error"].startswith("WhatsApp process detection failed")
            else "running" if state["running"] else "not detected"
        )
        return (
            f"WhatsApp Desktop process: {process_status}. "
            f"UI Automation: unavailable. {state['error']}"
        )

    voice_call_controls = _voice_call_controls(state["controls"])
    if len(voice_call_controls) == 1:
        call_status = "one enabled voice-call control is accessible"
    elif voice_call_controls:
        call_status = "multiple enabled voice-call controls are ambiguous"
    else:
        call_status = "no enabled voice-call control is accessible in the current view"
    return (
        "WhatsApp Desktop process: running. UI Automation: accessible; "
        f"{call_status}."
    )


def _active_call_visible(controls: list[tuple[Any, str, str]]) -> bool:
    return any(
        name.strip().casefold() in _ACTIVE_CALL_SIGNALS
        and control_type in {"Button", "Text", "StatusBar"}
        for _, control_type, name in controls
    )


def _select_contact(receiver: str) -> None:
    import pyautogui

    from actions.send_message import _search_in_app

    _search_in_app(receiver)
    pyautogui.press("enter")
    time.sleep(0.8)


def _perform_call(
    receiver: str,
    *,
    logger: Callable[[str], None] = print,
    inspect: Callable[[], dict[str, Any]] | None = None,
    select_contact: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    from actions.open_app import open_app
    from actions.whatsapp_guard import _control_key, _selected_header_identity

    if inspect is None:
        inspect = _inspect_whatsapp
    if select_contact is None:
        select_contact = _select_contact

    state = inspect()
    needs_launch_or_focus = (
        not state["running"] and not state["error"]
    ) or "No visible WhatsApp window" in state["error"]
    if needs_launch_or_focus:
        launch_result = open_app({"app_name": "WhatsApp"})
        if (
            not launch_result.startswith("Opened WhatsApp")
            and not state["running"]
        ):
            return (
                "WhatsApp call not started: WhatsApp Desktop is not running, "
                f"and the existing application-launch action did not confirm "
                f"opening it ({launch_result})."
            )
        for _ in range(20):
            sleep(0.5)
            state = inspect()
            if (
                state["window"] is not None
                or state["error"]
                and "No visible WhatsApp window" not in state["error"]
            ):
                break

    if state["error"]:
        return f"WhatsApp call not started: {state['error']}"
    if state["window"] is None:
        return (
            "WhatsApp call not started: WhatsApp Desktop has no visible "
            "UI Automation window."
        )

    try:
        state["window"].set_focus()
        select_contact(receiver)
    except Exception as exc:
        logger(f"[WhatsApp] Contact selection failed: {type(exc).__name__}: {exc}")
        return (
            "WhatsApp call not started: the requested contact could not be "
            "selected through the existing controls "
            f"({type(exc).__name__}: {str(exc)[:180]})."
        )

    state = inspect()
    if state["error"] or state["window"] is None:
        reason = state["error"] or "The visible WhatsApp window disappeared."
        return f"WhatsApp call not started: {reason}"
    identity = _selected_header_identity(receiver, state["controls"])
    if identity is None:
        return (
            "WhatsApp call not started: UI Automation could not verify that "
            "the requested contact is the selected conversation."
        )

    controls = _voice_call_controls(state["controls"])
    if len(controls) != 1:
        return (
            "WhatsApp call not started: UI Automation found "
            f"{len(controls)} enabled voice-call controls; exactly one is required."
        )

    selected_control_key = _control_key(controls[0])
    state = inspect()
    if state["error"] or state["window"] is None:
        reason = state["error"] or "The visible WhatsApp window disappeared."
        return f"WhatsApp call not started: {reason}"
    if _selected_header_identity(receiver, state["controls"]) != identity:
        return (
            "WhatsApp call not started: the selected conversation changed "
            "or could not be revalidated."
        )
    controls = _voice_call_controls(state["controls"])
    if (
        len(controls) != 1
        or selected_control_key is None
        or _control_key(controls[0]) != selected_control_key
    ):
        return (
            "WhatsApp call not started: the verified voice-call control "
            "changed or could not be revalidated."
        )

    try:
        controls[0].click_input()
    except Exception as exc:
        logger(f"[WhatsApp] Voice-call control failed: {type(exc).__name__}: {exc}")
        return (
            "WhatsApp call not started: the verified voice-call control "
            f"could not be activated ({type(exc).__name__}: {str(exc)[:180]})."
        )

    for _ in range(12):
        sleep(0.5)
        state = inspect()
        if state["error"] or state["window"] is None:
            continue
        if _active_call_visible(state["controls"]):
            return (
                f"WhatsApp call to {receiver} initiated; an active-call "
                "control is visible."
            )
    return (
        f"WhatsApp's voice-call control was activated for {receiver}, but no "
        "active-call indicator became accessible. The call could not be verified."
    )


def whatsapp_control(
    parameters: dict[str, Any] | None = None,
    player: Any = None,
) -> str:
    params = parameters or {}
    action = str(params.get("action") or "").strip().casefold()
    if action == "status":
        result = _status_result(_inspect_whatsapp())
    elif action == "call":
        receiver = str(params.get("contact") or "").strip()
        if not receiver:
            return "WhatsApp call not started: a contact name or number is required."
        result = _perform_call(
            receiver,
            logger=(lambda _message: player.write_log("[WhatsApp] Call workflow progress; contact details redacted.")) if player else (lambda _message: None),
        )
    else:
        return "WhatsApp control action must be 'status' or 'call'."

    if player:
        player.write_log("[WhatsApp] Call workflow completed; contact details redacted." if action == "call" else "[WhatsApp] Status inspected.")
    return result


TOOL = {
    "name": "whatsapp_control",
    "description": (
        "Inspect WhatsApp Desktop's running state and accessible UI Automation "
        "controls, or initiate a verified voice call. For a call, first use "
        "action='status'; use action='call' only with the requested contact. "
        "A call is not reported as initiated unless the selected contact, "
        "voice-call control, and subsequent active-call indicator are verified."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "status | call",
            },
            "contact": {
                "type": "STRING",
                "description": "WhatsApp contact name or phone number for action=call",
            },
        },
        "required": ["action"],
    },
    "handler": whatsapp_control,
}
