from __future__ import annotations

from pathlib import Path
from typing import Any


_PERMISSION_CATEGORIES = (
    ("computer_use", "Computer Use", "Allow NEBIX to control the desktop with mouse and keyboard actions.", False),
    ("clipboard_access", "Copy and paste", "Read from or write to the system clipboard.", True),
    ("window_control", "Window control", "Focus, switch, resize, minimize, or maximize windows.", True),
    ("application_launch", "Application launch", "Open applications and browser instances.", True),
    ("application_close", "Application close", "Close ordinary applications, windows, or NEBIX.", True),
    ("browser_control", "Browser control", "Navigate, inspect, and control browser windows and tabs.", True),
    ("website_interaction", "Website interaction", "Click controls, enter text, and interact with websites.", True),
    ("system_information", "System information", "Read system status, process counts, and disk usage.", True),
    ("screen_observation", "Screen Vision", "Capture, analyze, or transmit screen content when explicitly requested.", False),
    ("camera_access", "Camera access", "Capture or stream images from a camera.", False),
    ("microphone_access", "Microphone access", "Capture audio from a microphone for voice input or remote audio.", False),
    ("file_read", "File reading", "List, inspect, search, and read local files.", True),
    ("file_create", "File creation", "Create files and generated output.", True),
    ("file_edit", "File editing", "Write or change existing files and documents.", True),
    ("file_move", "File moving and renaming", "Move, copy, or rename files.", True),
    ("folder_operations", "Folder operations", "Create, organize, and manage folders.", True),
    ("file_delete", "File and folder deletion", "Delete files or folders.", False),
    ("downloads", "Downloads", "Download files or software from the network.", True),
    ("uploads", "Uploads", "Upload files from this device to a remote service or dashboard.", False),
    ("terminal_execution", "Terminal and system commands", "Run shell, terminal, PowerShell, or system commands.", False),
    ("code_execution", "Code execution", "Build, test, or execute code and generated scripts.", False),
    ("system_settings", "Reversible system settings", "Change reversible settings such as volume, brightness, and appearance.", True),
    ("network_configuration", "Network and firewall configuration", "Change Wi-Fi, firewall, or network configuration.", False),
    ("software_installation", "Software installation and updates", "Install or update software and packages.", False),
    ("software_removal", "Software removal", "Uninstall or remove software.", False),
    ("process_management", "Process management", "Inspect, stop, or otherwise manage running processes.", False),
    ("network_access", "Network access", "Search the web or retrieve information from online services.", True),
    ("external_communication", "External communication", "Send messages or other information to people or services.", False),
    ("financial_transactions", "Financial transactions", "Perform purchases, payments, transfers, or donations.", False),
    ("account_security", "Account and security actions", "Sign in or out, change account security, or delete accounts.", False),
    ("sensitive_data_handling", "Sensitive data", "Read, enter, or transmit credentials and other sensitive data.", False),
    ("memory_read", "NEBIX memory reading", "Read NEBIX's saved personal memories.", True),
    ("memory_write", "NEBIX memory changes", "Save or change NEBIX's long-term memories.", True),
    ("background_monitoring", "Background monitoring", "Add or change recurring topic monitoring.", False),
    ("scheduled_tasks", "Scheduled tasks", "Create recurring or timed operating-system tasks.", False),
    ("computer_shutdown", "Computer shutdown", "Shut down the computer.", False),
    ("computer_restart", "Computer restart", "Restart the computer.", False),
    ("remote_control", "Remote control", "Accept commands and live control from paired remote devices.", False),
    ("plugin_execution", "Plugin execution", "Run third-party or user-added NEBIX plugins.", False),
    ("undo_actions", "Undo actions", "Reverse a recent action performed by NEBIX.", True),
    ("data_generation", "Data generation", "Generate non-sensitive example data.", True),
    ("application_settings", "NEBIX application settings", "Change reversible NEBIX preferences by voice or chat.", True),
    ("startup_configuration", "Startup configuration", "Change Windows startup and launch configuration.", False),
)

_PERMISSION_DEFAULTS = {
    category: default
    for category, _label, _description, default in _PERMISSION_CATEGORIES
}
_PERMISSION_IDS = frozenset(_PERMISSION_DEFAULTS)
_LEGACY_COMPUTER_PERMISSION_IDS = frozenset(
    {"keyboard_input", "mouse_control", "scrolling"}
)


