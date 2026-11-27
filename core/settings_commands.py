from __future__ import annotations

import re
import unicodedata


_COMPONENTS = {
    "clock": ("clock", "time display"),
    "systemMonitor": ("system monitor", "monitor"),
    "commandBar": ("command bar", "command panel", "command"),
    "activityLog": ("activity log", "activity"),
    "weather": ("weather", "environment"),
}

_CLOCK_STYLES = {
    "current": ("current", "default", "original"),
    "iphone": ("modern", "iphone", "phone"),
    "apple-thin": ("apple thin", "thin"),
    "sf-minimalist": ("sf minimalist", "minimalist"),
    "digital": ("digital", "digital display"),
    "digital-bold": ("digital bold", "bold digital"),
    "futuristic": ("futuristic",),
    "hud": ("hud", "heads up display"),
    "cyber": ("cyber",),
    "mono": ("mono", "monospace"),
    "terminal": ("terminal",),
    "matrix": ("matrix",),
    "luxury": ("luxury",),
    "elegant": ("elegant",),
    "thin-elegant": ("thin elegant",),
    "tech": ("tech", "technical"),
    "geometric": ("geometric",),
    "modern-wide": ("modern wide", "wide"),
    "condensed": ("condensed",),
    "ultra-minimal": ("ultra minimal", "ultra light"),
    "impact": ("impact",),
    "classic": ("classic",),
    "editorial": ("editorial",),
}

_COMPONENT_STYLES = {
    "systemMonitor": {
        "current": ("current", "default", "simple"),
        "circular": ("circular", "circle", "radial"),
        "digital": ("digital",),
        "bars": ("bars", "bar"),
        "hud": ("hud",),
        "cyber": ("cyber",),
        "terminal": ("terminal",),
        "glass": ("glass", "glassmorphism"),
        "reactor": ("reactor",),
        "command": ("command", "command center"),
    },
    "commandBar": {
        "current": ("current", "default"),
        "hud": ("hud",),
        "terminal": ("terminal",),
        "glass": ("glass",),
    },
    "activityLog": {
        "current": ("current", "default"),
        "terminal": ("terminal",),
        "glass": ("glass",),
        "cyber": ("cyber",),
    },
    "weather": {
        "current": ("current", "default"),
        "glass": ("glass",),
        "minimal": ("minimal",),
        "hud": ("hud",),
    },
}

_THEME_COLORS = {
    "red": "#ff304a",
    "orange": "#ff8b32",
    "yellow": "#ffc247",
    "green": "#38d996",
    "blue": "#378bff",
    "purple": "#a478ff",
    "pink": "#ff6fae",
    "cyan": "#00f0ff",
    "teal": "#00e5c9",
}

_VOICES = {
    "zephyr": "Zephyr",
    "puck": "Puck",
    "charon": "Charon",
    "kore": "Kore",
    "fenrir": "Fenrir",
    "aoede": "Aoede",
}

_PERFORMANCE_MODES = {
    "balanced": ("balanced",),
    "performance": ("performance",),
    "battery_saver": ("battery saver", "battery saving"),
}

_EFFICIENCY_MODES = {
    "Normal": ("normal",),
    "Reduced Background Activity": ("reduced background activity",),
    "Maximum Efficiency": ("maximum efficiency",),
}

_CHAT_THEMES = {
    "nebix-dark": ("nebix dark",),
    "nebix-light": ("nebix light",),
    "midnight": ("midnight",),
    "aurora": ("aurora",),
    "cyber-cyan": ("cyber cyan",),
    "neon-purple": ("neon purple",),
    "emerald": ("emerald",),
    "crimson": ("crimson",),
    "ocean": ("ocean",),
    "sunset": ("sunset",),
    "glass": ("glass",),
    "amoled": ("amoled",),
    "cyberpunk": ("cyberpunk",),
    "minimal": ("minimal",),
}
_POSITIONS = ("left", "center", "right")

_VOICE_LAYOUTS = {
    "default": ("default", "original", "nebix original", "default interface"),
    "interface1": ("interface 1", "layout 1", "first interface"),
    "interface2": ("interface 2", "layout 2", "second interface"),
    "interface3": ("interface 3", "layout 3", "third interface"),
    "interface4": ("interface 4", "layout 4", "fourth interface"),
    "interface5": ("interface 5", "layout 5", "fifth interface"),
}

