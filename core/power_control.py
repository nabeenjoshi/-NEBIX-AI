"""Read and select supported Windows power plans without shell interpolation."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess


POWER_PLAN_GUIDS = {
    "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "battery_saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
}


def _powercfg() -> str:
    executable = shutil.which("powercfg")
    if not executable:
        raise RuntimeError("Windows power plan control is unavailable (powercfg was not found).")
    return executable


def _run_powercfg(*arguments: str) -> str:
    result = subprocess.run(
        [_powercfg(), *arguments],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(message or f"powercfg failed with exit code {result.returncode}.")
    return result.stdout


def available_performance_modes() -> list[str]:
    if platform.system() != "Windows":
        return []
    try:
        plans = _run_powercfg("/list").lower()
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return []
    return [
        mode
        for mode, guid in POWER_PLAN_GUIDS.items()
        if guid in plans
    ]


def active_performance_mode() -> str | None:
    if platform.system() != "Windows":
        return None
    try:
        active = _run_powercfg("/getactivescheme").lower()
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return None
    return next(
        (mode for mode, guid in POWER_PLAN_GUIDS.items() if guid in active),
        None,
    )


def set_performance_mode(mode: str) -> str:
    if platform.system() != "Windows":
        raise RuntimeError("Windows power plan control is unavailable on this platform.")
    if mode not in POWER_PLAN_GUIDS:
        raise ValueError("Unsupported performance mode.")
    if mode not in available_performance_modes():
        raise RuntimeError(f"The Windows {mode.replace('_', ' ')} power plan is not available.")
    _run_powercfg("/setactive", POWER_PLAN_GUIDS[mode])
    actual = active_performance_mode()
    if actual != mode:
        raise RuntimeError("Windows did not confirm the requested power plan.")
    return actual


def format_power_mode(mode: str | None) -> str:
    return {
        "balanced": "Balanced",
        "performance": "Performance",
        "battery_saver": "Battery Saver",
    }.get(mode, "Balanced")