def get_permission_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": category,
            "label": label,
            "description": description,
            "default": default,
        }
        for category, label, description, default in _PERMISSION_CATEGORIES
    ]


def normalize_permission_state(value: Any) -> dict[str, bool]:
    """Normalize current permissions and migrate prior mouse/keyboard grants."""
    if value is None:
        return dict(_PERMISSION_DEFAULTS)
    if not isinstance(value, dict):
        raise ValueError("permissions must be an object of category booleans.")
    unknown = sorted(set(value) - _PERMISSION_IDS - _LEGACY_COMPUTER_PERMISSION_IDS)
    if unknown:
        raise ValueError(f"Unknown permission category: {', '.join(unknown)}.")
    invalid = sorted(key for key, enabled in value.items() if not isinstance(enabled, bool))
    if invalid:
        raise ValueError(f"Permission values must be true or false: {', '.join(invalid)}.")
    normalized = dict(_PERMISSION_DEFAULTS)
    normalized.update({key: enabled for key, enabled in value.items() if key in _PERMISSION_IDS})
    if "computer_use" not in value and any(key in value for key in _LEGACY_COMPUTER_PERMISSION_IDS):
        # Preserve prior access only when every previously separate input grant
        # was explicitly enabled. Missing legacy values fail closed.
        normalized["computer_use"] = all(
            value.get(key) is True for key in _LEGACY_COMPUTER_PERMISSION_IDS
        )
    return normalized


def merge_permission_state(current: Any, updates: Any) -> dict[str, bool]:
    if not isinstance(updates, dict):
        raise ValueError("permissions must be an object of category booleans.")
    base = normalize_permission_state(current)
    unknown = sorted(set(updates) - _PERMISSION_IDS - _LEGACY_COMPUTER_PERMISSION_IDS)
    if unknown:
        raise ValueError(f"Unknown permission category: {', '.join(unknown)}.")
    invalid = sorted(key for key, enabled in updates.items() if not isinstance(enabled, bool))
    if invalid:
        raise ValueError(f"Permission values must be true or false: {', '.join(invalid)}.")
    merged = {**base, **{key: enabled for key, enabled in updates.items() if key in _PERMISSION_IDS}}
    if "computer_use" not in updates and any(key in updates for key in _LEGACY_COMPUTER_PERMISSION_IDS):
        old = current if isinstance(current, dict) else {}
        merged["computer_use"] = all(
            updates.get(key, old.get(key, False)) is True
            for key in _LEGACY_COMPUTER_PERMISSION_IDS
        )
    return merged


def permission_is_enabled(state: Any, category: str) -> bool:
    if category not in _PERMISSION_IDS:
        return False
    return normalize_permission_state(state)[category]


def required_settings_command_categories(
    command: dict[str, Any],
) -> tuple[str, ...] | None:
    """Map parsed voice settings requests to their capability permission."""
    if not isinstance(command, dict):
        return None
    kind = str(command.get("kind") or "")
    if kind in {"clarify"}:
        return ()
    if kind == "desktopShortcut":
        return ("file_create", "startup_configuration")
    if kind == "setting":
        key = str(command.get("key") or "")
        if key in {"startupEnabled", "startMinimized", "restorePreviousInterface"}:
            return ("startup_configuration",)
        if key == "performanceMode":
            return ("system_settings",)
    return ("application_settings",)


def _unique_categories(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(category for group in groups for category in group))


