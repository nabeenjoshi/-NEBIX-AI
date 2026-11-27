# ============================================================
# NEBIX — WEB UI / PYWEBVIEW BRIDGE
# File: D:/NEBIX/web_ui.py
# ============================================================

from __future__ import annotations

import json
import re
import threading
import platform
import socket
import os
import sys
import time
import traceback
import subprocess
from pathlib import Path
from typing import Any

from core.communication_style import (
    PERSONAL_RESPONSE_DEFAULTS,
    WHATSAPP_STYLE_DEFAULTS,
    normalize_personal_response_settings,
    normalize_whatsapp_style_settings,
    validate_personal_response_settings,
    validate_whatsapp_style_settings,
)
from core.nepal_time import format_nepal_clock, nepal_now
from core.power_control import (
    active_performance_mode,
    available_performance_modes,
    set_performance_mode,
)
from core.paths import (
    get_config_file,
    get_data_dir,
    is_validation_mode,
    load_api_config,
    resource_path,
    save_api_config,
)
from core.permissions import (
    get_permission_catalog,
    merge_permission_state,
    normalize_permission_state,
)
from core.settings_manager import SettingsManager, normalize_quick_access_settings
from core.tts import WindowsSapiTTS
# ============================================================
# PATHS
# ============================================================

def get_base_dir():
    """
    Returns the correct NEBIX resource directory.

    Normal Python:
        D:/NEBIX

    PyInstaller:
        _MEIPASS / bundled resource directory
    """
    if getattr(sys, "frozen", False):
        return Path(
            getattr(
                sys,
                "_MEIPASS",
                Path(sys.executable).parent,
            )
        )

    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
INTERFACE_DIR = BASE_DIR / "interface"

DEFAULT_DESIGN = 1
SHUTDOWN_FORCE_EXIT_SECONDS = 8.0
MAX_CHAT_THEME_BYTES = 3 * 1024 * 1024
MAX_DIGITAL_TEXT_BYTES = 16 * 1024
MAX_INTERFACE_PROFILES_BYTES = 512 * 1024
INTERFACE_IDS = {
    "default",
    "interface1",
    "interface2",
    "interface3",
    "interface4",
    "interface5",
    "electric-storm",
    "fusion-sun",
    "neural-holographic",
    "quantum-orbit",
    "cyber-void",
    "aether-energy",
    "titan-command",
    "holographic-glass",
    "nexus-future",
}
LEGACY_INTERFACE_IDS = {
    "arc": "default",
    "red-hud": "electric-storm",
    "cinematic": "electric-storm",
    "hologram": "neural-holographic",
    "radial": "quantum-orbit",
    "command": "quantum-orbit",
}
INTERFACE_MODULES = {
    "clock",
    "system",
    "metrics",
    "core",
    "command",
    "activity",
    "environment",
}
INTERFACE_PROFILE_COMPONENTS = {
    "centralVisual",
    "navigation",
    "clock",
    "systemMonitor",
    "activityLog",
    "commandBar",
    "weather",
    "statusArea",
    "interfaceIcons",
}
INTERFACE_PROFILE_COMPONENT_BOUNDS = {
    "scale": (60, 140),
    "x": (-180, 180),
    "y": (-140, 140),
    "width": (60, 140),
    "height": (60, 140),
    "fontSize": (75, 140),
    "spacing": (0, 32),
    "opacity": (25, 100),
    "glow": (0, 100),
    "size": (20, 130),
}
INTERFACE_PROFILE_COMPONENT_STYLES = {
    "clock": {
        "current", "iphone", "apple-thin", "sf-minimalist", "digital",
        "digital-bold", "futuristic", "hud", "cyber", "mono", "terminal",
        "matrix", "luxury", "elegant", "thin-elegant", "tech", "geometric",
        "modern-wide", "condensed", "ultra-minimal", "impact", "classic",
        "editorial",
    },
    "systemMonitor": {
        "current", "circular", "digital", "bars", "hud", "cyber",
        "terminal", "glass", "reactor", "command",
    },
    "activityLog": {"current", "terminal", "glass", "cyber"},
    "commandBar": {"current", "hud", "terminal", "glass"},
    "weather": {"current", "glass", "minimal", "hud"},
}

# Matches the Startup/Desktop shortcut AppUserModelID so Windows
# shows nebix.ico on the taskbar instead of the Python icon.
try:
    from config.windows_shortcut import (
        NEBIX_APP_ID,
        install_nebix_shortcuts,
        set_autostart,
    )
except Exception:
    NEBIX_APP_ID = "NEBIX"
    install_nebix_shortcuts = None
    set_autostart = None


def apply_windows_app_identity():
    if platform.system() != "Windows":
        return

    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            NEBIX_APP_ID
        )
    except Exception:
        pass


def apply_windows_window_icon(
    title: str = "NEBIX — Personal AI Intelligence",
):
    if platform.system() != "Windows":
        return

    ico = resource_path("config", "nebix.ico")

    if not ico.is_file():
        return

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        GCLP_HICON = -14
        GCLP_HICONSM = -34

        load_image = user32.LoadImageW
        load_image.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        load_image.restype = wintypes.HANDLE

        path = str(ico)
        hicon_big = load_image(
            None, path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE
        )
        hicon_small = load_image(
            None, path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE
        )

        if not hicon_big:
            return

        hwnd = user32.FindWindowW(None, title)

        if not hwnd:
            return

        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
        user32.SendMessageW(
            hwnd,
            WM_SETICON,
            ICON_SMALL,
            hicon_small or hicon_big,
        )

        try:
            user32.SetClassLongPtrW(hwnd, GCLP_HICON, hicon_big)
            user32.SetClassLongPtrW(
                hwnd, GCLP_HICONSM, hicon_small or hicon_big
            )
        except Exception:
            pass
    except Exception:
        pass


apply_windows_app_identity()


# ============================================================
# OPTIONAL PSUTIL
# ============================================================

try:
    import psutil
except Exception:
    psutil = None

try:
    from actions.system_monitor import _get_gpu_usage
except Exception:
    _get_gpu_usage = None


# ============================================================
# VOICE CONFIG
# ============================================================

AVAILABLE_VOICES = [
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Aoede",
]

DEFAULT_VOICE = "Puck"

VOICE_INTERFACE_CUSTOMIZATION_DEFAULTS = {
    "red-hud": {
        "accent": "#ff304a",
        "secondary": "#9ce8ed",
        "background": "#07090c",
        "transparency": 20,
        "blur": 2,
        "glow": 78,
        "animation": 72,
        "speed": 100,
        "systemWidgets": True,
        "activityWidgets": True,
    },
    "hologram": {
        "accent": "#52e8ff",
        "secondary": "#ffad67",
        "background": "#03070b",
        "transparency": 24,
        "blur": 8,
        "glow": 72,
        "animation": 68,
        "speed": 88,
        "systemWidgets": True,
        "activityWidgets": True,
    },
    "radial": {
        "accent": "#27d9ff",
        "secondary": "#d9ae67",
        "background": "#02060a",
        "transparency": 14,
        "blur": 1,
        "glow": 66,
        "animation": 58,
        "speed": 90,
        "systemWidgets": True,
        "activityWidgets": True,
    },
}


def _default_voice_interface_customization():
    return {
        mode: dict(values)
        for mode, values in VOICE_INTERFACE_CUSTOMIZATION_DEFAULTS.items()
    }


def _merge_voice_interface_customization(current, updates):
    if not isinstance(updates, dict):
        raise ValueError("Voice interface customization must be an object.")

    merged = _default_voice_interface_customization()
    if isinstance(current, dict):
        for mode, values in current.items():
            if mode in merged and isinstance(values, dict):
                merged[mode].update(values)

    for mode, values in updates.items():
        if mode not in merged or not isinstance(values, dict):
            raise ValueError("Customization is only available for Interfaces 2, 3, and 4.")

        for key, value in values.items():
            if key not in merged[mode]:
                continue
            if key in {"accent", "secondary", "background"}:
                if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                    raise ValueError(f"{key} must be a six-digit hex color.")
                merged[mode][key] = value.lower()
            elif key in {"glow", "animation"}:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
                    raise ValueError(f"{key} must be between 0 and 100.")
                merged[mode][key] = round(value)
            elif key == "transparency":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 60:
                    raise ValueError("transparency must be between 0 and 60.")
                merged[mode][key] = round(value)
            elif key == "blur":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 20:
                    raise ValueError("blur must be between 0 and 20.")
                merged[mode][key] = round(value)
            elif key == "speed":
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 50 <= value <= 150:
                    raise ValueError("speed must be between 50 and 150.")
                merged[mode][key] = round(value)
            elif key in {"systemWidgets", "activityWidgets"}:
                if not isinstance(value, bool):
                    raise ValueError(f"{key} must be a boolean.")
                merged[mode][key] = value

    return merged


def _normalize_interface_id(value):
    interface_id = str(value or "default").strip().lower()
    return LEGACY_INTERFACE_IDS.get(interface_id, interface_id)


