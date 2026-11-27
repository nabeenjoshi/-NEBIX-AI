from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any


_CONTACT_INFO = "contact info"
_UNSAVED_MARKERS = {
    "add to contacts",
    "not in your contacts",
    "not a contact",
}
_POSITIVE_SIGNALS = {
    ("Text", "edit contact"),
    ("Button", "delete contact"),
}
_HEADER_ACTIONS = {
    "video call",
    "voice call",
    "search",
    "more",
    "more options",
}


def has_saved_contact_signal(controls: Iterable[tuple[str, str]]) -> bool:
    """Accept only explicit saved-contact controls on a Contact info surface."""
    normalized = {
        (control_type.strip(), name.strip().casefold())
        for control_type, name in controls
    }
    if ("Text", _CONTACT_INFO) not in normalized:
        return False
    if any(marker in name for _, name in normalized for marker in _UNSAVED_MARKERS):
        return False
    return any(signal in normalized for signal in _POSITIVE_SIGNALS)


def verify_current_whatsapp_contact(
    logger: Callable[[str], None] = print,
    *,
    expected_receiver: str | None = None,
    desktop_factory: Callable[..., Any] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, str]:
    """Verify the selected WhatsApp conversation using visible UIA evidence only."""
    logger("CHECKING WHATSAPP CONTACT STATUS")
    try:
        if desktop_factory is None:
            from pywinauto import Desktop

            desktop_factory = Desktop

        windows = [
            window
            for window in desktop_factory(backend="uia").windows()
            if window.window_text().strip().casefold() == "whatsapp"
            and window.is_visible()
        ]
        if len(windows) != 1:
            return _blocked(
                logger,
                "WhatsApp window is missing or ambiguous.",
            )

        window = windows[0]
        controls = _visible_controls(window)
        if not expected_receiver:
            return _blocked(logger, "The requested recipient is empty.")
        selected_header = _selected_header_identity(
            expected_receiver,
            controls,
        )
        if selected_header is None:
            return _blocked(
                logger,
                "The selected conversation header is missing or ambiguous.",
            )

        if not _has_contact_info(controls):
            return _blocked(
                logger,
                "The Contact info surface is not already visible; "
                "verification will not change WhatsApp state.",
            )

        if not has_saved_contact_signal(
            (control_type, name)
            for _, control_type, name in controls
        ):
            return _blocked(
                logger,
                "No positive saved-contact UI signal was found.",
            )

        composer = _find_message_composer(window, sleep)
        if composer is None:
            return _blocked(
                logger,
                "The WhatsApp message composer could not be identified.",
            )
        if not hasattr(composer, "has_focus") or not composer.has_focus():
            return _blocked(
                logger,
                "The message composer is not already focused; "
                "verification will not change focus.",
            )

        controls = _visible_controls(window)
        current_header = _selected_header_identity(
            expected_receiver,
            controls,
        )
        if current_header is None or current_header != selected_header:
            return _blocked(
                logger,
                "The selected conversation changed or could not be revalidated.",
            )
        if not has_saved_contact_signal(
            (control_type, name)
            for _, control_type, name in controls
        ):
            return _blocked(
                logger,
                "The saved-contact UI signal changed or could not be revalidated.",
            )
        current_composers = [
            control
            for control, control_type, name in controls
            if control_type == "Edit" and name.casefold() == "type a message"
        ]
        if (
            len(current_composers) != 1
            or _control_key(current_composers[0]) != _control_key(composer)
            or not current_composers[0].has_focus()
        ):
            return _blocked(
                logger,
                "The message composer changed or could not be revalidated.",
            )

        logger("CONTACT STATUS: SAVED")
        return True, "Saved contact verified."
    except Exception as exc:
        return _blocked(
            logger,
            f"UI Automation failed ({type(exc).__name__}).",
        )


def _visible_controls(window: Any) -> list[tuple[Any, str, str]]:
    controls = []
    seen: set[tuple[Any, ...]] = set()
    for control in window.descendants():
        info = control.element_info
        if not control.is_visible():
            continue
        control_type = str(info.control_type or "")
        name = control.window_text().strip()
        key = _control_key(control)
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        controls.append(
            (
                control,
                control_type,
                name,
            )
        )
    return controls