def required_permission_categories(
    name: str,
    parameters: dict[str, Any],
) -> tuple[str, ...] | None:
    """Map each built-in action to capability categories; unknown actions fail closed."""
    tool_name = str(name or "").strip()
    args = parameters if isinstance(parameters, dict) else {}
    action = str(args.get("action") or "").strip().casefold()

    if tool_name.startswith("plugin:"):
        return ("plugin_execution",)

    if tool_name in {
        "system_status",
    }:
        return ("system_information",)
    if tool_name == "screen_process":
        return ("camera_access", "network_access") if str(args.get("angle", "screen")).casefold() == "camera" else ("screen_observation", "network_access")
    if tool_name == "close_camera":
        return ("camera_access",)
    if tool_name == "manage_monitor":
        if action in {"add", "remove"}:
            return ("background_monitoring",)
        if action == "list":
            return ("memory_read",)
        return None
    if tool_name == "shutdown_nebix":
        return ("application_close",)
    if tool_name == "save_memory":
        return _unique_categories(
            ("memory_write",),
            ("sensitive_data_handling",) if _sensitive_data_intent(args) else (),
        )
    if tool_name == "recall_memory":
        return ("memory_read",)
    if tool_name == "undo":
        return ("undo_actions",)

    if tool_name == "open_app":
        return ("application_launch",)

    if tool_name == "computer_control":
        categories = {
            "type": ("computer_use",),
            "smart_type": ("computer_use",),
            "press": ("computer_use",),
            "hold_key": ("computer_use",),
            "clear_field": ("computer_use",),
            "click": ("computer_use",),
            "left_click": ("computer_use",),
            "double_click": ("computer_use",),
            "right_click": ("computer_use",),
            "move": ("computer_use",),
            "drag": ("computer_use",),
            "hotkey": ("computer_use",),
            "scroll": ("computer_use",),
            "copy": ("computer_use", "clipboard_access"),
            "paste": ("computer_use", "clipboard_access"),
            "screenshot": ("screen_observation", "network_access"),
            "screen_find": ("screen_observation", "network_access"),
            "screen_click": ("computer_use", "screen_observation", "network_access"),
            "wait": ("data_generation",),
            "focus_window": ("computer_use", "window_control"),
            "random_data": ("data_generation",),
            "user_data": ("memory_read", "sensitive_data_handling"),
        }
        required = categories.get(action)
        if required is None:
            return None
        if action == "hotkey":
            keys = str(args.get("keys") or "").casefold()
            if any(key in keys.split("+") for key in ("c", "x", "v")):
                required = _unique_categories(required, ("clipboard_access",))
        if action in {"type", "smart_type"}:
            text = str(args.get("text") or "")
            uses_clipboard = not text.isascii() or (
                action == "smart_type" and len(text) > 20
            )
            if uses_clipboard:
                required = _unique_categories(required, ("clipboard_access",))
        if _sensitive_data_intent(args):
            required = _unique_categories(required, ("sensitive_data_handling",))
        return required

    if tool_name == "computer_settings":
        if not action and args.get("description"):
            try:
                from actions.computer_settings import _detect_action

                action = _detect_action(str(args["description"])).get("action", "")
            except (ImportError, AttributeError, TypeError, ValueError):
                return None
        categories = {
            **dict.fromkeys(
                ("volume_up", "volume_down", "volume_set", "mute", "brightness_up", "brightness_down", "sleep_display", "dark_mode", "lock_screen"),
                ("system_settings",),
            ),
            "close_app": ("application_close",),
            "close_window": ("computer_use", "window_control", "application_close"),
            "full_screen": ("computer_use", "window_control"),
            "minimize": ("computer_use", "window_control"),
            "maximize": ("computer_use", "window_control"),
            "snap_left": ("computer_use", "window_control"),
            "snap_right": ("computer_use", "window_control"),
            "switch_window": ("computer_use", "window_control"),
            "show_desktop": ("computer_use", "window_control"),
            "focus_search": ("computer_use",),
            **dict.fromkeys(
                ("refresh_page", "go_back", "go_forward"),
                ("computer_use", "browser_control", "website_interaction", "network_access"),
            ),
            **dict.fromkeys(
                ("close_tab", "new_tab", "next_tab", "prev_tab", "zoom_in", "zoom_out", "zoom_reset", "find_on_page"),
                ("computer_use", "browser_control", "website_interaction"),
            ),
            **dict.fromkeys(("scroll_up", "scroll_down", "scroll_top", "scroll_bottom", "page_up", "page_down"), ("computer_use",)),
            "copy": ("computer_use", "clipboard_access"),
            "paste": ("computer_use", "clipboard_access"),
            "cut": ("computer_use", "clipboard_access"),
            "undo": ("computer_use", "file_edit"),
            "redo": ("computer_use", "file_edit"),
            "select_all": ("computer_use",),
            "save": ("file_edit", "computer_use"),
            "enter": ("computer_use",),
            "escape": ("computer_use",),
            "press_key": ("computer_use",),
            "type_text": ("computer_use",),
            "screenshot": ("screen_observation",),
            "open_settings": ("system_settings",),
            "file_explorer": ("application_launch", "file_read"),
            "open_run": ("terminal_execution",),
            "toggle_wifi": ("network_configuration",),
            "task_manager": ("process_management",),
            "restart": ("computer_restart",),
            "shutdown": ("computer_shutdown",),
        }
        required = categories.get(action)
        if required is None:
            return None
        if _sensitive_data_intent(args):
            required = _unique_categories(required, ("sensitive_data_handling",))
        return required

    if tool_name == "browser_control":
        navigation = {"go_to", "search", "back", "forward", "reload", "new_tab", "switch"}
        reading = {"get_text", "get_url", "screenshot"}
        interaction = {"click", "type", "scroll", "fill_form", "smart_click", "smart_type", "press"}
        closing = {"close_tab", "close", "close_all"}
        if action in navigation:
            required = ("browser_control", "website_interaction")
            if action in {"go_to", "search", "back", "forward", "reload"}:
                required = _unique_categories(required, ("network_access",))
        elif action == "list_browsers":
            required = ("browser_control",)
        elif action in reading:
            required = ("browser_control", "network_access")
            if action == "screenshot":
                required = _unique_categories(required, ("screen_observation",))
        elif action in interaction:
            required = (
                "computer_use", "browser_control", "website_interaction", "network_access",
            )
            target_text = " ".join(
                str(args.get(key) or "").casefold()
                for key in ("text", "description", "selector", "query")
            )
            if any(token in target_text for token in ("buy", "purchase", "pay", "transfer", "checkout", "donate", "transaction")):
                required = _unique_categories(required, ("financial_transactions",))
            if any(token in target_text for token in ("sign out", "log out", "logout", "account security", "delete account", "reset password")):
                required = _unique_categories(required, ("account_security",))
            if action in {"type", "smart_type", "fill_form"} and _sensitive_data_intent(args):
                required = _unique_categories(required, ("sensitive_data_handling",))
        elif action in closing:
            required = ("application_close", "browser_control")
        elif action == "download":
            required = ("browser_control", "downloads", "network_access", "file_create")
        elif action == "upload":
            required = ("browser_control", "uploads", "file_read")
        else:
            return None
        return required

    if tool_name == "file_controller":
        categories = {
            "list": ("file_read",),
            "read": ("file_read",),
            "find": ("file_read",),
            "largest": ("file_read",),
            "disk_usage": ("file_read", "system_information"),
            "info": ("file_read",),
            "create_file": ("file_create",),
            "create_folder": ("folder_operations",),
            "write": ("file_edit",),
            "copy": ("file_read", "file_create"),
            "move": ("file_move",),
            "rename": ("file_move",),
            "delete": ("file_delete",),
            "organize_desktop": ("file_move", "folder_operations", "file_delete"),
        }
        return categories.get(action)

    if tool_name == "file_processor":
        reading = {
            "info", "inspect", "describe", "ocr", "summarize", "extract_text",
            "word_count", "analyze", "stats", "filter", "sort", "validate",
            "review", "explain", "list",
        }
        created_output = {
            "resize", "compress", "convert", "to_word", "to_bullet", "to_csv",
            "format", "reformat", "translate_hint", "trim", "extract_audio",
            "extract_frame", "extract", "fix", "optimize",
        }
        if action in reading:
            required = ("file_read",)
            if action in {"summarize", "analyze", "review", "explain", "translate_hint"}:
                required = _unique_categories(required, ("network_access",))
        elif action in created_output:
            required = ("file_read", "file_create")
            if action in {"fix", "optimize", "format", "reformat"}:
                required = _unique_categories(required, ("file_edit",))
        elif action in {"run", "test", "document"}:
            required = ("file_read", "terminal_execution", "code_execution")
            if action == "document":
                required = _unique_categories(required, ("file_create",))
        elif action == "transcribe":
            required = ("file_read", "network_access")
        else:
            return None
        return _unique_categories(
            required,
            ("sensitive_data_handling",) if _sensitive_data_intent(args) else (),
        )

    if tool_name == "excel_control":
        if action in {"status", "attach", "open", "list_workbooks", "list_sheets", "inspect", "read_range", "read_formulas"}:
            return ("file_read",)
        if action == "create":
            return ("file_create",)
        if action in {"write_range", "write_formulas", "add_sheet", "rename_sheet", "format", "save", "save_as", "close"}:
            return ("file_edit",)
        return None

    if tool_name == "desktop_control":
        if action == "wallpaper":
            return ("system_settings", "file_read")
        if action == "wallpaper_url":
            return ("system_settings", "network_access", "downloads")
        if action == "current_wallpaper":
            return ("system_information",)
        if action == "organize":
            return ("file_move", "folder_operations")
        if action == "clean":
            return ("file_delete",)
        if action == "list":
            return ("file_read",)
        if action == "stats":
            return ("system_information",)
        if action == "task" or args.get("task"):
            return ("terminal_execution", "code_execution", "file_read", "file_create", "file_edit", "file_delete")
        return None

    if tool_name == "code_helper":
        if action == "screen_debug":
            return ("screen_observation", "network_access")
        if action in {"read", "inspect", "explain", "review", "analyze"}:
            return ("file_read",)
        if action in {"write", "edit", "build", "optimize", "auto"}:
            target = args.get("file_path") or args.get("output_path")
            file_category = "file_edit" if _path_exists(target) else "file_create"
            required = (file_category, "file_read")
            if action in {"build", "auto"}:
                required = _unique_categories(required, ("terminal_execution", "code_execution"))
            return required
        if action in {"run", "test"}:
            return ("file_read", "terminal_execution", "code_execution")
        return None

    if tool_name in {"dev_agent", "engineering_task"}:
        return (
            "file_read", "file_create", "file_edit", "file_delete",
            "terminal_execution", "code_execution", "software_installation",
            "network_access",
        )

    if tool_name == "game_updater":
        if action in {"list", "download_status", "schedule_status"}:
            return ("system_information",)
        if action == "cancel_schedule":
            return ("scheduled_tasks",)
        if action == "schedule":
            return ("scheduled_tasks", "software_installation", "network_access")
        if action in {"update", "install", "download", ""}:
            required = ("software_installation", "downloads", "network_access", "application_launch")
            # Steam's existing sign-in recovery workflow captures its app window.
            required = _unique_categories(required, ("screen_observation", "computer_use"))
            if str(args.get("shutdown_when_done") or "").casefold() in {"true", "1", "yes"}:
                required = _unique_categories(required, ("computer_shutdown",))
            return required
        return None

    if tool_name == "reminder":
        return ("scheduled_tasks",)
    if tool_name == "send_message":
        return _unique_categories(
            ("computer_use", "external_communication"),
            ("sensitive_data_handling",) if _sensitive_data_intent(args) else (),
        )
    if tool_name == "whatsapp_control":
        if action == "status":
            return ("system_information",)
        if action in {"send", "message", "reply", "type", "click", "react"}:
            return ("computer_use", "external_communication")
        if action == "call":
            return (
                "external_communication",
                "application_launch",
                "computer_use",
                "window_control",
            )
        return None
    if tool_name in {"web_search", "weather_report", "flight_finder"}:
        return ("network_access",)
    if tool_name == "youtube_video":
        required = ("network_access",)
        if args.get("save", True):
            required = _unique_categories(required, ("file_create",))
        if action in {"download", "save_video"}:
            required = _unique_categories(required, ("downloads", "file_create"))
        return required

    return None


