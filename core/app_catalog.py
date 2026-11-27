from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import time
import unicodedata
import base64
import ctypes
import io
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


_CACHE_TTL_SECONDS = 15 * 60
_SCAN_TIMEOUT_SECONDS = 30
_APP_ID_RE = re.compile(r"^[A-Za-z0-9._-]+![A-Za-z0-9._-]+$")
_ALIASES = {
    "chrome": {"chrome", "google chrome"},
    "edge": {"edge", "ms edge", "microsoft edge"},
    "vscode": {"vscode", "vs code", "visual studio code", "code"},
    "word": {"word", "microsoft word"},
    "excel": {"excel", "microsoft excel"},
    "powerpoint": {"powerpoint", "power point", "microsoft powerpoint"},
    "whatsapp": {"whatsapp", "whats app"},
    "telegram": {"telegram", "telegram desktop"},
    "discord": {"discord", "discord app"},
    "spotify": {"spotify", "spotify music"},
}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _dedup_name(value: str) -> str:
    normalized = _normalize(value)
    for canonical, aliases in _ALIASES.items():
        if normalized in {_normalize(alias) for alias in aliases}:
            return _normalize(canonical)
    return normalized


def _application_id(launch_type: str, launch_value: str, name: str) -> str:
    identity = f"{launch_type}\0{launch_value.casefold()}\0{_normalize(name)}"
    return hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:24]


def _shortcut_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in (os.environ.get("APPDATA"), os.environ.get("PROGRAMDATA")):
        if value:
            root = Path(value) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            if root.is_dir():
                roots.append(root)
    return tuple(roots)


def _scan_shortcuts(add) -> None:
    for root in _shortcut_roots():
        for directory, _, files in os.walk(root):
            for filename in files:
                path = Path(directory) / filename
                suffix = path.suffix.casefold()
                if suffix not in {".lnk", ".exe"}:
                    continue
                if suffix == ".exe" and not path.is_file():
                    continue
                add(path.stem, "shortcut" if suffix == ".lnk" else "exe", str(path), 1)


def _scan_start_apps(add) -> None:
    if os.name != "nt":
        return
    command = (
        "$OutputEncoding = [Console]::OutputEncoding = "
        "[System.Text.UTF8Encoding]::new(); "
        "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_SCAN_TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0 or not result.stdout.strip():
            return
        records = json.loads(result.stdout)
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            return
        for record in records:
            if not isinstance(record, dict):
                continue
            name = str(record.get("Name") or "").strip()
            app_id = str(record.get("AppID") or "").strip()
            if name and _APP_ID_RE.fullmatch(app_id):
                add(name, "app_id", app_id, 0)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return


def _scan_app_paths(add) -> None:
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return

    roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths"),
    )
    for hive, key_path in roots:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                count = winreg.QueryInfoKey(key)[0]
                for index in range(count):
                    try:
                        subkey_name = winreg.EnumKey(key, index)
                        with winreg.OpenKey(key, subkey_name) as entry:
                            executable, _ = winreg.QueryValueEx(entry, None)
                        executable = os.path.expandvars(str(executable).strip().strip('"'))
                        target = Path(executable)
                        if target.suffix.casefold() == ".exe" and target.is_file():
                            add(target.stem, "exe", str(target), 2)
                    except (OSError, ValueError):
                        continue
        except OSError:
            continue


def _display_icon_executable(value: str) -> Path | None:
    value = os.path.expandvars(str(value or "").strip())
    match = re.match(r'^\s*"([^\"]+\.exe)"', value, re.IGNORECASE)
    if not match:
        match = re.match(r"^\s*(.+?\.exe)(?:\s*,\s*-?\d+)?\s*$", value, re.IGNORECASE)
    if not match:
        return None
    path = Path(match.group(1).strip().strip('"'))
    return path if path.suffix.casefold() == ".exe" and path.is_file() else None