def _merge_interface_profiles(current, updates):
    if not isinstance(updates, dict):
        raise ValueError("Interface profiles must be an object.")

    merged = {}
    customizable_ids = INTERFACE_IDS
    if isinstance(current, dict):
        for interface_id, profile in current.items():
            if interface_id in customizable_ids and isinstance(profile, dict):
                merged[interface_id] = profile

    for interface_id, profile in updates.items():
        if interface_id not in customizable_ids or not isinstance(profile, dict):
            raise ValueError("Unsupported interface customization profile.")

        target = dict(merged.get(interface_id, {}))
        for key, value in profile.items():
            if key == "colorPreset":
                if not isinstance(value, str) or value not in {"red", "blue", "cyan", "purple", "green", "gold", "orange", "white", "custom"}:
                    raise ValueError("Unsupported interface color preset.")
                target[key] = value
            elif key == "customColor":
                if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                    raise ValueError("Custom interface color must be a six-digit hex color.")
                target[key] = value.lower()
            elif key == "secondaryColor":
                if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                    raise ValueError("Secondary interface color must be a six-digit hex color.")
                target[key] = value.lower()
            elif key == "density":
                if not isinstance(value, str) or value not in {"compact", "standard", "spacious"}:
                    raise ValueError("Unsupported interface layout density.")
                target[key] = value
            elif key == "effects":
                if not isinstance(value, dict):
                    raise ValueError("Interface effects must be an object.")
                effects = dict(target.get("effects", {}))
                for effect, amount in value.items():
                    if effect not in {"glow", "particles", "lighting", "animation"}:
                        continue
                    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 <= amount <= 100:
                        raise ValueError(f"{effect} must be between 0 and 100.")
                    effects[effect] = round(amount)
                target[key] = effects
            elif key == "modules":
                if not isinstance(value, dict):
                    raise ValueError("Interface modules must be an object.")
                modules = dict(target.get("modules", {}))
                for module, settings in value.items():
                    if module not in INTERFACE_MODULES or not isinstance(settings, dict):
                        continue
                    module_settings = dict(modules.get(module, {}))
                    if "visible" in settings:
                        if not isinstance(settings["visible"], bool):
                            raise ValueError("Module visibility must be a boolean.")
                        module_settings["visible"] = settings["visible"]
                    if "zone" in settings:
                        if not isinstance(settings["zone"], str) or settings["zone"] not in {"left", "center", "right"}:
                            raise ValueError("Unsupported module placement zone.")
                        module_settings["zone"] = settings["zone"]
                    if "size" in settings:
                        if not isinstance(settings["size"], str) or settings["size"] not in {"small", "medium", "large", "full"}:
                            raise ValueError("Unsupported module size.")
                        module_settings["size"] = settings["size"]
                    modules[module] = module_settings
                target[key] = modules
            elif key == "components":
                if not isinstance(value, dict):
                    raise ValueError("Interface component settings must be an object.")
                components = dict(target.get("components", {}))
                for component, settings in value.items():
                    if component not in INTERFACE_PROFILE_COMPONENTS or not isinstance(settings, dict):
                        continue
                    component_settings = dict(components.get(component, {}))
                    for setting, amount in settings.items():
                        if setting in INTERFACE_PROFILE_COMPONENT_BOUNDS:
                            minimum, maximum = INTERFACE_PROFILE_COMPONENT_BOUNDS[setting]
                            if setting == "size" and component == "clock":
                                maximum = 68
                            elif setting == "size":
                                minimum = 70
                            if (
                                isinstance(amount, bool)
                                or not isinstance(amount, (int, float))
                                or not minimum <= amount <= maximum
                            ):
                                raise ValueError(
                                    f"{component} {setting} must be between {minimum} and {maximum}."
                                )
                            component_settings[setting] = round(amount)
                        elif setting in {"visible", "active"}:
                            if not isinstance(amount, bool):
                                raise ValueError(f"{component} {setting} must be true or false.")
                            component_settings[setting] = amount
                        elif setting == "style":
                            if not isinstance(amount, str) or amount not in INTERFACE_PROFILE_COMPONENT_STYLES.get(component, set()):
                                raise ValueError(f"Unsupported {component} style.")
                            component_settings[setting] = amount
                        elif setting == "position":
                            if not isinstance(amount, str) or amount not in {"left", "center", "right"}:
                                raise ValueError(f"Unsupported {component} position.")
                            component_settings[setting] = amount
                        elif setting == "order":
                            if isinstance(amount, bool) or not isinstance(amount, int) or not 0 <= amount <= 9:
                                raise ValueError(f"{component} order must be between 0 and 9.")
                            component_settings[setting] = amount
                        elif setting == "componentWidth" and component == "commandBar":
                            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 60 <= amount <= 100:
                                raise ValueError("Command width must be between 60 and 100.")
                            component_settings[setting] = round(amount)
                        elif setting == "density" and component == "activityLog":
                            if not isinstance(amount, str) or amount not in {"compact", "standard", "spacious"}:
                                raise ValueError("Unsupported Activity density.")
                            component_settings[setting] = amount
                    components[component] = component_settings
                target[key] = components

        merged[interface_id] = target

    try:
        encoded = json.dumps(merged, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError(f"Interface profiles are invalid: {exc}") from exc
    if len(encoded) > MAX_INTERFACE_PROFILES_BYTES:
        raise ValueError("Interface profiles exceed the 512 KB limit.")

    return merged


def _get_saved_voice():
    try:
        from memory.config_manager import get_voice

        voice = str(
            get_voice() or DEFAULT_VOICE
        ).strip()

        if voice in AVAILABLE_VOICES:
            return voice

    except Exception:
        pass

    return DEFAULT_VOICE


def _save_voice(voice: str):
    voice = str(voice or "").strip()

    if voice not in AVAILABLE_VOICES:
        raise ValueError(
            f"Unsupported NEBIX voice: {voice}"
        )

    from memory.config_manager import save_voice

    save_voice(voice)

    return voice


# ============================================================
# SAFE JSON
# ============================================================

def _safe_json(value: Any):
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


# ============================================================
# PYWEBVIEW BRIDGE
# ============================================================

class NebixBridge:

    def __init__(self, ui: "NebixUI"):
        self.ui = ui
        self._tts = WindowsSapiTTS(self._set_tts_state)

    def _set_tts_state(self, state: str, message: str) -> None:
        if not self._is_shutting_down():
            self.ui.set_state(state, message)
            if state == "SPEAKING":
                self.ui.write_log(f"VOICE: {message}")
            elif state == "ERROR":
                self.ui.write_log(f"ERR: {message}")
            elif message in {"Speech playback finished.", "Speech playback stopped."}:
                self.ui.write_log(f"VOICE: {message}")

    def _permission_error(self, *categories):
        from core.permissions import (
            get_permission_catalog,
            normalize_permission_state,
        )

        try:
            permissions = normalize_permission_state(
                self.ui.settings.get("permissions")
            )
        except ValueError as exc:
            return f"Blocked: NEBIX permission state is invalid: {exc}"
        denied = [category for category in categories if not permissions[category]]
        if not denied:
            return ""
        labels = {
            item["id"]: item["label"]
            for item in get_permission_catalog()
        }
        names = ", ".join(labels.get(category, category) for category in denied)
        return (
            f"Blocked by Settings → Permissions: {names} is disabled. "
            "Enable the required permission and try again."
        )

    def _settings_permission_error(self, settings):
        if not isinstance(settings, dict):
            return ""
        current = self.ui.settings
        categories = []
        if (
            settings.get("startupEnabled") is True
            and settings.get("startupEnabled") != current.get("startupEnabled")
        ):
            categories.append("startup_configuration")
        if any(
            key in settings and settings[key] != current.get(key)
            for key in ("startMinimized", "restorePreviousInterface")
        ):
            categories.append("startup_configuration")
        if (
            "performanceMode" in settings
            and settings["performanceMode"] != current.get("performanceMode")
        ):
            categories.append("system_settings")
        return self._permission_error(*dict.fromkeys(categories))

    def _is_shutting_down(self):
        event = getattr(self.ui, "shutdown_event", None)
        return bool(event and event.is_set())

    # ========================================================
    # BASIC
    # ========================================================

    def ready(self):
        if is_validation_mode():
            marker = get_data_dir() / "validation-bridge-ready"
            marker.write_text("ready", encoding="utf-8")

        return {
            "ok": True,
            "app": "NEBIX",
            "bridge": "pywebview",
            "version": "1.0",
        }

    def status(self):
        return self.ui.get_status()

    def system(self):
        return self.ui.get_system()

    def state(self):
        return self.ui.get_status()

    # ========================================================
    # API KEY
    # ========================================================

    def has_api_key(self):
        return self.ui.wait_for_api_key()

    def test_api(self):
        return self.test_ai_provider("gemini")

    def ai_provider_state(self):
        try:
            from core.ai_providers import get_provider_settings

            settings = get_provider_settings(
                gemini_live_connected=bool(self.ui.connected),
            )
            return {"ok": True, **settings}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def test_ai_provider(self, provider="gemini"):
        denied = self._permission_error("network_access")
        if denied:
            return {"ok": False, "error": denied}
        try:
            from core.ai_providers import (
                DEFAULT_GEMINI_CHAT_MODEL,
                PROVIDER_INFO,
                generate_chat_response,
            )

            provider_id = str(provider or "gemini").strip().lower()
            info = PROVIDER_INFO.get(provider_id)
            if not info:
                return {"ok": False, "error": "Unsupported AI provider."}
            config = load_api_config()
            api_key = str(config.get(info["key_name"]) or "").strip()
            if not api_key:
                return {"ok": False, "error": f"No {info['name']} API key is connected."}
            selected = config.get("ai_provider_selected_models", {})
            model = (
                selected.get(provider_id)
                if isinstance(selected, dict)
                else None
            ) or DEFAULT_GEMINI_CHAT_MODEL
            reply = generate_chat_response(
                provider_id,
                api_key,
                str(model),
                [{"role": "user", "text": "Reply with exactly: OK"}],
            )
            return {
                "ok": True,
                "message": f"{info['name']} responded successfully.",
                "response": reply,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def connect_ai_provider(self, provider="", key=""):
        try:
            from core.ai_providers import connect_provider, PROVIDER_INFO

            provider_id = str(provider or "").strip().lower()
            if provider_id not in PROVIDER_INFO:
                return {"ok": False, "error": "Unsupported AI provider."}
            result = connect_provider(provider_id, str(key or ""))
            return {
                "ok": True,
                "provider": result["provider"],
                "connected": result["connected"],
                "models": result["models"],
                "model": result["selected_model"],
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def refresh_ai_provider_models(self, provider=""):
        denied = self._permission_error("network_access")
        if denied:
            return {"ok": False, "error": denied}
        try:
            from core.ai_providers import refresh_provider_models

            return {
                "ok": True,
                **refresh_provider_models(provider),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_active_ai_provider(self, provider=""):
        try:
            return self.ui.settings_manager.set_setting(
                "ai.provider",
                provider,
                sync_frontend=False,
            )
        except (KeyError, ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}

    def _set_active_ai_provider(self, provider=""):
        try:
            from core.ai_providers import set_active_provider

            return {
                "ok": True,
                **set_active_provider(
                    provider,
                    gemini_live_connected=bool(self.ui.connected),
                ),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_ai_provider_model(self, provider="", model=""):
        try:
            return self.ui.settings_manager.set_setting(
                f"ai.model.{str(provider or '').strip().lower()}",
                model,
                sync_frontend=False,
            )
        except (KeyError, ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}

    def _set_ai_provider_model(self, provider="", model=""):
        try:
            from core.ai_providers import set_provider_model

            return {"ok": True, **set_provider_model(provider, model)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def remove_ai_provider(self, provider=""):
        try:
            from core.ai_providers import remove_provider, PROVIDER_INFO

            provider_id = str(provider or "").strip().lower()
            if provider_id not in PROVIDER_INFO:
                return {"ok": False, "error": "Unsupported AI provider."}
            settings = remove_provider(provider_id)
            if provider_id == "gemini":
                stop_result = self.ui.stop() if self.ui.activated else None
                callback = self.ui.on_api_key_removed
                if callback:
                    callback()
                self.ui.set_state(
                    "STANDBY",
                    "Google Gemini API key removed. NEBIX is in standby.",
                )
                return {
                    "ok": True,
                    **settings,
                    "activated": False,
                    "result": _safe_json(stop_result),
                }
            return {"ok": True, **settings}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def set_api_key(self, key=""):
        key = str(key or "").strip()

        if not key:
            return {
                "ok": False,
                "error": "Gemini API key is empty.",
            }

        try:
            result = self.connect_ai_provider("gemini", key)
            if not result.get("ok"):
                return result

            self.ui.write_log(
                "Gemini API key saved."
            )

            self.ui.set_state(
                "READY",
                "Gemini API key saved. Starting backend...",
            )

            return {
                "ok": True,
                "saved": True,
                "has_api_key": True,
                "models": result.get("models", []),
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc)[:500],
            }

    def remove_api_key(self):
        result = self.remove_ai_provider("gemini")
        if result.get("ok"):
            result["has_api_key"] = False
        return result

    # ========================================================
    # ACTIVATION
    # ========================================================

    def activate(self):
        try:
            result = self.ui.activate()

            return {
                "ok": True,
                "activated": True,
                "result": _safe_json(result),
            }

        except Exception as exc:
            return {
                "ok": False,
                "activated": False,
                "error": str(exc),
            }

    def stop(self):
        try:
            result = self.ui.stop()

            return {
                "ok": True,
                "activated": False,
                "result": _safe_json(result),
            }

        except Exception as exc:
            return {
                "ok": False,
                "activated": self.ui.activated,
                "error": str(exc),
            }

    def reset(self):
        try:
            result = self.ui.reset()

            return {
                "ok": True,
                "result": _safe_json(result),
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    # ========================================================
    # COMMAND / CHAT
    # ========================================================

    def send_command(self, command=""):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        if not self.ui.activated:
            return {"ok": False, "error": "NEBIX is off. Turn it on in Settings to send commands."}
        command = str(command or "").strip()

        if not command:
            return {
                "ok": False,
                "error": "Empty command.",
            }

        callback = self.ui.on_text_command

        if not callback:
            return {
                "ok": False,
                "error": (
                    "NEBIX command handler is not ready."
                ),
            }

        try:
            result = callback(command)

            if isinstance(result, dict) and result.get("ok") is False:
                return result

            return {
                "ok": True,
                "command": command,
                "result": _safe_json(result),
            }

        except Exception as exc:
            traceback.print_exc()

            return {
                "ok": False,
                "error": str(exc),
            }

    def chat(self, command=""):
        return self.send_command(command)

    def get_nepal_clock(self):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        return {"ok": True, "time": format_nepal_clock()}

    def set_mode(self, mode="voice"):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        mode = str(mode or "voice").strip().lower()
        if mode not in {"voice", "chat"}:
            return {"ok": False, "error": "Unsupported NEBIX mode."}

        callback = getattr(self.ui, "on_mode_change", None)
        if callback:
            try:
                result = callback(mode)
                if isinstance(result, dict) and result.get("ok") is False:
                    return result
            except Exception as exc:
                return {"ok": False, "error": str(exc)}

        self.ui.write_log(f"Interface mode changed to {mode}.")
        return {"ok": True, "mode": mode}

    def speak_text(self, text="", voice=""):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        return self._tts.speak(str(text or ""), str(voice or ""))

    def stop_speaking(self):
        return self._tts.stop()

    def get_activity(self):
        return self.ui.get_activity()

    def clear_activity(self):
        return self.ui.clear_activity()

    def log_activity(self, message=""):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        message = str(message or "").strip()
        if not message:
            return {"ok": False, "error": "Activity message is empty."}
        self.ui.write_log(message[:4000])
        return {"ok": True}

    def send_chat(self, text="", attachment=None, request_meta=None):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        text = str(text or "").strip()
        callback = getattr(self.ui, "on_chat_command", None)
        if not callback:
            return {"ok": False, "error": "NEBIX chat handler is not ready."}
        received_at = time.perf_counter()
        metadata = dict(request_meta) if isinstance(request_meta, dict) else {}
        metadata["_bridge_received_at"] = received_at
        try:
            result = callback(text, attachment, metadata)
            if (
                os.environ.get("NEBIX_LATENCY_TRACE") == "1"
                and isinstance(result, dict)
                and result.get("ok")
            ):
                trace = dict(result.get("trace") or {})
                trace["bridgeHandlerMs"] = round(
                    (time.perf_counter() - received_at) * 1000, 2
                )
                result["trace"] = trace
            return result
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def copy_to_clipboard(self, text=""):
        denied = self._permission_error("clipboard_access")
        if denied:
            return {"ok": False, "error": denied}
        if platform.system().lower() != "windows":
            return {"ok": False, "error": "System clipboard access is unavailable on this platform."}
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool
        user32.EmptyClipboard.restype = ctypes.c_bool
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.restype = ctypes.c_bool
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.restype = ctypes.c_bool
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.restype = ctypes.c_void_p

        payload = (str(text or "") + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(0x0002, len(payload))
        if not handle:
            return {"ok": False, "error": "Could not allocate clipboard memory."}
        opened = False
        try:
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(pointer, payload, len(payload))
            kernel32.GlobalUnlock(handle)
            if not user32.OpenClipboard(None):
                raise ctypes.WinError(ctypes.get_last_error())
            opened = True
            if not user32.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            if not user32.SetClipboardData(13, handle):
                raise ctypes.WinError(ctypes.get_last_error())
            handle = None
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            if opened:
                user32.CloseClipboard()
            if handle:
                kernel32.GlobalFree(handle)

    def command(self, command=""):
        return self.send_command(command)

    # ========================================================
    # INTERRUPT
    # ========================================================

    def interrupt(self):
        callback = self.ui.on_interrupt

        if not callback:
            return {
                "ok": True,
                "message": (
                    "No interrupt handler registered."
                ),
            }

        try:
            result = callback()

            return {
                "ok": True,
                "result": _safe_json(result),
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    # ========================================================
    # REMOTE
    # ========================================================

    def remote_clicked(self, action=""):
        if not self.ui.activated:
            return {"ok": False, "error": "NEBIX is off. Turn it on in Settings to use Remote Control."}
        action = str(action or "").strip()

        callback = self.ui.on_remote_clicked

        if not callback:
            return {
                "ok": False,
                "error": (
                    "Remote control handler is not ready."
                ),
            }

        try:
            try:
                result = callback(action)
            except TypeError:
                result = callback()

            return {
                "ok": True,
                "action": action,
                "result": _safe_json(result),
            }

        except Exception as exc:
            traceback.print_exc()

            return {
                "ok": False,
                "action": action,
                "error": str(exc),
            }

    def remote(self, action=""):
        return self.remote_clicked(action)

    # ========================================================
    # VOICE
    # ========================================================

    def set_voice(self, voice=""):
        voice = str(voice or "").strip()

        if not voice:
            return {
                "ok": False,
                "error": "Voice is required.",
            }

        if voice not in AVAILABLE_VOICES:
            return {
                "ok": False,
                "error": (
                    "Unsupported voice. "
                    "Available voices: "
                    + ", ".join(AVAILABLE_VOICES)
                ),
                "available": list(AVAILABLE_VOICES),
            }

        try:
            change = self.ui.settings_manager.set_setting(
                "voice.selection",
                voice,
                sync_frontend=False,
            )
            if not change.get("ok"):
                return {
                    "ok": False,
                    "error": change.get("error") or "Assistant voice could not be saved.",
                    "available": list(AVAILABLE_VOICES),
                }
            selected_voice = str(change["setting"]["current_value"])
            callback = self.ui.on_voice_change
            return {
                "ok": True,
                "voice": selected_voice,
                "saved": True,
                "reconnecting": bool(callback),
                "available": list(AVAILABLE_VOICES),
                "result": None,
            }

        except Exception as exc:
            traceback.print_exc()

            return {
                "ok": False,
                "voice": voice,
                "saved": False,
                "error": str(exc),
            }

    def get_voices(self):
        current = _get_saved_voice()

        self.ui.settings["voice"] = current

        return {
            "ok": True,
            "voices": list(AVAILABLE_VOICES),
            "current": current,
            "default": DEFAULT_VOICE,
        }

    # ========================================================
    # AUDIO DEVICE
    # ========================================================

    def audio_devices(self):
        try:
            from core.audio_devices import list_devices
            from memory.config_manager import get_input_device, get_output_device

            return {
                "ok": True,
                "input": ["", *list_devices("input")],
                "output": ["", *list_devices("output")],
                "selected_input": get_input_device(),
                "selected_output": get_output_device(),
            }
        except Exception as exc:
            return {"ok": False, "input": [], "output": [], "error": str(exc)}

    def set_audio_device(self, device=None, kind="input"):
        kind = str(kind or "input").strip().lower()
        if kind not in {"input", "output"}:
            return {"ok": False, "error": "Audio direction must be input or output."}
        callback = self.ui.on_audio_device_change
        try:
            from memory.config_manager import save_input_device, save_output_device
            save_device = save_input_device if kind == "input" else save_output_device
            save_device(str(device or ""))
            self.ui.settings[kind + "Device"] = str(device or "")
            result = callback() if callback else None
            return {"ok": True, "kind": kind, "device": str(device or ""), "result": _safe_json(result)}
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    # ========================================================
    # SETTINGS
    # ========================================================

    def get_settings(self):
        return self.ui.settings_manager.get_settings()

    def set_settings(self, settings=None):
        if settings is None:
            settings = {}

        if not isinstance(settings, dict):
            return {
                "ok": False,
                "error": "Settings must be an object.",
            }

        denied = self._settings_permission_error(settings)
        if denied:
            return {"ok": False, "error": denied}

        try:
            previous_permissions = dict(
                self.ui.settings.get("permissions", {})
                if isinstance(self.ui.settings.get("permissions"), dict)
                else {}
            )
            result = self.ui.settings_manager.set_settings(settings)
            if isinstance(result, dict) and result.get("ok") is False:
                return result
            if "permissions" in settings:
                callback = getattr(self.ui, "on_permissions_changed", None)
                if callback:
                    callback(
                        previous_permissions,
                        self.ui.settings.get("permissions", {}),
                    )
                from core.permissions import permission_is_enabled

                if not permission_is_enabled(
                    self.ui.settings.get("permissions"),
                    "computer_use",
                ):
                    callback = getattr(self.ui, "on_computer_use_toggle", None)
                    if callback:
                        callback(False)

                permissions = self.ui.settings.get("permissions")
                if (
                    not permission_is_enabled(permissions, "screen_observation")
                    or not permission_is_enabled(permissions, "network_access")
                ):
                    callback = getattr(self.ui, "on_screen_vision_toggle", None)
                    if callback:
                        callback(False)

            return {
                "ok": True,
                "settings": self.ui.settings_manager.get_settings(),
                "result": _safe_json(result),
            }

        except Exception as exc:
            traceback.print_exc()

            return {
                "ok": False,
                "error": str(exc),
            }

    def set_screen_vision(self, enabled=False):
        if not isinstance(enabled, bool):
            return {"ok": False, "error": "Screen Vision enabled must be true or false."}
        if enabled:
            denied = self._permission_error("screen_observation")
            if denied:
                return {"ok": False, "error": denied}
        callback = getattr(self.ui, "on_screen_vision_toggle", None)
        if not callback:
            return {"ok": False, "error": "Screen Vision is not available."}
        try:
            metrics = callback(enabled)
            return {
                "ok": True,
                "active": bool(metrics.get("active")) if isinstance(metrics, dict) else enabled,
                "metrics": _safe_json(metrics),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_screen_vision_status(self):
        callback = getattr(self.ui, "on_screen_vision_status", None)
        if not callback:
            return {"ok": True, "active": False, "metrics": {}}
        try:
            metrics = callback()
            return {
                "ok": True,
                "active": bool(metrics.get("active")) if isinstance(metrics, dict) else False,
                "metrics": _safe_json(metrics),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_setting_registry(self):
        return self.ui.settings_manager.get_setting_registry()

    def get_setting(self, setting_id=""):
        try:
            return {"ok": True, **self.ui.settings_manager.get_setting(setting_id)}
        except (KeyError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    def set_setting(self, setting_id="", value=None):
        normalized_id = str(setting_id or "").strip()
        settings_key = {
            "automation.startupEnabled": "startupEnabled",
            "startup_enabled": "startupEnabled",
            "startupEnabled": "startupEnabled",
            "automation.startMinimized": "startMinimized",
            "start_minimized": "startMinimized",
            "startMinimized": "startMinimized",
            "automation.performanceMode": "performanceMode",
            "performanceMode": "performanceMode",
        }.get(normalized_id)
        denied = self._settings_permission_error(
            {settings_key: value} if settings_key else {}
        )
        if denied:
            return {"ok": False, "error": denied}
        try:
            return self.ui.settings_manager.set_setting(setting_id, value)
        except (KeyError, ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}

    def get_identity(self):
        from core.identity_manager import get_identity

        return {"ok": True, "identity": get_identity()}

    def engineering_task_status(self):
        agent = getattr(self.ui, "engineering_agent", None)
        if agent is None:
            return {
                "ok": True,
                "task": {
                    "state": "IDLE",
                    "result": "",
                    "project_path": None,
                    "current_file": None,
                    "findings": [],
                    "evidence": [],
                },
            }
        return {"ok": True, "task": agent.snapshot()}

    def cancel_engineering_task(self):
        agent = getattr(self.ui, "engineering_agent", None)
        if agent is None:
            return {"ok": False, "error": "The engineering task engine is unavailable."}
        cancelled = agent.cancel()
        return {
            "ok": cancelled,
            "cancelled": cancelled,
            "task": agent.snapshot(),
            **(
                {}
                if cancelled
                else {"error": "There is no active engineering task to cancel."}
            ),
        }

    # ========================================================
    # DESKTOP SHORTCUT
    # ========================================================

    def create_desktop_shortcut(self):
        denied = self._permission_error(
            "startup_configuration",
            "file_create",
        )
        if denied:
            return {"ok": False, "created": False, "error": denied}

        if platform.system().lower() != "windows":
            return {
                "ok": False,
                "error": (
                    "Desktop shortcut is supported "
                    "on Windows only."
                ),
            }

        if install_nebix_shortcuts is None:
            return {
                "ok": False,
                "created": False,
                "error": "Shortcut installer is unavailable.",
            }

        try:
            result = install_nebix_shortcuts(
                autostart=True,
            )

            self.ui.settings["startup"] = True
            self.ui.write_log(
                "NEBIX shortcut, icon, and boot autostart installed."
            )

            return result

        except Exception as exc:
            traceback.print_exc()

            return {
                "ok": False,
                "created": False,
                "error": str(exc),
            }

    def remove_desktop_shortcut(self):
        if platform.system().lower() != "windows":
            return {"ok": False, "error": "Desktop shortcut management is supported on Windows only."}
        try:
            from config.windows_shortcut import shortcut_locations
            removed = []
            for path in shortcut_locations(include_startup=False):
                if path.is_file():
                    path.unlink()
                    removed.append(str(path))
            self.ui.write_log("Desktop and Start menu shortcuts removed.")
            return {
                "ok": True,
                "removed": removed,
                "message": "Desktop and Start menu shortcuts removed." if removed else "No desktop or Start menu shortcuts were found.",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def startup_status(self):
        if platform.system().lower() != "windows":
            return {"ok": True, "available": False, "enabled": False}
        try:
            from config.windows_shortcut import startup_shortcut_path
            path = startup_shortcut_path()
            return {"ok": True, "available": True, "enabled": path.is_file(), "path": str(path)}
        except Exception as exc:
            return {"ok": False, "available": False, "error": str(exc)}

    def shortcut_status(self):
        if platform.system().lower() != "windows":
            return {"ok": True, "available": False, "installed": False}
        try:
            from config.windows_shortcut import shortcut_locations
            paths = shortcut_locations(include_startup=False)
            installed = [str(path) for path in paths if path.is_file()]
            return {
                "ok": True,
                "available": True,
                "installed": bool(installed),
                "paths": installed,
            }
        except Exception as exc:
            return {"ok": False, "available": False, "error": str(exc)}

    def set_startup(self, enabled=False):
        denied = self._permission_error("startup_configuration")
        if denied and enabled:
            return {"ok": False, "error": denied}
        if platform.system().lower() != "windows" or set_autostart is None:
            return {"ok": False, "error": "Windows startup control is unavailable on this platform."}
        try:
            return self.ui.set_settings({"startupEnabled": bool(enabled)})
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def memory_entries(self, query=""):
        denied = self._permission_error("memory_read")
        if denied:
            return {"ok": False, "entries": [], "error": denied}
        try:
            from memory.memory_manager import all_entries_for_ui
            entries = all_entries_for_ui()
            needle = str(query or "").strip().lower()
            if needle:
                entries = [row for row in entries if needle in " ".join(str(row.get(k, "")) for k in ("category", "key", "value")).lower()]
            return {"ok": True, "entries": entries}
        except Exception as exc:
            return {"ok": False, "entries": [], "error": str(exc)}

    def delete_memory(self, category="", key=""):
        denied = self._permission_error("memory_write")
        if denied:
            return {"ok": False, "error": denied}
        try:
            from memory.memory_manager import forget
            result = forget(str(key or ""), str(category or "notes"))
            return {"ok": not result.startswith("Not found:"), "result": result}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def clear_memory(self):
        denied = self._permission_error("memory_write")
        if denied:
            return {"ok": False, "error": denied}
        try:
            from memory.memory_manager import _empty_memory, save_memory
            save_memory(_empty_memory())
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def diagnostics(self):
        checks = []
        checks.append({"name": "Gemini API configuration", "status": "PASS" if self.ui.wait_for_api_key() else "NOT CONFIGURED"})
        api_test = self.test_api()
        checks.append({"name": "Gemini API request", "status": "PASS" if api_test.get("ok") else "FAIL"})
        checks.append({"name": "Live AI session", "status": "PASS" if self.ui.connected else "FAIL"})
        checks.append({"name": "System monitor", "status": "PASS" if psutil else "NOT AVAILABLE"})
        try:
            from core.audio_devices import list_devices
            checks.append({"name": "Microphone device enumeration", "status": "PASS" if list_devices("input") else "NOT AVAILABLE"})
            checks.append({"name": "Speaker device enumeration", "status": "PASS" if list_devices("output") else "NOT AVAILABLE"})
        except Exception:
            checks.extend([{"name": "Microphone device enumeration", "status": "NOT AVAILABLE"}, {"name": "Speaker device enumeration", "status": "NOT AVAILABLE"}])
        try:
            with socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=2):
                internet_status = "PASS"
        except OSError:
            internet_status = "FAIL"
        checks.append({"name": "Internet", "status": internet_status})
        try:
            from memory.memory_manager import load_memory
            load_memory()
            memory_status = "PASS"
        except Exception:
            memory_status = "FAIL"
        checks.append({"name": "Memory store", "status": memory_status})
        checks.append({"name": "Plugins", "status": "PASS" if getattr(self.ui, "get_plugins", None) else "NOT AVAILABLE"})
        checks.append({"name": "Actions", "status": "PASS" if getattr(self.ui, "get_actions", None) else "NOT AVAILABLE"})
        startup = self.startup_status()
        checks.append({"name": "Windows startup", "status": ("PASS" if startup.get("enabled") else "WARNING") if startup.get("available") else "NOT AVAILABLE"})
        shortcut = self.shortcut_status()
        checks.append({"name": "Desktop shortcut", "status": ("PASS" if shortcut.get("installed") else "WARNING") if shortcut.get("available") else "NOT AVAILABLE"})
        return {"ok": True, "checks": checks}

    # ========================================================
    # WINDOW
    # ========================================================

    def minimize(self):
        try:
            self.ui.minimize()

            return {
                "ok": True,
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    def get_applications(self, refresh=False):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        try:
            from core.app_catalog import APPLICATION_CATALOG
            return APPLICATION_CATALOG.list_applications(force=bool(refresh))
        except Exception as exc:
            return {"ok": False, "error": f"Application discovery failed: {type(exc).__name__}."}

    def get_application_icons(self, application_ids=None):
        if self._is_shutting_down():
            return {"ok": False, "icons": {}, "error": "NEBIX is shutting down."}
        try:
            from core.app_catalog import APPLICATION_CATALOG
            return {"ok": True, "icons": APPLICATION_CATALOG.get_icons(application_ids or [])}
        except Exception as exc:
            return {"ok": False, "icons": {}, "error": f"Application icons are unavailable: {type(exc).__name__}."}

    def launch_application(self, application_id=""):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        denied = self._permission_error("application_launch")
        if denied:
            return {"ok": False, "error": denied}
        try:
            from core.app_catalog import APPLICATION_CATALOG
            result = APPLICATION_CATALOG.launch(str(application_id or ""))
            if not result.get("ok"):
                return result
            quick_access = normalize_quick_access_settings(
                self.ui.settings.get("quickAccess", {"favorites": [], "recent": []})
            )
            recent = [result["id"]] + [
                item for item in quick_access["recent"] if item != result["id"]
            ]
            quick_access["recent"] = recent[:32]
            persisted = self.set_settings({"quickAccess": quick_access})
            if not persisted or persisted.get("ok") is False:
                result["persistence_warning"] = (
                    persisted.get("error") if isinstance(persisted, dict)
                    else "Recent application could not be saved."
                )
            self.ui.write_log(f"APP: Launched {result['name']} via {result['method']}.")
            return result
        except Exception as exc:
            return {"ok": False, "error": f"Could not launch the application: {type(exc).__name__}."}

    def launch_application_by_name(self, application_name=""):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        denied = self._permission_error("application_launch")
        if denied:
            return {"ok": False, "error": denied}
        try:
            from core.app_catalog import APPLICATION_CATALOG
            result = APPLICATION_CATALOG.resolve_name(str(application_name or ""))
            if result.get("ok"):
                quick_access = normalize_quick_access_settings(
                    self.ui.settings.get("quickAccess", {"favorites": [], "recent": []})
                )
                quick_access["recent"] = [result["id"]] + [
                    item for item in quick_access["recent"] if item != result["id"]
                ]
                persisted = self.set_settings({"quickAccess": quick_access})
                if not persisted or persisted.get("ok") is False:
                    result["persistence_warning"] = (
                        persisted.get("error") if isinstance(persisted, dict)
                        else "Recent application could not be saved."
                    )
                self.ui.write_log(f"APP: Voice launched {result['name']} via {result['method']}.")
            return result
        except Exception as exc:
            return {"ok": False, "error": f"Could not launch the application: {type(exc).__name__}."}

    def toggle_fullscreen(self):
        try:
            result = self.ui.toggle_fullscreen()

            return {
                "ok": True,
                "result": _safe_json(result),
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    def close(self):
        try:
            self.ui.close()

            return {
                "ok": True,
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    # ========================================================
    # TOOLS
    # ========================================================

    def tool(self, name=""):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        name = str(name or "").strip()

        if not name:
            return {
                "ok": False,
                "error": "Tool name is required.",
            }

        callback = getattr(
            self.ui,
            "on_tool",
            None,
        )

        if callback:
            try:
                try:
                    result = callback(name)
                except TypeError:
                    result = callback()

                return {
                    "ok": True,
                    "tool": name,
                    "result": _safe_json(result),
                }

            except Exception as exc:
                return {
                    "ok": False,
                    "tool": name,
                    "error": str(exc),
                }

        return self.send_command(
            f"tool {name}"
        )

    # ========================================================
    # SHORTCUTS
    # ========================================================

    def shortcut(self, name=""):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        name = str(name or "").strip()

        if not name:
            return {
                "ok": False,
                "error": "Shortcut name is required.",
            }

        callback = getattr(
            self.ui,
            "on_shortcut",
            None,
        )

        if callback:
            try:
                try:
                    result = callback(name)
                except TypeError:
                    result = callback()

                return {
                    "ok": True,
                    "shortcut": name,
                    "result": _safe_json(result),
                }

            except Exception as exc:
                return {
                    "ok": False,
                    "shortcut": name,
                    "error": str(exc),
                }

        return self.send_command(
            f"open {name}"
        )

    # ========================================================
    # GENERIC ACTION
    # ========================================================

    def action(self, action="", value=None):
        if self._is_shutting_down():
            return {"ok": False, "error": "NEBIX is shutting down."}
        if not self.ui.activated:
            return {"ok": False, "error": "NEBIX is off. Turn it on in Settings to run actions."}
        action = str(action or "").strip()

        if not action:
            return {
                "ok": False,
                "error": "Action is required.",
            }

        callback = getattr(
            self.ui,
            "on_action",
            None,
        )

        if callback:
            try:
                try:
                    result = callback(
                        action,
                        value,
                    )
                except TypeError:
                    result = callback(action)

                return {
                    "ok": True,
                    "action": action,
                    "value": _safe_json(value),
                    "result": _safe_json(result),
                }

            except Exception as exc:
                return {
                    "ok": False,
                    "error": str(exc),
                }

        return self.send_command(action)

    # ========================================================
    # CONFIRMATION
    # ========================================================

    def confirm_result(self, accepted=False):
        try:
            result = self.ui.confirm_result(
                bool(accepted)
            )

            return {
                "ok": True,
                "accepted": bool(accepted),
                "result": _safe_json(result),
            }

        except Exception as exc:
            return {
                "ok": False,
                "accepted": bool(accepted),
                "error": str(exc),
            }

    # ========================================================
    # PLUGINS
    # ========================================================

    def plugins(self):
        try:
            return {
                "ok": True,
                "plugins": self.ui.plugin_list(),
            }

        except Exception as exc:
            return {
                "ok": False,
                "plugins": [],
                "error": str(exc),
            }

    def plugin_settings(self):
        try:
            return {
                "ok": True,
                "settings": self.ui.plugin_settings(),
            }

        except Exception as exc:
            return {
                "ok": False,
                "settings": {},
                "error": str(exc),
            }

    def actions(self):
        getter = getattr(self.ui, "get_actions", None)
        return {"ok": True, "actions": getter() if getter else []}

    def update_memory(self, category="", key="", value=""):
        denied = self._permission_error("memory_write")
        if denied:
            return {"ok": False, "error": denied}
        category = str(category or "").strip()
        key = str(key or "").strip()
        value = str(value or "").strip()
        if category not in {"identity", "preferences", "projects", "relationships", "wishes", "notes"} or not key or not value:
            return {"ok": False, "error": "A valid category, key, and non-empty value are required."}
        try:
            from memory.memory_manager import update_memory
            update_memory({category: {key: {"value": value}}})
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ========================================================
    # WAKE WORD
    # ========================================================

    def wake_state(self):
        try:
            return {
                "ok": True,
                "wake": self.ui.wake_state(),
            }

        except Exception as exc:
            return {
                "ok": False,
                "wake": {},
                "error": str(exc),
            }

    def wake_toggle(self, enabled=False):
        if enabled:
            denied = self._permission_error("microphone_access")
            if denied:
                return {"ok": False, "error": denied}
        callback = self.ui.on_wake_toggle

        if not callback:
            return {
                "ok": False,
                "error": (
                    "Wake-word toggle is not available."
                ),
            }

        try:
            try:
                result = callback(bool(enabled))
            except TypeError:
                result = callback()

            return {
                "ok": True,
                "enabled": bool(enabled),
                "result": _safe_json(result),
            }

        except Exception as exc:
            return {
                "ok": False,
                "enabled": bool(enabled),
                "error": str(exc),
            }

    def wake_manual(self):
        denied = self._permission_error("microphone_access")
        if denied:
            return {"ok": False, "error": denied}
        callback = self.ui.on_wake_manual

        if not callback:
            return {
                "ok": False,
                "error": (
                    "Manual wake-word control "
                    "is not available."
                ),
            }

        try:
            result = callback()

            return {
                "ok": True,
                "result": _safe_json(result),
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }

    def wake_install(self):
        denied = self._permission_error(
            "software_installation",
            "downloads",
            "network_access",
        )
        if denied:
            return {"ok": False, "error": denied}
        callback = self.ui.on_wake_install

        if not callback:
            return {
                "ok": False,
                "error": (
                    "Wake-word installation "
                    "is not available."
                ),
            }

        try:
            result = callback()

            return {
                "ok": True,
                "result": _safe_json(result),
            }

        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
            }


# ============================================================
# NEBIX UI
# ============================================================

class NebixUI:

    def __init__(
        self,
        design=DEFAULT_DESIGN,
        muted=False,
    ):

        if isinstance(design, str):
            muted = design
            design = DEFAULT_DESIGN

        self.muted = bool(muted)

        try:
            self.design = int(design)
        except Exception:
            self.design = DEFAULT_DESIGN

        if self.design < 1 or self.design > 10:
            self.design = DEFAULT_DESIGN

        # ----------------------------------------------------
        # Main callbacks
        # ----------------------------------------------------

        self.on_text_command = None
        self.on_chat_command = None
        self.on_mode_change = None
        self.on_remote_clicked = None
        self.on_screen_vision_toggle = None
        self.on_screen_vision_status = None
        self.on_computer_use_toggle = None
        self.on_permissions_changed = None
        self.on_interrupt = None
        self.on_power_off = None
        self.on_api_key_removed = None
        self.on_voice_change = None
        self.on_communication_profile_change = None
        self.on_audio_device_change = None
        self.on_tool = None
        self.on_shortcut = None
        self.on_action = None

        # ----------------------------------------------------
        # Backend functions
        # ----------------------------------------------------

        self.get_plugins = None
        self.get_plugin_settings = None
        self.request_say = None

        # ----------------------------------------------------
        # Wake-word hooks
        # ----------------------------------------------------

        self.wake_is_ready = None
        self.wake_get_state = None
        self.on_wake_toggle = None
        self.on_wake_manual = None
        self.on_wake_install = None

        # ----------------------------------------------------
        # Window
        # ----------------------------------------------------

        self._window = None
        self._win = self

        # ----------------------------------------------------
        # WebView lifecycle
        # ----------------------------------------------------

        self._window_lock = threading.RLock()

        self._ready = False
        self._closing = False
        self._closed = False
        self.shutdown_event = threading.Event()
        self.on_shutdown = None
        self._shutdown_callback_invoked = False
        self._shutdown_exit_watchdog = None

        self._webview_generation = 0

        # IMPORTANT:
        # Every evaluate_js call is serialized.
        # Closing also uses this lock before destroying
        # the WebView, preventing destruction while a JS
        # call is actively inside WebView2.
        self._js_lock = threading.RLock()

        # ----------------------------------------------------
        # State
        # ----------------------------------------------------

        self.activated = False
        self.powered_off = False
        self.connected = False
        self.voice_session_state = "DISCONNECTED"
        self.voice_session_message = "Gemini Live session has not connected."
        self.state = "READY"
        self.state_message = "NEBIX is ready."
        self.last_response = ""
        self.started_at = time.time()
        self._network_sample = None

        # ----------------------------------------------------
        # Security
        # ----------------------------------------------------

        self.activation_required = True

        # ----------------------------------------------------
        # Settings
        # ----------------------------------------------------

        self.settings = {
            "startup": True,
            "minimized": False,
            "activity": True,
            "voice": _get_saved_voice(),
            "wakeWord": False,
            "wakeWordText": "NEBIX",
            "activationRequired": True,
            "confirmSensitive": True,
            "permissions": normalize_permission_state(None),
            "voiceLayout": "default",
            "theme": "dark",
            "settingsTheme": "light",
            "clockSettings": {
                "style": "current",
                "size": 48,
                "weight": 700,
                "letterSpacing": 5,
                "format": "mm:ss",
            },
            "voiceInterfaceCustomization": _default_voice_interface_customization(),
            "interfaceProfiles": {},
            "chatTheme": None,
            "quickAccess": {"favorites": [], "recent": []},
            "digitalText": None,
            "personalResponse": dict(PERSONAL_RESPONSE_DEFAULTS),
            "whatsappStyle": dict(WHATSAPP_STYLE_DEFAULTS),
            "performanceMode": "balanced",
            "backgroundEfficiency": "Normal",
            "startupEnabled": True,
            "startMinimized": False,
            "restorePreviousInterface": True,
        }
        self.settings_manager = SettingsManager(
            self,
            interface_ids=INTERFACE_IDS,
            component_styles=INTERFACE_PROFILE_COMPONENT_STYLES,
            voices=AVAILABLE_VOICES,
        )
        self._clock_settings_persisted = False
        performance_mode_saved = False

        try:
            stored_settings = self.settings_manager.load_persisted_settings()
            if isinstance(stored_settings, dict):
                stored_layout = _normalize_interface_id(stored_settings.get("voiceLayout"))
                if stored_layout in INTERFACE_IDS:
                    self.settings["voiceLayout"] = stored_layout
                try:
                    self.settings["interfaceProfiles"] = _merge_interface_profiles(
                        {},
                        stored_settings.get("interfaceProfiles", {}),
                    )
                except ValueError:
                    pass
                if stored_settings.get("theme") in {"dark", "light"}:
                    self.settings["theme"] = stored_settings["theme"]
                if stored_settings.get("settingsTheme") in {"dark", "light"}:
                    self.settings["settingsTheme"] = stored_settings["settingsTheme"]
                if isinstance(stored_settings.get("activity"), bool):
                    self.settings["activity"] = stored_settings["activity"]
                if isinstance(stored_settings.get("confirmSensitive"), bool):
                    self.settings["confirmSensitive"] = stored_settings["confirmSensitive"]
                stored_permissions = stored_settings.get("permissions")
                if stored_permissions is not None:
                    try:
                        self.settings["permissions"] = normalize_permission_state(stored_permissions)
                    except ValueError as exc:
                        print(f"[Settings] Invalid permission state; using safe defaults: {exc}")
                stored_chat_theme = stored_settings.get("chatTheme")
                if isinstance(stored_chat_theme, dict):
                    try:
                        encoded_chat_theme = json.dumps(
                            stored_chat_theme,
                            ensure_ascii=False,
                        ).encode("utf-8")
                        if len(encoded_chat_theme) <= MAX_CHAT_THEME_BYTES:
                            self.settings["chatTheme"] = json.loads(
                                encoded_chat_theme.decode("utf-8")
                            )
                    except (TypeError, ValueError, UnicodeError):
                        pass
                stored_quick_access = stored_settings.get("quickAccess")
                if isinstance(stored_quick_access, dict):
                    try:
                        self.settings["quickAccess"] = normalize_quick_access_settings(
                            stored_quick_access
                        )
                    except ValueError:
                        pass
                stored_digital_text = stored_settings.get("digitalText")
                if isinstance(stored_digital_text, dict):
                    try:
                        encoded_digital_text = json.dumps(
                            stored_digital_text,
                            ensure_ascii=False,
                        ).encode("utf-8")
                        if len(encoded_digital_text) <= MAX_DIGITAL_TEXT_BYTES:
                            self.settings["digitalText"] = json.loads(
                                encoded_digital_text.decode("utf-8")
                            )
                    except (TypeError, ValueError, UnicodeError):
                        pass
                self.settings["whatsappStyle"] = normalize_whatsapp_style_settings(
                    stored_settings.get("whatsappStyle")
                )
                self.settings["personalResponse"] = normalize_personal_response_settings(
                    stored_settings.get("personalResponse")
                )
                performance_mode = stored_settings.get("performanceMode")
                if isinstance(performance_mode, str) and performance_mode in {"balanced", "performance", "battery_saver"}:
                    self.settings["performanceMode"] = performance_mode
                    performance_mode_saved = True
                background_efficiency = stored_settings.get("backgroundEfficiency")
                if isinstance(background_efficiency, str) and background_efficiency in {
                    "Normal",
                    "Reduced Background Activity",
                    "Maximum Efficiency",
                }:
                    self.settings["backgroundEfficiency"] = background_efficiency
                for key in (
                    "startupEnabled",
                    "startMinimized",
                    "restorePreviousInterface",
                ):
                    if isinstance(stored_settings.get(key), bool):
                        self.settings[key] = stored_settings[key]
                try:
                    self.settings["voiceInterfaceCustomization"] = _merge_voice_interface_customization(
                        self.settings["voiceInterfaceCustomization"],
                        stored_settings.get("voiceInterfaceCustomization", {}),
                    )
                except ValueError:
                    pass
                stored_clock_settings = stored_settings.get("clockSettings")
                if isinstance(stored_clock_settings, dict):
                    self.settings["clockSettings"] = {
                        **self.settings["clockSettings"],
                        **stored_clock_settings,
                    }
                    self._clock_settings_persisted = True
        except Exception:
            traceback.print_exc()

        if not performance_mode_saved:
            self.settings["performanceMode"] = active_performance_mode() or "balanced"

        # ----------------------------------------------------
        # Activity
        # ----------------------------------------------------

        self._logs = []
        self._log_lock = threading.RLock()

        # ----------------------------------------------------
        # Content
        # ----------------------------------------------------

        self.current_file = None
        self.content_title = ""
        self.content_text = ""

        # ----------------------------------------------------
        # Audio
        # ----------------------------------------------------

        self.audio_level = 0.0

        # ----------------------------------------------------
        # Camera
        # ----------------------------------------------------

        self.camera_active = False

        # ----------------------------------------------------
        # Confirmation
        # ----------------------------------------------------

        self._confirm_callback = None

        # ----------------------------------------------------
        # Phone
        # ----------------------------------------------------

        self.phone_connected = False

        # ----------------------------------------------------
        # PyWebView bridge
        # ----------------------------------------------------

        self.bridge = NebixBridge(self)

    # ========================================================
    # INDEX FILE
    # ========================================================

    def _get_index_file(self):

        candidates = [
            INTERFACE_DIR / "index.html",
            INTERFACE_DIR
            / f"design{self.design}"
            / "index.html",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return candidates[0]

    # ========================================================
    # API KEY
    # ========================================================

    def wait_for_api_key(self):

        config_path = get_config_file()

        if not config_path.exists():
            return False

        try:
            data = load_api_config()

            key = str(
                data.get(
                    "gemini_api_key",
                    "",
                )
            ).strip()

            return bool(key)

        except Exception:
            return False

    # ========================================================
    # WEBVIEW LIFECYCLE
    # ========================================================

    def _mark_webview_closing(self):
        """
        Signal shutdown without waiting for JavaScript evaluation.
        """
        self.request_shutdown()

    def _mark_webview_closed(self):
        """
        Final lifecycle state after the WebView has closed.
        """
        self.request_shutdown()
        with self._window_lock:
            self._closing = True
            self._closed = True
            self._ready = False

    def request_shutdown(self):
        """Set the shutdown signal and notify the backend without blocking."""
        with self._window_lock:
            self.shutdown_event.set()
            self._closing = True
            self._ready = False
            if self._shutdown_exit_watchdog is None:
                self._shutdown_exit_watchdog = threading.Timer(
                    SHUTDOWN_FORCE_EXIT_SECONDS,
                    self._force_shutdown_exit,
                )
                self._shutdown_exit_watchdog.daemon = True
                self._shutdown_exit_watchdog.start()
            callback = self.on_shutdown
            notify_backend = bool(
                callback and not self._shutdown_callback_invoked
            )
            if notify_backend:
                self._shutdown_callback_invoked = True

        if notify_backend:
            try:
                callback()
            except Exception as exc:
                traceback.print_exc()
                try:
                    self.write_log(f"Shutdown signal error: {exc}")
                except Exception:
                    pass
        return True

    def _force_shutdown_exit(self):
        if not self.shutdown_event.is_set():
            return
        try:
            print("NEBIX shutdown deadline elapsed; forcing process exit.")
        except Exception:
            pass
        os._exit(0)

    def _is_webview_available(self):
        with self._window_lock:
            return bool(
                self._window is not None
                and self._ready
                and not self._closing
                and not self._closed
            )

    # ========================================================
    # START PYWEBVIEW
    # ========================================================

    def start(
        self,
        debug=False,
        width=1500,
        height=900,
    ):

        try:
            import webview
        except ImportError as exc:
            raise RuntimeError(
                "pywebview is not installed. "
                "Install it with: pip install pywebview"
            ) from exc

        html_file = self._get_index_file()

        if not html_file.exists():
            raise FileNotFoundError(
                "NEBIX interface not found:\n"
                f"{html_file}"
            )

        # ----------------------------------------------------
        # Reset lifecycle
        # ----------------------------------------------------

        with self._window_lock:
            if self._shutdown_exit_watchdog is not None:
                self._shutdown_exit_watchdog.cancel()
                self._shutdown_exit_watchdog = None
            self._ready = False
            self._closing = False
            self._closed = False
            self.shutdown_event.clear()
            self._shutdown_callback_invoked = False
            self._webview_generation += 1

            generation = self._webview_generation

        # ----------------------------------------------------
        # Create window
        # ----------------------------------------------------

        window = webview.create_window(
            "NEBIX — Personal AI Intelligence",
            url=html_file.as_uri(),
            js_api=self.bridge,
            width=width,
            height=height,
            min_size=(1050, 700),
            background_color="#03070b",
            text_select=True,
        )

        with self._window_lock:
            self._window = window

        # ----------------------------------------------------
        # Loaded
        # ----------------------------------------------------

        def on_loaded(*args, **kwargs):

            with self._window_lock:

                if generation != self._webview_generation:
                    return

                if self._window is not window:
                    return

                if self._closing or self._closed:
                    return

                self._ready = True

            apply_windows_window_icon()

            # Do not sleep inside the pywebview event callback.
            #
            # The frontend can initialize itself and later
            # receive state/activity updates from the bridge.
            #
            # We still perform one initial synchronization,
            # but only after the lifecycle checks above.
            try:
                payload = {
                    "state": self.state,
                    "message": self.state_message,
                    "activated": bool(
                        self.activated
                    ),
                    "connected": bool(
                        self.connected
                    ),
                    "voiceSessionState": self.voice_session_state,
                    "voiceSessionMessage": self.voice_session_message,
                    "voice": self.settings.get(
                        "voice",
                        DEFAULT_VOICE,
                    ),
                }

                self._js(
                    "window.NEBIX && "
                    "window.NEBIX.setState && "
                    "window.NEBIX.setState("
                    + json.dumps(
                        payload,
                        ensure_ascii=False,
                    )
                    + ");"
                )

                activity = self.get_activity()

                if activity:

                    self._js(
                        "window.NEBIX && "
                        "window.NEBIX.restoreActivity && "
                        "window.NEBIX.restoreActivity("
                        + json.dumps(
                            activity,
                            ensure_ascii=False,
                        )
                        + ");"
                    )

            except Exception:
                pass

            if self.settings.get("startMinimized"):
                self.minimize()

        # ----------------------------------------------------
        # Closing
        # ----------------------------------------------------

        def on_closing(*args, **kwargs):
            self.request_shutdown()

        # ----------------------------------------------------
        # Closed
        # ----------------------------------------------------

        def on_closed(*args, **kwargs):
            self._mark_webview_closed()

            with self._window_lock:
                if self._window is window:
                    self._window = None

        # ----------------------------------------------------
        # Events
        # ----------------------------------------------------

        try:
            window.events.loaded += on_loaded
        except Exception:
            pass

        try:
            window.events.closing += on_closing
        except Exception:
            pass

        try:
            window.events.closed += on_closed
        except Exception:
            pass

        # ----------------------------------------------------
        # Start
        # ----------------------------------------------------

        try:

            try:
                webview.start(
                    gui="edgechromium",
                    debug=debug,
                )

            except TypeError:
                webview.start(
                    debug=debug,
                )

        finally:

            # Do not wait for an outstanding evaluate_js() call after the GUI loop exits.
            self.request_shutdown()
            with self._window_lock:
                self._ready = False
                self._closing = True
                self._closed = True
                if self._window is window:
                    self._window = None

    # ========================================================
    # SHOW
    # ========================================================

    def show(self):
        return self.start()

    # ========================================================
    # DESIGN
    # ========================================================

    def set_design(self, design):

        try:
            design = int(design)
        except Exception:
            return False

        if design < 1 or design > 10:
            return False

        self.design = design

        return True

    # ========================================================
    # ACTIVATE
    # ========================================================

    def activate(self):

        self.activated = True
        self.powered_off = False
        self.state = "ACTIVE"
        self.state_message = "NEBIX is active."

        self.write_log(
            "NEBIX activated."
        )

        self.set_state(
            "ACTIVE",
            "NEBIX is active.",
        )

        return {
            "activated": True,
            "state": self.state,
        }

    # ========================================================
    # STOP
    # ========================================================

    def stop(self):

        self.activated = False
        self.powered_off = True
        self.state = "STANDBY"
        self.state_message = "NEBIX is in standby."

        self.write_log(
            "NEBIX stopped."
        )

        self.set_state(
            "STANDBY",
            "NEBIX is disconnected.",
        )

        callback = self.on_interrupt

        if callback:
            try:
                callback()
            except Exception:
                traceback.print_exc()

        power_off_callback = self.on_power_off
        if power_off_callback:
            power_off_callback()

        self.set_state(
            "STANDBY",
            "NEBIX is in standby.",
        )

        return {
            "activated": False,
            "state": self.state,
        }

    # ========================================================
    # RESET
    # ========================================================

    def reset(self):

        self.last_response = ""
        self.state = "READY"
        self.state_message = "NEBIX session reset."

        self.write_log(
            "Session reset."
        )

        self.set_state(
            "READY",
            "NEBIX session reset.",
        )

        return {
            "state": self.state,
        }

    # ========================================================
    # STATUS
    # ========================================================

    def get_status(self):

        uptime = max(
            0,
            int(time.time() - self.started_at),
        )

        with self._window_lock:
            web_ready = bool(
                self._window is not None
                and self._ready
                and not self._closing
                and not self._closed
            )

        return {
            "ok": True,
            "app": "NEBIX",
            "connected": bool(self.connected),
            "voice_session_state": self.voice_session_state,
            "voice_session_message": self.voice_session_message,
            "activated": bool(self.activated),
            "active": bool(self.activated),
            "state": self.state,
            "message": self.state_message,
            "design": self.design,
            "activation_required": bool(
                self.activation_required
            ),
            "uptime": uptime,
            "ready": web_ready,
            "phone_connected": bool(
                self.phone_connected
            ),
            "camera_active": bool(
                self.camera_active
            ),
            "has_api_key": bool(
                self.wait_for_api_key()
            ),
            "voice": _get_saved_voice(),
            "available_voices": list(
                AVAILABLE_VOICES
            ),
        }

    # ========================================================
    # SYSTEM INFORMATION
    # ========================================================

    def get_system(self):

        cpu = 0.0
        ram = 0.0
        disk = 0.0
        gpu = None
        network = None
        battery = None
        battery_plugged = None
        battery_state = None
        power_source = None
        total_ram = None
        uptime = None

        if psutil:

            try:
                cpu = float(
                    psutil.cpu_percent(
                        interval=None
                    )
                )
            except Exception:
                pass

            try:
                ram_info = psutil.virtual_memory()

                ram = float(
                    ram_info.percent
                )

                total_ram = (
                    f"{ram_info.total / (1024 ** 3):.1f} GB"
                )

            except Exception:
                pass

            try:
                disk = float(
                    psutil.disk_usage(
                        os.path.abspath(os.sep)
                    ).percent
                )
            except Exception:
                pass

            try:
                counters = psutil.net_io_counters()
                now = time.monotonic()
                previous = self._network_sample
                self._network_sample = (
                    now,
                    counters.bytes_sent + counters.bytes_recv,
                )
                if previous:
                    elapsed = now - previous[0]
                    if elapsed > 0:
                        network = max(
                            0.0,
                            (self._network_sample[1] - previous[1])
                            / elapsed
                            / 1024,
                        )
            except Exception:
                pass

            try:
                batt = psutil.sensors_battery()

                if batt:
                    battery = float(
                        batt.percent
                    )
                    battery_plugged = (
                        bool(batt.power_plugged)
                        if batt.power_plugged is not None
                        else None
                    )
                    battery_state = (
                        "Charging"
                        if batt.power_plugged and batt.percent < 100
                        else "Not charging"
                        if batt.power_plugged is not None
                        else "Unknown"
                    )
                    power_source = (
                        "AC power"
                        if batt.power_plugged
                        else "Battery power"
                    )

            except Exception:
                pass

            try:
                uptime = max(0, int(time.time() - psutil.boot_time()))
            except Exception:
                pass

        if platform.system() == "Windows":
            try:
                import ctypes

                class _SystemPowerStatus(ctypes.Structure):
                    _fields_ = [
                        ("ACLineStatus", ctypes.c_ubyte),
                        ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte),
                        ("SystemStatusFlag", ctypes.c_ubyte),
                        ("BatteryLifeTime", ctypes.c_ulong),
                        ("BatteryFullLifeTime", ctypes.c_ulong),
                    ]

                power_status = _SystemPowerStatus()
                if ctypes.windll.kernel32.GetSystemPowerStatus(
                    ctypes.byref(power_status)
                ):
                    if power_status.ACLineStatus in (0, 1):
                        battery_plugged = power_status.ACLineStatus == 1
                        power_source = (
                            "AC power"
                            if battery_plugged
                            else "Battery power"
                        )
                    if power_status.BatteryLifePercent <= 100:
                        battery = float(power_status.BatteryLifePercent)
                    if power_status.BatteryFlag == 255:
                        battery_state = "Unknown"
                    elif power_status.BatteryFlag & 8:
                        battery_state = "Charging"
                    elif power_status.BatteryFlag & 128:
                        battery_state = "No battery"
                    else:
                        battery_state = "Not charging"
            except (AttributeError, OSError, ValueError):
                pass

        if _get_gpu_usage is not None:
            try:
                measured_gpu = float(_get_gpu_usage())
                if measured_gpu >= 0:
                    gpu = round(measured_gpu, 1)
            except Exception:
                pass

        cpu_name = (
            platform.processor()
            or platform.machine()
            or "Unknown CPU"
        )

        os_name = (
            f"{platform.system()} "
            f"{platform.release()}"
        )

        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = "Unknown"

        return {
            "ok": True,
            "cpu": round(cpu, 1),
            "ram": round(ram, 1),
            "disk": round(disk, 1),
            "gpu": gpu,
            "network": round(network, 1) if network is not None else None,
            "battery": (
                round(battery, 1)
                if battery is not None
                else None
            ),
            "battery_plugged": battery_plugged,
            "battery_state": battery_state,
            "power_source": power_source,
            "uptime_seconds": uptime,
            "os": os_name,
            "cpu_name": cpu_name,
            "total_ram": (
                total_ram
                or "Unknown"
            ),
            "hostname": hostname,
            "nebix_status": self.state,
            "activated": bool(self.activated),
            "connected": bool(self.connected),
            "voice": _get_saved_voice(),
        }

    # ========================================================
    # SETTINGS
    # ========================================================

    def get_settings(self):
        manager = getattr(self, "settings_manager", None)
        return manager.get_settings() if manager else self._get_settings()

    def _get_settings(self):

        self.settings["voice"] = _get_saved_voice()
        from core.ai_providers import get_provider_settings

        ai_settings = get_provider_settings(
            gemini_live_connected=bool(self.connected),
        )
        active_provider = next(
            (
                item
                for item in ai_settings["providers"]
                if item["id"] == ai_settings["activeProvider"]
            ),
            None,
        )
        if platform.system() == "Windows":
            try:
                from config.windows_shortcut import startup_shortcut_path
                self.settings["startupEnabled"] = startup_shortcut_path().is_file()
            except Exception:
                pass

        return {
            **self.settings,
            "activationRequired": bool(
                self.activation_required
            ),
            "availableVoices": list(
                AVAILABLE_VOICES
            ),
            "availablePerformanceModes": available_performance_modes(),
            "activePerformanceMode": active_performance_mode(),
            "activeProvider": active_provider["name"] if active_provider else "Not connected",
            "activeModel": (
                active_provider["model"]
                if active_provider and active_provider["id"] != "gemini"
                else getattr(self, "active_model", None)
            ),
            "providerConnected": bool(self.connected),
            "aiProviders": ai_settings["providers"],
            "activeAiProvider": ai_settings["activeProvider"],
            "activeAiModel": ai_settings["activeModel"],
            "clockSettingsPersisted": getattr(self, "_clock_settings_persisted", False),
            "permissionCatalog": get_permission_catalog(),
        }

    def set_settings(self, settings):
        manager = getattr(self, "settings_manager", None)
        if manager:
            return manager.set_settings(settings)
        return self._apply_settings(settings)

    def _apply_settings(self, settings):

        if not isinstance(settings, dict):
            return self.get_settings()

        allowed = {
            "startup",
            "minimized",
            "activity",
            "voice",
            "wakeWord",
            "wakeWordText",
            "activationRequired",
            "confirmSensitive",
            "permissions",
            "voiceLayout",
            "theme",
            "settingsTheme",
            "clockSettings",
            "voiceInterfaceCustomization",
            "interfaceProfiles",
            "chatTheme",
            "quickAccess",
            "digitalText",
            "personalResponse",
            "whatsappStyle",
            "performanceMode",
            "backgroundEfficiency",
            "startupEnabled",
            "startMinimized",
            "restorePreviousInterface",
        }

        voice_changed = None
        communication_changed = False
        whatsapp_style_changed = False
        previous_values = {
            key: self.settings.get(key)
            for key in allowed
            if key in self.settings
        }
        previous_power_mode = active_performance_mode()
        power_mode_changed = False

        for key in allowed:

            if key not in settings:
                continue

            value = settings[key]

            if key in {
                "startup",
                "minimized",
                "activity",
                "wakeWord",
                "activationRequired",
                "confirmSensitive",
                "startupEnabled",
                "startMinimized",
                "restorePreviousInterface",
            }:

                if key in {
                    "startupEnabled",
                    "startMinimized",
                    "restorePreviousInterface",
                }:
                    if not isinstance(value, bool):
                        return {"ok": False, "error": f"{key} must be true or false."}
                else:
                    value = bool(value)

            elif key == "voice":

                value = str(
                    value or ""
                ).strip()

                if not value:
                    continue

                if value not in AVAILABLE_VOICES:
                    return {
                        "ok": False,
                        "error": (
                            f"Unsupported voice: {value}"
                        ),
                        "availableVoices": list(
                            AVAILABLE_VOICES
                        ),
                    }

                current = _get_saved_voice()

                if value != current:

                    _save_voice(value)

                    voice_changed = value

                self.settings["voice"] = value

                continue

            elif key == "wakeWordText":

                value = str(
                    value or ""
                ).strip()

                if not value:
                    value = "NEBIX"

            elif key == "voiceLayout":
                value = _normalize_interface_id(value)
                if value not in INTERFACE_IDS:
                    return {"ok": False, "error": "Unsupported voice interface layout."}

            elif key == "theme":
                value = str(value or "dark").strip().lower()
                if value not in {"dark", "light"}:
                    return {"ok": False, "error": "Unsupported theme."}

            elif key == "settingsTheme":
                value = str(value or "light").strip().lower()
                if value not in {"dark", "light"}:
                    return {"ok": False, "error": "Unsupported Settings theme."}

            elif key == "clockSettings":
                if not isinstance(value, dict):
                    return {"ok": False, "error": "Clock settings must be an object."}
                current_clock = self.settings.get("clockSettings", {})
                clock = dict(current_clock) if isinstance(current_clock, dict) else {}
                clock.update(value)
                if clock.get("style") not in INTERFACE_PROFILE_COMPONENT_STYLES["clock"]:
                    return {"ok": False, "error": "Unsupported Clock style."}
                for property_name, minimum, maximum in (
                    ("size", 20, 68),
                    ("weight", 300, 800),
                    ("letterSpacing", -5, 18),
                ):
                    amount = clock.get(property_name)
                    if (
                        isinstance(amount, bool)
                        or not isinstance(amount, (int, float))
                        or not minimum <= amount <= maximum
                    ):
                        return {"ok": False, "error": f"Clock {property_name} must be between {minimum} and {maximum}."}
                    clock[property_name] = round(amount)
                clock["format"] = "mm:ss"
                value = clock

            elif key == "permissions":
                try:
                    value = merge_permission_state(
                        self.settings.get("permissions"),
                        value,
                    )
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}

            elif key == "voiceInterfaceCustomization":
                try:
                    value = _merge_voice_interface_customization(
                        self.settings.get("voiceInterfaceCustomization"),
                        value,
                    )
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}

            elif key == "interfaceProfiles":
                try:
                    value = _merge_interface_profiles(
                        self.settings.get("interfaceProfiles"),
                        value,
                    )
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}

            elif key == "chatTheme":
                if not isinstance(value, dict):
                    return {"ok": False, "error": "Chat theme settings must be an object."}
                try:
                    encoded_chat_theme = json.dumps(
                        value,
                        ensure_ascii=False,
                    ).encode("utf-8")
                    if len(encoded_chat_theme) > MAX_CHAT_THEME_BYTES:
                        return {"ok": False, "error": "Chat theme settings exceed the 3 MB limit."}
                    value = json.loads(encoded_chat_theme.decode("utf-8"))
                except (TypeError, ValueError, UnicodeError) as exc:
                    return {"ok": False, "error": f"Chat theme settings are invalid: {exc}"}

            elif key == "quickAccess":
                try:
                    value = normalize_quick_access_settings(value)
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}

            elif key == "digitalText":
                if not isinstance(value, dict):
                    return {"ok": False, "error": "Digital Text settings must be an object."}
                current_digital_text = self.settings.get("digitalText")
                merged_digital_text = (
                    dict(current_digital_text)
                    if isinstance(current_digital_text, dict)
                    else {}
                )
                merged_digital_text.update(value)
                value = merged_digital_text
                if not isinstance(value.get("enabled"), bool):
                    return {"ok": False, "error": "Digital Text enabled must be true or false."}
                if not isinstance(value.get("message"), str):
                    return {"ok": False, "error": "Digital Text message must be text."}
                if not value["message"].strip():
                    return {"ok": False, "error": "Enter a message before saving Digital Text settings."}
                try:
                    encoded_digital_text = json.dumps(
                        value,
                        ensure_ascii=False,
                    ).encode("utf-8")
                    if len(encoded_digital_text) > MAX_DIGITAL_TEXT_BYTES:
                        return {"ok": False, "error": "Digital Text settings exceed the 16 KB limit."}
                    value = json.loads(encoded_digital_text.decode("utf-8"))
                except (TypeError, ValueError, UnicodeError) as exc:
                    return {"ok": False, "error": f"Digital Text settings are invalid: {exc}"}

            elif key == "personalResponse":
                try:
                    value = validate_personal_response_settings(value)
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
                communication_changed = (
                    value != self.settings.get("personalResponse")
                )

            elif key == "whatsappStyle":
                try:
                    value = validate_whatsapp_style_settings(value)
                except ValueError as exc:
                    return {"ok": False, "error": str(exc)}
                whatsapp_style_changed = (
                    value != self.settings.get("whatsappStyle")
                )
                communication_changed = communication_changed or whatsapp_style_changed

            elif key == "performanceMode":
                if not isinstance(value, str) or value not in {"balanced", "performance", "battery_saver"}:
                    return {"ok": False, "error": "Unsupported Performance Mode."}
                power_mode_changed = value != self.settings.get("performanceMode")

            elif key == "backgroundEfficiency":
                if not isinstance(value, str) or value not in {
                    "Normal",
                    "Reduced Background Activity",
                    "Maximum Efficiency",
                }:
                    return {"ok": False, "error": "Unsupported Background Efficiency mode."}

            self.settings[key] = value

        startup_changed = "startupEnabled" in settings
        if power_mode_changed:
            try:
                set_performance_mode(self.settings["performanceMode"])
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
                for key, value in previous_values.items():
                    self.settings[key] = value
                return {"ok": False, "error": str(exc)}

        if startup_changed:
            if platform.system() != "Windows" or set_autostart is None:
                for key, value in previous_values.items():
                    self.settings[key] = value
                if power_mode_changed and previous_power_mode:
                    try:
                        set_performance_mode(previous_power_mode)
                    except Exception:
                        traceback.print_exc()
                return {"ok": False, "error": "Windows startup control is unavailable on this platform."}
            try:
                set_autostart(self.settings["startupEnabled"])
            except Exception as exc:
                for key, value in previous_values.items():
                    self.settings[key] = value
                if power_mode_changed and previous_power_mode:
                    try:
                        set_performance_mode(previous_power_mode)
                    except Exception:
                        traceback.print_exc()
                return {"ok": False, "error": f"Could not update Windows startup: {exc}"}

        if (
            "voiceLayout" in settings
            or "theme" in settings
            or "settingsTheme" in settings
            or "clockSettings" in settings
            or "activity" in settings
            or "confirmSensitive" in settings
            or "permissions" in settings
            or "voiceInterfaceCustomization" in settings
            or "interfaceProfiles" in settings
            or "chatTheme" in settings
            or "quickAccess" in settings
            or "digitalText" in settings
            or "personalResponse" in settings
            or "whatsappStyle" in settings
            or "performanceMode" in settings
            or "backgroundEfficiency" in settings
            or "startupEnabled" in settings
            or "startMinimized" in settings
            or "restorePreviousInterface" in settings
        ):
            try:
                self.settings_manager.save_persisted_settings(self.settings)
            except Exception as exc:
                for key, value in previous_values.items():
                    self.settings[key] = value
                if power_mode_changed and previous_power_mode:
                    try:
                        set_performance_mode(previous_power_mode)
                    except Exception:
                        traceback.print_exc()
                if startup_changed and platform.system() == "Windows" and set_autostart is not None:
                    try:
                        set_autostart(previous_values.get("startupEnabled", False))
                    except Exception:
                        traceback.print_exc()
                return {"ok": False, "error": f"Could not save settings: {exc}"}
            if "clockSettings" in settings:
                self._clock_settings_persisted = True

        self.activation_required = bool(
            self.settings.get(
                "activationRequired",
                True,
            )
        )

        if voice_changed:

            callback = self.on_voice_change

            if callback:

                try:
                    callback(voice_changed)
                except TypeError:
                    callback()

            self.write_log(
                f"Voice selected: {voice_changed}"
            )

            self.set_state(
                "THINKING",
                (
                    "Switching voice to "
                    f"{voice_changed}..."
                ),
            )

        else:

            self.write_log(
                "Settings updated."
            )

        if communication_changed and self.on_communication_profile_change:
            self.on_communication_profile_change()

        return self.get_settings()

    # ========================================================
    # JAVASCRIPT EXECUTION
    # ========================================================

    def _js(self, script, callback=None):

        if not script or self.shutdown_event.is_set():
            return None

        script = str(script)

        # ----------------------------------------------------
        # Serialize ordinary calls, but never require the GUI close path to
        # acquire this lock. The close callback may run on the WebView thread.
        # ----------------------------------------------------

        with self._js_lock:

            with self._window_lock:

                window = self._window
                generation = self._webview_generation

                if (
                    window is None
                    or not self._ready
                    or self._closing
                    or self._closed
                    or self.shutdown_event.is_set()
                ):
                    return None

            # ------------------------------------------------
            # Final lifecycle check immediately before call.
            # ------------------------------------------------

            with self._window_lock:

                if (
                    window is not self._window
                    or generation != self._webview_generation
                    or not self._ready
                    or self._closing
                    or self._closed
                    or self.shutdown_event.is_set()
                ):
                    return None

            try:

                return window.evaluate_js(script, callback=callback)

            except Exception as exc:

                error_text = str(
                    exc or ""
                ).lower()

                disposed_errors = (
                    "disposed object",
                    "object has been disposed",
                    "cannot access a disposed",
                    "webview2",
                    "browser process",
                    "browser is disposed",
                    "control.invoke",
                    "marshaledinvoke",
                    "invalid operation",
                    "element is no longer attached",
                )

                if any(
                    item in error_text
                    for item in disposed_errors
                ):

                    # Do not print the expected lifecycle
                    # disposal error to the console.
                    #
                    # The backend/Gemini system must continue
                    # safely even if the frontend has gone away.

                    with self._window_lock:

                        if self._window is window:

                            self._ready = False
                            self._closing = True

                    return None

                # ------------------------------------------------
                # Never allow a frontend JS failure to kill
                # Gemini Live/backend execution.
                # ------------------------------------------------

                message = f"Frontend JavaScript dispatch failed: {exc}"
                print(f"[NEBIX] {message}")
                traceback.print_exc()
                with self._log_lock:
                    self._logs.append(
                        {
                            "time": nepal_now().strftime("%H:%M:%S"),
                            "text": f"ERR: {message}",
                        }
                    )
                    if len(self._logs) > 500:
                        self._logs = self._logs[-500:]

                return None

    # ========================================================
    # RESPONSE
    # ========================================================

    def set_response(self, text):

        text = str(text or "")

        self.last_response = text

        self._js(
            "window.NEBIX && "
            "window.NEBIX.setResponse && "
            "window.NEBIX.setResponse("
            + json.dumps(
                text,
                ensure_ascii=False,
            )
            + ");"
        )

    def set_chat_delta(self, request_id, text, trace=None):
        payload = {
            "request_id": str(request_id or ""),
            "text": str(text or ""),
        }
        if os.environ.get("NEBIX_LATENCY_TRACE") == "1" and trace:
            payload["trace"] = trace
        self._js(
            "window.NEBIX && window.NEBIX.chatDelta && window.NEBIX.chatDelta("
            + json.dumps(payload, ensure_ascii=False)
            + ");"
        )

    def set_chat_message(self, role, text, request_id=None, trace=None):
        payload = {"role": str(role or "assistant"), "text": str(text or "")}
        if request_id:
            payload["request_id"] = str(request_id)
        if os.environ.get("NEBIX_LATENCY_TRACE") == "1" and trace:
            trace_payload = dict(trace)
            python_completed_at = trace_payload.pop("python_completed_at", None)
            trace_payload["pythonUiDispatchMs"] = round(
                (time.perf_counter() - python_completed_at) * 1000,
                2,
            ) if isinstance(python_completed_at, (int, float)) else None
            payload["trace"] = trace_payload
        self._js(
            "window.NEBIX && window.NEBIX.chatMessage && window.NEBIX.chatMessage("
            + json.dumps(payload, ensure_ascii=False)
            + ");"
        )

    # ========================================================
    # STATE
    # ========================================================

    def set_state(
        self,
        state,
        message="",
    ):

        self.state = str(
            state or "READY"
        ).upper()

        self.state_message = str(
            message or ""
        )

        payload = {
            "state": self.state,
            "message": self.state_message,
            "activated": bool(
                self.activated
            ),
            "connected": bool(
                self.connected
            ),
            "voiceSessionState": self.voice_session_state,
            "voiceSessionMessage": self.voice_session_message,
            "voice": self.settings.get(
                "voice",
                DEFAULT_VOICE,
            ),
        }

        self._js(
            "window.NEBIX && "
            "window.NEBIX.setState && "
            "window.NEBIX.setState("
            + json.dumps(
                payload,
                ensure_ascii=False,
            )
            + ");"
        )

    # ========================================================
    # METRICS
    # ========================================================

    def update_metrics(
        self,
        cpu=0,
        ram=0,
        gpu=0,
        upload=0,
        download=0,
    ):

        payload = {
            "cpu": float(cpu or 0),
            "ram": float(ram or 0),
            "gpu": float(gpu or 0),
            "upload": float(upload or 0),
            "download": float(download or 0),
        }

        self._js(
            "window.NEBIX && "
            "window.NEBIX.setMetrics && "
            "window.NEBIX.setMetrics("
            + json.dumps(
                payload,
                ensure_ascii=False,
            )
            + ");"
        )

    # ========================================================
    # AUDIO LEVEL
    # ========================================================

    def set_audio_level(self, level):

        try:
            self.audio_level = float(
                level or 0
            )
        except Exception:
            self.audio_level = 0.0

        self._js(
            "window.NEBIX && "
            "window.NEBIX.setAudioLevel && "
            "window.NEBIX.setAudioLevel("
            + json.dumps(
                self.audio_level
            )
            + ");"
        )

    # ========================================================
    # ACTIVITY LOG
    # ========================================================

    def write_log(self, message):

        message = str(message or "")

        if not message:
            return

        entry = {
            "time": nepal_now().strftime("%H:%M:%S"),
            "text": message,
        }

        with self._log_lock:

            self._logs.append(entry)

            if len(self._logs) > 500:
                self._logs = self._logs[-500:]

        if not self.settings.get(
            "activity",
            True,
        ):
            return

        self._js(
            "window.NEBIX && "
            "window.NEBIX.addActivity && "
            "window.NEBIX.addActivity("
            + json.dumps(
                entry,
                ensure_ascii=False,
            )
            + ");"
        )

    def get_activity(self):

        with self._log_lock:
            return list(self._logs)

    def clear_activity(self):

        with self._log_lock:
            self._logs.clear()

        self._js(
            "window.NEBIX && "
            "window.NEBIX.clearActivity && "
            "window.NEBIX.clearActivity();"
        )

        return {
            "ok": True,
        }

    # ========================================================
    # CONTENT
    # ========================================================

    def show_content(
        self,
        title,
        content,
    ):

        self.content_title = str(
            title or ""
        )

        self.content_text = str(
            content or ""
        )

        payload = {
            "title": self.content_title,
            "content": self.content_text,
        }

        self._js(
            "window.NEBIX && "
            "window.NEBIX.showContent && "
            "window.NEBIX.showContent("
            + json.dumps(
                payload,
                ensure_ascii=False,
            )
            + ");"
        )

    def open_browser(self, url, new_tab=False):
        """Show a validated web URL inside NEBIX's Chromium WebView2 surface."""
        from urllib.parse import urlparse

        value = str(url or "").strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        return self._js(
            "window.NEBIX && typeof window.NEBIX.openBrowser === 'function' "
            "&& window.NEBIX.openBrowser(" + json.dumps(value) + ", "
            + ("true" if new_tab else "false") + ");"
        ) is True

    # ========================================================
    # CAMERA
    # ========================================================

    def start_camera_stream(self):

        self.camera_active = True

        self._js(
            "window.NEBIX && "
            "window.NEBIX.cameraStarted && "
            "window.NEBIX.cameraStarted();"
        )

    def stop_camera_stream(self):

        self.camera_active = False

        self._js(
            "window.NEBIX && "
            "window.NEBIX.cameraStopped && "
            "window.NEBIX.cameraStopped();"
        )

    # ========================================================
    # CONFIRMATION
    # ========================================================

    def show_confirm(
        self,
        title,
        message,
        callback=None,
    ):

        self._confirm_callback = callback

        payload = {
            "title": str(
                title or "Confirm"
            ),
            "message": str(
                message or ""
            ),
        }

        script = (
            "(function(){"
            "if (!window.NEBIX || "
            "typeof window.NEBIX.showConfirm !== 'function') return false;"
            "window.NEBIX.showConfirm("
            + json.dumps(payload, ensure_ascii=False)
            + ");return true;})()"
        )
        try:
            shown = self._js(script)
        except Exception:
            self._confirm_callback = None
            raise
        if shown is not True:
            self._confirm_callback = None
            raise RuntimeError(
                "The confirmation dialog could not be displayed; "
                "the action was not performed."
            )

    def hide_confirm(self):

        self._confirm_callback = None

        self._js(
            "window.NEBIX && "
            "window.NEBIX.hideConfirm && "
            "window.NEBIX.hideConfirm();"
        )

    def confirm_result(
        self,
        accepted=False,
    ):

        callback = self._confirm_callback

        self._confirm_callback = None

        if callback:

            try:

                return callback(
                    bool(accepted)
                )

            except TypeError:

                try:
                    return callback()

                except Exception:
                    traceback.print_exc()

            except Exception:
                traceback.print_exc()

        return bool(accepted)

    # ========================================================
    # PHONE
    # ========================================================

    def notify_phone_connected(self):

        self.phone_connected = True

        self._js(
            "window.NEBIX && "
            "window.NEBIX.phoneConnected && "
            "window.NEBIX.phoneConnected();"
        )

        self.write_log(
            "Phone connected."
        )

    # ========================================================
    # API CONFIGURATION
    # ========================================================

    def prompt_reconfig(self):

        self._js(
            "window.NEBIX && "
            "window.NEBIX.showApiConfig && "
            "window.NEBIX.showApiConfig();"
        )

    # ========================================================
    # PLUGINS
    # ========================================================

    def plugin_list(self):

        if not self.get_plugins:
            return []

        try:
            result = self.get_plugins()

            return _safe_json(result)

        except Exception:
            traceback.print_exc()
            return []

    def plugin_settings(self):

        if not self.get_plugin_settings:
            return {}

        try:
            result = self.get_plugin_settings()

            return _safe_json(result)

        except Exception:
            traceback.print_exc()
            return {}

    # ========================================================
    # WAKE STATE
    # ========================================================

    def wake_state(self):

        ready = False
        state = {}

        if self.wake_is_ready:

            try:
                ready = bool(
                    self.wake_is_ready()
                )
            except Exception:
                pass

        if self.wake_get_state:

            try:
                state = (
                    self.wake_get_state()
                    or {}
                )
            except Exception:
                state = {}

        return {
            "ready": ready,
            "state": _safe_json(state),
        }

    # ========================================================
    # WINDOW HELPERS
    # ========================================================

    def minimize(self):

        with self._window_lock:

            window = self._window

            if (
                window is None
                or self._closing
                or self._closed
            ):
                return False

        try:
            window.minimize()
            return True

        except Exception:
            return False

    def toggle_fullscreen(self):

        with self._window_lock:

            window = self._window

            if (
                window is None
                or self._closing
                or self._closed
            ):
                return False

        try:

            current = bool(
                getattr(
                    window,
                    "fullscreen",
                    False,
                )
            )

            window.toggle_fullscreen()

            return not current

        except Exception:
            return False

    # ========================================================
    # CLOSE
    # ========================================================

    def close(self):
        self.request_shutdown()
        with self._window_lock:
            window = self._window

        if window is None:
            self._closed = True
            return True

        threading.Thread(
            target=self._destroy_window,
            args=(window,),
            name="NEBIX-WebViewClose",
            daemon=True,
        ).start()
        return True

    def _destroy_window(self, window):
        try:
            window.destroy()
        except Exception:
            traceback.print_exc()
        finally:
            with self._window_lock:
                self._closed = True
                self._ready = False
                self._closing = True
                if self._window is window:
                    self._window = None

    # ========================================================
    # READY PROPERTY
    # ========================================================

    @property
    def ready(self):
        return self._is_webview_available()


# ============================================================
# END OF FILE
# ============================================================