def check_action_permissions(
    name: str,
    parameters: dict[str, Any],
    state: Any,
) -> dict[str, Any]:
    required = required_permission_categories(name, parameters)
    if required is None:
        return {
            "allowed": False,
            "required": [],
            "denied": [],
            "message": (
                f"Blocked: no permission category is defined for action '{name}' "
                "with these parameters."
            ),
        }
    current = normalize_permission_state(state)
    tool_name = str(name or "").strip()
    action = str((parameters or {}).get("action") or "").strip().casefold()
    cleanup = (
        tool_name == "close_camera"
        or (tool_name == "manage_monitor" and action == "remove")
        or (tool_name == "game_updater" and action == "cancel_schedule")
    )
    denied = [
        category
        for category in required
        if not current[category]
        and not (cleanup and category in {"camera_access", "background_monitoring", "scheduled_tasks"})
    ]
    if denied:
        labels = {item["id"]: item["label"] for item in get_permission_catalog()}
        names = ", ".join(labels[category] for category in denied)
        return {
            "allowed": False,
            "required": list(required),
            "denied": denied,
            "message": (
                f"Blocked by Settings → Permissions: {names} "
                "is disabled. Enable the required permission and try again."
            ),
        }
    return {
        "allowed": True,
        "required": list(required),
        "denied": [],
        "message": "",
    }