def _has_contact_info(controls: Iterable[tuple[Any, str, str]]) -> bool:
    return any(
        control_type == "Text" and name.casefold() == _CONTACT_INFO
        for _, control_type, name in controls
    )


def _find_message_composer(
    window: Any,
    sleep: Callable[[float], None],
) -> Any | None:
    for _ in range(20):
        matches = [
            control
            for control, control_type, name in _visible_controls(window)
            if control_type == "Edit" and name.casefold() == "type a message"
        ]
        if len(matches) == 1:
            return matches[0]
        sleep(0.1)
    return None


def _receiver_matches(
    expected_receiver: str,
    name: str,
) -> bool:
    expected = expected_receiver.strip().casefold()
    actual = name.strip().casefold()
    if expected and actual == expected:
        return True

    expected_digits = "".join(character for character in expected if character.isdigit())
    if len(expected_digits) < 7:
        return False
    actual_digits = "".join(
        character for character in actual if character.isdigit()
    )
    return actual_digits == expected_digits


def _selected_header_identity(
    expected_receiver: str,
    controls: list[tuple[Any, str, str]],
) -> tuple[tuple[Any, ...], tuple[Any, ...], str] | None:
    """Match only a unique title Button in the header's shared UIA Group."""
    chains: dict[tuple[Any, ...], list[tuple[tuple[Any, ...], str]]] = {}
    by_key: dict[tuple[Any, ...], tuple[Any, str, str]] = {}
    for control, control_type, name in controls:
        key = _control_key(control)
        if key is None:
            continue
        chain = _ancestor_chain(control)
        if chain is None:
            continue
        chains[key] = chain
        by_key[key] = (control, control_type, name)

    matches: set[tuple[tuple[Any, ...], tuple[Any, ...], str]] = set()
    for header_key, (_, group_type, _) in by_key.items():
        if group_type != "Group":
            continue
        direct_group_controls = []
        for key, record in by_key.items():
            chain = chains[key]
            nearest_group = next(
                (
                    ancestor_key
                    for ancestor_key, ancestor_type in chain
                    if ancestor_type == "Group"
                ),
                None,
            )
            if nearest_group == header_key:
                direct_group_controls.append((key, record[1], record[2]))

        profile_controls = [
            key
            for key, control_type, name in direct_group_controls
            if control_type == "Button" and "profile" in name.casefold()
        ]
        call_controls = [
            key
            for key, control_type, name in direct_group_controls
            if control_type == "Button"
            and name.casefold() in _HEADER_ACTIONS - {"more", "more options"}
        ]
        if len(profile_controls) != 1 or not call_controls:
            continue

        recipient_controls = [
            key
            for key, control_type, name in direct_group_controls
            if control_type == "Button"
            and name
            and name.casefold() not in {"back", *_HEADER_ACTIONS}
            and "profile" not in name.casefold()
            and _receiver_matches(expected_receiver, name)
        ]
        if len(recipient_controls) != 1:
            continue
        title_key = recipient_controls[0]
        matches.add(
            (
                header_key,
                title_key,
                by_key[title_key][2].strip().casefold(),
            )
        )
    return next(iter(matches)) if len(matches) == 1 else None


def _control_key(control: Any) -> tuple[Any, ...] | None:
    runtime_id = tuple(control.element_info.runtime_id or ())
    return runtime_id or None


def _ancestor_chain(
    control: Any,
) -> list[tuple[tuple[Any, ...], str]] | None:
    chain: list[tuple[tuple[Any, ...], str]] = []
    seen: set[tuple[Any, ...]] = set()
    current = control
    for _ in range(16):
        key = _control_key(current)
        if key is None:
            return None
        if key in seen:
            break
        seen.add(key)
        chain.append(
            (key, str(current.element_info.control_type or ""))
        )
        current = current.parent()
        if current is None:
            break
    return chain


def _blocked(
    logger: Callable[[str], None],
    reason: str,
) -> tuple[bool, str]:
    logger(f"CONTACT STATUS: UNVERIFIED — {reason} No WhatsApp message sent.")
    return False, reason
