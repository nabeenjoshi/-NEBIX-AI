from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo


NEPAL_TIMEZONE = ZoneInfo("Asia/Kathmandu")


def nepal_now() -> datetime:
    return datetime.now(NEPAL_TIMEZONE)


def as_nepal_time(value: datetime | None = None) -> datetime:
    current = nepal_now() if value is None else value
    if current.tzinfo is None:
        return current.replace(tzinfo=NEPAL_TIMEZONE)
    return current.astimezone(NEPAL_TIMEZONE)


def format_nepal_date(value: datetime | None = None) -> str:
    current = as_nepal_time(value)
    return f"{current:%A, %B} {current.day}, {current.year}"


def format_nepal_time(value: datetime | None = None) -> str:
    current = as_nepal_time(value)
    hour = current.strftime("%I").lstrip("0") or "12"
    return f"{hour}:{current:%M} {current:%p}"


def format_nepal_clock(value: datetime | None = None) -> str:
    return as_nepal_time(value).strftime("%I:%M %p")


def nepal_datetime_context(value: datetime | None = None) -> str:
    current = as_nepal_time(value)
    return (
        "[CURRENT DATE & TIME — NEPAL]\n"
        f"Current Nepal date: {format_nepal_date(current)}\n"
        f"Current Nepal time: {format_nepal_time(current)}\n"
        "Use this runtime-provided value for current date/time questions. "
        "Never infer or guess the current date or time. "
        "Repeat the runtime hour, minute, and AM/PM exactly; do not recalculate them. "
        "Creation and launch dates in identity or memory are historical facts, never today's date. "
        "NEBIX uses the Asia/Kathmandu timezone (UTC+05:45).\n"
    )


def answer_nepal_datetime_question(
    text: str,
    value: datetime | None = None,
) -> str | None:
    raw_text = str(text or "").casefold().replace("’", "'").replace("'", "")
    normalized = " ".join(
        "".join(
            char if char.isalnum() or char.isspace() else " "
            for char in raw_text
        ).split()
    )
    normalized = re.sub(r"^(?:hey\s+)?nebix\s+", "", normalized)

    date_questions = {
        "what is todays date",
        "whats todays date",
        "what date is it today",
        "what is the date today",
        "what date is it",
        "what is the date",
        "whats the date",
        "what day is it today",
        "what day is it",
        "tell me the date",
        "tell me todays date",
        "date today",
    }
    if normalized in date_questions:
        return f"Today is {format_nepal_date(value)} in Nepal."

    time_questions = {
        "what time is it",
        "what is the time",
        "whats the time",
        "what is the current time",
        "what is current time",
        "what is the current time in nepal",
        "what is current time in nepal",
        "what time is it in nepal",
        "whats the time in nepal",
        "current time in nepal",
        "tell me the time",
    }
    if normalized in time_questions:
        return f"It is {format_nepal_time(value)} in Nepal."

    return None
