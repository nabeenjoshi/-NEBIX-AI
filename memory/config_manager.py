import json
import sys
from pathlib import Path
from core.paths import (
    APIConfigDecryptionError,
    get_config_file,
    load_api_config,
    save_api_config,
)


# ============================================================
# BASE DIRECTORY
# ============================================================

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent

    return Path(__file__).resolve().parent.parent


CONFIG_FILE = get_config_file()
CONFIG_DIR = CONFIG_FILE.parent


# ============================================================
# CONFIG HELPERS
# ============================================================

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def config_exists() -> bool:
    return CONFIG_FILE.exists()


def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()

    data = load_api_config()
    data["gemini_api_key"] = (
        gemini_api_key or ""
    ).strip()
    save_api_config(data, CONFIG_FILE)


def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}

    try:
        return load_api_config(CONFIG_FILE)

    except APIConfigDecryptionError:
        # The app must remain usable so the key can be replaced in Settings.
        return {}
    except Exception as e:
        print(f"❌ Failed to load api_keys.json ({type(e).__name__}).")
        return {}


def get_gemini_key() -> str | None:
    return load_api_keys().get(
        "gemini_api_key"
    )


def is_configured() -> bool:
    key = get_gemini_key()

    return bool(
        key
        and len(key) > 15
    )


# ============================================================
# ASSISTANT CONFIG
# ============================================================

def get_assistant_name() -> str:
    """
    Return the configured assistant name.
    """

    return (
        load_api_keys().get(
            "assistant_name",
            "NEBIX"
        )
        or "NEBIX"
    )


def get_user_name() -> str:
    """
    Return the configured user name.
    """

    return (
        load_api_keys().get(
            "user_name",
            ""
        )
        or ""
    )


def save_assistant_config(
    assistant_name: str,
    user_name: str
) -> None:
    """
    Persist assistant name and user name.
    """

    ensure_config_dir()

    data: dict = {}

    if CONFIG_FILE.exists():
        try:
            data = json.loads(
                CONFIG_FILE.read_text(
                    encoding="utf-8"
                )
            )

            if not isinstance(data, dict):
                data = {}

        except Exception:
            data = {}

    data["assistant_name"] = (
        assistant_name or ""
    ).strip() or "NEBIX"

    data["user_name"] = (
        user_name or ""
    ).strip()

    CONFIG_FILE.write_text(
        json.dumps(
            data,
            indent=4
        ),
        encoding="utf-8"
    )


# ============================================================
# ASSISTANT VOICES
# ============================================================

# IMPORTANT:
#
# These names MUST match the voice cards shown
# in the NEBIX interface.
#
# Interface voices:
#
#   Zephyr
#   Puck
#   Charon
#   Kore
#   Fenrir
#   Aoede
#
# main.py calls get_voice()
# and sends the returned voice_name
# to Gemini Live.
#
# The selected voice is stored in:
#
#   config/api_keys.json
#
# Example:
#
# {
#     "voice_name": "Zephyr"
# }


AVAILABLE_VOICES = [
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Aoede",
]


# Default voice used when no valid voice
# has been selected yet.
DEFAULT_VOICE = "Puck"


def get_available_voices() -> list[str]:
    """
    Return a copy of all voices available
    in the NEBIX interface.
    """

    return list(AVAILABLE_VOICES)


def _remove_legacy_tts_settings(data: dict) -> bool:
    changed = False
    for key in tuple(data):
        normalized = key.lower()
        if normalized.startswith("elevenlabs") or normalized in {
            "tts_engine",
            "tts_voice",
        }:
            del data[key]
            changed = True
    return changed


def get_voice() -> str:
    """
    Return the currently selected Gemini Live voice.

    If no voice is saved:
        DEFAULT_VOICE is returned.

    If an invalid/old voice is stored:
        DEFAULT_VOICE is returned.

    This guarantees that an unsupported voice
    is never sent to Gemini Live.
    """

    data = load_api_keys()
    if not data:
        return DEFAULT_VOICE

    changed = _remove_legacy_tts_settings(data)

    voice = (
        data.get(
            "voice_name",
            DEFAULT_VOICE
        )
        or DEFAULT_VOICE
    )

    voice = str(
        voice
    ).strip()

    if voice not in AVAILABLE_VOICES:
        voice = DEFAULT_VOICE
        data["voice_name"] = voice
        changed = True

    if changed:
        save_api_config(data, CONFIG_FILE)

    return voice


def save_voice(
    voice_name: str
) -> None:
    """
    Save the selected Gemini Live voice.

    Only voices listed in AVAILABLE_VOICES
    are accepted.

    Invalid values automatically fall back
    to DEFAULT_VOICE.
    """

    ensure_config_dir()

    data = load_api_keys()
    _remove_legacy_tts_settings(data)

    voice = str(voice_name or "").strip()

    if voice in AVAILABLE_VOICES:
        selected_voice = voice
    else:
        selected_voice = DEFAULT_VOICE

    data["voice_name"] = selected_voice

    save_api_config(data, CONFIG_FILE)

    print(
        f"[Voice] Saved: {selected_voice}"
    )


def is_valid_voice(
    voice_name: str
) -> bool:
    """
    Check whether a voice is supported
    by the NEBIX interface/Gemini configuration.
    """

    return (
        str(
            voice_name or ""
        ).strip()
        in AVAILABLE_VOICES
    )


