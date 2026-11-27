"""Personal communication style settings and prompt instructions."""

from __future__ import annotations

from typing import Any


WHATSAPP_STYLE_DEFAULTS = {
    "enabled": True,
    "intensity": "Natural",
    "shortFormLevel": "Natural",
    "casualness": "Natural",
    "respectfulness": "Contextual",
    "englishMixing": "Natural",
    "messageLength": "Short",
    "emojiUsage": "Natural",
}

PERSONAL_RESPONSE_DEFAULTS = {
    "responseStyle": "Balanced",
    "responseLength": "Normal",
    "languagePreference": "Auto Detect",
    "voiceResponseLength": "Normal",
    "confirmationBehavior": "Normal",
    "personalityIntensity": 50,
}

_PERSONAL_RESPONSE_OPTIONS = {
    "responseStyle": {"Balanced", "Concise", "Detailed", "Direct", "Technical", "Friendly"},
    "responseLength": {"Very Short", "Short", "Normal", "Detailed", "Very Detailed"},
    "languagePreference": {"English", "Nepali", "Nepali + English", "Auto Detect"},
    "voiceResponseLength": {"Short", "Normal", "Detailed"},
    "confirmationBehavior": {"Minimal", "Normal", "Confirm Important Actions"},
}

_WHATSAPP_STYLE_OPTIONS = {
    "intensity": {"Off", "Light", "Natural", "Strong"},
    "shortFormLevel": {"Minimal", "Natural", "More"},
    "casualness": {"Reserved", "Natural", "Very casual"},
    "respectfulness": {"Contextual", "Casual", "Respectful", "Mixed"},
    "englishMixing": {"Contextual", "Less", "Natural", "More"},
    "messageLength": {"Very Short", "Short", "Normal", "Detailed"},
    "emojiUsage": {"None", "Minimal", "Natural", "More"},
}


def normalize_whatsapp_style_settings(value: Any) -> dict[str, Any]:
    """Return valid saved options with defaults for missing or invalid values."""
    normalized = dict(WHATSAPP_STYLE_DEFAULTS)
    if not isinstance(value, dict):
        return normalized

    for key, option in _WHATSAPP_STYLE_OPTIONS.items():
        selected = value.get(key)
        if isinstance(selected, str) and selected in option:
            normalized[key] = selected

    if isinstance(value.get("enabled"), bool):
        normalized["enabled"] = value["enabled"]

    return normalized


def validate_whatsapp_style_settings(value: Any) -> dict[str, Any]:
    """Validate a settings update and return a complete normalized profile."""
    if not isinstance(value, dict):
        raise ValueError("WhatsApp Style settings must be an object.")

    unsupported = set(value) - set(WHATSAPP_STYLE_DEFAULTS)
    if unsupported:
        raise ValueError(
            "Unsupported WhatsApp Style setting: "
            + ", ".join(sorted(unsupported))
        )

    normalized = dict(WHATSAPP_STYLE_DEFAULTS)
    for key, option in _WHATSAPP_STYLE_OPTIONS.items():
        if key in value:
            if not isinstance(value[key], str) or value[key] not in option:
                raise ValueError(f"Unsupported WhatsApp Style value for {key}.")
            normalized[key] = value[key]

    if "enabled" in value:
        if not isinstance(value["enabled"], bool):
            raise ValueError("WhatsApp Style enabled must be true or false.")
        normalized["enabled"] = value["enabled"]

    return normalized


def normalize_personal_response_settings(value: Any) -> dict[str, Any]:
    normalized = dict(PERSONAL_RESPONSE_DEFAULTS)
    if not isinstance(value, dict):
        return normalized
    for key, options in _PERSONAL_RESPONSE_OPTIONS.items():
        selected = value.get(key)
        if isinstance(selected, str) and selected in options:
            normalized[key] = selected
    intensity = value.get("personalityIntensity")
    if isinstance(intensity, int) and not isinstance(intensity, bool):
        normalized["personalityIntensity"] = max(0, min(100, intensity))
    return normalized