_COMMAND_VERBS = (
    "change", "switch", "set", "make", "turn", "enable", "disable",
    "show", "hide", "move", "increase", "decrease", "raise", "lower",
    "grow", "shrink", "bigger", "larger", "smaller", "reduce", "use",
    "choose", "select", "compact", "spacious", "reset", "add", "remove", "create",
    "enter", "gara", "gar", "garne", "bana", "hataideu", "dekhaau",
    "rakha", "rakh", "raakh",
)
_STYLE_WORDS = ("style", "design", "look", "appearance")


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    cleaned: list[str] = []
    for char in value:
        category = unicodedata.category(char)
        if char.isspace():
            cleaned.append(" ")
        elif category.startswith(("L", "N")) or category in {"Mn", "Mc", "Me"}:
            cleaned.append(char)
        else:
            cleaned.append(" ")
    return " ".join("".join(cleaned).split())


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _find_component(text: str) -> str | None:
    matches = [
        (len(alias), component)
        for component, aliases in _COMPONENTS.items()
        for alias in aliases
        if _contains_phrase(text, alias)
    ]
    if not matches:
        return None
    if len({component for _, component in matches}) > 1:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _find_value(text: str, choices: dict[str, tuple[str, ...]]) -> str | None:
    matches = [
        (len(alias), value)
        for value, aliases in choices.items()
        for alias in aliases
        if _contains_phrase(text, alias)
    ]
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(_contains_phrase(text, phrase) for phrase in phrases)


