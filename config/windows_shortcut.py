# ============================================================
# NEBIX — Windows shortcut / autostart installer
# ============================================================

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.paths import resource_path


NEBIX_APP_ID = "NEBIX"
ICON_RELATIVE = Path("config") / "nebix.ico"
APPID_SCRIPT_RELATIVE = Path("config") / "set_lnk_appid.ps1"
PORTABLE_EXE_RELATIVE = Path("dist") / "NEBIX-Portable" / "NEBIX.exe"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_executable_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return (get_base_dir() / "dist" / "NEBIX-Portable" / "NEBIX.exe").resolve()


def icon_path(base_dir: Path | None = None) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return (base_dir or get_base_dir()) / ICON_RELATIVE


def _ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def set_shortcut_app_identity(
    shortcut_path: Path,
    app_id: str,
    relaunch_command: str,
    display_name: str,
    icon_resource: str,
) -> None:
    script = resource_path(*APPID_SCRIPT_RELATIVE.parts)
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-LnkPath",
            str(shortcut_path),
            "-AppId",
            app_id,
            "-RelaunchCommand",
            relaunch_command,
            "-DisplayName",
            display_name,
            "-IconResource",
            icon_resource,
        ],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            completed.stderr.strip()
            or completed.stdout.strip()
            or "Failed to set shortcut AppUserModelID."
        )


def shortcut_locations(include_startup: bool = True) -> list[Path]:
    desktop = Path.home() / "Desktop"
    start_menu = (
        Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
    )
    startup = start_menu / "Startup"

    paths = [
        desktop / "NEBIX.lnk",
        start_menu / "NEBIX.lnk",
    ]
    if include_startup:
        paths.append(startup / "NEBIX.lnk")
    return paths


def startup_shortcut_path() -> Path:
    return (
        Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / "NEBIX.lnk"
    )


def _create_lnk_shell(
    shortcut_path: Path,
    target: Path,
    arguments: str,
    working_directory: Path,
    icon_file: Path,
) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)

    script = (
        "$shell = New-Object -ComObject WScript.Shell;"
        f"$shortcut = $shell.CreateShortcut({_ps_quote(shortcut_path)});"
        f"$shortcut.TargetPath = {_ps_quote(target)};"
        f"$shortcut.Arguments = {_ps_quote(arguments)};"
        f"$shortcut.WorkingDirectory = {_ps_quote(working_directory)};"
        f"$shortcut.IconLocation = {_ps_quote(str(icon_file) + ',0')};"
        "$shortcut.WindowStyle = 7;"
        "$shortcut.Description = 'NEBIX';"
        "$shortcut.Save();"
    )

    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        check=True,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or "Shortcut creation failed.")


def install_nebix_shortcuts(autostart: bool | None = True) -> dict:
    base_dir = get_base_dir()
    if getattr(sys, "frozen", False):
        target = Path(sys.executable).resolve()
    else:
        target = get_executable_path()
        if not target.is_file():
            raise FileNotFoundError(
                "Build the standalone NEBIX application before creating "
                f"shortcuts. Expected executable: {target}"
            )
    if target.suffix.lower() != ".exe":
        raise RuntimeError(f"NEBIX shortcuts must target an executable: {target}")

    ico = icon_path(base_dir)
    if not ico.is_file():
        raise FileNotFoundError(f"NEBIX icon not found: {ico}")

    arguments = ""
    relaunch = f'"{target}"'
    include_startup = (
        autostart
        if autostart is not None
        else startup_shortcut_path().is_file()
    )

    created = []
    for shortcut_path in shortcut_locations(include_startup=include_startup):
        _create_lnk_shell(
            shortcut_path,
            target,
            arguments,
            target.parent,
            ico,
        )
        set_shortcut_app_identity(
            shortcut_path,
            NEBIX_APP_ID,
            relaunch,
            "NEBIX",
            f"{ico},0",
        )
        created.append(str(shortcut_path))

    if autostart is False:
        stale = startup_shortcut_path()
        if stale.is_file():
            stale.unlink()

    return {
        "ok": True,
        "created": True,
        "autostart": include_startup,
        "icon": str(ico),
        "launcher": None,
        "paths": created,
        "message": (
            "NEBIX shortcut installed with the custom icon, "
            "taskbar App ID, and "
            + (
                "boot autostart."
                if include_startup
                else "desktop/start-menu only."
            )
        ),
    }


def set_autostart(enabled: bool) -> dict:
    if enabled:
        return install_nebix_shortcuts(autostart=True)

    startup = startup_shortcut_path()
    if startup.is_file():
        startup.unlink()
    return {
        "ok": True,
        "created": True,
        "autostart": False,
        "message": "NEBIX boot autostart removed. Desktop and Start Menu shortcuts kept.",
    }


if __name__ == "__main__":
    result = install_nebix_shortcuts(autostart=True)
    print(result["message"])
    for path in result["paths"]:
        print(path)