def validate_personal_response_settings(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Personal Response settings must be an object.")
    unsupported = set(value) - set(PERSONAL_RESPONSE_DEFAULTS)
    if unsupported:
        raise ValueError(
            "Unsupported Personal Response setting: "
            + ", ".join(sorted(unsupported))
        )
    normalized = dict(PERSONAL_RESPONSE_DEFAULTS)
    for key, options in _PERSONAL_RESPONSE_OPTIONS.items():
        if key in value:
            selected = value[key]
            if not isinstance(selected, str) or selected not in options:
                raise ValueError(f"Unsupported Personal Response value for {key}.")
            normalized[key] = selected
    if "personalityIntensity" in value:
        intensity = value["personalityIntensity"]
        if not isinstance(intensity, int) or isinstance(intensity, bool) or not 0 <= intensity <= 100:
            raise ValueError("Personality intensity must be a whole number from 0 to 100.")
        normalized["personalityIntensity"] = intensity
    return normalized


def build_personal_response_instructions(value: Any) -> str:
    settings = normalize_personal_response_settings(value)
    style = {
        "Balanced": "Use a clear, natural balance of warmth and useful detail.",
        "Concise": "Prefer concise answers and omit repetition.",
        "Detailed": "Explain the reasoning and useful context when the request benefits from it.",
        "Direct": "Lead with the answer or action; keep the wording straightforward.",
        "Technical": "Use precise technical language and explain specialized terms when useful.",
        "Friendly": "Be warm and approachable without being overfamiliar or slang-heavy.",
    }[settings["responseStyle"]]
    length = {
        "Very Short": "Keep ordinary answers to one brief sentence when possible.",
        "Short": "Prefer a few concise sentences for ordinary answers.",
        "Normal": "Use the amount of detail the request reasonably needs.",
        "Detailed": "Provide a fuller explanation when useful, while staying focused.",
        "Very Detailed": "Be thorough for substantive requests; do not inflate simple answers.",
    }[settings["responseLength"]]
    language = {
        "English": "Respond in English unless the user explicitly requests another language.",
        "Nepali": "Prefer Nepali for responses, preserving technical names and requested quotations as appropriate.",
        "Nepali + English": "Use a natural Nepali-English mix, following the user's wording and context.",
        "Auto Detect": "Follow the language and language mix used by the user.",
    }[settings["languagePreference"]]
    voice_length = {
        "Short": "For spoken replies, keep the spoken answer short and easy to follow.",
        "Normal": "For spoken replies, use a natural amount of detail and avoid reading long formatting aloud.",
        "Detailed": "For spoken replies, include the requested detail, organized into easy-to-follow phrases.",
    }[settings["voiceResponseLength"]]
    confirmation = {
        "Minimal": "Avoid unnecessary verbal check-ins, but never bypass required user confirmation for irreversible or safety-sensitive actions.",
        "Normal": "Ask a brief clarification or confirmation when it is genuinely needed; preserve every required safety confirmation.",
        "Confirm Important Actions": "Ask before consequential actions when appropriate, and always preserve the interface's required confirmation gate for irreversible actions.",
    }[settings["confirmationBehavior"]]
    intensity = settings["personalityIntensity"]
    personality = (
        "Express the configured NEBIX personality subtly."
        if intensity < 34
        else "Express the configured NEBIX personality naturally without artificial slang."
        if intensity < 68
        else "Express the configured NEBIX personality clearly but naturally; do not become theatrical, excessively slang-heavy, or artificial."
    )
    return "\n".join(
        (
            "[PERSONAL RESPONSE PROFILE]",
            "Apply these preferences to normal answers in both chat and voice. Follow the user's explicit request first and keep every response natural.",
            style,
            length,
            language,
            voice_length,
            confirmation,
            f"Personality intensity: {intensity}/100. {personality}",
        )
    )


def build_whatsapp_style_instructions(value: Any) -> str:
    """Build the personal-message-only prompt section from saved settings."""
    settings = normalize_whatsapp_style_settings(value)
    if not settings["enabled"] or settings["intensity"] == "Off":
        return ""

    intensity = {
        "Light": "Apply gently and preserve the user's requested language and wording.",
        "Natural": "Use naturally when the user asks for a personal message; do not force it.",
        "Strong": "Use the established profile consistently when asked for a personal message, without making it unreadable.",
    }[settings["intensity"]]
    short_forms = {
        "Minimal": "Use only the most established forms when they fit; otherwise spell words naturally.",
        "Natural": "Use preferred short forms in context, but do not abbreviate every word.",
        "More": "Use preferred short forms more often where they remain immediately readable; never invent compressed spellings.",
    }[settings["shortFormLevel"]]
    casualness = {
        "Reserved": "Keep the message relaxed but restrained.",
        "Natural": "Keep it informal, direct, and spontaneous without adding slang just to sound casual.",
        "Very casual": "Allow close-friend expressions when the relationship and message make them natural.",
    }[settings["casualness"]]
    respectfulness = {
        "Contextual": "Match the relationship and the user's requested level of respect; preserve respectful forms when present.",
        "Casual": "Use familiar, casual forms only when the relationship supports them.",
        "Respectful": "Keep respectful Nepali forms such as 'sanchai hunuhunxa hjr' and 'vannuhunthyo'; do not flatten them into casual speech.",
        "Mixed": "Allow mixed casual-respectful phrasing when the user uses it, preserving honorific verbs and address naturally.",
    }[settings["respectfulness"]]
    english_mixing = {
        "Contextual": "Follow the language balance implied by the request and conversation.",
        "Less": "Prefer Romanized Nepali when the user's request is Nepali, while retaining English words that fit naturally.",
        "Natural": "Mix English and Romanized Nepali naturally; do not force either language.",
        "More": "Allow somewhat more English mixing when it sounds like the user's own message; never translate everything mechanically.",
    }[settings["englishMixing"]]
    message_length = {
        "Very Short": "Prefer one very short message; expand only if the user explicitly asks.",
        "Short": "Default to one or two short sentences, usually just the message itself. Expand only when explicitly asked for detail or context requires it.",
        "Normal": "Match the requested length while keeping simple messages short.",
        "Detailed": "Give more detail only when the user asks for a detailed message; otherwise stay concise.",
    }[settings["messageLength"]]
    emoji_usage = {
        "None": "Do not add emojis unless the user explicitly asks for them.",
        "Minimal": "Use an emoji only when it clearly fits the user's intent.",
        "Natural": "Mirror the user's emoji use and the tone of the conversation; do not add one by default.",
        "More": "Allow emojis more often in friendly personal messages, but keep them relevant and avoid clutter.",
    }[settings["emojiUsage"]]

    return "\n".join(
        (
            "[PERSONAL MESSAGE DRAFTING — NABEENEYYY WHATSAPP STYLE]",
            "This is a specific Romanized Nepali texting profile, not generic casual or Gen Z English. Apply it only to the message text when the user explicitly asks you to write, rewrite, or suggest a personal/social message for another person. Never use this profile for NEBIX's own answers, voice, chat, system messages, explanations, confirmations, or commands. Understanding informal Nepali is not permission to mirror its slang. Keep NEBIX's own voice respectful, professional, calm, and concise; use Boss or Sir naturally only when appropriate.",
            intensity,
            short_forms,
            "Preferred spellings, only where grammatically and conversationally appropriate: छ → chha, छु → xu, छौ → xau, छौं → xam, के → k, भ/भा → va, छस् → xas, छैन → xaina, छैनौ → xainau, गर्छु → garxu, गर्छौ → garxau, जान्छौ → janxau, आउँछु → aauxu, आउँछौ → aauxau, खानुभयो → khanuvayo, भन्नुहुन्थ्यो → vannuhunthyo, भन्दै थियो → vandai thi, भन्दै छ → vandai xa.",
            "Use person and number accurately: ma sanchai xu; timi sanchai xau; u ghar ma xa; timi kata xas; hami ghar ma xam. Do not substitute these forms for one another.",
            "Keep messages short, lowercase, natural, direct, and conversational. Avoid formal punctuation, long paragraphs, and aggressive abbreviation. Natural examples include 'k gardai xau', 'ma pani sanchai xu', and 'jhut na bola yrr'; never compress them into unreadable forms like 'k grdx x'.",
            "Use established expressions such as k, ahh, lala, umm, aww, hora, hoina, hola, ksm, and yrr only when they fit the conversation. Respectful examples include 'sanchai hunuhunxa hjr' and 'vannuhunthyo'. Do not repeat expressions mechanically, add 'yrr' to every message, or invent slang/abbreviations. Learn no new style patterns unless the user explicitly provides or configures them.",
            casualness,
            respectfulness,
            english_mixing,
            message_length,
            emoji_usage,
            "Preserve the user's intended meaning and the language balance of the conversation. Return the requested message itself without explaining the style unless asked.",
        )
    )