def parse_settings_command(text: str) -> dict[str, object] | None:
    """Parse explicit, supported requests that map to existing settings."""
    normalized = _normalize(text)
    if not normalized:
        return None
    if "?" in str(text or "") or any(
        phrase in normalized
        for phrase in ("how do i ", "how to ", "should i ", "can you explain ")
    ):
        return None

    component = _find_component(normalized)
    has_verb = _has_any(normalized, _COMMAND_VERBS)
    has_style_word = _has_any(normalized, _STYLE_WORDS)
    component_mentions = {
        item
        for item, aliases in _COMPONENTS.items()
        if any(_contains_phrase(normalized, alias) for alias in aliases)
    }
    if len(component_mentions) > 1:
        marker_positions = [
            position
            for marker in (" style ", " design ", " look ", " appearance ", " to ")
            if (position := normalized.find(marker)) >= 0
        ]
        for position in sorted(marker_positions):
            explicit_component = _find_component(normalized[:position])
            if not explicit_component:
                continue
            available = _CLOCK_STYLES if explicit_component == "clock" else _COMPONENT_STYLES.get(explicit_component, {})
            if _find_value(normalized, available) is not None:
                component = explicit_component
                component_mentions = {explicit_component}
                break
    if len(component_mentions) > 1 and has_verb:
        return {
            "kind": "clarify",
            "message": "Which component should I change: Clock, Monitor, Command, Activity, or Weather?",
        }

    if has_verb and _has_any(normalized, ("reset interface", "reset interface layout", "reset layout")):
        return {"kind": "resetInterface"}
    if has_verb and _has_any(normalized, ("enter layout mode", "edit layout", "arrange the interface", "arrange interface")):
        return {"kind": "editLayout", "value": True}

    if component and has_verb and _has_any(normalized, ("add", "restore", "put back")):
        return {"kind": "componentPresence", "component": component, "value": True}
    if component and has_verb and _has_any(normalized, ("remove", "take out", "hataideu")):
        if component == "activityLog" and _has_any(normalized, ("hataideu",)):
            return {"kind": "visibility", "component": component, "value": False}
        return {"kind": "componentPresence", "component": component, "value": False}

    if has_verb and _has_any(normalized, ("activity logging", "log activity")):
        words = set(normalized.split())
        if words.intersection({"enable", "show", "on"}):
            return {"kind": "setting", "key": "activity", "value": True, "label": "Activity logging enabled"}
        if words.intersection({"disable", "hide", "off"}):
            return {"kind": "setting", "key": "activity", "value": False, "label": "Activity logging disabled"}

    if has_verb and _has_any(normalized, ("digital text", "digital ticker", "ticker")):
        words = set(normalized.split())
        if words.intersection({"enable", "show", "on"}):
            return {"kind": "digitalText", "value": True}
        if words.intersection({"disable", "hide", "off"}):
            return {"kind": "digitalText", "value": False}

    if component == "activityLog":
        density = next(
            (value for value in ("compact", "standard", "spacious") if value in normalized.split()),
            None,
        )
        if density and has_verb:
            return {"kind": "componentDensity", "component": component, "value": density}

    if component == "clock" or component is None and has_style_word:
        style = _find_value(normalized, _CLOCK_STYLES)
    else:
        style = None

    component_styles = _COMPONENT_STYLES.get(component, {})
    component_style = _find_value(normalized, component_styles)
    if component == "systemMonitor":
        component_style = _find_value(normalized, _COMPONENT_STYLES["systemMonitor"])

    if component is None and has_style_word:
        style_targets = set()
        if style is not None:
            style_targets.add("clock")
        for target, styles in _COMPONENT_STYLES.items():
            if _find_value(normalized, styles) is not None:
                style_targets.add(target)
        if len(style_targets) > 1 or not style_targets:
            return {
                "kind": "clarify",
                "message": "Which style should I change: Clock, Monitor, Command, Activity, or Weather?",
            }
        component = next(iter(style_targets))
        component_styles = _COMPONENT_STYLES.get(component, {})
        component_style = _find_value(normalized, component_styles)

    if component == "clock" and (has_style_word or style is not None):
        if not has_verb:
            return None
        return {
            "kind": "style",
            "component": "clock",
            "value": style or "next",
        }

    if component and component != "clock" and (has_style_word or component_style is not None):
        if component_style is None:
            if has_verb and has_style_word:
                return {"kind": "style", "component": component, "value": "next"}
            return None
        return {
            "kind": "style",
            "component": component,
            "value": component_style,
        }

    if component and any(word in normalized.split() for word in ("left", "center", "right")):
        if _has_any(normalized, ("position", "move", "place", "put", "to the")):
            position = next(
                (value for value in ("left", "center", "right") if value in normalized.split()),
                None,
            )
            if position:
                return {"kind": "position", "component": component, "value": position}

    if _has_any(normalized, ("chat theme", "chat appearance")) and has_verb:
        selected_theme = _find_value(normalized, _CHAT_THEMES)
        return {"kind": "chatTheme", "value": selected_theme or "next"}

    if _has_any(normalized, ("open chat", "open nebix chat", "show chat", "switch to chat")):
        return {"kind": "mode", "value": "chat"}
    if _has_any(normalized, ("open voice", "open nebix voice", "show voice", "switch to voice")):
        return {"kind": "mode", "value": "voice"}
    if has_verb and _has_any(normalized, ("desktop shortcut", "desktop icon")):
        return {"kind": "desktopShortcut"}

    if component and has_verb and _has_any(normalized, ("visible", "visibility", "show", "hide", "enable", "disable", "turn on", "turn off", "dekhaau")):
        words = set(normalized.split())
        visible = not bool(words.intersection({"hide", "disable", "off", "invisible"}))
        return {"kind": "visibility", "component": component, "value": visible}

    if component and has_verb and _has_any(normalized, ("size", "bigger", "larger", "smaller", "increase", "decrease", "grow", "shrink", "thulo", "sano")):
        numeric = re.search(r"\b(\d{1,3})(?:\s*(?:px|percent|%))?\b", normalized)
        if numeric and _has_any(normalized, ("size", "to")):
            return {"kind": "size", "component": component, "value": int(numeric.group(1))}
        words = set(normalized.split())
        direction = "smaller" if words.intersection({"smaller", "decrease", "shrink", "reduce", "lower", "sano"}) else "larger"
        return {"kind": "size", "component": component, "value": direction}

    if component == "clock" and has_verb and _has_any(normalized, ("weight", "thicker", "thinner", "heavier", "lighter")):
        words = set(normalized.split())
        if "weight" in words or words.intersection({"thicker", "thinner", "heavier", "lighter"}):
            direction = "lighter" if words.intersection({"thinner", "lighter", "decrease", "lower"}) else "heavier"
            return {"kind": "weight", "value": direction}

    if component == "clock" and has_verb and _has_any(normalized, ("spacing", "letter spacing", "wider", "tighter")):
        direction = "tighter" if _has_any(normalized, ("tighter", "narrower", "decrease", "lower")) else "wider"
        return {"kind": "spacing", "value": direction}

    if _has_any(normalized, ("theme", "accent", "color", "colour", "appearance")):
        color = next((name for name in _THEME_COLORS if _contains_phrase(normalized, name)), None)
        if color and has_verb:
            return {"kind": "accent", "value": _THEME_COLORS[color], "label": color.title()}
        if "accent" in normalized.split() and has_verb:
            return {"kind": "accentCycle"}
        if "dark" in normalized.split() or "light" in normalized.split():
            return {"kind": "theme", "value": "dark" if "dark" in normalized.split() else "light"}
        if has_verb:
            return {"kind": "clarify", "message": "Should I change the interface color, or switch between the Light and Dark theme?"}

    if has_verb and _has_any(normalized, ("glow", "motion")):
        words = set(normalized.split())
        if "glow" in words and words.intersection({"on", "enable", "increase", "more"}):
            return {"kind": "effect", "effect": "glow", "value": 75}
        if "glow" in words and words.intersection({"off", "disable", "decrease", "less"}):
            return {"kind": "effect", "effect": "glow", "value": 0}
        if "motion" in words:
            direction = -1 if words.intersection({"decrease", "lower", "less", "reduce"}) else 1
            return {"kind": "effect", "effect": "animation", "value": direction}

    if has_verb and _has_any(normalized, ("voice interface", "interface layout", "interface", "layout")):
        layout = _find_value(normalized, _VOICE_LAYOUTS)
        if layout:
            return {"kind": "layout", "value": layout}

    if _has_any(normalized, ("interface density", "interface layout", "interface")):
        density = next((value for value in ("compact", "standard", "spacious") if value in normalized.split()), None)
        if density and (has_verb or "interface" in normalized.split()):
            return {"kind": "density", "value": density}
    if has_verb and _has_any(normalized, ("interface position", "move interface", "place interface", "interface")):
        position = next(
            (value for value in _POSITIONS if value in normalized.split()),
            None,
        )
        if position:
            return {"kind": "interfacePosition", "value": position}
    if component and has_verb:
        return {
            "kind": "clarify",
            "message": f"Monitor ko style change garne, hide garne, ki remove garne?"
            if component == "systemMonitor"
            else f"Should I change {component.replace('Log', '')} style, visibility, size, or remove it?",
        }
    if _has_any(normalized, ("voice", "speaker")):
        selected_voice = next(
            (voice for alias, voice in _VOICES.items() if _contains_phrase(normalized, alias)),
            None,
        )
        if selected_voice and has_verb:
            return {"kind": "setting", "key": "voice", "value": selected_voice, "label": selected_voice}
        if has_verb and _has_any(normalized, ("change voice", "select voice", "set voice")):
            return {"kind": "clarify", "message": "Which voice should I use: Zephyr, Puck, Charon, Kore, Fenrir, or Aoede?"}

    if _has_any(normalized, ("performance mode", "power mode")):
        mode = _find_value(normalized, _PERFORMANCE_MODES)
        if mode and has_verb:
            label = "Battery Saver" if mode == "battery_saver" else mode.title()
            return {"kind": "setting", "key": "performanceMode", "value": mode, "label": label}

    if _has_any(normalized, ("background efficiency", "efficiency mode")):
        mode = _find_value(normalized, _EFFICIENCY_MODES)
        if mode and has_verb:
            return {"kind": "setting", "key": "backgroundEfficiency", "value": mode, "label": mode}

    if _has_any(normalized, ("start on startup", "start with windows", "startup", "launch at startup")) and has_verb:
        words = set(normalized.split())
        enabled = not bool(words.intersection({"disable", "off", "remove", "stop"}))
        if "minimized" in words:
            return {"kind": "setting", "key": "startMinimized", "value": enabled, "label": "Start minimized" if enabled else "Start normally"}
        return {"kind": "setting", "key": "startupEnabled", "value": enabled, "label": "Startup enabled" if enabled else "Startup disabled"}

    if component is None and has_style_word and not has_verb:
        return None
    return None