_READ_ONLY_FILE_ACTIONS = {"list", "read", "find", "largest", "disk_usage", "info"}
_FILE_WRITE_ACTIONS = {
    "create_file", "create_folder", "write", "copy", "move", "rename",
}
_DESKTOP_READ_ACTIONS = {"current_wallpaper", "list", "stats"}
_GAME_READ_ACTIONS = {"list", "download_status", "schedule_status"}
_EDITING_ACTIONS = {"write", "edit", "build", "optimize", "auto"}
_DESTRUCTIVE_TOKENS = (
    "delete", "remove", "uninstall", "shutdown", "restart",
    "purchase", "buy", "pay", "payment", "transfer", "transaction",
    "checkout", "donate", "send", "submit", "publish", "post",
    "overwrite", "format",
)
_SENSITIVE_DATA_TOKENS = (
    "password", "passcode", "one-time code", "verification code",
    "api key", "secret", "credential", "otp", "private key",
    "access token", "bearer token", "credit card", "card number",
    "bank account", "social security", "ssn", "personal data",
)


def _path_exists(value: Any) -> bool:
    if not isinstance(value, (str, Path)) or not str(value).strip():
        return False
    try:
        return Path(value).expanduser().exists()
    except (OSError, RuntimeError, ValueError):
        return False


