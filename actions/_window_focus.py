from __future__ import annotations

import ctypes
import time


_TARGET_ATTRIBUTE = "_nebix_recent_open_window"
_TARGET_MAX_AGE_SECONDS = 120.0


def remember_open_window(player, title: str) -> None:
    if player is not None:
        setattr(player, _TARGET_ATTRIBUTE, (title, time.monotonic(), None))


def remember_unavailable_window(player, title: str, reason: str) -> None:
    if player is not None:
        setattr(player, _TARGET_ATTRIBUTE, (title, time.monotonic(), reason))


def resolve_target_window(player, requested: str | None = None) -> str | None:
    stored = getattr(player, _TARGET_ATTRIBUTE, None) if player is not None else None
    if player is not None and hasattr(player, _TARGET_ATTRIBUTE):
        delattr(player, _TARGET_ATTRIBUTE)

    if isinstance(requested, str) and requested.strip():
        return requested.strip()
    if (
        isinstance(stored, tuple)
        and len(stored) == 3
        and isinstance(stored[0], str)
    ):
        if time.monotonic() - stored[1] > _TARGET_MAX_AGE_SECONDS:
            raise RuntimeError(
                f"The target window '{stored[0]}' expired before typing; open the app again."
            )
        if stored[2]:
            raise RuntimeError(
                f"The last opened app window '{stored[0]}' was not verified: {stored[2]}"
            )
        return stored[0]
    return None


def _matching_window(title: str, timeout: float):
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("Window targeting requires pywinauto on Windows.") from exc

    deadline = time.monotonic() + timeout
    while True:
        matches = []
        for window in Desktop(backend="win32").windows():
            try:
                window_title = window.window_text().strip()
                if window.is_visible() and title.casefold() in window_title.casefold():
                    matches.append(window)
            except (RuntimeError, OSError):
                continue

        if matches:
            exact_matches = [
                window
                for window in matches
                if window.window_text().strip().casefold() == title.casefold()
            ]
            candidates = exact_matches or matches
            foreground = _foreground_window()
            foreground_matches = [
                window for window in candidates if window.handle == foreground
            ]
            if foreground_matches:
                return foreground_matches[0]
            if len(candidates) == 1:
                return candidates[0]
            raise RuntimeError(
                f"More than one window matches '{title}'; specify a more exact window title."
            )
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)

    raise RuntimeError(f"No visible window matching '{title}' appeared.")


def _foreground_window() -> int:
    return ctypes.windll.user32.GetForegroundWindow()


def activate_window(title: str, timeout: float = 2.0) -> str:
    target = _matching_window(title, timeout)
    try:
        target.restore()
        target.set_focus()
    except (RuntimeError, OSError) as exc:
        raise RuntimeError(f"Could not activate '{target.window_text()}': {exc}") from exc

    if _foreground_window() != target.handle:
        raise RuntimeError(
            f"Could not verify '{target.window_text()}' as the foreground window."
        )
    return target.window_text().strip()


def activate_target_window(player, requested: str | None = None) -> str | None:
    title = resolve_target_window(player, requested)
    if title is None:
        return None
    return activate_window(title)


def wait_and_activate_application(
    app_name: str,
    player=None,
    *,
    timeout: float = 10.0,
) -> str:
    hint = app_name.strip()
    if hint.casefold().endswith(".exe"):
        hint = hint[:-4]
    try:
        title = activate_window(hint, timeout)
    except Exception as exc:
        raise RuntimeError(
            f"Could not resolve or activate the '{hint}' window "
            f"({type(exc).__name__}: {exc})."
        ) from exc
    remember_open_window(player, title)
    return title
