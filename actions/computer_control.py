#computer_control.py
import io
import json
import platform
import re
import string
import subprocess
import sys
import threading

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}
import time
import random
from pathlib import Path
from core.paths import get_config_file, get_memory_file, load_api_config
from core.windows_display import image_point_to_desktop, virtual_screen_bounds
from actions._window_focus import activate_target_window

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE    = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_CONFIG_PATH  = get_config_file()
_MEMORY_PATH  = get_memory_file()
_CONTROL_LOCK = threading.Lock()

def _load_config() -> dict:
    try:
        return load_api_config(_CONFIG_PATH)
    except Exception:
        return {}

def _platform_os() -> str:
    return {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(
        platform.system(), "linux"
    )

def _get_os() -> str:
    return _load_config().get("os_system", _platform_os()).lower()


def _get_api_key() -> str:
    return _load_config().get("gemini_api_key", "")

def _require_pyautogui():
    if not _PYAUTOGUI:
        raise RuntimeError("PyAutoGUI not installed. Run: pip install pyautogui")

_FIRST_NAMES = [
    "NEBIX", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper",
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson",
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def _random_data(data_type: str) -> str:
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    if dt == "last_name":
        return random.choice(_LAST_NAMES)

    if dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    if dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    if dt == "username":
        return f"{random.choice(_FIRST_NAMES).lower()}{random.randint(100, 9999)}"

    if dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        raw   = (
            random.choice(string.ascii_uppercase)
            + random.choice(string.digits)
            + random.choice("!@#$%")
            + "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(raw, len(raw)))

    if dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1_000_000, 9_999_999)}"

    if dt == "birthday":
        y = random.randint(1980, 2000)
        m = random.randint(1, 12)
        d = random.randint(1, 28)
        return f"{m:02d}/{d:02d}/{y}"

    if dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    if dt == "zip_code":
        return str(random.randint(10000, 99999))

    if dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000, 9999)}"

def _user_profile() -> dict:
    """Read identity fields from long-term memory."""
    try:
        if _MEMORY_PATH.exists():
            data     = json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {k: v.get("value", "") for k, v in identity.items()}
    except Exception:
        pass
    return {}

def _type(
    text: str,
    interval: float = 0.03,
    *,
    player=None,
    target_window: str | None = None,
) -> str:
    _require_pyautogui()
    activate_target_window(player, target_window)
    pyautogui.typewrite(text, interval=interval)
    return f"Typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _smart_type(
    text: str,
    clear_first: bool = True,
    *,
    player=None,
    target_window: str | None = None,
    cancel_event=None,
) -> str:
    _require_pyautogui()
    text = str(text or "")
    _check_cancel_event(cancel_event)
    target = activate_target_window(player, target_window)
    if clear_first:
        _clear_field()
        _check_cancel_event(cancel_event)
        time.sleep(0.1)
        if target:
            activate_target_window(player, target)

    if (len(text) > 20 or not text.isascii()) and _PYPERCLIP:
        _paste_with_clipboard(
            text, player=player, target_window=target, cancel_event=cancel_event
        )
        _check_cancel_event(cancel_event)
        return f"Smart-typed (clipboard): {text[:60]}{'…' if len(text) > 60 else ''}"

    if not text.isascii():
        raise RuntimeError("Unicode typing requires pyperclip and Clipboard access.")
    for offset in range(0, len(text), 24):
        _check_cancel_event(cancel_event)
        pyautogui.write(text[offset:offset + 24], interval=0.04)
    _check_cancel_event(cancel_event)
    return f"Smart-typed: {text[:60]}{'…' if len(text) > 60 else ''}"