def _file_target(parameters: dict[str, Any], action: str) -> Path | None:
    home = Path.home()
    shortcuts = {
        "desktop": home / "Desktop",
        "downloads": home / "Downloads",
        "documents": home / "Documents",
        "pictures": home / "Pictures",
        "music": home / "Music",
        "videos": home / "Videos",
        "home": home,
    }

    def resolve(value: Any) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            return None
        raw = value.strip()
        return shortcuts.get(raw.casefold(), Path(raw).expanduser())

    name = str(parameters.get("name") or "").strip()
    base = resolve(parameters.get("path") or "desktop")
    if action in {"create_file", "write"}:
        return base / name if base and name else base
    if action in {"copy", "move"}:
        destination = resolve(parameters.get("destination"))
        if destination and destination.is_dir() and name:
            return destination / Path(name).name
        return destination
    if action == "rename":
        new_name = str(parameters.get("new_name") or "").strip()
        if base and new_name:
            return base / new_name
    return base / name if base and name else base


def _destructive_intent(parameters: dict[str, Any]) -> bool:
    fields = (
        "action", "description", "text", "selector", "keys", "target",
        "key", "command", "operation", "intent", "task", "query", "message",
        "instruction", "value",
    )
    combined = " ".join(
        str(parameters.get(key) or "").casefold()
        for key in fields
    )
    return (
        any(token in combined for token in _DESTRUCTIVE_TOKENS)
        or _sensitive_data_intent(parameters)
    )


def _sensitive_data_intent(parameters: dict[str, Any]) -> bool:
    fields = ("text", "value", "message", "query", "fields", "form_data")
    combined = " ".join(
        str(parameters.get(key) or "").casefold()
        for key in fields
    )
    return any(token in combined for token in _SENSITIVE_DATA_TOKENS)


