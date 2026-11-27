from __future__ import annotations

import os
import base64
import ctypes
import json
import shutil
import sys
import threading
from pathlib import Path

_DPAPI_PREFIX = "dpapi:v1:"
_CONFIG_LOCK = threading.RLock()


class APIConfigDecryptionError(RuntimeError):
    """A saved credential is DPAPI-protected for a different user context."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(
            f"Saved credential '{field}' cannot be decrypted by the current Windows user."
        )


def is_validation_mode() -> bool:
    return os.environ.get("NEBIX_VALIDATION_MODE") == "1"


def get_resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(
            getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)
        ).resolve()
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    if is_validation_mode():
        validation_root = os.environ.get("NEBIX_VALIDATION_DATA_DIR")
        if not validation_root:
            raise RuntimeError(
                "NEBIX_VALIDATION_DATA_DIR must point to an isolated directory "
                "when validation mode is enabled."
            )

        data_dir = Path(validation_root).expanduser().resolve() / "NEBIX"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    if not getattr(sys, "frozen", False):
        return get_resource_dir()

    if sys.platform == "win32":
        root = Path(
            os.environ.get(
                "LOCALAPPDATA",
                Path.home() / "AppData" / "Local",
            )
        )
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    data_dir = root / "NEBIX"
    data_dir.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_user_data(data_dir)
    return data_dir


def get_config_file(name: str = "api_keys.json") -> Path:
    path = get_data_dir() / "config" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_ui_settings_file() -> Path:
    path = get_data_dir() / "data" / "ui_settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_api_config(path: Path | None = None) -> dict:
    with _CONFIG_LOCK:
        config_path = path or get_config_file()
        if not config_path.exists():
            return {}

        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid API configuration format: {config_path}")

        migrate_plaintext = False
        for key, value in tuple(data.items()):
            if not str(key).lower().endswith("_api_key") or not isinstance(value, str):
                continue
            if value.startswith(_DPAPI_PREFIX):
                try:
                    data[key] = _unprotect_secret(value[len(_DPAPI_PREFIX):])
                except Exception as exc:
                    raise APIConfigDecryptionError(str(key)) from exc
            elif value and sys.platform == "win32":
                migrate_plaintext = True

        if migrate_plaintext:
            save_api_config(data, config_path)
        return data


def get_gemini_api_key() -> str:
    """Return the configured Gemini key, or an empty string when unset."""
    return str(load_api_config().get("gemini_api_key") or "")


def load_api_config_raw(path: Path | None = None) -> dict:
    """Read the config object without attempting to decrypt protected secrets.

    This is only for the validated Settings replacement flow, which must retain
    opaque credentials belonging to other providers while updating one field.
    """
    with _CONFIG_LOCK:
        config_path = path or get_config_file()
        if not config_path.exists():
            return {}
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Invalid API configuration format: {config_path}")
        return data


def backup_api_config(path: Path | None = None) -> Path:
    """Create a non-overwriting byte-for-byte backup before credential repair."""
    with _CONFIG_LOCK:
        config_path = path or get_config_file()
        if not config_path.is_file():
            raise FileNotFoundError("The existing API configuration file is missing.")
        source_bytes = config_path.read_bytes()
        base = config_path.with_name(f"{config_path.name}.dpapi-backup")
        backup_path = base
        suffix = 1
        while backup_path.exists():
            if backup_path.read_bytes() == source_bytes:
                return backup_path
            backup_path = base.with_name(f"{base.name}.{suffix}")
            suffix += 1
        shutil.copy2(config_path, backup_path)
        if backup_path.read_bytes() != source_bytes:
            raise OSError("The API configuration backup could not be verified.")
        return backup_path


def save_api_config(data: dict, path: Path | None = None) -> Path:
    if not isinstance(data, dict):
        raise TypeError("API configuration must be a dictionary.")

    with _CONFIG_LOCK:
        config_path = path or get_config_file()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        protected = dict(data)
        if sys.platform == "win32":
            for key, value in tuple(protected.items()):
                if (
                    str(key).lower().endswith("_api_key")
                    and isinstance(value, str)
                    and value
                    and not value.startswith(_DPAPI_PREFIX)
                ):
                    protected[key] = _DPAPI_PREFIX + _protect_secret(value)

        temp_path = config_path.with_name(
            f"{config_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(protected, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp_path.replace(config_path)
        finally:
            temp_path.unlink(missing_ok=True)
        return config_path


def get_memory_file(name: str = "long_term.json") -> Path:
    path = get_data_dir() / "memory" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(*parts: str) -> Path:
    return get_resource_dir().joinpath(*parts)


def _migrate_legacy_user_data(data_dir: Path) -> None:
    executable_dir = Path(sys.executable).resolve().parent
    candidate_bases = [
        executable_dir,
        get_resource_dir(),
    ]
    candidate_bases.extend(
        parent
        for parent in executable_dir.parents
        if (parent / "main.py").is_file() and (parent / "web_ui.py").is_file()
    )
    for folder, filename in (("config", "api_keys.json"), ("memory", "long_term.json")):
        destination = data_dir / folder / filename
        if destination.exists():
            continue

        for base in dict.fromkeys(candidate_bases):
            source = base / folder / filename
            if not source.is_file() or source.resolve() == destination.resolve():
                continue
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                break
            except OSError:
                continue


def _protect_secret(value: str) -> str:
    raw = value.encode("utf-8")
    result = _dpapi_transform(raw, protect=True)
    return base64.b64encode(result).decode("ascii")


def _unprotect_secret(value: str) -> str:
    encrypted = base64.b64decode(value, validate=True)
    return _dpapi_transform(encrypted, protect=False).decode("utf-8")


def _dpapi_transform(value: bytes, *, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Windows DPAPI data can only be accessed on Windows.")

    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
        ]

    buffer = ctypes.create_string_buffer(value)
    input_blob = DataBlob(
        len(value),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    output_blob = DataBlob()
    description = wintypes.LPWSTR()

    crypt32 = ctypes.WinDLL("Crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("Kernel32", use_last_error=True)
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    if protect:
        transform = crypt32.CryptProtectData
        transform.argtypes = [
            ctypes.POINTER(DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
        transform.restype = wintypes.BOOL
        succeeded = transform(
            ctypes.byref(input_blob),
            "NEBIX API key",
            None,
            None,
            None,
            0x1,
            ctypes.byref(output_blob),
        )
    else:
        transform = crypt32.CryptUnprotectData
        transform.argtypes = [
            ctypes.POINTER(DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(DataBlob),
        ]
        transform.restype = wintypes.BOOL
        succeeded = transform(
            ctypes.byref(input_blob),
            ctypes.byref(description),
            None,
            None,
            None,
            0x1,
            ctypes.byref(output_blob),
        )

    if not succeeded:
        error = ctypes.WinError(ctypes.get_last_error())
        if description:
            local_free(ctypes.cast(description, ctypes.c_void_p))
        raise error

    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        local_free(ctypes.cast(output_blob.pbData, ctypes.c_void_p))
        if description:
            local_free(ctypes.cast(description, ctypes.c_void_p))