def _check_cancel_event(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("Computer action was cancelled.")


def _require_clipboard_permission(player) -> None:
    if player is None:
        raise PermissionError("Clipboard access permission is required for paste-based typing.")
    from core.permissions import permission_is_enabled

    settings = getattr(player, "settings", {})
    permissions = settings.get("permissions") if isinstance(settings, dict) else None
    if not permission_is_enabled(permissions, "clipboard_access"):
        raise PermissionError("Clipboard access is disabled in NEBIX Settings.")


def _paste_with_clipboard(
    text: str,
    *,
    player=None,
    target_window: str | None = None,
    cancel_event=None,
) -> None:
    """Paste text while restoring the user's prior clipboard contents."""
    if not _PYPERCLIP:
        raise RuntimeError("pyperclip is required for Unicode or long-text paste.")
    _require_clipboard_permission(player)
    _require_pyautogui()
    if target_window:
        activate_target_window(player, target_window)

    previous_clipboard = pyperclip.paste()
    paste_key = "command" if _get_os() == "mac" else "ctrl"
    try:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Computer action was cancelled.")
        pyperclip.copy(text)
        pyautogui.hotkey(paste_key, "v")
        # Allow the focused application to read the clipboard before restoring it.
        time.sleep(0.15)
    finally:
        pyperclip.copy(previous_clipboard)


def _screen_point(x, y) -> tuple[int, int]:
    """Validate physical screen coordinates before issuing OS input."""
    _require_pyautogui()
    if x is None or y is None:
        raise ValueError("Both x and y screen coordinates are required.")
    point = (int(x), int(y))
    left, top, width, height = virtual_screen_bounds()
    if not (left <= point[0] < left + width and top <= point[1] < top + height):
        raise ValueError(
            "Coordinates must be inside the virtual desktop "
            f"({left},{top} to {left + width - 1},{top + height - 1})."
        )
    return point


def _click(x=None, y=None, button: str = "left", clicks: int = 1) -> str:
    _require_pyautogui()
    if (x is None) != (y is None):
        raise ValueError("Both x and y coordinates must be supplied together.")
    if x is not None:
        x, y = _screen_point(x, y)
        pyautogui.click(x, y, button=button, clicks=clicks)
        return f"{'Double-c' if clicks == 2 else 'C'}licked ({x}, {y}) [{button}]"
    pyautogui.click(button=button, clicks=clicks)
    return f"Clicked at current position [{button}]"


def _hotkey(*keys, cancel_event=None) -> str:
    _require_pyautogui()
    if not keys:
        raise ValueError("At least one key is required for a hotkey.")
    pressed = []
    normalized = []
    try:
        for value in keys:
            _check_cancel_event(cancel_event)
            key = str(value or "").strip().casefold()
            if not key:
                raise ValueError("Hotkey key names cannot be empty.")
            normalized.append(key)
            pressed.append(key)
            pyautogui.keyDown(key)
        for key in reversed(pressed.copy()):
            _check_cancel_event(cancel_event)
            pyautogui.keyUp(key)
            pressed.remove(key)
    finally:
        for key in reversed(pressed):
            try:
                pyautogui.keyUp(key)
            except Exception:
                pass
    return f"Hotkey: {'+'.join(normalized)}"


def _press(key: str) -> str:
    _require_pyautogui()
    key = str(key or "enter").strip().casefold()
    if not key:
        raise ValueError("A key name is required.")
    try:
        pyautogui.keyDown(key)
    finally:
        pyautogui.keyUp(key)
    return f"Pressed: {key}"


def _hold_key(key: str, seconds: float = 0.2, cancel_event=None) -> str:
    """Hold one key for a bounded interval and release it even on cancellation."""
    _require_pyautogui()
    key = str(key or "").strip().casefold()
    if not key:
        raise ValueError("A key name is required.")
    seconds = max(0.01, min(float(seconds), 5.0))
    _check_cancel_event(cancel_event)
    pyautogui.keyDown(key)
    try:
        if cancel_event is not None:
            if cancel_event.wait(seconds):
                raise InterruptedError("Computer action was cancelled.")
        else:
            time.sleep(seconds)
        _check_cancel_event(cancel_event)
    finally:
        pyautogui.keyUp(key)
    return f"Held and released: {key}"


def _scroll(direction: str = "down", amount: int = 3) -> str:
    if direction not in {"up", "down", "left", "right"}:
        raise ValueError("Scroll direction must be up, down, left, or right.")
    amount = max(1, min(abs(int(amount)), 20))
    _require_pyautogui()
    vertical   = direction in ("up", "down")
    clicks     = amount if direction in ("up", "right") else -amount
    pyautogui.scroll(clicks) if vertical else pyautogui.hscroll(clicks)
    return f"Scrolled {direction} ×{amount}"


def _move(x: int, y: int, duration: float = 0.3, cancel_event=None) -> str:
    _require_pyautogui()
    x, y = _screen_point(x, y)
    duration = max(0.0, min(float(duration), 0.75))
    start_x, start_y = pyautogui.position()
    steps = max(1, min(20, int(duration / 0.025)))
    for step in range(1, steps + 1):
        _check_cancel_event(cancel_event)
        fraction = step / steps
        pyautogui.moveTo(
            round(start_x + (x - start_x) * fraction),
            round(start_y + (y - start_y) * fraction),
            duration=duration / steps if duration else 0,
            _pause=False,
        )
    _check_cancel_event(cancel_event)
    return f"Mouse → ({x}, {y})"


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5, cancel_event=None) -> str:
    _require_pyautogui()
    x1, y1 = _screen_point(x1, y1)
    x2, y2 = _screen_point(x2, y2)
    try:
        pyautogui.moveTo(x1, y1, duration=0.15)
        _check_cancel_event(cancel_event)
        pyautogui.mouseDown(button="left")
        steps = max(1, min(20, int(duration / 0.025)))
        for step in range(1, steps + 1):
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Computer action was cancelled.")
            fraction = step / steps
            pyautogui.moveTo(
                round(x1 + (x2 - x1) * fraction),
                round(y1 + (y2 - y1) * fraction),
                duration=duration / steps,
                _pause=False,
            )
    finally:
        pyautogui.mouseUp(button="left")
    return f"Dragged ({x1},{y1}) → ({x2},{y2})"