def tool_permission(
    name: str,
    parameters: dict[str, Any],
    *,
    confirm_sensitive: bool = True,
) -> dict[str, str] | None:
    """Describe the HUD confirmation needed before a registered tool runs.

    High-impact operations always require confirmation. Meaningful medium-risk
    operations follow confirmSensitive; routine computer interactions pass
    through directly.
    """
    tool_name = str(name or "").strip()
    args = parameters if isinstance(parameters, dict) else {}
    action = str(args.get("action") or "").strip().casefold()
    target = (
        args.get("file_path")
        or args.get("output_path")
        or args.get("path")
        or args.get("name")
    )
    risk = ""
    operation = ""

    if tool_name == "file_controller":
        if action in {"delete", "organize_desktop"}:
            risk, operation = "high", f"file operation '{action}'"
        elif action in _FILE_WRITE_ACTIONS:
            if _path_exists(_file_target(args, action)):
                risk, operation = "high", f"overwrite data with file operation '{action}'"
        elif action not in _READ_ONLY_FILE_ACTIONS:
            risk, operation = "medium", f"file operation '{action or 'unknown'}'"
    elif tool_name == "excel_control":
        if action in {"save", "close"} or args.get("discard_changes") is True:
            risk, operation = "high", f"Excel workbook operation '{action or 'close'}'"
        elif action == "save_as" and _path_exists(args.get("path")):
            risk, operation = "high", "overwrite an existing Excel workbook"
    elif tool_name == "code_helper":
        if action in _EDITING_ACTIONS:
            risk = "high" if _path_exists(args.get("file_path") or args.get("output_path")) else "medium"
            operation = f"code operation '{action}'"
        elif action == "run":
            risk, operation = "medium", "run project code"
    elif tool_name == "dev_agent":
        project_name = str(args.get("project_name") or "").strip()
        project_dir = Path.home() / "Desktop" / "NEBIXProjects" / project_name
        risk = "high" if project_name and project_dir.exists() else "medium"
        operation = "generate or modify project files, install declared packages, and run generated code"
    elif tool_name == "desktop_control":
        if action in {"clean", "organize", "task"} or args.get("task"):
            risk, operation = "high", f"desktop operation '{action or 'task'}'"
        elif action in _DESKTOP_READ_ACTIONS:
            pass
        elif action:
            risk, operation = "medium", f"desktop operation '{action}'"
    elif tool_name == "game_updater":
        shutdown = str(args.get("shutdown_when_done") or "").casefold() in {
            "true", "1", "yes",
        }
        if shutdown:
            risk, operation = "high", "shut down the computer after game downloads finish"
        elif action not in _GAME_READ_ACTIONS:
            risk, operation = "medium", f"game updater operation '{action or 'update'}'"
    elif tool_name == "reminder":
        risk, operation = "medium", "create a scheduled system reminder"
    elif tool_name == "computer_settings":
        if action in {"restart", "shutdown", "toggle_wifi"}:
            pass
        elif action in {"type_text", "write_on_screen", "paste"}:
            if _sensitive_data_intent(args):
                risk, operation = "high", "enter or paste sensitive information"
        elif action in {"press_key", "enter"}:
            if _destructive_intent(args):
                risk, operation = "high", f"computer settings action '{action}'"
        elif _destructive_intent(args):
            risk, operation = "high", f"computer settings action '{action}'"
    elif tool_name == "computer_control":
        if action == "user_data":
            risk, operation = "high", "read user profile data"
        elif action in {"type", "smart_type", "paste"}:
            if _sensitive_data_intent(args):
                risk, operation = "high", "enter or paste sensitive information"
        elif _sensitive_data_intent(args):
            risk, operation = "high", "handle sensitive information"
        elif _destructive_intent(args):
            risk, operation = "high", f"computer action '{action or 'unknown action'}'"
    elif tool_name == "browser_control":
        if action == "close_all":
            risk, operation = "medium", "close all browser windows"
        elif action in {"type", "smart_type", "fill_form"}:
            if _sensitive_data_intent(args):
                risk, operation = "high", "enter sensitive information in a browser"
        elif action in {"click", "smart_click", "press"} and _destructive_intent(args):
            risk, operation = "high", f"perform a consequential browser action ({action})"
        elif action == "press" and str(args.get("key") or "").casefold() in {"enter", "return"}:
            risk, operation = "high", "submit or activate the current browser control"
        elif _sensitive_data_intent(args):
            risk, operation = "high", "handle sensitive information in a browser"
    elif tool_name == "send_message":
        risk, operation = "high", "send a message to another person"
    elif tool_name == "whatsapp_control" and action == "call":
        risk, operation = "high", "start a WhatsApp call with another person"
    elif tool_name == "file_processor":
        if _destructive_intent(args):
            risk, operation = "high", f"file processing action '{action or 'unknown'}'"
        elif action not in {
            "read", "inspect", "info", "validate", "list", "word_count",
        }:
            risk, operation = "medium", f"process or change a file ({action or 'unknown action'})"
    elif tool_name == "youtube_video":
        if action == "summarize" and args.get("save", True):
            risk, operation = "medium", "save a video summary to a local file"
    elif tool_name.startswith("plugin:"):
        risk = "high" if _destructive_intent(args) else "medium"
        operation = f"run plugin '{tool_name.partition(':')[2]}'"

    if not risk:
        return None
    if risk == "medium" and not confirm_sensitive:
        return None

    title = (
        "Confirm destructive computer action"
        if risk == "high"
        else "Confirm computer action"
    )
    detail = f"NEBIX is requesting permission to {operation}."
    if isinstance(target, str) and target.strip():
        detail += f" Target: {target.strip()[:240]}."
    if risk == "high":
        detail += " This action always requires explicit confirmation."
    return {"risk": risk, "title": title, "detail": detail}