def _scan_registered_desktop_apps(add) -> None:
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return

    subkeys = (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey_path in subkeys:
            try:
                with winreg.OpenKey(hive, subkey_path) as root:
                    count = winreg.QueryInfoKey(root)[0]
                    for index in range(count):
                        try:
                            subkey_name = winreg.EnumKey(root, index)
                            with winreg.OpenKey(root, subkey_name) as entry:
                                name, _ = winreg.QueryValueEx(entry, "DisplayName")
                                try:
                                    icon, _ = winreg.QueryValueEx(entry, "DisplayIcon")
                                except OSError:
                                    continue
                            name = str(name or "").strip()
                            executable = _display_icon_executable(icon)
                            if name and executable:
                                add(name, "exe", str(executable), 3)
                        except (OSError, ValueError):
                            continue
            except OSError:
                continue


def _windows_icon_data(path: str) -> str:
    if os.name != "nt" or not Path(path).is_file():
        return ""
    try:
        import win32gui
        import win32ui
        from PIL import Image

        class _ShellFileInfo(ctypes.Structure):
            _fields_ = [
                ("hIcon", ctypes.c_void_p),
                ("iIcon", ctypes.c_int),
                ("dwAttributes", ctypes.c_ulong),
                ("szDisplayName", ctypes.c_wchar * 260),
                ("szTypeName", ctypes.c_wchar * 80),
            ]

        info = _ShellFileInfo()
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        handle = shell32.SHGetFileInfoW(
            str(path), 0, ctypes.byref(info), ctypes.sizeof(info), 0x100 | 0x1
        )
        if not handle or not info.hIcon:
            return ""
        color_bitmap = mask_bitmap = None
        screen_dc = memory_dc = bitmap_object = None
        previous_bitmap = None
        try:
            _, _, _, mask_bitmap, color_bitmap = win32gui.GetIconInfo(info.hIcon)
            if not color_bitmap:
                return ""
            bitmap = win32gui.GetObject(color_bitmap)
            width, height = int(bitmap.bmWidth), int(bitmap.bmHeight)
            screen_dc = win32gui.GetDC(0)
            source_dc = win32ui.CreateDCFromHandle(screen_dc)
            memory_dc = source_dc.CreateCompatibleDC()
            bitmap_object = win32ui.CreateBitmap()
            bitmap_object.CreateCompatibleBitmap(source_dc, width, height)
            previous_bitmap = memory_dc.SelectObject(bitmap_object)
            win32gui.DrawIconEx(memory_dc.GetSafeHdc(), 0, 0, info.hIcon, width, height, 0, None, 3)
            pixels = bitmap_object.GetBitmapBits(True)
            image = Image.frombuffer("RGBA", (width, height), pixels, "raw", "BGRA", 0, -1)
            image = image.convert("RGBA").resize((32, 32), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        finally:
            if memory_dc:
                if previous_bitmap:
                    memory_dc.SelectObject(previous_bitmap)
                memory_dc.DeleteDC()
            if screen_dc:
                win32gui.ReleaseDC(0, screen_dc)
            win32gui.DestroyIcon(info.hIcon)
            for bitmap_handle in (color_bitmap, mask_bitmap):
                if bitmap_handle:
                    win32gui.DeleteObject(bitmap_handle)
    except Exception:
        return ""


class WindowsApplicationCatalog:
    """Thread-safe, in-memory Windows app catalog with one background scan."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._applications: list[dict[str, str]] = []
        self._by_id: dict[str, dict[str, str]] = {}
        self._scan_started = False
        self._scanning = False
        self._last_scan = 0.0
        self._duplicates_removed = 0
        self._last_error = ""
        self._icon_cache: dict[str, str] = {}

    def start_scan(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            expired = time.monotonic() - self._last_scan >= _CACHE_TTL_SECONDS
            if self._scanning:
                return self._snapshot()
            if self._scan_started and not force and not expired:
                return self._snapshot()
            self._scan_started = True
            self._scanning = True
            thread = threading.Thread(
                target=self._scan_worker,
                name="NEBIX-AppDiscovery",
                daemon=True,
            )
            thread.start()
            return self._snapshot()

    def list_applications(self, force: bool = False) -> dict[str, Any]:
        return self.start_scan(force=force)

    def _wait_for_scan(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._scanning:
                    return
            time.sleep(0.05)

    def get_icons(self, app_ids: list[str]) -> dict[str, str]:
        if not isinstance(app_ids, list):
            return {}
        with self._lock:
            records = [dict(self._by_id[item]) for item in dict.fromkeys(app_ids[:64]) if item in self._by_id]
        icons: dict[str, str] = {}
        for item in records:
            app_id = item["id"]
            with self._lock:
                icon = self._icon_cache.get(app_id)
            if icon is None:
                target = item.get("launch_value", "")
                icon = _windows_icon_data(target) if item.get("launch_type") in {"exe", "shortcut"} else ""
                with self._lock:
                    self._icon_cache[app_id] = icon
                    if app_id in self._by_id:
                        self._by_id[app_id]["icon"] = icon
                    for public_item in self._applications:
                        if public_item["id"] == app_id:
                            public_item["icon"] = icon
                            break
            if icon:
                icons[app_id] = icon
        return icons

    def open_browser_url(self, url: str, preferred: str = "chrome") -> dict[str, Any]:
        parsed = urlsplit(str(url or ""))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return {"ok": False, "error": "Only safe HTTP or HTTPS browser URLs can be opened."}
        self.start_scan()
        self._wait_for_scan()
        with self._lock:
            apps = [dict(item) for item in self._by_id.values()]
            scanning = self._scanning
        if scanning and not apps:
            return {"ok": False, "error": "Application discovery is still running. Try again shortly."}

        browser_names = {
            "chrome": ({"chrome", "googlechrome"}, "Google Chrome"),
            "edge": ({"edge", "msedge", "microsoftedge"}, "Microsoft Edge"),
        }
        preferred_key = _normalize(preferred)
        chosen = browser_names.get(preferred_key, browser_names["chrome"])
        search_names = [chosen]
        if preferred_key == "chrome":
            search_names.append(browser_names["edge"])

        for aliases, display_name in search_names:
            candidates = [
                item for item in apps
                if _normalize(item.get("name", "")) in aliases
                and item.get("launch_type") in {"exe", "shortcut"}
            ]
            if not candidates:
                continue
            item = candidates[0]
            executable = Path(item.get("launch_value", ""))
            try:
                if item.get("launch_type") == "shortcut":
                    if executable.suffix.casefold() != ".lnk" or not executable.is_file():
                        continue
                    os.startfile(str(executable), arguments=str(url))
                else:
                    if executable.suffix.casefold() != ".exe" or not executable.is_file():
                        continue
                    subprocess.Popen(
                        [str(executable), str(url)],
                        cwd=str(executable.parent),
                        close_fds=True,
                        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                    )
                actual_name = item.get("name") or display_name
                method = "verified executable" if item.get("launch_type") == "exe" else "verified browser shortcut"
                return {"ok": True, "name": actual_name, "url": url, "method": method}
            except (OSError, ValueError, subprocess.SubprocessError):
                continue

        if os.name == "nt" and hasattr(os, "startfile"):
            try:
                os.startfile(str(url))
                return {"ok": True, "name": "Windows default browser", "url": url, "method": "registered URL handler"}
            except OSError as exc:
                return {"ok": False, "error": f"No installed browser could open this search: {exc}"}
        return {"ok": False, "error": "No installed browser has a supported launch target."}

    def _snapshot(self) -> dict[str, Any]:
        return {
            "ok": True,
            "scanning": self._scanning,
            "applications": [dict(item) for item in self._applications],
            "count": len(self._applications),
            "duplicates_removed": self._duplicates_removed,
            "refreshed_at": self._last_scan,
            "error": self._last_error,
        }

    def _scan_worker(self) -> None:
        candidates: dict[str, tuple[int, dict[str, str]]] = {}
        duplicates = 0

        def add(name: str, launch_type: str, launch_value: str, priority: int) -> None:
            nonlocal duplicates
            name = str(name or "").strip()
            if not name or len(name) > 160:
                return
            if launch_type in {"shortcut", "exe"} and not Path(launch_value).is_file():
                return
            app_id = _application_id(launch_type, launch_value, name)
            normalized_name = _dedup_name(name)
            if not normalized_name:
                return
            record = {
                "id": app_id,
                "name": name,
                "launch_type": launch_type,
                "icon": "",
                "launch_value": launch_value,
            }
            previous = candidates.get(normalized_name)
            if previous:
                duplicates += 1
                if priority >= previous[0]:
                    return
            candidates[normalized_name] = (priority, record)

        error = ""
        try:
            if os.name != "nt":
                error = "Installed application discovery is supported on Windows only."
            else:
                _scan_shortcuts(add)
                _scan_start_apps(add)
                _scan_app_paths(add)
                _scan_registered_desktop_apps(add)
        except Exception as exc:
            error = f"Application discovery failed: {type(exc).__name__}."

        applications = sorted(
            (item for _, item in candidates.values()),
            key=lambda item: item["name"].casefold(),
        )
        by_id = {
            item["id"]: item
            for _, item in candidates.values()
        }
        public_applications = [
            {key: item[key] for key in ("id", "name", "launch_type", "icon")}
            for item in applications
        ]
        # The public listing omits executable paths; launch accepts opaque IDs.
        with self._lock:
            self._applications = public_applications
            self._by_id = by_id
            self._duplicates_removed = duplicates
            self._last_scan = time.monotonic()
            self._last_error = error
            self._scanning = False

    def launch(self, app_id: str) -> dict[str, Any]:
        with self._lock:
            item = dict(self._by_id.get(str(app_id or ""), {}))
        if not item:
            return {"ok": False, "error": "This application is no longer available. Refresh Quick Access and try again."}

        launch_type = item.get("launch_type")
        launch_value = item.get("launch_value", "")
        name = item.get("name", "Application")
        try:
            if launch_type == "app_id":
                if os.name != "nt" or not _APP_ID_RE.fullmatch(launch_value):
                    return {"ok": False, "error": "The Windows application identifier is invalid."}
                subprocess.Popen(
                    ["explorer.exe", f"shell:AppsFolder\\{launch_value}"],
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                method = "Windows app identifier"
            elif launch_type == "shortcut":
                path = Path(launch_value)
                if path.suffix.casefold() != ".lnk" or not path.is_file():
                    return {"ok": False, "error": "The application shortcut is no longer available."}
                if os.name != "nt" or not hasattr(os, "startfile"):
                    return {"ok": False, "error": "Windows shortcut launching is unavailable."}
                os.startfile(str(path))
                method = "Start Menu shortcut"
            elif launch_type == "exe":
                path = Path(launch_value)
                if path.suffix.casefold() != ".exe" or not path.is_file():
                    return {"ok": False, "error": "The application executable is no longer available."}
                subprocess.Popen(
                    [str(path)],
                    cwd=str(path.parent),
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                )
                method = "verified executable"
            else:
                return {"ok": False, "error": "This application has no supported launch method."}
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            return {"ok": False, "error": f"Could not launch {name}: {exc}"}

        return {"ok": True, "id": app_id, "name": name, "method": method}

    def resolve_name(self, requested_name: str) -> dict[str, Any]:
        requested = _normalize(requested_name)
        if not requested:
            return {"ok": False, "error": "Enter an application name."}

        snapshot = self.start_scan()
        self._wait_for_scan()
        with self._lock:
            apps = [dict(item) for item in self._applications]
            scanning = self._scanning
        if scanning and not apps:
            return {"ok": False, "error": "Application discovery is still running. Please try again in a moment."}

        aliases = {requested}
        for alias_group in _ALIASES.values():
            normalized_aliases = {_normalize(alias) for alias in alias_group}
            if requested in normalized_aliases:
                aliases.update(normalized_aliases)

        exact_name = [item for item in apps if _normalize(item["name"]) == requested]
        exact = exact_name or [item for item in apps if _normalize(item["name"]) in aliases]
        if not exact:
            exact = [item for item in apps if requested in _normalize(item["name"])]

        if not exact:
            return {"ok": False, "error": f"{requested_name} is not in the installed application list."}
        if len(exact) > 1:
            return {
                "ok": False,
                "ambiguous": True,
                "matches": [{"id": item["id"], "name": item["name"]} for item in exact[:8]],
                "error": "More than one installed application matches. Ask which one the user means.",
            }
        return self.launch(exact[0]["id"])


APPLICATION_CATALOG = WindowsApplicationCatalog()