def _clipboard_get() -> str:
    if _PYPERCLIP:
        return pyperclip.paste()
    _hotkey("ctrl", "c")
    time.sleep(0.2)
    return "(copied — pyperclip unavailable for read)"


def _clipboard_paste(text: str, player=None, cancel_event=None) -> str:
    text = str(text or "")
    if _PYPERCLIP:
        _paste_with_clipboard(
            str(text), player=player, cancel_event=cancel_event
        )
        return f"Pasted: {text[:60]}{'…' if len(text) > 60 else ''}"
    return "pyperclip not available"


def _clear_field() -> str:
    _require_pyautogui()
    select_key = "command" if _get_os() == "mac" else "ctrl"
    pyautogui.hotkey(select_key, "a")
    time.sleep(0.1)
    pyautogui.press("delete")
    return "Field cleared"

def _focus_window(title: str) -> str:
    os_name = _get_os()

    if os_name == "windows":
        try:
            if not str(title or "").strip():
                raise ValueError("A window title is required.")
            focused = activate_target_window(None, str(title))
            return f"Focused window: {focused}"
        except Exception as e:
            return f"focus_window (Windows) failed: {e}"

    if os_name == "mac":
        script = (
            f'tell application "System Events" to '
            f'set frontmost of (first process whose name contains "{title}") to true'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"focus_window (macOS) failed: {e}"

    if os_name == "linux":
        try:
            result = subprocess.run(
                ["wmctrl", "-a", title],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                time.sleep(0.3)
                return f"Focused window: {title}"
        except FileNotFoundError:
            pass
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", title, "windowactivate"],
                capture_output=True, timeout=5,
            )
            time.sleep(0.3)
            return f"Focused window: {title}"
        except FileNotFoundError:
            return "focus_window (Linux) requires wmctrl or xdotool"
        except Exception as e:
            return f"focus_window (Linux) failed: {e}"

    return f"focus_window: unknown OS '{os_name}'"

def _screen_find(description: str, player=None, cancel_event=None) -> tuple[int, int] | None:
    def permitted() -> bool:
        try:
            from core.permissions import permission_is_enabled
            state = getattr(player, "settings", {}).get("permissions")
            return (
                permission_is_enabled(state, "screen_observation")
                and permission_is_enabled(state, "network_access")
            )
        except (AttributeError, TypeError, ValueError):
            return False

    if not permitted():
        print("[ComputerControl] Screen Vision or Network Access is disabled.")
        return None
    api_key = _get_api_key()
    if not api_key:
        print("[ComputerControl] ⚠️ No API key for screen_find")
        return None

    try:
        from google import genai
        from google.genai import types as gtypes

        _require_pyautogui()
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Computer action was cancelled.")
        if not permitted():
            print("[ComputerControl] Screen permissions were revoked before capture.")
            return None
        from PIL import Image
        from actions.screen_processor import _capture_screen

        left, top, desktop_width, desktop_height = virtual_screen_bounds()
        image_bytes, _mime_type = _capture_screen()
        with Image.open(io.BytesIO(image_bytes)) as image:
            image_width, image_height = image.size
            image = image.convert("RGB")
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            image_bytes = buf.getvalue()

        if not permitted():
            print("[ComputerControl] Screen permissions were revoked before transmission.")
            return None
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("Computer action was cancelled.")

        client = genai.Client(
            api_key=api_key,
            http_options=gtypes.HttpOptions(api_version="v1beta"),
        )
        prompt = (
            f"This is a screenshot of the combined virtual desktop, resized to "
            f"{image_width}×{image_height} image pixels. The virtual desktop has "
            f"physical bounds left={left}, top={top}, width={desktop_width}, "
            f"height={desktop_height}. "
            f"Locate the UI element described as: '{description}'. "
            f"Reply with ONLY its center coordinates in this image as: x,y "
            f"If the element is not visible, reply: NOT_FOUND"
        )

        response = client.models.generate_content(
            model="gemini-flash-lite-latest",
            contents=[
                gtypes.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                prompt,
            ],
        )

        text = (response.text or "").strip()
        if "NOT_FOUND" in text.upper():
            return None

        match = re.search(r"(\d+)\s*,\s*(\d+)", text)
        if match:
            x, y = int(match.group(1)), int(match.group(2))
            if 0 <= x < image_width and 0 <= y < image_height:
                return image_point_to_desktop(
                    x,
                    y,
                    (image_width, image_height),
                    (left, top, desktop_width, desktop_height),
                )

    except Exception as e:
        print(f"[ComputerControl] ⚠️ screen_find failed: {type(e).__name__}")

    return None

def _computer_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    cancel_event=None,
) -> str:
    """
    Dispatch table for all computer control actions.

    parameters keys (all optional unless noted):
      action        : (required) one of the actions listed below
      text          : text to type or paste
      x, y          : screen coordinates
      button        : 'left' | 'right' (default: left)
      keys          : hotkey string, e.g. 'ctrl+c'
      key           : single key name, e.g. 'enter'
      direction     : 'up' | 'down' | 'left' | 'right'
      amount        : scroll amount (default: 3)
      seconds       : wait duration
      title         : window title fragment for focus_window
      description   : natural-language element description for screen_find/click
      type          : data type for random_data
      field         : memory field name for user_data
      clear_first   : bool, clear field before typing (default: true)
      path          : deprecated; screenshots are never saved by this action

    Actions:
      type          — type text at cursor
      smart_type    — clear field + type (clipboard-backed)
      click         — left click
      double_click  — double left click
      right_click   — right click
      move          — move mouse
      drag          — click-drag between two points
      hotkey        — key combination
      press         — single key
      hold_key      — hold one key briefly and always release it
      scroll        — scroll the wheel
      copy          — read clipboard
      paste         — write + paste clipboard
      screenshot    — request temporary screen capture through NEBIX vision
      wait          — sleep N seconds
      clear_field   — select-all + delete
      focus_window  — bring window to foreground
      screen_find   — AI element finder (returns x,y)
      screen_click  — AI element finder + click
      random_data   — generate fake form data
      user_data     — pull real data from memory
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    if not action:
        return "No action specified for computer_control."

    if player:
        player.write_log(f"[Computer] {action}")

    print(f"[ComputerControl] ▶ {action}")

    def check_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            if _PYAUTOGUI:
                try:
                    for button in ("left", "right", "middle"):
                        pyautogui.mouseUp(button=button)
                    for key in ("ctrl", "shift", "alt", "win"):
                        pyautogui.keyUp(key)
                except Exception:
                    pass
            raise InterruptedError("Computer action was cancelled.")

    try:
        check_cancelled()

        if action == "type":
            _require_pyautogui()
            target = activate_target_window(player, params.get("target_window"))
            text = str(params.get("text", ""))
            check_cancelled()
            if target:
                activate_target_window(player, target)
            if not text.isascii():
                _paste_with_clipboard(
                    text,
                    player=player,
                    target_window=target,
                    cancel_event=cancel_event,
                )
            else:
                for offset in range(0, len(text), 24):
                    check_cancelled()
                    if target:
                        activate_target_window(player, target)
                    pyautogui.write(text[offset:offset + 24], interval=0.03)
            check_cancelled()
            return f"Typed {len(text)} characters."

        if action == "smart_type":
            return _smart_type(
                params.get("text", ""),
                clear_first=params.get("clear_first", True),
                player=player,
                target_window=params.get("target_window"),
                cancel_event=cancel_event,
            )

        if action in ("click", "left_click"):
            return _click(params.get("x"), params.get("y"), "left", 1)

        if action == "double_click":
            return _click(params.get("x"), params.get("y"), "left", 2)

        if action == "right_click":
            return _click(params.get("x"), params.get("y"), "right", 1)

        if action == "move":
            return _move(
                params.get("x"),
                params.get("y"),
                duration=max(0.0, min(float(params.get("duration", 0.3)), 0.75)),
                cancel_event=cancel_event,
            )

        if action == "drag":
            duration = max(0.1, min(float(params.get("duration", 0.5)), 2.0))
            return _drag(
                params.get("x1"), params.get("y1"),
                params.get("x2"), params.get("y2"),
                duration=duration,
                cancel_event=cancel_event,
            )

        if action == "hotkey":
            raw  = params.get("keys", "")
            keys = [k.strip() for k in raw.split("+")] if isinstance(raw, str) else raw
            check_cancelled()
            result = _hotkey(*keys, cancel_event=cancel_event)
            check_cancelled()
            return result

        if action == "press":
            check_cancelled()
            result = _press(params.get("key", "enter"))
            check_cancelled()
            return result

        if action == "hold_key":
            return _hold_key(
                params.get("key", ""),
                params.get("seconds", 0.2),
                cancel_event=cancel_event,
            )

        if action == "scroll":
            return _scroll(
                direction=str(params.get("direction", "down")).casefold(),
                amount=max(1, min(abs(int(params.get("amount", 3))), 20)),
            )

        if action == "copy":
            return _clipboard_get()

        if action == "paste":
            return _clipboard_paste(
                params.get("text", ""), player=player, cancel_event=cancel_event
            )

        if action == "screenshot":
            return "Use screen_process for a temporary screen capture; screenshots are not saved to disk."

        if action == "screen_find":
            coords = _screen_find(params.get("description", ""), player, cancel_event)
            check_cancelled()
            return f"{coords[0]},{coords[1]}" if coords else "NOT_FOUND"

        if action == "screen_click":
            desc   = params.get("description", "")
            coords = _screen_find(desc, player, cancel_event)
            check_cancelled()
            if coords:
                if cancel_event is not None:
                    cancel_event.wait(0.2)
                else:
                    time.sleep(0.2)
                check_cancelled()
                _click(x=coords[0], y=coords[1])
                return f"Clicked '{desc}' at {coords}"
            return f"Element not found on screen: '{desc}'"

        if action == "wait":
            secs = max(0.0, min(float(params.get("seconds", 1.0)), 30.0))
            if cancel_event is not None:
                if cancel_event.wait(secs):
                    check_cancelled()
            else:
                time.sleep(secs)
            return f"Waited {secs}s"

        if action == "clear_field":
            return _clear_field()

        if action == "focus_window":
            return _focus_window(params.get("title", ""))

        if action == "random_data":
            dt     = params.get("type", "name")
            return _random_data(dt)

        if action == "user_data":
            field   = params.get("field", "name")
            profile = _user_profile()
            value   = profile.get(field, "")
            if not value:
                value = _random_data(field)
            return value

        return f"Unknown action: '{action}'"

    except Exception as e:
        if isinstance(e, InterruptedError):
            return str(e)
        print(f"[ComputerControl] ❌ {action}: {type(e).__name__}")
        return f"computer_control '{action}' failed: {type(e).__name__}."


def computer_control(parameters=None, response=None, player=None, session_memory=None, cancel_event=None) -> str:
    if not _CONTROL_LOCK.acquire(blocking=False):
        return "Another computer action is active; retry after it finishes."
    indicator_started = False
    try:
        action = str((parameters or {}).get("action", "")).strip().casefold()
        if action in {
            "type", "smart_type", "click", "left_click", "double_click",
            "right_click", "move", "drag", "hotkey", "press", "hold_key", "scroll",
            "copy", "paste", "clear_field", "focus_window", "screen_find",
            "screen_click",
        }:
            if platform.system() == "Windows":
                try:
                    from core.desktop_indicator import start_desktop_indicator

                    indicator_started = start_desktop_indicator()
                except Exception:
                    indicator_started = False
                if not indicator_started:
                    return (
                        "Computer action was not performed because the NEBIX desktop "
                        "control indicator could not be started."
                    )
        from core.windows_display import per_monitor_dpi_awareness

        with per_monitor_dpi_awareness():
            return _computer_control(
                parameters,
                response=response,
                player=player,
                session_memory=session_memory,
                cancel_event=cancel_event,
            )
    finally:
        if indicator_started:
            try:
                from core.desktop_indicator import stop_desktop_indicator

                stop_desktop_indicator()
            except Exception:
                pass
        _CONTROL_LOCK.release()


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "computer_control",
    "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "type | smart_type | click | double_click | right_click | hotkey | press | hold_key | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"
            },
            "text": {
                "type": "STRING",
                "description": "Text to type or paste"
            },
            "target_window": {
                "type": "STRING",
                "description": "Exact window title returned by open_app. NEBIX verifies this window is foreground before typing."
            },
            "x": {
                "type": "INTEGER",
                "description": "X coordinate"
            },
            "y": {
                "type": "INTEGER",
                "description": "Y coordinate"
            },
            "keys": {
                "type": "STRING",
                "description": "Key combination e.g. 'ctrl+c'"
            },
            "key": {
                "type": "STRING",
                "description": "Single key e.g. 'enter'"
            },
            "direction": {
                "type": "STRING",
                "description": "up | down | left | right"
            },
            "amount": {
                "type": "INTEGER",
                "description": "Scroll amount (default: 3)"
            },
            "seconds": {
                "type": "NUMBER",
                "description": "Seconds to wait or hold a key (key holds are capped at 5 seconds)"
            },
            "title": {
                "type": "STRING",
                "description": "Window title for focus_window"
            },
            "description": {
                "type": "STRING",
                "description": "Element description for screen_find/screen_click"
            },
            "type": {
                "type": "STRING",
                "description": "Data type for random_data"
            },
            "field": {
                "type": "STRING",
                "description": "Field for user_data: name|email|city"
            },
            "clear_first": {
                "type": "BOOLEAN",
                "description": "Clear field before typing (default: true)"
            },
            "path": {
                "type": "STRING",
                "description": "Deprecated. Screen content is not written to disk."
            }
        },
        "required": [
            "action"
        ]
    },
    "handler": computer_control,
}
