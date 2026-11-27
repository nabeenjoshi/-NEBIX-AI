from __future__ import annotations

import re
import unicodedata


EXIT_NEBIX = "EXIT_NEBIX"
CANCEL_CURRENT_ACTION = "CANCEL_CURRENT_ACTION"
WINDOWS_SYSTEM_SHUTDOWN = "WINDOWS_SYSTEM_SHUTDOWN"

_TOKEN_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SHUTDOWN_WORDS = (
    "shutdown",
    "shut down",
    "power off",
    "turn off",
    "switch off",
    "बन्द गर",
    "बन्द गर्नु",
    "बन्द गरिदेऊ",
    "बन्द गरिदेउ",
)
_DEVICE_WORDS = (
    "laptop",
    "computer",
    "pc",
    "desktop",
    "ल्यापटप",
    "कम्प्युटर",
)
_STOP_WORDS = (
    "stop",
    "cancel",
    "abort",
    "halt",
    "रोक",
    "रोक्नु",
    "रोकिदेऊ",
    "रोकिदेउ",
)


def _normalise(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    cleaned_chars: list[str] = []
    for ch in value:
        category = unicodedata.category(ch)
        if ch.isspace():
            cleaned_chars.append(" ")
        elif category.startswith(("L", "N")) or category in {"Mn", "Mc", "Me"}:
            cleaned_chars.append(ch)
        else:
            cleaned_chars.append(" ")
    return " ".join("".join(cleaned_chars).split())


def _has_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    normalized_text = f" {text} "
    return any(f" {phrase} " in normalized_text for phrase in phrases)


def _matches_exit_phrase(text: str) -> bool:
    normalized = _normalise(text)
    return bool(
        normalized in {"goodbye", "bye", "बिदा", "अलविदा"}
        or "nebix" in normalized.split() and any(word in normalized.split() for word in {"goodbye", "bye", "exit", "quit", "close", "बिदा", "अलविदा"})
        or "nebix" in normalized.split() and _has_phrase(normalized, ("shutdown", "shut down", "power off", "turn off", "switch off", "बन्द गर", "बन्द गर्नु", "बन्द गरिदेऊ", "बन्द गरिदेउ"))
        or "nebix" in normalized.split() and "बन्द" in normalized.split() and any(token in normalized.split() for token in ("गर", "गर्नु", "हो", "गरिदेऊ", "गरिदेउ"))
    )


def _matches_cancel_phrase(text: str) -> bool:
    normalized = _normalise(text)
    tokens = normalized.split()
    if not tokens:
        return False
    has_stop = _has_phrase(normalized, _STOP_WORDS)
    if not has_stop:
        return False
    stop_scope = {
        "nebix",
        "action",
        "task",
        "current",
        "that",
        "this",
        "it",
        "download",
        "काम",
        "यो",
        "अहिले",
        "गरिरहेको",
    }
    return bool("nebix" in tokens or len(tokens) == 1 or stop_scope.intersection(tokens))


def classify_command_intent(text: str) -> str | None:
    """Classify only explicit, high-confidence local control commands."""
    normalized = _normalise(text)
    if not normalized:
        return None

    tokens = normalized.split()
    has_device = _has_phrase(normalized, _DEVICE_WORDS)
    has_shutdown = _has_phrase(normalized, _SHUTDOWN_WORDS)
    is_question = (
        "?" in str(text or "")
        or any(
            phrase in normalized
            for phrase in (
                "how do i ",
                "how to ",
                "should i ",
                "can you explain ",
                "can you tell me ",
                "is it safe to ",
                "what happens if ",
                "whether i should ",
            )
        )
    )

    if has_device and has_shutdown and not is_question:
        return WINDOWS_SYSTEM_SHUTDOWN

    if _matches_exit_phrase(text):
        return EXIT_NEBIX

    if _matches_cancel_phrase(text):
        return CANCEL_CURRENT_ACTION

    return None