# ============================================================
# GENERIC CONFIG PATCH
# ============================================================

def _patch_config(**fields) -> None:
    """
    Read-modify-write one or more keys
    in api_keys.json.

    Existing settings are preserved.
    """

    ensure_config_dir()

    data: dict = {}

    if CONFIG_FILE.exists():
        try:
            data = json.loads(
                CONFIG_FILE.read_text(
                    encoding="utf-8"
                )
            )

            if not isinstance(data, dict):
                data = {}

        except Exception:
            data = {}

    data.update(fields)

    CONFIG_FILE.write_text(
        json.dumps(
            data,
            indent=4
        ),
        encoding="utf-8"
    )


# ============================================================
# WAKE WORD
# ============================================================

def get_wake_word_enabled() -> bool:
    """
    Whether local wake-word gating is enabled.
    """

    return bool(
        load_api_keys().get(
            "wake_word_enabled",
            False
        )
    )


def save_wake_word_enabled(
    enabled: bool
) -> None:

    _patch_config(
        wake_word_enabled=bool(
            enabled
        )
    )


# ============================================================
# MORNING BRIEF
# ============================================================

def get_brief_enabled() -> bool:
    return bool(
        load_api_keys().get(
            "morning_brief_enabled",
            True
        )
    )


def save_brief_enabled(
    enabled: bool
) -> None:

    _patch_config(
        morning_brief_enabled=bool(
            enabled
        )
    )


# ============================================================
# AUDIO DEVICES
# ============================================================

# Device names are stored instead of
# sounddevice indices.
#
# Empty string:
#     System default device.
#
# This prevents device-index changes when
# USB/Bluetooth devices are plugged/unplugged.


def get_input_device() -> str:
    """
    Return saved microphone device name.

    Empty string means system default.
    """

    return (
        load_api_keys().get(
            "input_device",
            ""
        )
        or ""
    ).strip()


def save_input_device(
    name: str
) -> None:

    _patch_config(
        input_device=(
            name or ""
        ).strip()
    )


def get_output_device() -> str:
    """
    Return saved speaker device name.

    Empty string means system default.
    """

    return (
        load_api_keys().get(
            "output_device",
            ""
        )
        or ""
    ).strip()


def save_output_device(
    name: str
) -> None:

    _patch_config(
        output_device=(
            name or ""
        ).strip()
    )


# ============================================================
# PLUGIN ENABLED
# ============================================================

def get_plugin_enabled(
    plugin_name: str
) -> bool:
    """
    Plugins are enabled by default.
    """

    plugins = load_api_keys().get(
        "plugins_enabled",
        {}
    )

    if not isinstance(
        plugins,
        dict
    ):
        return True

    return bool(
        plugins.get(
            plugin_name,
            True
        )
    )


def save_plugin_enabled(
    plugin_name: str,
    enabled: bool
) -> None:

    ensure_config_dir()

    data: dict = {}

    if CONFIG_FILE.exists():
        try:
            data = json.loads(
                CONFIG_FILE.read_text(
                    encoding="utf-8"
                )
            )

            if not isinstance(data, dict):
                data = {}

        except Exception:
            data = {}

    plugins_cfg = data.get(
        "plugins_enabled"
    )

    if not isinstance(
        plugins_cfg,
        dict
    ):
        plugins_cfg = {}

    plugins_cfg[
        plugin_name
    ] = bool(enabled)

    data[
        "plugins_enabled"
    ] = plugins_cfg

    CONFIG_FILE.write_text(
        json.dumps(
            data,
            indent=4
        ),
        encoding="utf-8"
    )


# ============================================================
# PLUGIN CONFIG
# ============================================================

def get_plugin_config(
    namespace: str
) -> dict:
    """
    Return all stored values for
    a plugin namespace.
    """

    cfg = load_api_keys().get(
        "plugin_config"
    )

    if not isinstance(
        cfg,
        dict
    ):
        return {}

    val = cfg.get(
        namespace
    )

    if not isinstance(
        val,
        dict
    ):
        return {}

    return dict(val)


def get_plugin_setting(
    namespace: str,
    key: str,
    default=None
):
    """
    Return one plugin setting.
    """

    return get_plugin_config(
        namespace
    ).get(
        key,
        default
    )


def save_plugin_config(
    namespace: str,
    values: dict
) -> None:
    """
    Merge plugin settings into the
    existing plugin namespace.
    """

    ensure_config_dir()

    data: dict = {}

    if CONFIG_FILE.exists():
        try:
            data = json.loads(
                CONFIG_FILE.read_text(
                    encoding="utf-8"
                )
            )

            if not isinstance(data, dict):
                data = {}

        except Exception:
            data = {}

    plugin_config = data.get(
        "plugin_config"
    )

    if not isinstance(
        plugin_config,
        dict
    ):
        plugin_config = {}

    current = plugin_config.get(
        namespace
    )

    if not isinstance(
        current,
        dict
    ):
        current = {}

    if isinstance(
        values,
        dict
    ):
        current.update(
            values
        )

    plugin_config[
        namespace
    ] = current

    data[
        "plugin_config"
    ] = plugin_config

    CONFIG_FILE.write_text(
        json.dumps(
            data,
            indent=4
        ),
        encoding="utf-8"
    )
