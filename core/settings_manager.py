from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from core.paths import (
    APIConfigDecryptionError,
    get_ui_settings_file,
    load_api_config,
)


_SETTINGS_LOCK = threading.RLock()
_DENSITIES = ("compact", "standard", "spacious")
_POSITIONS = ("left", "center", "right")
_CHAT_THEMES = {
    "nebix-dark": "NEBIX Dark",
    "nebix-light": "NEBIX Light",
    "midnight": "Midnight",
    "aurora": "Aurora",
    "cyber-cyan": "Cyber Cyan",
    "neon-purple": "Neon Purple",
    "emerald": "Emerald",
    "crimson": "Crimson",
    "ocean": "Ocean",
    "sunset": "Sunset",
    "glass": "Glass",
    "amoled": "AMOLED",
    "cyberpunk": "Cyberpunk",
    "minimal": "Minimal",
}
_CLOCK_DEFAULTS = {
    "style": "current",
    "size": 48,
    "weight": 700,
    "letterSpacing": 5,
    "format": "mm:ss",
}
_QUICK_ACCESS_ID = re.compile(r"^[a-f0-9]{24}$")


def normalize_quick_access_settings(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise ValueError("Quick Access settings must be an object.")
    normalized: dict[str, list[str]] = {}
    for key, limit in (("favorites", 500), ("recent", 32)):
        items = value.get(key, [])
        if not isinstance(items, list):
            raise ValueError(f"Quick Access {key} must be a list.")
        unique: list[str] = []
        for item in items:
            if not isinstance(item, str) or not _QUICK_ACCESS_ID.fullmatch(item):
                raise ValueError(f"Quick Access {key} contains an invalid application ID.")
            if item not in unique:
                unique.append(item)
            if len(unique) > limit:
                raise ValueError(f"Quick Access {key} supports up to {limit} applications.")
        normalized[key] = unique
    return normalized
_PERSISTED_KEYS = (
    "confirmSensitive",
    "permissions",
    "voiceLayout",
    "theme",
    "settingsTheme",
    "activity",
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
    "clockSettings",
)
_BULK_SETTING_KEYS = {
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
    "clockSettings",
}
_ALIASES = {
    "activity_density": "interface.components.activityLog.density",
    "clock_style": "interface.components.clock.style",
    "clock_position": "interface.components.clock.position",
    "command_position": "interface.components.commandBar.position",
    "activity_position": "interface.components.activityLog.position",
    "weather_position": "interface.components.weather.position",
    "monitor_position": "interface.components.systemMonitor.position",
    "interface_layout": "interface.layout",
    "interface_theme": "interface.theme",
    "interface_density": "interface.density",
    "settings_theme": "interface.settingsTheme",
    "chat_theme": "chat.theme",
    "assistant_voice": "voice.selection",
    "startup_enabled": "startup.enabled",
    "start_minimized": "startup.minimized",
    "ai_provider": "ai.provider",
}
_SETTING_INFO = {
    "voiceLayout": ("interface.layout", "Interface layout", "Interface", "Selects the active Voice layout.", "Settings → Interface → Preset", ("default", "interface1", "interface2", "interface3", "interface4", "interface5"), "immediate", False),
    "theme": ("interface.theme", "Interface theme", "Interface", "Sets the Voice interface theme.", "Settings → Global Appearance → Theme", ("dark", "light"), "immediate", False),
    "settingsTheme": ("interface.settingsTheme", "Settings theme", "Interface", "Sets the appearance of the Settings workspace.", "Settings → Global Appearance → Settings appearance", ("dark", "light"), "immediate", False),
    "activity": ("general.activityLogging", "Activity logging", "General", "Enables or disables Activity logging.", "Settings → General", (True, False), "immediate", False),
    "voice": ("voice.selection", "Assistant voice", "Voice", "Selects the Gemini Live voice.", "Settings → Voice & Audio", None, "immediate", False),
    "performanceMode": ("automation.performanceMode", "Performance mode", "Automation", "Selects the Windows power plan mode.", "Settings → Power & Performance", ("balanced", "performance", "battery_saver"), "immediate", False),
    "backgroundEfficiency": ("automation.backgroundEfficiency", "Background efficiency", "Automation", "Selects background polling efficiency.", "Settings → Power & Performance", ("Normal", "Reduced Background Activity", "Maximum Efficiency"), "immediate", False),
    "startupEnabled": ("automation.startupEnabled", "Start with Windows", "Automation", "Controls the existing Windows Startup shortcut.", "Settings → System Startup & Launch", (True, False), "immediate", False),
    "startMinimized": ("automation.startMinimized", "Start minimized", "Automation", "Minimizes NEBIX after a future launch.", "Settings → System Startup & Launch", (True, False), "next_launch", False),
    "restorePreviousInterface": ("automation.restorePreviousInterface", "Restore previous interface", "Automation", "Opens the last-used Voice interface on launch.", "Settings → System Startup & Launch", (True, False), "next_launch", False),
}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class SettingsManager:
    """Single validated interface for NEBIX's persisted UI settings."""

    def __init__(
        self,
        ui: Any,
        *,
        interface_ids: set[str],
        component_styles: dict[str, set[str]],
        voices: list[str],
    ) -> None:
        self._ui = ui
        self._interface_ids = tuple(sorted(interface_ids))
        self._component_styles = component_styles
        self._voices = tuple(voices)

    def load_persisted_settings(self) -> dict[str, Any]:
        with _SETTINGS_LOCK:
            path = get_ui_settings_file()
            if path.is_file():
                saved = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(saved, dict):
                    raise ValueError(f"UI settings must be an object: {path}")
                return saved

            try:
                config = load_api_config()
            except APIConfigDecryptionError:
                # API credentials are independent of UI preferences. Keep
                # startup usable so Settings can repair an unreadable key.
                return {}
            legacy = config.get("ui_settings")
            if not isinstance(legacy, dict):
                return {}
            _write_json(path, legacy)
            return legacy

    def save_persisted_settings(self, settings: dict[str, Any]) -> None:
        payload = {
            key: settings[key]
            for key in _PERSISTED_KEYS
            if key in settings
        }
        with _SETTINGS_LOCK:
            _write_json(get_ui_settings_file(), payload)

    def get_settings(self) -> dict[str, Any]:
        getter = getattr(self._ui, "_get_settings", None)
        if not callable(getter):
            raise RuntimeError("NEBIX settings source is unavailable.")
        return getter()

    def set_settings(self, settings: Any) -> dict[str, Any]:
        if not isinstance(settings, dict):
            return {"ok": False, "error": "Settings must be an object."}
        unknown = sorted(set(settings) - _BULK_SETTING_KEYS)
        if unknown:
            return {
                "ok": False,
                "error": f"Unsupported setting key: {', '.join(unknown)}.",
            }
        setter = getattr(self._ui, "_apply_settings", None)
        if not callable(setter):
            raise RuntimeError("NEBIX settings controller is unavailable.")
        with _SETTINGS_LOCK:
            result = setter(settings)
        if isinstance(result, dict) and result.get("ok") is False:
            return result
        return result if isinstance(result, dict) else self.get_settings()

    def get_setting_registry(self) -> list[dict[str, Any]]:
        settings = self.get_settings()
        items: list[dict[str, Any]] = []
        for key, metadata in _SETTING_INFO.items():
            setting_id, name, category, description, location, choices, mode, restart = metadata
            allowed_values = list(choices) if choices is not None else None
            if key == "voice":
                allowed_values = list(settings.get("availableVoices", self._voices))
            items.append(self._entry(
                setting_id,
                name,
                category,
                description,
                settings.get(key),
                allowed_values,
                self._default_value(key),
                location,
                mode,
                restart,
            ))
        provider_options = {
            str(provider.get("id")): str(provider.get("name") or provider.get("id"))
            for provider in settings.get("aiProviders", [])
            if isinstance(provider, dict) and provider.get("id")
        }
        if provider_options:
            items.append(self._entry(
                "ai.provider",
                "AI provider",
                "AI Model & Provider",
                "Selects the configured AI provider.",
                settings.get("activeAiProvider"),
                list(provider_options),
                "gemini",
                "Settings → AI Model & Provider",
                "immediate",
                False,
                option_labels=provider_options,
            ))
            for provider in settings.get("aiProviders", []):
                if not isinstance(provider, dict) or not provider.get("id"):
                    continue
                provider_id = str(provider["id"])
                model_options = provider.get("models")
                items.append(self._entry(
                    f"ai.model.{provider_id}",
                    f"{provider.get('name') or provider_id} Chat model",
                    "AI Model & Provider",
                    f"Selects the Chat model configured for {provider.get('name') or provider_id}.",
                    provider.get("model"),
                    list(model_options) if isinstance(model_options, list) else [],
                    None,
                    "Settings → AI Model & Provider",
                    "immediate",
                    False,
                ))

        profiles = settings.get("interfaceProfiles")
        layout = str(settings.get("voiceLayout") or "default")
        profile = profiles.get(layout, {}) if isinstance(profiles, dict) else {}
        components = profile.get("components", {}) if isinstance(profile, dict) else {}
        component_labels = {
            "clock": "Clock",
            "commandBar": "Command",
            "activityLog": "Activity",
            "weather": "Weather",
            "systemMonitor": "Monitor",
        }
        for component_id, label in component_labels.items():
            component = components.get(component_id)
            if not isinstance(component, dict):
                continue
            base = f"interface.components.{component_id}"
            location = f"Settings → Interface → {label}"
            style_choices = sorted(self._component_styles.get(component_id, ()))
            items.extend((
                self._entry(
                    f"{base}.position",
                    f"{label} position",
                    "Interface",
                    f"Places {label} in the selected Voice layout.",
                    component.get("position"),
                    list(_POSITIONS),
                    "left",
                    location,
                    "immediate",
                    False,
                ),
                self._entry(
                    f"{base}.style",
                    f"{label} style",
                    "Clock" if component_id == "clock" else "Interface",
                    f"Selects the visual style used by {label}.",
                    component.get("style"),
                    style_choices,
                    "current",
                    "Settings → Clock" if component_id == "clock" else location,
                    "immediate",
                    False,
                ),
                self._entry(
                    f"{base}.visible",
                    f"{label} visibility",
                    "Interface",
                    f"Shows or hides {label} in the selected Voice layout.",
                    component.get("visible"),
                    [True, False],
                    True,
                    location,
                    "immediate",
                    False,
                ),
                self._entry(
                    f"{base}.active",
                    f"{label} enabled",
                    "Interface",
                    f"Includes or removes {label} from the selected Voice layout.",
                    component.get("active", True),
                    [True, False],
                    True,
                    location,
                    "immediate",
                    False,
                ),
                self._entry(
                    f"{base}.size",
                    f"{label} size",
                    "Clock" if component_id == "clock" else "Interface",
                    f"Controls the size of {label}.",
                    component.get("size"),
                    None,
                    48 if component_id == "clock" else 100,
                    "Settings → Clock" if component_id == "clock" else location,
                    "immediate",
                    False,
                    value_range=(20, 68) if component_id == "clock" else (70, 130),
                ),
            ))
            if component_id == "commandBar":
                items.append(self._entry(
                    f"{base}.componentWidth",
                    "Command width",
                    "Interface",
                    "Controls the width of the Command panel.",
                    component.get("componentWidth"),
                    None,
                    80,
                    location,
                    "immediate",
                    False,
                    value_range=(60, 100),
                ))
        activity = components.get("activityLog", {})
        items.append(self._entry(
            "interface.components.activityLog.density",
            "Activity density",
            "Interface",
            "Controls the density of the Activity panel.",
            activity.get("density") if isinstance(activity, dict) else None,
            list(_DENSITIES),
            "standard",
            "Settings → Interface → Activity → Density",
            "immediate",
            False,
        ))
        active_density = profile.get("density") if isinstance(profile, dict) else None
        items.append(self._entry(
            "interface.density",
            "Interface density",
            "Interface",
            "Controls the overall layout density.",
            active_density,
            list(_DENSITIES),
            "standard",
            "Settings → Interface → Density",
            "immediate",
            False,
        ))

        clock = settings.get("clockSettings")
        if not isinstance(clock, dict):
            clock = _CLOCK_DEFAULTS
        items.extend((
            self._entry(
                "clock.weight",
                "Clock weight",
                "Clock",
                "Controls the clock text weight.",
                clock.get("weight"),
                None,
                700,
                "Settings → Clock → Weight",
                "immediate",
                False,
                value_range=(300, 800),
            ),
            self._entry(
                "clock.letterSpacing",
                "Clock letter spacing",
                "Clock",
                "Controls the clock text letter spacing.",
                clock.get("letterSpacing"),
                None,
                5,
                "Settings → Clock → Letter Spacing",
                "immediate",
                False,
                value_range=(-5, 18),
            ),
        ))
        digital_text = settings.get("digitalText")
        items.append(self._entry(
            "interface.digitalText.enabled",
            "Digital Text ticker",
            "Interface",
            "Shows or hides the Digital Text ticker.",
            digital_text.get("enabled", False) if isinstance(digital_text, dict) else False,
            [True, False],
            False,
            "Settings → Global Appearance → Digital Text",
            "immediate",
            False,
        ))
        chat_theme = settings.get("chatTheme")
        if not isinstance(chat_theme, dict):
            chat_theme = {}
        custom_themes = chat_theme.get("customThemes", [])
        custom_options = {
            str(theme.get("id")): str(theme.get("name") or theme.get("id"))
            for theme in custom_themes
            if isinstance(theme, dict) and theme.get("id")
        } if isinstance(custom_themes, list) else {}
        chat_options = {**_CHAT_THEMES, **custom_options}
        items.append(self._entry(
            "chat.theme",
            "Chat theme",
            "Chat",
            "Selects the current Chat appearance.",
            chat_theme.get("selectedTheme", "nebix-dark"),
            list(chat_options),
            "nebix-dark",
            "Settings → Chat → Chat Themes",
            "immediate",
            False,
            option_labels=chat_options,
        ))
        voice_customization = settings.get("voiceInterfaceCustomization")
        customization = voice_customization if isinstance(voice_customization, dict) else {}
        for layout_id, values in customization.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                items.append(self._entry(
                    f"voiceInterfaceCustomization.{layout_id}.{key}",
                    f"{layout_id} {key}",
                    "Voice",
                    f"Controls {key} for the {layout_id} Voice interface.",
                    value,
                    None,
                    None,
                    f"Settings → Voice & Audio → {layout_id}",
                    "immediate",
                    False,
                ))
        return items

    def get_setting(self, setting_id: str) -> dict[str, Any]:
        target = self._canonical_id(setting_id)
        for entry in self.get_setting_registry():
            if entry["setting_id"] == target:
                return entry
        raise KeyError(f"Unknown setting: {setting_id}")

    def set_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        sync_frontend: bool = True,
    ) -> dict[str, Any]:
        target = self._canonical_id(setting_id)
        entry = self.get_setting(target)
        choices = entry.get("allowed_values")
        value_range = entry.get("value_range")
        if value == "next" and target.endswith(".style"):
            current = entry.get("current_value")
            value = (
                choices[(choices.index(current) + 1) % len(choices)]
                if choices and current in choices
                else choices[0] if choices else None
            )
        if choices is not None and (
            (choices and isinstance(choices[0], bool) and not isinstance(value, bool))
            or value not in choices
        ):
            labels = entry.get("option_labels", {})
            valid = ", ".join(labels.get(item, str(item)) for item in choices)
            return {
                "ok": False,
                "error": f"{entry['name']} supports {valid}.",
                "setting": entry,
            }
        if value_range is not None:
            minimum, maximum = value_range
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not minimum <= value <= maximum
            ):
                return {
                    "ok": False,
                    "error": f"{entry['name']} must be between {minimum} and {maximum}.",
                    "setting": entry,
                }
        if target == "ai.provider":
            bridge = getattr(self._ui, "bridge", None)
            setter = getattr(bridge, "_set_active_ai_provider", None)
            if not callable(setter):
                return {"ok": False, "error": "AI provider selection is unavailable."}
            result = setter(value)
            if not isinstance(result, dict) or result.get("ok") is False:
                return result if isinstance(result, dict) else {"ok": False, "error": "AI provider could not be changed."}
            settings = self.get_settings()
            if sync_frontend:
                self._sync_frontend(settings)
            return {"ok": True, "setting": self.get_setting(target), "settings": settings}
        if target.startswith("ai.model."):
            provider_id = target.removeprefix("ai.model.")
            bridge = getattr(self._ui, "bridge", None)
            setter = getattr(bridge, "_set_ai_provider_model", None)
            if not callable(setter):
                return {"ok": False, "error": "AI model selection is unavailable."}
            result = setter(provider_id, value)
            if not isinstance(result, dict) or result.get("ok") is False:
                return result if isinstance(result, dict) else {"ok": False, "error": "AI model could not be changed."}
            settings = self.get_settings()
            if sync_frontend:
                self._sync_frontend(settings)
            return {"ok": True, "setting": self.get_setting(target), "settings": settings}
        payload = self._payload_for(target, value)
        if isinstance(payload, dict) and payload.get("ok") is False:
            return payload
        result = self.set_settings(payload)
        if isinstance(result, dict) and result.get("ok") is False:
            return result
        if sync_frontend:
            self._sync_frontend(result)
        updated = self.get_setting(target)
        return {"ok": True, "setting": updated, "settings": result}

    def apply_command(self, command: dict[str, Any]) -> dict[str, Any]:
        kind = command.get("kind")
        component = str(command.get("component") or "")
        value = command.get("value")
        component_key = {
            "clock": "clock",
            "commandBar": "commandBar",
            "activityLog": "activityLog",
            "weather": "weather",
            "systemMonitor": "systemMonitor",
        }.get(component)

        if kind == "setting":
            return self._apply_general_command(
                str(command.get("key") or ""),
                value,
                str(command.get("label") or ""),
            )
        if kind == "style" and component_key:
            return self._apply_registered(
                f"interface.components.{component_key}.style",
                value,
            )
        if kind == "position" and component_key:
            return self._apply_registered(
                f"interface.components.{component_key}.position",
                value,
            )
        if kind == "visibility" and component_key:
            return self._apply_registered(
                f"interface.components.{component_key}.visible",
                value,
            )
        if kind == "componentDensity":
            return self._apply_registered(
                "interface.components.activityLog.density",
                value,
            )
        if kind == "componentPresence" and component_key:
            return self._set_component_active(component_key, value is True)
        if kind == "size" and component_key:
            return self._set_component_size(component_key, value)
        if kind == "density":
            return self._set_global_density(value)
        if kind == "interfacePosition":
            return self._set_all_positions(value)
        if kind == "weight":
            return self._adjust_clock("weight", value)
        if kind == "spacing":
            return self._adjust_clock("letterSpacing", value)
        if kind == "theme":
            return self._apply_registered("interface.theme", value)
        if kind == "layout":
            return self._apply_registered("interface.layout", value)
        if kind in {"accent", "effect"}:
            return self._set_visual_option(kind, command)
        if kind == "accentCycle":
            return self._cycle_accent()
        if kind == "digitalText":
            settings = self.get_settings()
            digital_text = settings.get("digitalText")
            if not isinstance(digital_text, dict) or not str(digital_text.get("message") or "").strip():
                return {"ok": False, "error": "Digital Text needs a saved message before it can be enabled."}
            updated = dict(digital_text)
            updated["enabled"] = value is True
            return self._apply_payload(
                {"digitalText": updated},
                f"Digital Text {'enabled' if value is True else 'disabled'}.",
            )
        if kind == "chatTheme":
            return self._set_chat_theme(value)
        if kind == "mode":
            bridge = getattr(self._ui, "bridge", None)
            setter = getattr(bridge, "set_mode", None)
            if not callable(setter):
                return {"ok": False, "error": "Voice and Chat mode switching is unavailable."}
            result = setter(value)
            if not isinstance(result, dict) or result.get("ok") is False:
                return result if isinstance(result, dict) else {"ok": False, "error": "Mode could not be changed."}
            return {"ok": True, "message": f"NEBIX {str(value).title()} mode opened."}
        if kind == "desktopShortcut":
            bridge = getattr(self._ui, "bridge", None)
            creator = getattr(bridge, "create_desktop_shortcut", None)
            if not callable(creator):
                return {"ok": False, "error": "Desktop shortcut creation is unavailable."}
            result = creator()
            if not isinstance(result, dict) or result.get("ok") is False:
                return result if isinstance(result, dict) else {"ok": False, "error": "Desktop shortcut creation failed."}
            return {
                "ok": True,
                "message": result.get("message") or "NEBIX desktop shortcut created.",
            }
        if kind == "resetInterface":
            return self._reset_interface()
        if kind == "editLayout":
            return self._set_layout_editing(value is True)
        return {"ok": False, "error": "That setting is not available in the Settings Registry."}

    def answer_query(self, text: str) -> str | None:
        normalized = self._normalize_query(text)
        entries = self.get_setting_registry()
        if any(term in normalized for term in (
            "what settings do i have",
            "what settings are available",
            "list settings",
            "show settings",
            "available settings",
            "what can i configure",
        )):
            grouped: dict[str, list[str]] = {}
            for entry in entries:
                grouped.setdefault(entry["category"], []).append(entry["name"])
            return "Available settings: " + "; ".join(
                f"{category}: {', '.join(names)}"
                for category, names in grouped.items()
            ) + "."

        is_location_question = any(word in normalized.split() for word in ("where", "location", "find"))
        is_value_question = any(phrase in normalized for phrase in (
            "current", "currently", "what is my", "what's my", "what is the", "whats my",
        ))
        if not is_location_question and not is_value_question:
            return None
        entry = self._match_entry(normalized, entries)
        if not entry:
            return None
        if is_location_question:
            return f"{entry['name']} is located at {entry['ui_location']}."
        display = self._display_value(entry, entry.get("current_value"))
        return f"{entry['name']} is currently set to {display}."

    def _apply_general_command(self, key: str, value: Any, label: str) -> dict[str, Any]:
        setting_ids = {
            "voice": "voice.selection",
            "activity": "general.activityLogging",
            "performanceMode": "automation.performanceMode",
            "backgroundEfficiency": "automation.backgroundEfficiency",
            "startupEnabled": "automation.startupEnabled",
            "startMinimized": "automation.startMinimized",
            "restorePreviousInterface": "automation.restorePreviousInterface",
        }
        target = setting_ids.get(key)
        if not target:
            return {"ok": False, "error": f"{key or 'That'} is not a registered setting."}
        result = self._apply_registered(target, value)
        if result.get("ok"):
            result["message"] = f"{label or self.get_setting(target)['name']} updated."
        return result

    def _apply_registered(self, setting_id: str, value: Any) -> dict[str, Any]:
        try:
            result = self.set_setting(setting_id, value)
        except KeyError:
            return {"ok": False, "error": f"{setting_id} is not available in the current Settings Registry."}
        if result.get("ok"):
            entry = result["setting"]
            result["message"] = (
                f"{entry['name']} changed to "
                f"{self._display_value(entry, entry.get('current_value'))}."
            )
        return result

    def _payload_for(self, setting_id: str, value: Any) -> dict[str, Any]:
        if setting_id.startswith("interface.components."):
            _, _, component_id, property_name = setting_id.split(".", 3)
            if property_name == "active":
                return self._component_active_payload(component_id, value)
            settings = self.get_settings()
            layout = str(settings.get("voiceLayout") or "default")
            profiles = settings.get("interfaceProfiles")
            profile = profiles.get(layout) if isinstance(profiles, dict) else None
            components = profile.get("components") if isinstance(profile, dict) else None
            component = components.get(component_id) if isinstance(components, dict) else None
            if not isinstance(component, dict):
                return {"ok": False, "error": f"{component_id} is not available in the current interface."}
            updated_profiles = json.loads(json.dumps(profiles))
            updated_profiles[layout]["components"][component_id][property_name] = value
            payload = {"interfaceProfiles": updated_profiles}
            if component_id == "clock" and property_name in {"style", "size"}:
                clock = dict(settings.get("clockSettings") or _CLOCK_DEFAULTS)
                clock[property_name] = value
                payload["clockSettings"] = clock
            return payload
        if setting_id == "interface.layout":
            return {"voiceLayout": value}
        if setting_id == "interface.density":
            settings = self.get_settings()
            layout = str(settings.get("voiceLayout") or "default")
            profiles = json.loads(json.dumps(settings.get("interfaceProfiles") or {}))
            profiles.setdefault(layout, {})["density"] = value
            return {"interfaceProfiles": profiles}
        if setting_id == "interface.theme":
            return {"theme": value}
        if setting_id == "interface.settingsTheme":
            return {"settingsTheme": value}
        if setting_id == "general.activityLogging":
            return {"activity": value}
        if setting_id == "voice.selection":
            return {"voice": value}
        if setting_id == "automation.performanceMode":
            return {"performanceMode": value}
        if setting_id == "automation.backgroundEfficiency":
            return {"backgroundEfficiency": value}
        if setting_id == "automation.startupEnabled":
            return {"startupEnabled": value}
        if setting_id == "automation.startMinimized":
            return {"startMinimized": value}
        if setting_id == "automation.restorePreviousInterface":
            return {"restorePreviousInterface": value}
        if setting_id.startswith("voiceInterfaceCustomization."):
            _, layout_id, property_name = setting_id.split(".", 2)
            return {
                "voiceInterfaceCustomization": {
                    layout_id: {property_name: value},
                }
            }
        if setting_id == "clock.weight" or setting_id == "clock.letterSpacing":
            current = self.get_settings().get("clockSettings")
            clock = dict(current) if isinstance(current, dict) else dict(_CLOCK_DEFAULTS)
            property_name = "weight" if setting_id.endswith("weight") else "letterSpacing"
            clock[property_name] = value
            return {"clockSettings": clock}
        if setting_id == "interface.digitalText.enabled":
            current = self.get_settings().get("digitalText")
            if not isinstance(current, dict):
                return {"ok": False, "error": "Digital Text is unavailable until a message is configured."}
            digital_text = dict(current)
            digital_text["enabled"] = value
            return {"digitalText": digital_text}
        if setting_id == "chat.theme":
            return self._chat_theme_payload(value)
        return {"ok": False, "error": f"No settings handler is registered for {setting_id}."}

    def _set_component_active(self, component_id: str, active: bool) -> dict[str, Any]:
        payload = self._component_active_payload(component_id, active)
        if payload.get("ok") is False:
            return payload
        return self._apply_payload(
            payload,
            f"{self._component_name(component_id)} {'added to' if active else 'removed from'} the Interface.",
        )

    def _component_active_payload(self, component_id: str, active: Any) -> dict[str, Any]:
        if not isinstance(active, bool):
            return {"ok": False, "error": "Component enabled must be true or false."}
        settings = self.get_settings()
        layout = str(settings.get("voiceLayout") or "default")
        profiles = settings.get("interfaceProfiles")
        if not isinstance(profiles, dict) or layout not in profiles:
            return {"ok": False, "error": "Interface profile is unavailable."}
        updated = json.loads(json.dumps(profiles))
        component = updated[layout]["components"].get(component_id)
        if not isinstance(component, dict):
            return {"ok": False, "error": f"{component_id} is not a registered Interface component."}
        component["active"] = active
        if active and not component.get("visible", True):
            component["visible"] = True
        return {"interfaceProfiles": updated}

    def _set_component_size(self, component_id: str, requested: Any) -> dict[str, Any]:
        setting_id = f"interface.components.{component_id}.size"
        settings = self.get_settings()
        layout = str(settings.get("voiceLayout") or "default")
        profiles = settings.get("interfaceProfiles")
        profile = profiles.get(layout, {}) if isinstance(profiles, dict) else {}
        component = profile.get("components", {}).get(component_id, {}) if isinstance(profile, dict) else {}
        current = component.get("size", 48 if component_id == "clock" else 100)
        minimum, maximum = (20, 68) if component_id == "clock" else (70, 130)
        if requested in {"larger", "smaller"}:
            requested = int(current) + (4 if component_id == "clock" else 10) * (1 if requested == "larger" else -1)
        try:
            value = int(requested)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Size must be a number."}
        value = max(minimum, min(maximum, value))
        if component_id == "clock":
            clock = dict(settings.get("clockSettings") or _CLOCK_DEFAULTS)
            clock["size"] = value
            profiles = json.loads(json.dumps(profiles))
            profiles[layout]["components"][component_id]["size"] = value
            return self._apply_payload(
                {"clockSettings": clock, "interfaceProfiles": profiles},
                f"Clock size set to {value} pixels.",
            )
        payload = self._payload_for(setting_id, value)
        if payload.get("ok") is False:
            return payload
        return self._apply_payload(payload, f"{self._component_name(component_id)} size set to {value} percent.")

    def _set_global_density(self, value: Any) -> dict[str, Any]:
        if value not in _DENSITIES:
            return {"ok": False, "error": "Interface Density supports Compact, Standard, and Spacious."}
        settings = self.get_settings()
        layout = str(settings.get("voiceLayout") or "default")
        profiles = json.loads(json.dumps(settings.get("interfaceProfiles") or {}))
        profiles.setdefault(layout, {})["density"] = value
        return self._apply_payload(
            {"interfaceProfiles": profiles},
            f"Interface density changed to {value.title()}.",
        )

    def _set_all_positions(self, value: Any) -> dict[str, Any]:
        if value not in _POSITIONS:
            return {"ok": False, "error": "Interface position supports Left, Center, and Right."}
        settings = self.get_settings()
        layout = str(settings.get("voiceLayout") or "default")
        profiles = json.loads(json.dumps(settings.get("interfaceProfiles") or {}))
        components = profiles.get(layout, {}).get("components", {})
        for component in components.values():
            if isinstance(component, dict) and component.get("active", True):
                component["position"] = value
                component["order"] = 0
        return self._apply_payload(
            {"interfaceProfiles": profiles},
            f"All active Interface components moved to {value.title()}.",
        )

    def _adjust_clock(self, property_name: str, direction: Any) -> dict[str, Any]:
        settings = self.get_settings()
        clock = dict(settings.get("clockSettings") or _CLOCK_DEFAULTS)
        step = 100 if property_name == "weight" else 1
        change = -step if direction == "lighter" or direction == "tighter" else step
        minimum, maximum = (300, 800) if property_name == "weight" else (-5, 18)
        value = max(minimum, min(maximum, int(clock.get(property_name, 0)) + change))
        clock[property_name] = value
        label = f"Clock {'weight' if property_name == 'weight' else 'letter spacing'} set to {value}."
        return self._apply_payload({"clockSettings": clock}, label)

    def _set_visual_option(self, kind: str, command: dict[str, Any]) -> dict[str, Any]:
        settings = self.get_settings()
        layout = str(settings.get("voiceLayout") or "default")
        profiles = json.loads(json.dumps(settings.get("interfaceProfiles") or {}))
        profile = profiles.get(layout, {})
        if kind == "accent":
            value = str(command.get("value") or "").lower()
            if not re.fullmatch(r"#[0-9a-f]{6}", value):
                return {"ok": False, "error": "Interface accent must be a valid six-digit color."}
            profile["customColor"] = value
            profile["colorPreset"] = "custom"
            message = f"Interface accent changed to {command.get('label') or value}."
        else:
            effect = str(command.get("effect") or "")
            if effect not in {"glow", "animation"}:
                return {"ok": False, "error": "Only existing Glow and Motion controls can be changed."}
            current = int(profile.get("effects", {}).get(effect, 0))
            requested = command.get("value")
            value = current + requested * 10 if requested in {-1, 1} else requested
            try:
                value = max(0, min(100, int(value)))
            except (TypeError, ValueError):
                return {"ok": False, "error": f"{effect} must be from 0 to 100."}
            profile.setdefault("effects", {})[effect] = value
            message = f"{'Glow' if effect == 'glow' else 'Motion'} set to {value}%."
        profiles[layout] = profile
        return self._apply_payload({"interfaceProfiles": profiles}, message)

    def _set_chat_theme(self, value: Any) -> dict[str, Any]:
        choices = self.get_setting("chat.theme").get("allowed_values", [])
        if value == "next":
            current = self.get_setting("chat.theme")["current_value"]
            value = choices[(choices.index(current) + 1) % len(choices)] if current in choices else choices[0]
        if value not in choices:
            labels = self.get_setting("chat.theme").get("option_labels", {})
            valid = ", ".join(labels.get(item, str(item)) for item in choices)
            return {"ok": False, "error": f"Chat theme supports {valid}."}
        payload = self._chat_theme_payload(value)
        if payload.get("ok") is False:
            return payload
        return self._apply_payload(payload, f"Chat theme changed to {self.get_setting('chat.theme')['option_labels'][value]}.")

    def _chat_theme_payload(self, value: Any) -> dict[str, Any]:
        settings = self.get_settings()
        current = settings.get("chatTheme")
        if not isinstance(current, dict):
            current = {"selectedTheme": "nebix-dark", "favorites": [], "customThemes": []}
        updated = dict(current)
        updated["selectedTheme"] = value
        return {"chatTheme": updated}

    def _set_layout_editing(self, active: bool) -> dict[str, Any]:
        result = self._call_frontend(
            "(function(){ if (!window.NEBIX || "
            "typeof window.NEBIX.setInterfaceLayoutEditing !== 'function') "
            "return {ok:false,error:'The Interface editor is unavailable.'}; "
            f"return window.NEBIX.setInterfaceLayoutEditing({str(active).lower()}); }})()"
        )
        if result is True:
            return {"ok": True, "message": f"Interface layout editing {'enabled' if active else 'disabled'}."}
        if isinstance(result, dict):
            return result
        return {"ok": False, "error": "The Interface editor did not confirm the requested change."}

    def _reset_interface(self) -> dict[str, Any]:
        result = self._call_frontend(
            "(async function(){ if (!window.NEBIX || "
            "typeof window.NEBIX.resetInterfaceProfileFromCommand !== 'function') "
            "return {ok:false,error:'Interface reset is unavailable.'}; "
            "return await window.NEBIX.resetInterfaceProfileFromCommand(); })()"
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "The Interface reset did not return a result."}
        return result

    def _cycle_accent(self) -> dict[str, Any]:
        colors = ("#00f0ff", "#00e5c9", "#378bff", "#a478ff", "#ff8b32", "#38d996", "#ff6fae")
        settings = self.get_settings()
        layout = str(settings.get("voiceLayout") or "default")
        profiles = json.loads(json.dumps(settings.get("interfaceProfiles") or {}))
        profile = profiles.get(layout)
        if not isinstance(profile, dict):
            return {"ok": False, "error": "Interface accent control is unavailable."}
        current = str(profile.get("customColor") or "").lower()
        next_index = colors.index(current) + 1 if current in colors else 0
        color = colors[next_index % len(colors)]
        profile["customColor"] = color
        profile["colorPreset"] = "custom"
        return self._apply_payload({"interfaceProfiles": profiles}, "Interface accent changed.")

    def _call_frontend(self, script: str) -> Any:
        js = getattr(self._ui, "_js", None)
        if not callable(js):
            return {"ok": False, "error": "The Interface is unavailable."}
        event = threading.Event()
        holder: dict[str, Any] = {}

        def receive(value: Any) -> None:
            holder["value"] = value
            event.set()

        try:
            immediate = js(script, callback=receive)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if immediate is not None:
            result = immediate
        elif event.wait(20):
            result = holder.get("value")
        else:
            return {"ok": False, "error": "The Interface did not respond before the operation timed out."}
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (TypeError, ValueError):
                return {"ok": False, "error": "The Interface returned an unreadable result."}
        return result

    def _apply_payload(self, payload: dict[str, Any], message: str) -> dict[str, Any]:
        result = self.set_settings(payload)
        if isinstance(result, dict) and result.get("ok") is False:
            return result
        self._sync_frontend(result)
        return {"ok": True, "message": message, "settings": result}

    def _sync_frontend(self, settings: Any) -> None:
        js = getattr(self._ui, "_js", None)
        if callable(js) and isinstance(settings, dict):
            js(
                "window.NEBIX && window.NEBIX.syncSettings && "
                "window.NEBIX.syncSettings("
                + json.dumps(settings, ensure_ascii=False)
                + ");"
            )

    def _entry(
        self,
        setting_id: str,
        name: str,
        category: str,
        description: str,
        value: Any,
        allowed_values: list[Any] | None,
        default_value: Any,
        ui_location: str,
        apply_mode: str,
        requires_restart: bool,
        *,
        option_labels: dict[str, str] | None = None,
        value_range: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        result = {
            "setting_id": setting_id,
            "name": name,
            "category": category,
            "description": description,
            "current_value": value,
            "allowed_values": allowed_values,
            "default_value": default_value,
            "ui_location": ui_location,
            "apply_mode": apply_mode,
            "requires_restart": requires_restart,
        }
        if option_labels:
            result["option_labels"] = option_labels
        if value_range:
            result["value_range"] = list(value_range)
        return result

    def _canonical_id(self, setting_id: str) -> str:
        value = str(setting_id or "").strip()
        return _ALIASES.get(value, value)

    @staticmethod
    def _default_value(key: str) -> Any:
        defaults = {
            "voiceLayout": "default",
            "theme": "dark",
            "settingsTheme": "light",
            "activity": True,
            "voice": "Puck",
            "performanceMode": "balanced",
            "backgroundEfficiency": "Normal",
            "startupEnabled": True,
            "startMinimized": False,
            "restorePreviousInterface": True,
        }
        return defaults.get(key)

    @staticmethod
    def _component_name(component_id: str) -> str:
        return {
            "clock": "Clock",
            "commandBar": "Command",
            "activityLog": "Activity",
            "weather": "Weather",
            "systemMonitor": "Monitor",
        }.get(component_id, component_id)

    @staticmethod
    def _normalize_query(text: str) -> str:
        value = re.sub(r"[^\w\s]", " ", str(text or "").casefold(), flags=re.UNICODE)
        return " ".join(value.split())

    def _match_entry(
        self,
        normalized: str,
        entries: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        aliases = {
            "clock style": ("clock style", "clock design"),
            "clock position": ("clock position",),
            "command position": ("command position", "command bar position"),
            "activity position": ("activity position", "activity log position"),
            "weather position": ("weather position",),
            "monitor position": ("monitor position", "system monitor position"),
            "activity density": ("activity density", "activity spacing"),
            "interface density": ("interface density", "layout density"),
            "chat theme": ("chat theme", "chat appearance"),
            "assistant voice": ("assistant voice", "voice selection"),
        }
        matches = []
        for entry in entries:
            phrases = aliases.get(entry["name"].casefold(), (entry["name"].casefold(),))
            if entry["setting_id"] == "interface.components.clock.style":
                phrases = aliases["clock style"]
            elif entry["setting_id"] == "interface.components.activityLog.density":
                phrases = aliases["activity density"]
            elif entry["setting_id"] == "chat.theme":
                phrases = aliases["chat theme"]
            elif entry["setting_id"] == "voice.selection":
                phrases = aliases["assistant voice"]
            for phrase in phrases:
                if re.search(rf"\b{re.escape(phrase)}\b", normalized):
                    matches.append((len(phrase), entry))
        return max(matches, key=lambda item: item[0])[1] if matches else None

    @staticmethod
    def _display_value(entry: dict[str, Any], value: Any) -> str:
        labels = entry.get("option_labels", {})
        if value in labels:
            return labels[value]
        if isinstance(value, bool):
            return "Enabled" if value else "Disabled"
        if value is None:
            return "not set"
        return str(value).replace("_", " ").title()
