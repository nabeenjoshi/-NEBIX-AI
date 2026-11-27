from __future__ import annotations

from typing import Any

import requests

from core.paths import (
    APIConfigDecryptionError,
    _DPAPI_PREFIX,
    backup_api_config,
    get_config_file,
    load_api_config,
    load_api_config_raw,
    save_api_config,
    _unprotect_secret,
)


PROVIDER_INFO = {
    "gemini": {"name": "Google Gemini", "key_name": "gemini_api_key"},
    "openai": {"name": "OpenAI", "key_name": "openai_api_key"},
    "anthropic": {"name": "Anthropic", "key_name": "anthropic_api_key"},
    "groq": {"name": "Groq", "key_name": "groq_api_key"},
    "openrouter": {"name": "OpenRouter", "key_name": "openrouter_api_key"},
}

_OPENAI_COMPATIBLE = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}

DEFAULT_GEMINI_CHAT_MODEL = "gemini-flash-latest"


def _provider(provider: str) -> str:
    provider_id = str(provider or "").strip().lower()
    if provider_id not in PROVIDER_INFO:
        raise ValueError("Unsupported AI provider.")
    return provider_id


def _response_error(response: requests.Response, api_key: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    error = payload.get("error", payload) if isinstance(payload, dict) else {}
    if isinstance(error, dict):
        message = error.get("message") or error.get("detail") or ""
        code = error.get("code") or error.get("type") or ""
    else:
        message = str(error or "")
        code = ""

    if response.status_code in (401, 403):
        return "The provider rejected this API key or its permissions (HTTP " + str(response.status_code) + ")."
    if response.status_code == 429:
        return "The provider rate limit or quota was reached (HTTP 429)."
    if response.status_code >= 500:
        return "The provider returned a server error (HTTP " + str(response.status_code) + ")."

    detail = " ".join(str(message or code).replace(api_key, "[redacted]").split())
    if detail:
        return f"Provider request failed (HTTP {response.status_code}): {detail[:500]}"
    return f"Provider request failed (HTTP {response.status_code})."


def _get_json(
    provider: str,
    api_key: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict:
    headers = {"Accept": "application/json"}
    if provider == "anthropic":
        headers.update({
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        })
    else:
        headers["Authorization"] = "Bearer " + api_key
    try:
        response = requests.get(url, headers=headers, params=params, timeout=(5, 20))
    except requests.Timeout as exc:
        raise RuntimeError("The provider request timed out.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Could not connect to the provider. Check the network connection.") from exc
    if not response.ok:
        raise RuntimeError(_response_error(response, api_key))
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("The provider returned an invalid JSON response.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("The provider returned an unexpected response format.")
    return payload


def fetch_provider_models(provider: str, api_key: str) -> list[str]:
    provider_id = _provider(provider)
    key = str(api_key or "").strip()
    if not key:
        raise ValueError("Enter the provider API key.")

    if provider_id == "gemini":
        from google import genai

        client = None
        try:
            client = genai.Client(api_key=key)
            models = client.models.list()
            names = {
                str(model.name).removeprefix("models/")
                for model in models
                if getattr(model, "name", None)
                and "generateContent" in (getattr(model, "supported_actions", None) or [])
            }
        except Exception as exc:
            message = str(exc).replace(key, "[redacted]")
            raise RuntimeError(f"Google Gemini validation failed: {message}") from exc
        finally:
            if client is not None:
                client.close()
        return sorted(names)

    if provider_id == "anthropic":
        url = "https://api.anthropic.com/v1/models"
        query: dict[str, Any] = {"limit": 100}
    elif provider_id in _OPENAI_COMPATIBLE:
        url = _OPENAI_COMPATIBLE[provider_id] + "/models"
        query = {}
    else:
        raise ValueError("Unsupported AI provider.")

    found: set[str] = set()
    after_id = None
    for _ in range(20):
        if provider_id == "anthropic" and after_id:
            query["after_id"] = after_id
        payload = _get_json(provider_id, key, url, params=query)
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise RuntimeError("The provider returned an invalid model list.")
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                found.add(item["id"])
        if provider_id != "anthropic" or not payload.get("has_more"):
            break
        next_after = payload.get("last_id")
        if not next_after or next_after == after_id:
            raise RuntimeError("Anthropic model pagination did not advance.")
        after_id = next_after

    if not found:
        raise RuntimeError("The API key was accepted, but the provider returned no available models.")
    return sorted(found)


def validate_provider_key(provider: str, api_key: str) -> list[str]:
    models = fetch_provider_models(provider, api_key)
    if not models:
        raise RuntimeError("No supported generation models are available for this API key.")
    return models


def refresh_provider_models(provider: str) -> dict:
    provider_id = _provider(provider)
    config = load_api_config()
    api_key = str(config.get(PROVIDER_INFO[provider_id]["key_name"]) or "").strip()
    if not api_key:
        raise ValueError(f"No {PROVIDER_INFO[provider_id]['name']} API key is connected.")
    models = validate_provider_key(provider_id, api_key)
    cached_models = config.get("ai_provider_models", {})
    if not isinstance(cached_models, dict):
        cached_models = {}
    cached_models[provider_id] = models
    config["ai_provider_models"] = cached_models

    selected_models = config.get("ai_provider_selected_models", {})
    if not isinstance(selected_models, dict):
        selected_models = {}
    if selected_models.get(provider_id) not in models:
        selected_models[provider_id] = (
            DEFAULT_GEMINI_CHAT_MODEL
            if provider_id == "gemini" and DEFAULT_GEMINI_CHAT_MODEL in models
            else models[0]
        )
    config["ai_provider_selected_models"] = selected_models

    verification = config.get("ai_provider_verified", {})
    if not isinstance(verification, dict):
        verification = {}
    verification[provider_id] = True
    config["ai_provider_verified"] = verification
    save_api_config(config)
    return get_provider_settings()


def connect_provider(provider: str, api_key: str) -> dict:
    provider_id = _provider(provider)
    key = str(api_key or "").strip()
    models = validate_provider_key(provider_id, key)

    key_name = PROVIDER_INFO[provider_id]["key_name"]
    config_path = get_config_file()
    replaced_unreadable_key = False
    backup_path = None
    try:
        config = load_api_config(config_path)
    except APIConfigDecryptionError as exc:
        if provider_id != "gemini" or exc.field != key_name:
            raise
        config = load_api_config_raw(config_path)
        opaque_value = config.get(key_name)
        if not (
            isinstance(opaque_value, str)
            and opaque_value.startswith(_DPAPI_PREFIX)
        ):
            raise
        backup_path = backup_api_config(config_path)
        replaced_unreadable_key = True

    config[key_name] = key
    cached_models = config.get("ai_provider_models", {})
    if not isinstance(cached_models, dict):
        cached_models = {}
    cached_models[provider_id] = models
    config["ai_provider_models"] = cached_models

    selected_models = config.get("ai_provider_selected_models", {})
    if not isinstance(selected_models, dict):
        selected_models = {}
    current_model = selected_models.get(provider_id)
    if current_model not in models:
        if provider_id == "gemini" and DEFAULT_GEMINI_CHAT_MODEL in models:
            selected_models[provider_id] = DEFAULT_GEMINI_CHAT_MODEL
        else:
            selected_models[provider_id] = models[0]
    config["ai_provider_selected_models"] = selected_models

    verification = config.get("ai_provider_verified", {})
    if not isinstance(verification, dict):
        verification = {}
    verification[provider_id] = True
    config["ai_provider_verified"] = verification
    config["active_ai_provider"] = provider_id
    save_api_config(config, config_path)

    if replaced_unreadable_key:
        saved = load_api_config_raw(config_path).get(key_name)
        if not isinstance(saved, str) or not saved.startswith(_DPAPI_PREFIX):
            raise RuntimeError("The replacement Gemini key was not stored with DPAPI.")
        try:
            persisted_key = _unprotect_secret(saved[len(_DPAPI_PREFIX):])
        except Exception as exc:
            raise RuntimeError(
                "The replacement Gemini key could not be verified after saving."
            ) from exc
        if persisted_key != key:
            raise RuntimeError(
                "The replacement Gemini key did not match its protected saved value."
            )

    return {
        "provider": provider_id,
        "connected": True,
        "models": models,
        "selected_model": selected_models[provider_id],
        "replaced_unreadable_key": replaced_unreadable_key,
        "backup_created": backup_path is not None,
    }


def get_provider_settings(*, gemini_live_connected: bool = False) -> dict:
    config = load_api_config()
    verified = config.get("ai_provider_verified", {})
    if not isinstance(verified, dict):
        verified = {}
    model_lists = config.get("ai_provider_models", {})
    if not isinstance(model_lists, dict):
        model_lists = {}
    selected_models = config.get("ai_provider_selected_models", {})
    if not isinstance(selected_models, dict):
        selected_models = {}

    providers = []
    for provider_id, info in PROVIDER_INFO.items():
        has_key = bool(str(config.get(info["key_name"]) or "").strip())
        connected = has_key and (
            bool(verified.get(provider_id))
            or (provider_id == "gemini" and gemini_live_connected)
        )
        models = model_lists.get(provider_id, [])
        if not isinstance(models, list):
            models = []
        selected = str(selected_models.get(provider_id) or "")
        if selected not in models and models:
            selected = models[0]
        providers.append({
            "id": provider_id,
            "name": info["name"],
            "connected": connected,
            "models": models,
            "model": selected,
        })

    active = str(config.get("active_ai_provider") or "gemini").lower()
    if active not in PROVIDER_INFO:
        active = "gemini"
    selected_provider = next(item for item in providers if item["id"] == active)
    if not selected_provider["connected"]:
        active = "gemini" if next(item for item in providers if item["id"] == "gemini")["connected"] else ""

    return {
        "providers": providers,
        "activeProvider": active,
        "activeModel": next(
            (item["model"] for item in providers if item["id"] == active),
            "",
        ),
    }


def set_active_provider(
    provider: str,
    *,
    gemini_live_connected: bool = False,
) -> dict:
    provider_id = _provider(provider)
    config = load_api_config()
    info = PROVIDER_INFO[provider_id]
    verified = config.get("ai_provider_verified", {})
    if not isinstance(verified, dict):
        verified = {}
    verified_connection = bool(verified.get(provider_id)) or (
        provider_id == "gemini" and gemini_live_connected
    )
    if not config.get(info["key_name"]) or not verified_connection:
        raise ValueError(f"Connect {info['name']} before making it active.")
    config["active_ai_provider"] = provider_id
    save_api_config(config)
    return get_provider_settings()


def set_provider_model(provider: str, model: str) -> dict:
    provider_id = _provider(provider)
    selected_model = str(model or "").strip()
    config = load_api_config()
    models = config.get("ai_provider_models", {})
    available = models.get(provider_id, []) if isinstance(models, dict) else []
    if selected_model not in available:
        raise ValueError("Select a model returned by the connected provider.")
    selected = config.get("ai_provider_selected_models", {})
    if not isinstance(selected, dict):
        selected = {}
    selected[provider_id] = selected_model
    config["ai_provider_selected_models"] = selected
    save_api_config(config)
    return get_provider_settings()


def remove_provider(provider: str) -> dict:
    provider_id = _provider(provider)
    config = load_api_config()
    config.pop(PROVIDER_INFO[provider_id]["key_name"], None)
    for field in ("ai_provider_models", "ai_provider_selected_models", "ai_provider_verified"):
        values = config.get(field, {})
        if isinstance(values, dict):
            values.pop(provider_id, None)
            config[field] = values

    active = str(config.get("active_ai_provider") or "")
    if active == provider_id:
        config["active_ai_provider"] = next(
            (
                candidate
                for candidate, info in PROVIDER_INFO.items()
                if candidate != provider_id
                and config.get(info["key_name"])
                and config.get("ai_provider_verified", {}).get(candidate)
            ),
            "",
        )
    save_api_config(config)
    return get_provider_settings()


def generate_chat_response(
    provider: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    system_instruction: str = "",
    image: dict[str, str] | None = None,
    images: list[dict[str, str]] | None = None,
) -> str:
    provider_id = _provider(provider)
    if provider_id == "gemini":
        from google import genai

        contents = []
        for item in messages:
            role = "model" if item.get("role") == "assistant" else "user"
            text = str(item.get("text") or "")
            parts: list[dict[str, Any]] = []
            if text:
                parts.append({"text": text})
            if item is messages[-1]:
                attached_images = list(images or [])
                if image:
                    attached_images.append(image)
                for attached_image in attached_images:
                    parts.append({
                        "inline_data": {
                            "mime_type": attached_image["mime_type"],
                            "data": attached_image["data"],
                        }
                    })
            if parts:
                contents.append({"role": role, "parts": parts})
        client = None
        try:
            from google.genai import types

            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=60000),
            )
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction or None,
                ),
            )
        except Exception as exc:
            message = str(exc).replace(api_key, "[redacted]")
            raise RuntimeError(f"Google Gemini request failed: {message}") from exc
        finally:
            if client is not None:
                client.close()
        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            raise RuntimeError("Google Gemini returned an empty response.")
        return text

    if not messages:
        raise ValueError("At least one chat message is required.")

    if provider_id == "anthropic":
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        turns: list[dict[str, Any]] = []
        for index, item in enumerate(messages):
            role = "assistant" if item.get("role") == "assistant" else "user"
            content: Any = str(item.get("text") or "")
            if (image or images) and index == len(messages) - 1:
                attached_image = (images or [image])[0]
                content = [
                    {"type": "text", "text": content},
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": attached_image["mime_type"],
                            "data": attached_image["data"],
                        },
                    },
                ]
            turns.append({"role": role, "content": content})
        payload = {
            "model": model,
            "max_tokens": 2048,
            "messages": turns,
        }
        if system_instruction:
            payload["system"] = system_instruction
        url = "https://api.anthropic.com/v1/messages"
    else:
        headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        }
        turns = []
        if system_instruction:
            turns.append({"role": "system", "content": system_instruction})
        for index, item in enumerate(messages):
            content = str(item.get("text") or "")
            if (image or images) and index == len(messages) - 1:
                attached_image = (images or [image])[0]
                content = [
                    {"type": "text", "text": content},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{attached_image['mime_type']};base64,{attached_image['data']}"
                        },
                    },
                ]
            turns.append({
                "role": "assistant" if item.get("role") == "assistant" else "user",
                "content": content,
            })
        payload = {"model": model, "messages": turns, "max_tokens": 2048}
        url = _OPENAI_COMPATIBLE[provider_id] + "/chat/completions"

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=(5, 60))
    except requests.Timeout as exc:
        raise RuntimeError("The provider response timed out.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Could not connect to the provider. Check the network connection.") from exc
    if not response.ok:
        raise RuntimeError(_response_error(response, api_key))
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("The provider returned an invalid JSON response.") from exc

    if provider_id == "anthropic":
        response_content = result.get("content", [])
        text = "\n".join(
            block.get("text", "")
            for block in response_content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
    else:
        choices = result.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content", "")
        if isinstance(content, list):
            text = "\n".join(
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict)
            ).strip()
        else:
            text = str(content or "").strip()
    if not text:
        raise RuntimeError("The provider returned an empty response.")
    return text
