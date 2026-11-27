from __future__ import annotations

import json
from functools import lru_cache
from types import MappingProxyType
from typing import Mapping

from core.paths import resource_path


_IDENTITY_FIELDS = ("name", "creator", "brand", "created", "project")


@lru_cache(maxsize=1)
def _load_identity() -> Mapping[str, str]:
    path = resource_path("config", "nebix_identity.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"NEBIX identity must be a JSON object: {path}")
    identity = {
        field: data.get(field)
        for field in _IDENTITY_FIELDS
    }
    if any(not isinstance(value, str) or not value.strip() for value in identity.values()):
        raise ValueError(f"NEBIX identity has missing or invalid required fields: {path}")
    return MappingProxyType(identity)


def get_identity() -> dict[str, str]:
    return dict(_load_identity())


def get_name() -> str:
    return _load_identity()["name"]


def get_creator() -> str:
    return _load_identity()["creator"]


def get_brand() -> str:
    return _load_identity()["brand"]


def get_created_date() -> str:
    return _load_identity()["created"]


def get_project() -> str:
    return _load_identity()["project"]


def answer_identity_question(text: str) -> str | None:
    normalized = " ".join(
        "".join(char if char.isalnum() or char.isspace() else " " for char in str(text or "").casefold()).split()
    )
    identity = _load_identity()
    if any(phrase in normalized for phrase in (
        "who created you", "who made you", "who is your creator",
    )):
        return f"I was created by {identity['creator']}."
    if any(phrase in normalized for phrase in (
        "when were you created", "when were you made", "when was nebix created",
    )):
        return f"I was created on {identity['created']}."
    if any(phrase in normalized for phrase in (
        "what are you", "what is nebix", "what is your project",
    )):
        return f"I am {identity['project']}, by NABEENEYYY."
    if any(phrase in normalized for phrase in (
        "who are you", "what is your name", "tell me about yourself",
    )):
        return f"I am {identity['name']}, {identity['project']}, by NABEENEYYY."
    return None
