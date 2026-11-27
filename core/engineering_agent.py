from __future__ import annotations

import ast
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import queue
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


class TaskState(str, Enum):
    IDLE = "IDLE"
    PLANNED = "PLANNED"
    WAITING_FOR_CONFIRMATION = "WAITING_FOR_CONFIRMATION"
    SCANNING = "SCANNING"
    EXECUTING = "EXECUTING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    DOWNLOADING = "DOWNLOADING"
    INSTALLING = "INSTALLING"
    CONFIGURING = "CONFIGURING"
    TESTING = "TESTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    IDENTIFYING_PROJECT_TYPE = "IDENTIFYING_PROJECT_TYPE"


class TaskCancelled(Exception):
    pass


class PermissionDenied(RuntimeError):
    pass


_TERMINAL_STATES = {
    TaskState.COMPLETED,
    TaskState.FAILED,
    TaskState.BLOCKED,
    TaskState.CANCELLED,
}
_TRANSITIONS = {
    TaskState.IDLE: {TaskState.PLANNED, TaskState.WAITING_FOR_USER},
    TaskState.PLANNED: {
        TaskState.SCANNING,
        TaskState.EXECUTING,
        TaskState.WAITING_FOR_CONFIRMATION,
        TaskState.WAITING_FOR_USER,
        TaskState.BLOCKED,
        TaskState.CANCELLED,
    },
    TaskState.WAITING_FOR_CONFIRMATION: {
        TaskState.EXECUTING,
        TaskState.DOWNLOADING,
        TaskState.CONFIGURING,
        TaskState.WAITING_FOR_USER,
        TaskState.CANCELLED,
        TaskState.BLOCKED,
    },
    TaskState.SCANNING: {
        TaskState.IDENTIFYING_PROJECT_TYPE,
        TaskState.VERIFYING,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.IDENTIFYING_PROJECT_TYPE: {
        TaskState.PLANNED,
        TaskState.EXECUTING,
        TaskState.WAITING_FOR_CONFIRMATION,
        TaskState.TESTING,
        TaskState.VERIFYING,
        TaskState.BLOCKED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    },
    TaskState.EXECUTING: {
        TaskState.WAITING_FOR_CONFIRMATION,
        TaskState.DOWNLOADING,
        TaskState.INSTALLING,
        TaskState.CONFIGURING,
        TaskState.TESTING,
        TaskState.VERIFYING,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.BLOCKED,
        TaskState.CANCELLED,
    },
    TaskState.DOWNLOADING: {
        TaskState.INSTALLING,
        TaskState.CONFIGURING,
        TaskState.DOWNLOADING,
        TaskState.VERIFYING,
        TaskState.WAITING_FOR_USER,
        TaskState.FAILED,
        TaskState.BLOCKED,
        TaskState.CANCELLED,
    },
    TaskState.INSTALLING: {
        TaskState.DOWNLOADING,
        TaskState.CONFIGURING,
        TaskState.VERIFYING,
        TaskState.WAITING_FOR_USER,
        TaskState.FAILED,
        TaskState.BLOCKED,
        TaskState.CANCELLED,
    },
    TaskState.CONFIGURING: {
        TaskState.DOWNLOADING,
        TaskState.TESTING,
        TaskState.VERIFYING,
        TaskState.FAILED,
        TaskState.BLOCKED,
        TaskState.CANCELLED,
    },
    TaskState.TESTING: {
        TaskState.EXECUTING,
        TaskState.VERIFYING,
        TaskState.FAILED,
        TaskState.BLOCKED,
        TaskState.CANCELLED,
    },
    TaskState.VERIFYING: {
        TaskState.PLANNED,
        TaskState.WAITING_FOR_CONFIRMATION,
        TaskState.DOWNLOADING,
        TaskState.TESTING,
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.BLOCKED,
        TaskState.CANCELLED,
    },
    TaskState.WAITING_FOR_USER: {
        TaskState.PLANNED,
        TaskState.INSTALLING,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.BLOCKED,
    },
}

_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "target",
    "vendor",
    "packages",
}
_MAX_FILES = 6000
_MAX_DEPTH = 16
_MAX_SOURCE_BYTES = 512 * 1024
_MAX_SYNTAX_FILES = 300
_MAX_SYNTAX_BYTES = 16 * 1024 * 1024
_MAX_DIAGNOSTICS = 40
_MAX_COMMAND_OUTPUT = 10_000

_PROJECT_MARKERS = {
    "android": {
        "AndroidManifest.xml",
        "settings.gradle",
        "settings.gradle.kts",
        "gradlew",
        "gradlew.bat",
    },
    "python": {
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "Pipfile",
        "pytest.ini",
    },
    "node": {"package.json"},
    "rust": {"Cargo.toml"},
    "go": {"go.mod"},
    "dotnet": {".sln", ".csproj", ".fsproj"},
    "java": {"pom.xml", "build.gradle", "build.gradle.kts"},
    "cpp": {"CMakeLists.txt", "Makefile", ".vcxproj"},
}
_SOURCE_SUFFIXES = {
    ".py", ".pyi", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".html", ".htm", ".css",
    ".java", ".kt", ".kts", ".c", ".cc", ".cpp", ".h", ".hpp",
    ".cs", ".fs", ".go", ".rs", ".rb", ".php", ".swift",
}
_MANIFESTS = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "Pipfile",
    "Pipfile.lock",
    "setup.py",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradle.properties",
    "gradle-wrapper.properties",
    "AndroidManifest.xml",
    "CMakeLists.txt",
    "Makefile",
    "global.json",
    "Directory.Build.props",
}
_TEST_DIR_NAMES = {"test", "tests", "__tests__", "spec", "specs"}
_SOFTWARE_TARGETS = (
    {
        "name": "Android Studio",
        "patterns": ("android studio", "android-studio"),
        "package_id": "Google.AndroidStudio",
        "publisher": ("google",),
        "executables": (
            Path(r"C:\Program Files\Android\Android Studio\bin\studio64.exe"),
            Path.home() / "AppData" / "Local" / "Programs" / "Android Studio" / "bin" / "studio64.exe",
        ),
    },
    {
        "name": "Visual Studio Code",
        "patterns": ("visual studio code", "vs code", "vscode"),
        "package_id": "Microsoft.VisualStudioCode",
        "publisher": ("microsoft",),
        "executables": (
            Path(r"C:\Program Files\Microsoft VS Code\Code.exe"),
            Path(r"C:\Program Files (x86)\Microsoft VS Code\Code.exe"),
            Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "Code.exe",
        ),
    },
    {
        "name": "Git for Windows",
        "patterns": ("git for windows", "git"),
        "package_id": "Git.Git",
        "publisher": ("the git development community", "git"),
        "executables": (
            Path(r"C:\Program Files\Git\cmd\git.exe"),
            Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
        ),
    },
    {
        "name": "Node.js LTS",
        "patterns": ("node.js", "nodejs", "node js"),
        "package_id": "OpenJS.NodeJS.LTS",
        "publisher": ("openjs foundation",),
        "executables": (),
    },
    {
        "name": "Python 3.14",
        "patterns": ("python 3.14", "python"),
        "package_id": "Python.Python.3.14",
        "publisher": ("python software foundation",),
        "executables": (),
    },
    {
        "name": "Microsoft Excel",
        "patterns": ("microsoft excel", "excel"),
        "package_id": None,
        "publisher": ("microsoft",),
        "executables": (),
    },
)
_PATH_RE = re.compile(r"(?i)([a-z]:\\[^\"<>|?*\r\n]+|\\\\[^\"<>|?*\r\n]+)")
_QUOTED_PATH_RE = re.compile(r"""["']([^"']{2,})["']""")
_TRAILING_ACTION_WORDS = (
    " scan project",
    " inspect project",
    " check project",
    " open in",
    " मा खोल",
    " खोल",
    " scan गर",
    " हेरेर",
)


@dataclass
class EngineeringTask:
    task_id: str
    request: str
    intent: str
    state: TaskState
    created_at: float
    updated_at: float
    project_path: str | None = None
    current_file: str | None = None
    plan: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    result: str = ""
    error: str = ""


def classify_permission(operation: str) -> str:
    """Return the minimum policy tier for a requested operation."""
    value = str(operation or "").casefold()
    if any(token in value for token in ("delete", "uninstall", "registry", "credential", "shutdown", "restart")):
        return "high"
    if any(token in value for token in ("edit", "write", "install", "download", "system setting", "extension")):
        return "medium"
    return "low"


def _normalize(text: str) -> str:
    return " ".join(str(text or "").casefold().split())


def _extract_path(text: str) -> str | None:
    quoted = _QUOTED_PATH_RE.search(text)
    if quoted:
        candidate = quoted.group(1).strip()
        if re.match(r"(?i)^(?:[a-z]:\\|\\\\)", candidate):
            return candidate.rstrip(" .,:;")

    match = _PATH_RE.search(text)
    if not match:
        return None
    candidate = match.group(1).strip()
    lowered = candidate.casefold()
    for phrase in _TRAILING_ACTION_WORDS:
        offset = lowered.find(phrase)
        if offset >= 0:
            candidate = candidate[:offset].rstrip()
            lowered = candidate.casefold()
    return candidate.rstrip(" .,:;")


def _classify_request(text: str) -> str | None:
    normalized = _normalize(text)
    fix_markers = (
        "fix", "debug", "not working", "doesn't work", "does not work",
        "broken", "error fix", "fix error", "मिलाइदेऊ", "मिलाइदेउ",
        "ठीक गर", "काम गरिरहेको छैन", "login error",
        "find the error in the project", "has an error",
        "काम नगरेको", "काम गर्दैन", "ठीक पार", "समस्या हल", "गर्देन",
    )
    if any(marker in normalized for marker in fix_markers):
        return "diagnose"
    wants_open = (
        any(marker in normalized for marker in ("open project", "open this project"))
        or "खोल" in normalized
    )
    if wants_open and any(marker in normalized for marker in ("android studio", "android-studio")):
        return "open_android_studio"
    if wants_open and any(marker in normalized for marker in ("vs code", "vscode", "visual studio code")):
        return "open_vscode"
    if _requested_software(text) and any(marker in normalized for marker in (
        "is installed", "already installed", "installed?", "is excel", "check if",
        "detect installed", "installed छ",
    )):
        return "software_status"

    provisioning_terms = ("install", "download", "set up", "setup", "install गर", "डाउनलोड")
    install_target_terms = (
        "project", "dependency", "dependencies", "package", "extension",
        "android studio", "vscode", "vs code", "visual studio code",
        "software", "sdk", "jdk", "gradle", "excel", "microsoft excel",
        "node.js", "python", "git",
    )
    if (
        any(term in normalized for term in provisioning_terms)
        and any(term in normalized for term in install_target_terms)
    ):
        return "provision"

    scan_markers = (
        "scan project", "inspect project", "check project",
        "analyze project", "analyse project", "project scan",
        "check the whole project", "scan everything",
        "scan this project", "scan the project", "what does this project need",
        "scan dependencies", "missing extension", "missing extensions",
        "which extension is missing", "कहाँ error छ", "पहिला सबै scan",
        "यो project scan", "project हेरेर", "project लाई चाहिने",
        "scan गर", "जाँच गर",
    )
    if any(marker in normalized for marker in scan_markers):
        return "scan"
    if any(marker in normalized for marker in (
        "android studio", "android-studio", "vs code", "vscode", "visual studio code",
        "excel", "microsoft excel",
    )) and any(marker in normalized for marker in ("open", "launch", "start", "खोल", "चलाऊ")):
        return "open_application"
    return None


def _project_types(files: list[Path]) -> list[str]:
    names = {path.name for path in files}
    found = []
    for project_type, markers in _PROJECT_MARKERS.items():
        if any(
            name in names
            or (name.startswith(".") and any(p.name.endswith(name) for p in files))
            for name in markers
        ):
            found.append(project_type)
    if "android" in found and "java" in found:
        found.remove("java")
    return found or ["unknown"]


def scan_project(
    project_path: str | Path,
    *,
    event: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
    authorize_command: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Inventory a project and run bounded, non-executing source diagnostics."""
    root = Path(project_path).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Project path is not a directory: {root}")

    def log(message: str) -> None:
        if event:
            event(message)

    def check_cancelled() -> None:
        if cancel_event and cancel_event.is_set():
            raise TaskCancelled("Project scan cancelled by the user.")

    log(f"SCANNING PROJECT {root}")
    files: list[Path] = []
    scan_errors: list[str] = []
    truncated = False

    def on_walk_error(error: OSError) -> None:
        scan_errors.append(f"{error.filename or root}: {error.strerror or error}")

    for current, dir_names, file_names in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=on_walk_error,
    ):
        check_cancelled()
        current_path = Path(current)
        depth = len(current_path.relative_to(root).parts)
        dir_names[:] = sorted(
            name for name in dir_names
            if name.casefold() not in _EXCLUDED_DIRS
            and not (current_path / name).is_symlink()
        )
        if depth >= _MAX_DEPTH:
            dir_names.clear()
        for name in sorted(file_names):
            check_cancelled()
            path = current_path / name
            if path.is_symlink():
                continue
            files.append(path)
            if len(files) >= _MAX_FILES:
                truncated = True
                dir_names.clear()
                break
        if truncated:
            break

    relative_files = [path.relative_to(root) for path in files]
    log("IDENTIFYING PROJECT TYPE")
    project_types = _project_types(relative_files)
    manifests = sorted(
        path.as_posix() for path in relative_files
        if path.name in _MANIFESTS
        or path.name in {"package.json", "extensions.json"}
        and ".vscode" in path.parts
    )
    test_files = sorted(
        path.as_posix() for path in relative_files
        if any(part.casefold() in _TEST_DIR_NAMES for part in path.parts)
        or path.name.casefold().startswith(("test_", "spec_"))
        or ".test." in path.name.casefold()
        or ".spec." in path.name.casefold()
    )
    entrypoints = sorted(
        path.as_posix() for path in relative_files
        if path.name.casefold() in {
            "main.py", "app.py", "manage.py", "main.js", "index.js",
            "index.ts", "main.ts", "main.kt", "main.java", "program.cs",
            "main.go", "main.rs",
        }
    )
    source_files = [
        path for path in files if path.suffix.casefold() in _SOURCE_SUFFIXES
    ]
    runtime_commands = (
        "python", "node", "npm", "tsc", "java", "gradle", "mvn",
        "dotnet", "cargo", "go", "code", "winget",
    )
    available_tools = {
        name: shutil.which(name)
        for name in runtime_commands
        if shutil.which(name)
    }

    diagnostics: list[dict[str, Any]] = []
    log("RUNNING NON-EXECUTING SOURCE CHECKS")
    checked_files = set(source_files)
    checked_files.update(
        path for path in files
        if path.suffix.casefold() == ".json"
        and (
            path.name.casefold() in {"package.json", "extensions.json"}
            or path.name.casefold().endswith(".json")
        )
    )
    ordered_check_files = sorted(
        checked_files,
        key=lambda path: (
            0 if path.name.casefold() in {"package.json", "extensions.json"} else 1,
            path.as_posix().casefold(),
        ),
    )
    checks_truncated = False
    checks_run = 0
    bytes_checked = 0
    for index, path in enumerate(ordered_check_files):
        check_cancelled()
        if len(diagnostics) >= _MAX_DIAGNOSTICS:
            checks_truncated = index < len(ordered_check_files) - 1
            break
        try:
            size = path.stat().st_size
            if size > _MAX_SOURCE_BYTES:
                checks_truncated = True
                continue
            if checks_run >= _MAX_SYNTAX_FILES or bytes_checked + size > _MAX_SYNTAX_BYTES:
                checks_truncated = True
                continue
            contents = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            scan_errors.append(f"{path.relative_to(root)}: {exc}")
            continue
        checks_run += 1
        bytes_checked += size
        if path.suffix.casefold() == ".py":
            try:
                ast.parse(contents, filename=str(path))
            except SyntaxError as exc:
                diagnostics.append({
                    "file": path.relative_to(root).as_posix(),
                    "line": exc.lineno,
                    "column": exc.offset,
                    "message": exc.msg,
                    "kind": "python_syntax",
                })
        if path.suffix.casefold() == ".json":
            try:
                json.loads(contents)
            except json.JSONDecodeError as exc:
                diagnostics.append({
                    "file": path.relative_to(root).as_posix(),
                    "line": exc.lineno,
                    "column": exc.colno,
                    "message": exc.msg,
                    "kind": "json_syntax",
                })
        elif (
            path.suffix.casefold() in {".js", ".mjs", ".cjs"}
            and available_tools.get("node")
        ):
            try:
                if authorize_command and not authorize_command(
                    f"Check JavaScript syntax in {path.relative_to(root)}"
                ):
                    raise PermissionDenied("Permission denied for command execution.")
                result = subprocess.run(
                    [available_tools["node"], "--check", str(path)],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                scan_errors.append(f"{path.relative_to(root)}: Node syntax check timed out.")
            except OSError as exc:
                scan_errors.append(f"{path.relative_to(root)}: Node syntax check failed: {exc}")
            else:
                if result.returncode:
                    diagnostics.append({
                        "file": path.relative_to(root).as_posix(),
                        "line": None,
                        "column": None,
                        "message": (result.stderr or result.stdout).strip()[:1000],
                        "kind": "javascript_syntax",
                    })

    recommendations: list[str] = []
    extension_file = root / ".vscode" / "extensions.json"
    if extension_file.is_file():
        try:
            extension_data = json.loads(extension_file.read_text(encoding="utf-8"))
            raw = extension_data.get("recommendations", []) if isinstance(extension_data, dict) else None
            if not isinstance(raw, list):
                scan_errors.append(".vscode/extensions.json: recommendations must be an array.")
            else:
                for item in raw:
                    if not isinstance(item, str) or not re.fullmatch(
                        r"[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+",
                        item,
                    ):
                        scan_errors.append(
                            f".vscode/extensions.json: invalid extension recommendation {item!r}."
                        )
                        continue
                    recommendations.append(item)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            scan_errors.append(f".vscode/extensions.json: {exc}")

    installed_extensions: list[str] | None = None
    missing_extensions: list[str] | None = None
    if recommendations:
        code_cli = available_tools.get("code")
        if code_cli:
            try:
                installed_extensions = sorted(
                    EngineeringAgent._vscode_extension_versions(
                        code_cli,
                        authorize_command=authorize_command,
                    )
                )
                installed_set = set(installed_extensions)
                missing_extensions = [
                    recommendation for recommendation in recommendations
                    if recommendation.casefold() not in installed_set
                ]
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                scan_errors.append(f"Could not inspect installed VS Code extensions: {exc}")
        else:
            scan_errors.append(
                "Project declares VS Code extensions, but the `code` command is unavailable for status verification."
            )

    log("VERIFYING PROJECT INVENTORY")
    check_cancelled()
    scan = {
        "path": str(root),
        "project_types": project_types,
        "file_count": len(files),
        "source_file_count": len(source_files),
        "syntax_checks": checks_run,
        "syntax_checks_truncated": checks_truncated,
        "manifests": manifests,
        "entrypoints": entrypoints,
        "test_files": test_files,
        "vscode_extension_recommendations": recommendations,
        "vscode_extension_installed": installed_extensions,
        "vscode_extension_missing": missing_extensions,
        "available_tools": available_tools,
        "diagnostics": diagnostics,
        "scan_errors": scan_errors[:_MAX_DIAGNOSTICS],
        "truncated": truncated,
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "files": [path.as_posix() for path in relative_files],
        "source_files": [path.relative_to(root).as_posix() for path in source_files],
        "configuration_files": [
            path.as_posix() for path in relative_files
            if path.name.casefold() in {
                "tsconfig.json", "jsconfig.json", ".gitignore", ".editorconfig",
                "androidmanifest.xml", "gradle.properties", "gradle-wrapper.properties",
                "settings.gradle", "settings.gradle.kts", "vite.config.js",
                "vite.config.ts", "webpack.config.js", "webpack.config.ts",
                "eslint.config.js", ".eslintrc", ".eslintrc.json",
            }
        ],
        "documentation_files": [
            path.as_posix() for path in relative_files
            if path.name.casefold() in {"readme", "readme.md", "readme.rst", "contributing.md"}
            or path.suffix.casefold() in {".md", ".rst"}
        ],
        "scanned_at": time.time(),
    }
    scan["missing_references"] = _missing_local_references(root, relative_files)
    scan["commands"] = _project_commands(root, scan)
    return scan


def _missing_local_references(root: Path, files: list[Path]) -> list[dict[str, str]]:
    known = {path.as_posix() for path in files}
    diagnostics: list[dict[str, str]] = []
    py_modules = {
        path.with_suffix("").as_posix().replace("/", ".")
        for path in files
        if path.suffix.casefold() == ".py"
    }

    def add(source: Path, target: str) -> None:
        diagnostics.append({
            "file": source.as_posix(),
            "reference": target[:240],
            "message": f"Local reference was not found: {target}",
        })

    js_extensions = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json")
    import_pattern = re.compile(
        r"""(?:\bfrom\s*|\bimport\s*\(|\bimport\s*)["']([^"']+)["']"""
    )
    asset_pattern = re.compile(
        r"""\b(?:src|href)\s*=\s*["']([^"']+)["']|url\(\s*["']?([^"')]+)"""
    )
    for relative in files:
        suffix = relative.suffix.casefold()
        if suffix not in {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".html", ".htm", ".css"}:
            continue
        try:
            text = (root / relative).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        if suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        base = list(relative.parent.parts)
                        remove = max(0, node.level - 1)
                        if remove:
                            base = base[:-remove]
                        module = ".".join((*base, *(node.module or "").split("."))).strip(".")
                        modules = [module]
                    else:
                        modules = [node.module or ""]
                else:
                    continue
                for module in modules:
                    if not module or module in sys.stdlib_module_names or module.split(".")[0] in sys.stdlib_module_names:
                        continue
                    possible = module.replace(".", "/")
                    matches = (
                        f"{possible}.py" in known
                        or f"{possible}/__init__.py" in known
                        or f"{possible}.pyi" in known
                    )
                    if ("/" in possible or module in py_modules) and not matches:
                        add(relative, module)
        elif suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
            for specifier in import_pattern.findall(text):
                if not specifier.startswith("."):
                    continue
                target = (relative.parent / specifier).as_posix()
                if not any(
                    f"{target}{extension}" in known
                    for extension in js_extensions
                ) and not any(
                    f"{target}/index{extension}" in known
                    for extension in js_extensions
                ) and target not in known:
                    add(relative, specifier)
        elif suffix in {".html", ".htm", ".css"}:
            for match in asset_pattern.finditer(text):
                raw = (match.group(1) or match.group(2) or "").strip()
                if not raw or raw.startswith(("#", "/", "//", "data:", "http:", "https:", "mailto:")):
                    continue
                target = (relative.parent / raw.split("?", 1)[0].split("#", 1)[0]).as_posix()
                if target not in known and not (root / target).exists():
                    add(relative, raw)
    for relative in files:
        if relative.name not in {"settings.gradle", "settings.gradle.kts"}:
            continue
        try:
            contents = (root / relative).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            continue
        for module in re.findall(r"""include\s*\(?\s*["'](:[^"']+)["']""", contents):
            module_path = module.lstrip(":").replace(":", "/")
            if not (root / module_path).is_dir():
                add(relative, module)
    return diagnostics[:_MAX_DIAGNOSTICS]


def _project_commands(root: Path, scan: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    commands: dict[str, list[dict[str, Any]]] = {"test": [], "build": []}
    file_names = set(scan["files"])
    types = set(scan["project_types"])

    if "python" in types and scan["test_files"]:
        if importlib.util.find_spec("pytest") is not None:
            commands["test"].append({
                "label": "Python pytest suite",
                "argv": [sys.executable, "-m", "pytest", "-q"],
            })
        elif any(Path(name).name.startswith("test_") for name in scan["test_files"]):
            test_dirs = sorted({
                part for name in scan["test_files"]
                for part in Path(name).parts[:-1]
                if part.casefold() in _TEST_DIR_NAMES
            })
            commands["test"].append({
                "label": "Python unittest suite",
                "argv": [sys.executable, "-m", "unittest", "discover", "-s", test_dirs[0] if test_dirs else "."],
            })
    if "python" in types and (root / "pyproject.toml").is_file() and importlib.util.find_spec("build") is not None:
        commands["build"].append({
            "label": "Python wheel build",
            "argv": [sys.executable, "-m", "build", "--wheel"],
        })
    if "node" in types:
        try:
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            package = {}
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if isinstance(scripts, dict) and npm and (root / "node_modules").is_dir():
            if isinstance(scripts.get("test"), str):
                commands["test"].append({
                    "label": "package.json test script",
                    "argv": [npm, "test", "--"],
                })
            if isinstance(scripts.get("build"), str):
                commands["build"].append({
                    "label": "package.json build script",
                    "argv": [npm, "run", "build"],
                })
    if "android" in types or "java" in types:
        wrapper = next(
            (
                candidate for candidate in ("gradlew.bat", "gradlew", "mvnw.cmd", "mvnw")
                if candidate in file_names
            ),
            None,
        )
        if wrapper:
            executable = str(root / wrapper)
            if wrapper.startswith("gradlew"):
                test_task = "testDebugUnitTest" if "android" in types else "test"
                build_task = "assembleDebug" if "android" in types else "build"
                commands["test"].append({
                    "label": f"Gradle {test_task}",
                    "argv": [executable, test_task, "--no-daemon"],
                })
                commands["build"].append({
                    "label": f"Gradle {build_task}",
                    "argv": [executable, build_task, "--no-daemon"],
                })
            else:
                commands["test"].append({
                    "label": "Maven wrapper tests",
                    "argv": [executable, "test"],
                })
                commands["build"].append({
                    "label": "Maven wrapper package",
                    "argv": [executable, "package", "-DskipTests"],
                })
    if "dotnet" in types and shutil.which("dotnet"):
        dotnet = shutil.which("dotnet")
        commands["test"].append({"label": ".NET tests", "argv": [dotnet, "test", "--nologo"]})
        commands["build"].append({"label": ".NET build", "argv": [dotnet, "build", "--nologo"]})
    if "rust" in types and shutil.which("cargo"):
        commands["test"].append({"label": "Cargo tests", "argv": ["cargo", "test"]})
        commands["build"].append({"label": "Cargo build", "argv": ["cargo", "build"]})
    if "go" in types and shutil.which("go"):
        commands["test"].append({"label": "Go tests", "argv": ["go", "test", "./..."]})
        commands["build"].append({"label": "Go build", "argv": ["go", "build", "./..."]})
    return commands


def _project_install_commands(root: Path, scan: dict[str, Any]) -> list[dict[str, Any]]:
    names = set(scan["files"])
    types = set(scan["project_types"])
    commands: list[dict[str, Any]] = []

    if "python" in types:
        requirements = root / "requirements.txt"
        pyproject = root / "pyproject.toml"
        if requirements.is_file():
            local_python = next(
                (
                    candidate for candidate in (
                        root / ".venv" / "Scripts" / "python.exe",
                        root / "venv" / "Scripts" / "python.exe",
                    )
                    if candidate.is_file()
                ),
                None,
            )
            if local_python is None:
                local_python = root / ".venv" / "Scripts" / "python.exe"
                commands.append({
                    "label": "Create isolated project virtual environment",
                    "phase": "configure",
                    "argv": [sys.executable, "-m", "venv", str(root / ".venv")],
                })
            commands.extend((
                {
                    "label": "Install declared Python requirements",
                    "phase": "install",
                    "argv": [str(local_python), "-m", "pip", "install", "-r", str(requirements)],
                },
                {
                    "label": "Verify Python dependency consistency",
                    "phase": "verify",
                    "argv": [str(local_python), "-m", "pip", "check"],
                },
            ))
        elif pyproject.is_file():
            try:
                import tomllib

                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (ImportError, OSError, UnicodeError, tomllib.TOMLDecodeError):
                data = {}
            dependencies = data.get("project", {}).get("dependencies", []) if isinstance(data, dict) else []
            if isinstance(dependencies, list) and dependencies:
                local_python = next(
                    (
                        candidate for candidate in (
                            root / ".venv" / "Scripts" / "python.exe",
                            root / "venv" / "Scripts" / "python.exe",
                        )
                        if candidate.is_file()
                    ),
                    None,
                )
                if local_python is None:
                    local_python = root / ".venv" / "Scripts" / "python.exe"
                    commands.append({
                        "label": "Create isolated project virtual environment",
                        "phase": "configure",
                        "argv": [sys.executable, "-m", "venv", str(root / ".venv")],
                    })
                commands.extend((
                    {
                        "label": "Install declared Python project dependencies",
                        "phase": "install",
                        "argv": [str(local_python), "-m", "pip", "install", "."],
                    },
                    {
                        "label": "Verify Python dependency consistency",
                        "phase": "verify",
                        "argv": [str(local_python), "-m", "pip", "check"],
                    },
                ))

    if "node" in types and "package.json" in names:
        package_manager = shutil.which("npm.cmd") or shutil.which("npm")
        if "pnpm-lock.yaml" in names:
            package_manager = shutil.which("pnpm.cmd") or shutil.which("pnpm")
            install_args = ["install", "--frozen-lockfile"]
            verify_args = ["list", "--depth", "-1"]
        elif "yarn.lock" in names:
            package_manager = shutil.which("yarn.cmd") or shutil.which("yarn")
            install_args = ["install", "--frozen-lockfile"]
            verify_args = ["list", "--depth=0"]
        elif "package-lock.json" in names:
            install_args = ["ci"]
            verify_args = ["list", "--depth=0"]
        else:
            install_args = ["install"]
            verify_args = ["list", "--depth=0"]
        if package_manager:
            commands.extend((
                {
                    "label": f"Install declared Node dependencies with {Path(package_manager).stem}",
                    "phase": "install",
                    "argv": [package_manager, *install_args],
                },
                {
                    "label": "Verify installed Node dependencies",
                    "phase": "verify",
                    "argv": [package_manager, *verify_args],
                },
            ))

    if "android" in types or "java" in types:
        wrapper = next(
            (name for name in ("gradlew.bat", "gradlew", "mvnw.cmd", "mvnw") if name in names),
            None,
        )
        if wrapper:
            executable = str(root / wrapper)
            if wrapper.startswith("gradlew"):
                commands.append({
                    "label": "Resolve Gradle dependencies and build project",
                    "phase": "install",
                    "argv": [executable, "build", "--no-daemon", "--refresh-dependencies"],
                })
            else:
                commands.append({
                    "label": "Resolve Maven project dependencies",
                    "phase": "install",
                    "argv": [executable, "dependency:resolve"],
                })

    if "dotnet" in types and shutil.which("dotnet"):
        commands.append({
            "label": ".NET dependency restore",
            "phase": "install",
            "argv": [shutil.which("dotnet"), "restore"],
        })
    if "rust" in types and shutil.which("cargo"):
        commands.append({
            "label": "Fetch declared Rust dependencies",
            "phase": "install",
            "argv": [shutil.which("cargo"), "fetch"],
        })
    if "go" in types and shutil.which("go") and "go.mod" in names:
        commands.append({
            "label": "Download declared Go modules",
            "phase": "install",
            "argv": [shutil.which("go"), "mod", "download"],
        })
    return commands


def _redact_source(text: str) -> str:
    sensitive_key = (
        r"api[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
        r"password|passwd|secret|credential|private[_-]?key|authorization|"
        r"client[_-]?secret|aws_access_key_id|aws_secret_access_key|token"
    )
    assignment = re.compile(
        rf"(?i)([\"']?(?:{sensitive_key})[\"']?\s*[:=]\s*)"
        r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;}\]]+)"
    )

    def replace_assignment(match: re.Match[str]) -> str:
        value = match.group(2)
        quote = value[0] if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" else ""
        return f"{match.group(1)}{quote}[REDACTED]{quote}"

    redacted = re.sub(
        r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[REDACTED]",
        text,
    )
    redacted = assignment.sub(replace_assignment, redacted)
    redacted = re.sub(
        r"(?im)(-----BEGIN [A-Z ]*PRIVATE KEY-----).*?(-----END [A-Z ]*PRIVATE KEY-----)",
        r"\1[REDACTED]\2",
        redacted,
        flags=re.DOTALL,
    )
    return re.sub(
        r"(?i)(https?://[^:/\s]+:)[^@/\s]+@",
        r"\1[REDACTED]@",
        redacted,
    )


def _relevant_sources(
    root: Path,
    scan: dict[str, Any],
    request: str,
    selected_file: str | None,
    *,
    allowed_files: set[str] | None = None,
) -> list[dict[str, str]]:
    excluded_terms = {
        "please", "project", "error", "fix", "broken", "working", "this",
        "that", "with", "from", "file", "scan", "build", "test", "gar",
        "garnu", "mero", "ko", "the",
    }
    terms = {
        token.casefold()
        for token in re.findall(r"[A-Za-z_][A-Za-z_0-9]{2,}", request)
        if token.casefold() not in excluded_terms
    }
    candidates: list[tuple[int, str, str]] = []
    for relative in scan["source_files"]:
        if allowed_files is not None and relative not in allowed_files:
            continue
        path = root / relative
        if not path.is_file() or path.is_symlink():
            continue
        if any(part.casefold() in {".git", ".venv", "node_modules", "dist", "build"} for part in Path(relative).parts):
            continue
        try:
            raw = path.read_bytes()
            if len(raw) > 48 * 1024 or b"\x00" in raw:
                continue
            content = raw.decode("utf-8-sig")
        except (OSError, UnicodeError):
            continue
        score = 1000 if selected_file and Path(relative).as_posix() == Path(selected_file).as_posix() else 0
        score += sum(18 for term in terms if term in relative.casefold())
        score += sum(min(8, content.casefold().count(term) * 2) for term in terms)
        if score:
            candidates.append((score, relative, content))
    candidates.sort(key=lambda item: (-item[0], item[1].casefold()))
    return [
        {"file": relative, "content": _redact_source(content)}
        for _, relative, content in candidates[:10]
    ]


def _generate_patch(request: str, sources: list[dict[str, str]]) -> list[dict[str, str]]:
    from core.ai_providers import PROVIDER_INFO, generate_chat_response
    from core.paths import load_api_config
    from core.runtime_instructions import load_runtime_rules

    config = load_api_config()
    provider = str(config.get("active_ai_provider") or "gemini").casefold()
    provider_info = PROVIDER_INFO.get(provider)
    if provider_info is None:
        raise RuntimeError(f"Unsupported configured AI provider: {provider}.")
    api_key = str(config.get(provider_info["key_name"]) or "").strip()
    selected_models = config.get("ai_provider_selected_models", {})
    model = str(selected_models.get(provider) or "").strip() if isinstance(selected_models, dict) else ""
    if not api_key or not model:
        raise RuntimeError(
            f"Connect {provider_info['name']} and select a model in Settings before requesting code changes."
        )

    context = "\n\n".join(
        f"FILE: {item['file']}\n```{Path(item['file']).suffix.lstrip('.')}\n{item['content']}\n```"
        for item in sources
    )
    runtime_rules, _rule_issues = load_runtime_rules(
        Path(__file__).resolve().parents[1] / "core" / "runtime_rules"
    )
    answer = generate_chat_response(
        provider,
        api_key,
        model,
        [{
            "role": "user",
            "text": (
                f"User request: {_redact_source(request)}\n\n"
                "Make only the minimal change required; leave unrelated issues alone. "
                "Do not add files, dependencies, or redesign UI. Return only JSON: "
                "{\"changes\":[{\"file\":\"relative/path\",\"search\":\"exact unique existing text\","
                "\"replace\":\"replacement text\"}]}. Every search value must be an exact substring "
                "of the supplied source. Return {\"changes\":[]} if no safe fix can be determined.\n\n"
                f"Relevant project sources:\n{context}"
            ),
        }],
        system_instruction=(
            f"{runtime_rules}\n\n"
            "You are a careful software repair engineer. Return valid JSON only. "
            "Never include files that were not provided."
        ),
    )
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", answer.strip(), flags=re.IGNORECASE)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"The configured AI provider returned invalid patch JSON: {exc}.") from exc
    changes = payload.get("changes") if isinstance(payload, dict) else None
    if not isinstance(changes, list) or not changes or len(changes) > 8:
        raise RuntimeError("The provider did not return a bounded, applicable patch.")
    validated: list[dict[str, str]] = []
    size = 0
    for item in changes:
        if not isinstance(item, dict):
            raise RuntimeError("The provider returned an invalid patch item.")
        relative, search, replacement = item.get("file"), item.get("search"), item.get("replace")
        if not all(isinstance(value, str) for value in (relative, search, replacement)):
            raise RuntimeError("Each patch needs string file, search, and replace fields.")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError("The provider patch attempted to escape the project root.")
        if not search or search == replacement:
            raise RuntimeError("The provider returned an empty or ineffective replacement.")
        size += len(search.encode("utf-8")) + len(replacement.encode("utf-8"))
        if size > 64 * 1024:
            raise RuntimeError("The patch exceeds the 64 KiB safety limit.")
        validated.append({"file": relative_path.as_posix(), "search": search, "replace": replacement})
    return validated


def _backup_root(task_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(task_id))
    if not safe_id:
        raise ValueError("A valid task ID is required for the recovery backup.")
    local_data = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    return local_data / "NEBIX" / "engineering_backups" / safe_id


def _requested_software(text: str) -> dict[str, Any] | None:
    normalized = _normalize(text)
    for target in _SOFTWARE_TARGETS:
        for pattern in target["patterns"]:
            if pattern == "git":
                found = bool(re.search(r"\bgit\b", normalized))
            else:
                found = pattern in normalized
            if found:
                return target
    return None


def _installed_software(
    target: dict[str, Any],
    *,
    authorize_command: Callable[[str], bool] | None = None,
) -> dict[str, str] | None:
    name = target["name"]
    if name == "Microsoft Excel":
        if os.name == "nt":
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_CLASSES_ROOT,
                    r"Excel.Application\CLSID",
                ):
                    pass
            except (ImportError, OSError):
                return None
            exe = _registry_excel_path()
            return {
                "name": name,
                "path": str(exe) if exe else "Excel COM automation is registered",
                "version": _file_version(exe) if exe else "version unavailable",
            }
        return None
    for executable in target["executables"]:
        if executable.is_file():
            version = _file_version(executable)
            if name == "Android Studio":
                product_info = executable.parent.parent / "product-info.json"
                try:
                    metadata = json.loads(product_info.read_text(encoding="utf-8"))
                    version = str(metadata.get("version") or version)
                except (OSError, UnicodeError, json.JSONDecodeError):
                    pass
            return {"name": name, "path": str(executable), "version": version}
    command_name = {
        "Visual Studio Code": "code",
        "Node.js LTS": "node",
        "Git for Windows": "git",
    }.get(name)
    command = shutil.which(command_name) if command_name else None
    if command:
        arguments = [command, "--version"]
        if Path(command).suffix.casefold() in {".cmd", ".bat"}:
            arguments = [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/d",
                "/c",
                subprocess.list2cmdline([command, "--version"]),
            ]
        try:
            if authorize_command and not authorize_command(f"Check installed {name} version"):
                raise PermissionDenied("Permission denied for command execution.")
            result = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        version = ""
        if result and result.returncode == 0:
            version = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
        if version:
            return {"name": name, "path": command, "version": version}
    if name == "Python 3.14":
        if sys.version_info < (3, 14):
            return None
        return {
            "name": name,
            "path": sys.executable,
            "version": platform.python_version(),
        }
    return None


def _registry_excel_path() -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg

        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for key_path in (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\excel.exe",
            ):
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        value, _ = winreg.QueryValueEx(key, "")
                        candidate = Path(os.path.expandvars(value))
                        if candidate.is_file():
                            return candidate
                except OSError:
                    continue
    except ImportError:
        return None
    return None


def _file_version(path: Path | None) -> str:
    if path is None:
        return "version unavailable"
    if os.name == "nt":
        try:
            import win32api

            info = win32api.GetFileVersionInfo(str(path), "\\")
            ms = info["FileVersionMS"]
            ls = info["FileVersionLS"]
            return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
        except (ImportError, OSError, KeyError, TypeError):
            pass
    return "version unavailable"


def _validate_source(
    path: Path,
    content: str,
    *,
    authorize_command: Callable[[str], bool] | None = None,
) -> None:
    suffix = path.suffix.casefold()
    if suffix == ".py":
        ast.parse(content, filename=str(path))
    elif suffix == ".json":
        json.loads(content)
    elif suffix in {".js", ".mjs", ".cjs"}:
        node = shutil.which("node")
        if node:
            if authorize_command and not authorize_command(f"Validate JavaScript source {path.name}"):
                raise PermissionDenied("Permission denied for command execution.")
            result = subprocess.run(
                [node, "--check", str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                check=False,
            )
            if result.returncode:
                raise RuntimeError((result.stderr or result.stdout).strip()[:2000])
    elif suffix in {".html", ".htm"}:
        from html.parser import HTMLParser

        class _Parser(HTMLParser):
            def error(self, message: str) -> None:
                raise ValueError(message)

        _Parser().feed(content)


class EngineeringAgent:
    """Shared session task/context state used by voice transcripts and Chat."""

    def __init__(
        self,
        *,
        event: Callable[[str], None],
        set_state: Callable[[str, str], None],
        request_confirmation: Callable[[str, str, Callable[[], str]], str] | None = None,
        authorize: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._event = event
        self._set_ui_state = set_state
        self._request_confirmation = request_confirmation
        self._authorize_callback = authorize
        self._lock = threading.RLock()
        self._task = EngineeringTask(
            task_id="",
            request="",
            intent="",
            state=TaskState.IDLE,
            created_at=0,
            updated_at=0,
        )
        self._cancel_event = threading.Event()
        self._last_project_path: str | None = None
        self._last_scan: dict[str, Any] | None = None
        self._selected_file: str | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = asdict(self._task)
            snapshot["state"] = self._task.state.value
            snapshot["last_project_path"] = self._last_project_path
            snapshot["last_scan"] = self._public_scan(self._last_scan)
            return snapshot

    @staticmethod
    def _public_scan(scan: dict[str, Any] | None) -> dict[str, Any] | None:
        if scan is None:
            return None
        return {
            key: value for key, value in scan.items()
            if key != "scanned_at"
        }

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise TaskCancelled("Engineering task cancelled by the user.")

    def _authorize(self, capability: str, operation: str) -> bool:
        if self._authorize_callback is None:
            return False
        try:
            return bool(self._authorize_callback(capability, operation))
        except Exception:
            return False

    def _require_permission(self, capability: str, operation: str) -> None:
        if not self._authorize(capability, operation):
            raise PermissionDenied(f"Permission denied for {capability}: {operation}")

    def _authorize_command(self, operation: str) -> bool:
        return self._authorize("command.execute", operation)

    def _transition(
        self,
        state: TaskState,
        *,
        message: str = "",
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            current = self._task.state
            if state != current and state not in _TRANSITIONS.get(current, set()):
                raise RuntimeError(f"Invalid task transition: {current.value} → {state.value}")
            self._task.state = state
            self._task.updated_at = time.time()
            if result is not None:
                self._task.result = result
            if error is not None:
                self._task.error = error
            task_id = self._task.task_id
        if message:
            self._event(f"[ENGINEERING:{task_id}] {message}")
            self._set_ui_state(state.value, message)

    def handle_text(self, text: str) -> dict[str, Any] | None:
        intent = _classify_request(text)
        pending_path = _extract_path(text)
        if intent is None and pending_path:
            with self._lock:
                if self._task.state == TaskState.WAITING_FOR_USER and self._task.intent:
                    intent = self._task.intent
                    text = f"{self._task.request} {text}"
        if intent is None:
            if self._is_status_question(text):
                return {
                    "intent": "ENGINEERING_STATUS",
                    "ok": True,
                    "message": self._status_answer(text),
                    "state": self.snapshot(),
                }
            return None

        intent_capability = {
            "software_status": "engineering.software_status",
            "open_application": "engineering.open_application",
            "open_vscode": "engineering.open_application",
            "open_android_studio": "engineering.open_application",
            "scan": "engineering.project_discovery",
            "diagnose": "engineering.diagnose",
            "provision": "engineering.provision",
        }.get(intent, f"engineering.{intent}")
        if not self._authorize(intent_capability, str(text).strip()):
            return {
                "intent": "ENGINEERING_TASK",
                "ok": False,
                "message": f"Permission denied for {intent_capability}; no engineering action was started.",
                "state": self.snapshot(),
            }

        with self._lock:
            previous = self._task.state
            resumes_path_prompt = (
                previous == TaskState.WAITING_FOR_USER
                and pending_path is not None
                and bool(intent)
            )
            if (
                previous not in _TERMINAL_STATES
                and previous != TaskState.IDLE
                and not resumes_path_prompt
            ):
                return {
                    "intent": "ENGINEERING_TASK",
                    "ok": False,
                    "message": (
                        f"An engineering task is already {previous.value.replace('_', ' ').lower()}. "
                        "I did not start a second task."
                    ),
                    "state": self.snapshot(),
                }
            now = time.time()
            self._task = EngineeringTask(
                task_id=uuid.uuid4().hex[:12],
                request=str(text).strip(),
                intent=intent,
                state=TaskState.IDLE,
                created_at=now,
                updated_at=now,
            )
            self._cancel_event.clear()

        normalized_request = _normalize(text)
        if intent in {"software_status", "open_application"} or (
            intent == "provision"
            and not any(word in normalized_request for word in ("project", "extension", "dependency"))
        ):
            return self._handle_software_request(text, intent)

        if (
            intent == "provision"
            and "extension" in normalized_request
            and _extract_path(text) is None
            and "project" not in normalized_request
            and re.search(
                r"(?<![A-Za-z0-9_.-])[A-Za-z0-9][A-Za-z0-9_-]*\.[A-Za-z0-9][A-Za-z0-9_.-]*(?![A-Za-z0-9_.-])",
                text,
            )
        ):
            return self._handle_extension_install(text)

        path_text = _extract_path(text)
        selected_file = None
        if path_text:
            try:
                resolved_path = Path(path_text).expanduser().resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                self._transition(
                    TaskState.PLANNED,
                    message="PLANNED",
                    error=str(exc),
                )
                self._transition(
                    TaskState.FAILED,
                    message=f"Project path could not be resolved: {exc}",
                    result=f"I couldn't resolve the requested project path: {exc}",
                )
                return self._response(False)
            if resolved_path.is_file():
                selected_file = str(resolved_path)
                project_path = str(resolved_path.parent)
            elif resolved_path.is_dir():
                project_path = str(resolved_path)
            else:
                self._transition(
                    TaskState.PLANNED,
                    message="PLANNED",
                )
                self._transition(
                    TaskState.FAILED,
                    message=f"FAILED: The requested path is not a file or folder: {resolved_path}",
                    result=f"The requested path is not a file or folder: {resolved_path}",
                    error="Unsupported project path.",
                )
                return self._response(False)
        else:
            project_path = self._last_project_path

        if not project_path:
            self._transition(
                TaskState.WAITING_FOR_USER,
                message="WAITING FOR PROJECT PATH",
                result="Which project folder should I inspect? Please provide its full path.",
            )
            return self._response(True)

        self._task.project_path = project_path
        self._task.current_file = selected_file
        self._selected_file = selected_file
        self._task.plan = [
            f"Inspect project structure and recognized manifests under {project_path}.",
            "Run bounded, non-executing syntax checks on supported source/config files.",
        ]
        if intent.startswith("open_"):
            self._task.plan.append("Open the inspected project in the requested IDE and verify process launch.")
        elif intent == "diagnose":
            self._task.plan.extend((
                "Identify only source files relevant to the requested correction and inspect their local references.",
                "Request permission before sending redacted relevant source excerpts to the configured AI provider.",
                "Show a minimal patch preview and request approval before changing files.",
                "Create a recovery backup, apply only the approved patch, and run the project's discovered tests/build.",
            ))
        elif intent == "provision":
            self._task.plan.append(
                "Inspect declared project dependency or extension metadata, identify exact packages, "
                "and request approval before installation."
            )

        self._transition(TaskState.PLANNED, message="PLANNED")
        try:
            self._transition(TaskState.SCANNING, message=f"SCANNING PROJECT {project_path}")
            scan = scan_project(
                project_path,
                event=self._event,
                cancel_event=self._cancel_event,
                authorize_command=self._authorize_command,
            )
            with self._lock:
                self._last_project_path = scan["path"]
                self._last_scan = scan
                self._task.findings = self._findings(scan)
                self._task.evidence = [
                    f"Scanned {scan['file_count']} files ({scan['source_file_count']} source files).",
                    f"Detected project type: {', '.join(scan['project_types'])}.",
                ]
            self._transition(
                TaskState.IDENTIFYING_PROJECT_TYPE,
                message=f"IDENTIFYING PROJECT TYPE: {', '.join(scan['project_types'])}",
            )

            if intent == "scan":
                report = self._scan_report(scan)
                self._transition(TaskState.VERIFYING, message="VERIFYING INVENTORY")
                self._transition(TaskState.COMPLETED, message="COMPLETED", result=report)
                return self._response(True)

            if intent == "diagnose":
                root = Path(project_path)
                relative_selected = (
                    Path(selected_file).relative_to(root).as_posix()
                    if selected_file
                    else None
                )
                sources = _relevant_sources(
                    root,
                    scan,
                    str(text),
                    relative_selected,
                )
                if not sources:
                    message = (
                        f"I scanned {project_path}, but could not identify a relevant, readable source file "
                        "for the requested repair. No files were changed."
                    )
                    self._transition(
                        TaskState.BLOCKED,
                        message="BLOCKED: no relevant source file identified.",
                        result=message,
                        error="The requested code target could not be identified safely.",
                    )
                    return self._response(False)
                commands = _project_commands(root, scan)
                with self._lock:
                    self._task.commands = [
                        {"phase": phase, **command, "exit_code": None}
                        for phase, group in commands.items()
                        for command in group
                    ]
                if self._request_confirmation is None:
                    message = (
                        "The task is scanned and ready to create a minimal patch, but the on-screen "
                        "confirmation service is unavailable. No project code was sent or changed."
                    )
                    self._transition(
                        TaskState.BLOCKED,
                        message="BLOCKED: confirmation UI is unavailable.",
                        result=message,
                        error="Patch generation requires the existing HUD confirmation gate.",
                    )
                    return self._response(False)
                from core.ai_providers import PROVIDER_INFO
                from core.paths import load_api_config

                provider_config = load_api_config()
                provider_id = str(provider_config.get("active_ai_provider") or "gemini").casefold()
                provider_name = PROVIDER_INFO.get(provider_id, {}).get("name", provider_id)
                selected_names = ", ".join(item["file"] for item in sources)
                self._transition(
                    TaskState.WAITING_FOR_CONFIRMATION,
                    message=f"WAITING FOR CONFIRMATION TO ANALYZE {len(sources)} SOURCE FILE(S)",
                )
                confirmation = self._request_confirmation(
                    "Share relevant source and prepare a repair",
                    (
                        f"Request: {str(text)[:260]}. Files: {selected_names[:650]}. "
                        f"NEBIX will send these redacted source excerpts to {provider_name} to propose a minimal patch. "
                        "It will not modify anything until you review and separately approve the exact patch. "
                        "The approved workflow may execute this project's detected tests/build."
                    ),
                    lambda: self._prepare_repair(root, scan, str(text), sources, commands),
                    on_cancel=lambda: self._cancel_confirmation("Source analysis was declined or expired."),
                )
                with self._lock:
                    self._task.result = str(confirmation)
                    self._task.updated_at = time.time()
                if not str(confirmation).startswith("[CONFIRMATION_PENDING]"):
                    self._transition(
                        TaskState.BLOCKED,
                        message="BLOCKED: the HUD could not request user confirmation.",
                        result=str(confirmation),
                        error=str(confirmation),
                    )
                    return self._response(False)
                return self._response(True)

            if intent == "provision":
                return self._handle_project_provision(Path(project_path), scan, str(text))

            self._transition(TaskState.EXECUTING, message=f"OPENING {intent.removeprefix('open_').replace('_', ' ').upper()}")
            opened = self._open_ide(project_path, intent)
            if not opened["ok"]:
                self._transition(
                    TaskState.FAILED,
                    message=f"FAILED: {opened['message']}",
                    result=opened["message"],
                    error=opened["message"],
                )
                return self._response(False)
            if not opened.get("verified"):
                self._transition(
                    TaskState.BLOCKED,
                    message=f"BLOCKED: {opened['message']}",
                    result=opened["message"],
                    error="The requested IDE/project window was not visible with a matching title.",
                )
                return self._response(False)
            self._transition(TaskState.VERIFYING, message="VERIFYING IDE PROCESS")
            report = f"{opened['message']} Project path: {project_path}."
            self._transition(
                TaskState.COMPLETED,
                message="COMPLETED",
                result=report,
            )
            return self._response(True)
        except TaskCancelled as exc:
            if self.snapshot()["state"] not in {state.value for state in _TERMINAL_STATES}:
                self._transition(
                    TaskState.CANCELLED,
                    message=f"CANCELLED: {exc}",
                    result=str(exc),
                    error=str(exc),
                )
            return self._response(False)
        except (OSError, ValueError, RuntimeError) as exc:
            current = self.snapshot()["state"]
            if current not in {state.value for state in _TERMINAL_STATES}:
                self._transition(
                    TaskState.FAILED,
                    message=f"FAILED: {exc}",
                    result=f"The engineering task failed: {exc}",
                    error=str(exc),
                )
            return self._response(False)

    def _cancel_confirmation(self, reason: str) -> None:
        current = self.snapshot()["state"]
        if current not in {state.value for state in _TERMINAL_STATES}:
            self._transition(
                TaskState.CANCELLED,
                message="CANCELLED: user declined or confirmation expired.",
                result=reason,
                error=reason,
            )

    def _handle_project_provision(
        self,
        root: Path,
        scan: dict[str, Any],
        request: str,
    ) -> dict[str, Any]:
        if "extension" in _normalize(request):
            return self._handle_project_extensions(root, scan, request)
        commands = _project_install_commands(root, scan)
        if not commands:
            message = (
                f"NEBIX inspected {root} but found no supported, declared dependency installation "
                "command for this project. Nothing was installed."
            )
            self._transition(
                TaskState.BLOCKED,
                message="BLOCKED: no supported project dependency manifest/manager was detected.",
                result=message,
                error="No supported declared dependency installation workflow was identified.",
            )
            return self._response(False)
        plan = [
            f"{item['label']}: {subprocess.list2cmdline(item['argv'])}"
            for item in commands
        ]
        self._task.plan = plan
        self._task.commands = [
            {"phase": item["phase"], "label": item["label"], "argv": item["argv"], "exit_code": None}
            for item in commands
        ]
        self._task.evidence.append(
            f"Dependency manifests inspected: {', '.join(scan['manifests']) or 'none listed'}."
        )
        if self._request_confirmation is None:
            message = "The HUD approval service is unavailable; no dependencies were installed."
            self._transition(TaskState.BLOCKED, message=message, result=message, error=message)
            return self._response(False)
        detail = (
            f"Project: {root}\n"
            "The commands below use the project's declared manifests/lockfiles. They may download packages, "
            "create/update the project environment, and execute package-manager/build scripts:\n"
            + "\n".join(f"- {item}" for item in plan)
            + "\nNo unrelated project files will be intentionally changed."
        )
        self._transition(TaskState.WAITING_FOR_CONFIRMATION, message="WAITING FOR PROJECT DEPENDENCY INSTALL APPROVAL")
        confirmation = self._request_confirmation(
            "Install declared project dependencies",
            detail,
            lambda: self._run_project_install_commands(root, commands),
            on_cancel=lambda: self._cancel_confirmation("Project dependency installation was declined or expired."),
        )
        self._task.result = str(confirmation)
        if not str(confirmation).startswith("[CONFIRMATION_PENDING]"):
            self._transition(
                TaskState.BLOCKED,
                message="BLOCKED: the dependency-install confirmation could not be displayed.",
                result=str(confirmation),
                error=str(confirmation),
            )
            return self._response(False)
        return self._response(True)

    def _handle_project_extensions(
        self,
        root: Path,
        scan: dict[str, Any],
        request: str,
    ) -> dict[str, Any]:
        request_without_path = request
        path_text = _extract_path(request)
        if path_text:
            request_without_path = request_without_path.replace(path_text, "")
        requested = re.search(
            r"(?<![A-Za-z0-9_.-])([A-Za-z0-9][A-Za-z0-9_-]*\.[A-Za-z0-9][A-Za-z0-9_.-]*)(?![A-Za-z0-9_.-])",
            request_without_path,
        )
        recommendations = [requested.group(1)] if requested else scan["vscode_extension_recommendations"]
        if not recommendations:
            message = (
                f"No project-declared VS Code extension recommendations were found under {root}; "
                "no extension was installed."
            )
            self._transition(TaskState.BLOCKED, message=message, result=message, error=message)
            return self._response(False)
        vscode = _requested_software("VS Code")
        if vscode is None:
            raise RuntimeError("The Visual Studio Code software target is not configured.")
        try:
            installed_vscode = _installed_software(vscode, authorize_command=self._authorize_command)
        except PermissionDenied as exc:
            self._transition(TaskState.BLOCKED, message=str(exc), result=str(exc), error=str(exc))
            return self._response(False)
        cli = shutil.which("code")
        if not installed_vscode or not cli:
            message = (
                "Visual Studio Code and its `code` command are both required to verify/install "
                "the recommended extensions; no extension was installed."
            )
            self._transition(TaskState.BLOCKED, message=message, result=message, error=message)
            return self._response(False)
        try:
            gallery = self._verified_vscode_gallery(installed_vscode)
            installed = self._vscode_extension_versions(
                cli,
                authorize_command=self._authorize_command,
            )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            message = f"Could not verify the configured VS Code extension gallery/status: {exc}. Nothing was installed."
            self._transition(TaskState.FAILED, message=message, result=message, error=str(exc))
            return self._response(False)
        missing = [
            extension for extension in recommendations
            if extension.casefold() not in installed
        ]
        if not missing:
            message = (
                "All requested project extensions are already installed: "
                + ", ".join(recommendations)
                + "."
            )
            self._transition(TaskState.VERIFYING, message="VERIFYING PROJECT EXTENSION RECOMMENDATIONS")
            self._transition(TaskState.COMPLETED, message="COMPLETED", result=message)
            return self._response(True)
        self._task.plan = [
            f"Install missing VS Code extensions from {gallery}: {', '.join(missing)}.",
            "Query the installed extension list and versions to verify each exact identifier.",
        ]
        self._task.evidence.extend((
            f"Project recommendations: {', '.join(recommendations)}.",
            f"Already installed: {', '.join(sorted(set(recommendations) - set(missing))) or 'none'}.",
            f"Missing: {', '.join(missing)}.",
            f"Verified gallery service: {gallery}.",
        ))
        if self._request_confirmation is None:
            message = "The HUD approval service is unavailable; no extensions were installed."
            self._transition(TaskState.BLOCKED, message=message, result=message, error=message)
            return self._response(False)
        detail = (
            f"Project: {root}\nVerified VS Code gallery: {gallery}\n"
            f"Missing extension identifiers: {', '.join(missing)}.\n"
            "NEBIX will install only these IDs and verify the installed IDs/versions."
        )
        self._transition(TaskState.WAITING_FOR_CONFIRMATION, message="WAITING FOR PROJECT EXTENSION APPROVAL")
        confirmation = self._request_confirmation(
            "Install missing VS Code project extensions",
            detail,
            lambda: self._install_project_extensions(cli, missing),
            on_cancel=lambda: self._cancel_confirmation("Project extension installation was declined or expired."),
        )
        self._task.result = str(confirmation)
        if not str(confirmation).startswith("[CONFIRMATION_PENDING]"):
            self._transition(
                TaskState.BLOCKED,
                message="BLOCKED: the extension-install confirmation could not be displayed.",
                result=str(confirmation),
                error=str(confirmation),
            )
            return self._response(False)
        return self._response(True)

    @staticmethod
    def _verified_vscode_gallery(installed: dict[str, str]) -> str:
        executable = Path(installed["path"])
        product_files = [
            executable.parent / "resources" / "app" / "product.json",
            executable.parent.parent / "resources" / "app" / "product.json",
        ]
        product_files.extend(sorted(
            executable.parent.glob("*/resources/app/product.json"),
            key=lambda path: path.as_posix().casefold(),
        ))
        product_file = next((path for path in product_files if path.is_file()), None)
        if product_file is None:
            raise RuntimeError("Visual Studio Code product.json was not found; gallery identity is unverified.")
        product = json.loads(product_file.read_text(encoding="utf-8"))
        gallery = product.get("extensionsGallery", {}).get("serviceUrl") if isinstance(product, dict) else None
        if not isinstance(gallery, str):
            raise RuntimeError("Visual Studio Code does not declare an extension gallery service URL.")
        parsed = urlsplit(gallery)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "marketplace.visualstudio.com"
            or parsed.path.rstrip("/") != "/_apis/public/gallery"
        ):
            raise RuntimeError(f"Configured extension gallery is not the official VS Code Marketplace: {gallery}")
        return gallery

    def _install_project_extensions(self, cli: str, extensions: list[str]) -> str:
        installed_now: list[str] = []
        try:
            for extension in extensions:
                self._check_cancelled()
                self._transition(TaskState.DOWNLOADING, message=f"DOWNLOADING VS CODE EXTENSION {extension}")
                self._transition(TaskState.INSTALLING, message=f"INSTALLING VS CODE EXTENSION {extension}")
                command = [cli, "--install-extension", extension]
                if Path(cli).suffix.casefold() in {".cmd", ".bat"}:
                    command = [
                        os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                        subprocess.list2cmdline(command),
                    ]
                self._require_permission("install.package", f"Install VS Code extension {extension}")
                self._require_permission("network.access", f"Download VS Code extension {extension}")
                self._require_permission("command.execute", f"Run VS Code extension installer for {extension}")
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=600,
                    check=False,
                )
                output = (result.stdout or "") + "\n" + (result.stderr or "")
                self._event(f"VS CODE EXTENSION {extension}: {output[-1200:].strip()}")
                if result.returncode:
                    raise RuntimeError(
                        f"Extension {extension} installer exited {result.returncode}: {output[-1200:].strip()}"
                    )
                installed_now.append(extension)
            self._transition(TaskState.VERIFYING, message="VERIFYING INSTALLED PROJECT EXTENSIONS")
            versions = self._vscode_extension_versions(
                cli,
                authorize_command=self._authorize_command,
            )
            missing = [extension for extension in extensions if extension.casefold() not in versions]
            if missing:
                raise RuntimeError(f"Installed extensions were not verified: {', '.join(missing)}")
            report = "Installed and verified VS Code extensions: " + ", ".join(
                f"{extension} ({versions[extension.casefold()]})" for extension in extensions
            )
            self._transition(TaskState.COMPLETED, message="COMPLETED", result=report)
            return report
        except (OSError, RuntimeError, subprocess.SubprocessError, TaskCancelled) as exc:
            state = self.snapshot()["state"]
            if state not in {item.value for item in _TERMINAL_STATES}:
                if isinstance(exc, TaskCancelled):
                    self._transition(TaskState.CANCELLED, message=f"CANCELLED: {exc}", result=str(exc), error=str(exc))
                else:
                    message = (
                        f"Project extension installation failed: {exc}. "
                        f"Completed before failure: {', '.join(installed_now) or 'none'}."
                    )
                    self._transition(TaskState.FAILED, message=message, result=message, error=str(exc))
            return str(exc)

    def _run_project_install_commands(
        self,
        root: Path,
        commands: list[dict[str, Any]],
    ) -> str:
        results: list[dict[str, Any]] = []
        try:
            for spec in commands:
                self._check_cancelled()
                if spec["phase"] == "configure":
                    self._transition(TaskState.CONFIGURING, message=spec["label"].upper())
                elif spec["phase"] == "verify":
                    self._transition(TaskState.VERIFYING, message=spec["label"].upper())
                else:
                    self._transition(TaskState.DOWNLOADING, message=f"DOWNLOADING: {spec['label'].upper()}")
                    self._transition(TaskState.INSTALLING, message=f"RUNNING: {spec['label'].upper()}")
                argv = list(spec["argv"])
                command = self._windows_command(argv)
                self._event(f"RUNNING {spec['label']}: {subprocess.list2cmdline(argv)}")
                self._require_permission("command.execute", f"Run project install command: {spec['label']}")
                if spec["phase"] != "verify":
                    self._require_permission("install.package", f"Run project install command: {spec['label']}")
                    self._require_permission("network.access", f"Run project install command: {spec['label']}")
                process = subprocess.Popen(
                    command,
                    cwd=str(root),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                output: list[str] = []
                output_queue: queue.Queue[str | None] = queue.Queue()

                def consume() -> None:
                    assert process.stdout is not None
                    for line in process.stdout:
                        output_queue.put(line.rstrip())
                    output_queue.put(None)

                threading.Thread(target=consume, daemon=True, name="nebix-project-install-output").start()
                deadline = time.monotonic() + 1200
                while process.poll() is None:
                    if self._cancel_event.is_set():
                        process.terminate()
                        raise TaskCancelled("Project dependency installation cancelled; completed steps may remain installed.")
                    if time.monotonic() >= deadline:
                        process.terminate()
                        raise RuntimeError(f"{spec['label']} exceeded the 20-minute timeout.")
                    try:
                        line = output_queue.get(timeout=0.25)
                    except queue.Empty:
                        continue
                    if line is not None:
                        output.append(line)
                        self._event(f"{spec['label']}: {line[:500]}")
                exit_code = process.wait()
                record = {
                    "phase": spec["phase"],
                    "label": spec["label"],
                    "argv": argv,
                    "exit_code": exit_code,
                    "stdout": "\n".join(output)[-10000:],
                }
                results.append(record)
                with self._lock:
                    self._task.commands = list(results)
                if exit_code:
                    message = (
                        f"{spec['label']} failed with exit code {exit_code}. "
                        f"Output: {record['stdout'][-2000:]}"
                    )
                    self._transition(TaskState.FAILED, message=message, result=message, error=message)
                    return message
            self._transition(TaskState.VERIFYING, message="VERIFYING PROJECT DEPENDENCY INSTALLATION")
            report = (
                f"Project dependencies installed and verified in {root}. "
                f"Commands completed: {len(results)}; all returned exit code 0."
            )
            self._task.evidence.extend(
                f"{record['label']} exited {record['exit_code']}."
                for record in results
            )
            self._transition(TaskState.COMPLETED, message="COMPLETED", result=report)
            return report
        except TaskCancelled as exc:
            current = self.snapshot()["state"]
            if current not in {state.value for state in _TERMINAL_STATES}:
                self._transition(TaskState.CANCELLED, message=f"CANCELLED: {exc}", result=str(exc), error=str(exc))
            return str(exc)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            current = self.snapshot()["state"]
            message = (
                f"Project dependency installation failed: {exc}. "
                f"Completed commands: {len(results)}."
            )
            if current not in {state.value for state in _TERMINAL_STATES}:
                self._transition(TaskState.FAILED, message=message, result=message, error=str(exc))
            return message

    def _handle_software_request(self, request: str, intent: str) -> dict[str, Any]:
        target = _requested_software(request)
        if target is None:
            message = (
                "I could not safely identify which application you mean. "
                "No software was downloaded or installed."
            )
            self._transition(TaskState.PLANNED, message="PLANNED")
            self._transition(TaskState.BLOCKED, message=message, result=message, error=message)
            return self._response(False)
        self._task.plan = [
            f"Check the actual installation state for {target['name']}.",
            "If missing, verify its exact package and publisher from the configured official winget source.",
            "Request approval before running the visible interactive installation.",
            "Verify the executable/automation registration and version after setup.",
        ]
        self._transition(TaskState.PLANNED, message="PLANNED")
        self._transition(TaskState.EXECUTING, message=f"CHECKING {target['name'].upper()} INSTALLATION")
        try:
            installed = _installed_software(target, authorize_command=self._authorize_command)
        except PermissionDenied as exc:
            self._transition(TaskState.BLOCKED, message=str(exc), result=str(exc), error=str(exc))
            return self._response(False)
        if intent == "software_status" or installed:
            if installed:
                if intent == "open_application":
                    try:
                        launch_result = self._launch_application(target, installed)
                    except (ImportError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
                        message = f"{target['name']} is installed, but could not be opened: {exc}"
                        self._transition(TaskState.FAILED, message=message, result=message, error=str(exc))
                        return self._response(False)
                    message = (
                        f"{target['name']} is installed (version {installed['version']}) "
                        f"and was opened. {launch_result}"
                    )
                    self._transition(TaskState.VERIFYING, message=f"VERIFYING {target['name'].upper()} IS OPEN")
                    self._transition(TaskState.COMPLETED, message="COMPLETED", result=message)
                    return self._response(True)
                message = (
                    f"{target['name']} is installed. Version: {installed['version']}. "
                    f"Path: {installed['path']}."
                )
                self._transition(TaskState.VERIFYING, message=f"VERIFIED {target['name']} INSTALLATION")
                self._transition(TaskState.COMPLETED, message="COMPLETED", result=message)
                return self._response(True)
            message = f"{target['name']} is not detected on this computer."
            self._transition(TaskState.VERIFYING, message=f"VERIFIED {target['name']} IS NOT INSTALLED")
            self._transition(TaskState.COMPLETED, message="COMPLETED", result=message)
            return self._response(True)

        if intent == "open_application":
            message = (
                f"{target['name']} is not installed. NEBIX did not download or install it."
            )
            self._transition(TaskState.VERIFYING, message=f"VERIFIED {target['name']} IS NOT INSTALLED")
            self._transition(TaskState.BLOCKED, message=message, result=message, error=message)
            return self._response(False)

        package_id = target.get("package_id")
        if not package_id:
            message = (
                f"{target['name']} is not detected. NEBIX has no verified, exact official package "
                "for this application in the configured winget source, so it will not download or install "
                "a substitute."
            )
            self._transition(TaskState.VERIFYING, message=f"VERIFYING OFFICIAL SOURCE FOR {target['name'].upper()}")
            self._transition(
                TaskState.BLOCKED,
                message="BLOCKED: no verified official package is configured.",
                result=message,
                error="No approved exact-source package identifier is configured for this application.",
            )
            return self._response(False)
        winget = shutil.which("winget")
        if not winget:
            message = "Windows Package Manager (winget) is unavailable; nothing was downloaded or installed."
            self._transition(TaskState.FAILED, message=message, result=message, error="winget.exe was not found on PATH.")
            return self._response(False)

        self._transition(TaskState.VERIFYING, message=f"VERIFYING WINGET SOURCE FOR {target['name'].upper()}")
        try:
            source = self._inspect_winget_package(winget, target)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            message = f"Could not verify the official {target['name']} package: {exc}. Nothing was installed."
            self._transition(TaskState.FAILED, message=f"FAILED: {message}", result=message, error=str(exc))
            return self._response(False)
        version = source["version"]
        publisher = source["publisher"]
        summary = (
            f"{target['name']} is not installed. Verified package: {package_id}; "
            f"version: {version}; publisher: {publisher}; source: winget. "
            "The installer will be interactive and visible."
        )
        self._task.evidence.append(summary)
        if self._request_confirmation is None:
            message = summary + " The on-screen confirmation UI is unavailable; no installation was started."
            self._transition(TaskState.BLOCKED, message=message, result=message, error="HUD confirmation is unavailable.")
            return self._response(False)
        self._transition(TaskState.WAITING_FOR_CONFIRMATION, message=f"WAITING FOR INSTALLATION APPROVAL: {target['name']}")
        confirmation = self._request_confirmation(
            f"Install {target['name']}",
            (
                f"{summary} NEBIX will run winget with the exact package ID, show the vendor installer, "
                "and verify the installed executable afterward. If an installer choice or UAC prompt "
                "appears, you must review it yourself; NEBIX will not bypass it."
            ),
            lambda: self._install_winget_package(winget, target, version),
            on_cancel=lambda: self._cancel_confirmation("The software installation was declined or expired."),
        )
        self._task.result = str(confirmation)
        if not str(confirmation).startswith("[CONFIRMATION_PENDING]"):
            self._transition(
                TaskState.BLOCKED,
                message="BLOCKED: the installation confirmation could not be displayed.",
                result=str(confirmation),
                error=str(confirmation),
            )
            return self._response(False)
        return self._response(True)

    def _launch_application(self, target: dict[str, Any], installed: dict[str, str]) -> str:
        if target["name"] == "Microsoft Excel":
            from actions.excel_control import excel_control

            result = excel_control({"action": "create"})
            if not result.startswith("Created workbook "):
                raise RuntimeError(result)
            return result
        executable = Path(installed["path"])
        if not executable.is_file():
            raise RuntimeError(f"Verified application executable is no longer present: {executable}")
        command = [str(executable)]
        if executable.suffix.casefold() in {".cmd", ".bat"}:
            command = [
                os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                subprocess.list2cmdline(command),
            ]
        self._require_permission("command.execute", f"Open {target['name']}")
        process = subprocess.Popen(
            command,
            cwd=str(executable.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        process_name = executable.name.casefold()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is None:
                return f"Process started with PID {process.pid}."
            import psutil

            for candidate in psutil.process_iter(("pid", "name", "exe")):
                try:
                    if (
                        str(candidate.info.get("name") or "").casefold() == process_name
                        or Path(str(candidate.info.get("exe") or "")).name.casefold() == process_name
                    ):
                        return f"Process is running with PID {candidate.info['pid']}."
                except (psutil.Error, OSError):
                    continue
            time.sleep(0.1)
        raise RuntimeError(f"The application exited immediately with code {process.returncode}.")

    def _handle_extension_install(self, request: str) -> dict[str, Any]:
        identifier_match = re.search(
            r"(?<![A-Za-z0-9_.-])([A-Za-z0-9][A-Za-z0-9_-]*\.[A-Za-z0-9][A-Za-z0-9_.-]*)(?![A-Za-z0-9_.-])",
            request,
        )
        if not identifier_match:
            message = "A VS Code extension publisher.name identifier is required. No extension was installed."
            self._transition(TaskState.PLANNED, message="PLANNED")
            self._transition(TaskState.BLOCKED, message=message, result=message, error=message)
            return self._response(False)
        extension_id = identifier_match.group(1)
        vscode = _requested_software("VS Code")
        if vscode is None:
            raise RuntimeError("The Visual Studio Code software target is not configured.")
        try:
            installed_vscode = _installed_software(vscode, authorize_command=self._authorize_command)
        except PermissionDenied as exc:
            self._transition(TaskState.PLANNED, message="PLANNED")
            self._transition(TaskState.BLOCKED, message=str(exc), result=str(exc), error=str(exc))
            return self._response(False)
        if installed_vscode is None:
            message = "Visual Studio Code is not detected; no extension was installed."
            self._transition(TaskState.PLANNED, message="PLANNED")
            self._transition(TaskState.BLOCKED, message=message, result=message, error=message)
            return self._response(False)
        cli = shutil.which("code")
        if not cli:
            message = (
                f"Visual Studio Code is installed at {installed_vscode['path']}, "
                "but its `code` command-line tool is unavailable; no extension was installed."
            )
            self._transition(TaskState.PLANNED, message="PLANNED")
            self._transition(TaskState.BLOCKED, message=message, result=message, error=message)
            return self._response(False)
        self._transition(TaskState.PLANNED, message="PLANNED")
        self._transition(TaskState.EXECUTING, message=f"CHECKING VS CODE EXTENSION {extension_id}")
        try:
            existing = self._vscode_extension_versions(
                cli,
                authorize_command=self._authorize_command,
            )
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            message = f"Could not query installed VS Code extensions: {exc}"
            self._transition(TaskState.FAILED, message=message, result=message, error=str(exc))
            return self._response(False)
        if extension_id.casefold() in existing:
            message = f"VS Code extension {extension_id} is already installed ({existing[extension_id.casefold()]})."
            self._transition(TaskState.VERIFYING, message=f"VERIFIED EXTENSION {extension_id} IS INSTALLED")
            self._transition(TaskState.COMPLETED, message="COMPLETED", result=message)
            return self._response(True)
        try:
            gallery = self._verified_vscode_gallery(installed_vscode)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
            message = f"Could not verify the official VS Code extension gallery: {exc}. Nothing was installed."
            self._transition(TaskState.FAILED, message=message, result=message, error=str(exc))
            return self._response(False)
        description = (
            f"Install VS Code extension {extension_id} from {gallery} "
            "using the installed `code` CLI, then verify its exact installed identifier and version."
        )
        self._task.plan = [description]
        self._task.evidence.append(f"VS Code detected at {installed_vscode['path']}.")
        if self._request_confirmation is None:
            message = description + " The confirmation UI is unavailable; no extension was installed."
            self._transition(TaskState.BLOCKED, message=message, result=message, error="HUD confirmation is unavailable.")
            return self._response(False)
        self._transition(TaskState.WAITING_FOR_CONFIRMATION, message=f"WAITING FOR EXTENSION INSTALL APPROVAL: {extension_id}")
        confirmation = self._request_confirmation(
            f"Install VS Code extension {extension_id}",
            (
                f"NEBIX verified the configured official gallery at {gallery}. It will run "
                f"`code --install-extension {extension_id}` and then query `code --list-extensions --show-versions` "
                "to verify the exact extension. Continue?"
            ),
            lambda: self._install_vscode_extension(cli, extension_id),
            on_cancel=lambda: self._cancel_confirmation("The extension installation was declined or expired."),
        )
        self._task.result = str(confirmation)
        if not str(confirmation).startswith("[CONFIRMATION_PENDING]"):
            self._transition(
                TaskState.BLOCKED,
                message="BLOCKED: the extension confirmation could not be displayed.",
                result=str(confirmation),
                error=str(confirmation),
            )
            return self._response(False)
        return self._response(True)

    @staticmethod
    def _vscode_extension_versions(
        cli: str,
        *,
        authorize_command: Callable[[str], bool] | None = None,
    ) -> dict[str, str]:
        command = [cli, "--list-extensions", "--show-versions"]
        if Path(cli).suffix.casefold() in {".cmd", ".bat"}:
            command = [
                os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                subprocess.list2cmdline(command),
            ]
        if authorize_command and not authorize_command("List installed VS Code extensions"):
            raise PermissionDenied("Permission denied for command execution.")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(f"code --list-extensions exited {result.returncode}: {result.stderr[-1000:]}")
        versions = {}
        for line in result.stdout.splitlines():
            extension = line.strip()
            if "@" in extension:
                identifier, version = extension.rsplit("@", 1)
            else:
                identifier, version = extension, "version unavailable"
            if identifier:
                versions[identifier.casefold()] = version
        return versions

    def _install_vscode_extension(self, cli: str, extension_id: str) -> str:
        try:
            self._transition(TaskState.DOWNLOADING, message=f"DOWNLOADING VS CODE EXTENSION {extension_id}")
            self._transition(TaskState.INSTALLING, message=f"INSTALLING VS CODE EXTENSION {extension_id}")
            command = [cli, "--install-extension", extension_id]
            if Path(cli).suffix.casefold() in {".cmd", ".bat"}:
                command = [
                    os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                    subprocess.list2cmdline(command),
                ]
            self._require_permission("install.package", f"Install VS Code extension {extension_id}")
            self._require_permission("network.access", f"Download VS Code extension {extension_id}")
            self._require_permission("command.execute", f"Run VS Code extension installer for {extension_id}")
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                check=False,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            self._event(f"VS CODE EXTENSION INSTALLER: {output[-1800:].strip()}")
            if result.returncode:
                raise RuntimeError(f"code --install-extension exited {result.returncode}: {output[-1500:].strip()}")
            self._transition(TaskState.VERIFYING, message=f"VERIFYING VS CODE EXTENSION {extension_id}")
            installed = self._vscode_extension_versions(
                cli,
                authorize_command=self._authorize_command,
            )
            version = installed.get(extension_id.casefold())
            if not version:
                raise RuntimeError(
                    f"The installer returned success, but extension {extension_id} is not listed as installed."
                )
            report = f"VS Code extension {extension_id} installed and verified (version {version})."
            self._transition(TaskState.COMPLETED, message="COMPLETED", result=report)
            return report
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            current = self.snapshot()["state"]
            if current not in {state.value for state in _TERMINAL_STATES}:
                self._transition(
                    TaskState.FAILED,
                    message=f"EXTENSION INSTALLATION FAILED: {exc}",
                    result=str(exc),
                    error=str(exc),
                )
            return f"Extension installation failed: {exc}"

    def _inspect_winget_package(self, winget: str, target: dict[str, Any]) -> dict[str, str]:
        self._require_permission("network.access", f"Inspect official {target['name']} package metadata")
        self._require_permission("command.execute", f"Query winget for {target['name']} package metadata")
        result = subprocess.run(
            [
                winget, "show", "--id", target["package_id"], "--exact",
                "--source", "winget", "--accept-source-agreements",
                "--disable-interactivity",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if result.returncode:
            raise RuntimeError(f"winget show exited {result.returncode}: {output[-1500:].strip()}")
        publisher_match = re.search(r"(?im)^\s*Publisher\s*:\s*(.+?)\s*$", output)
        version_match = re.search(r"(?im)^\s*Version\s*:\s*(.+?)\s*$", output)
        if not publisher_match or not version_match:
            raise RuntimeError("The winget response did not expose a verifiable publisher and version.")
        publisher = publisher_match.group(1).strip()
        if not any(token in publisher.casefold() for token in target["publisher"]):
            raise RuntimeError(f"Publisher mismatch: expected {target['publisher']}, received {publisher!r}.")
        return {
            "publisher": publisher,
            "version": version_match.group(1).strip(),
            "details": output[-4000:],
        }

    def _install_winget_package(
        self,
        winget: str,
        target: dict[str, Any],
        expected_version: str,
    ) -> str:
        process = None
        lines: list[str] = []
        output_queue: queue.Queue[str | None] = queue.Queue()
        try:
            self._transition(TaskState.DOWNLOADING, message=f"DOWNLOADING {target['name']} THROUGH VERIFIED WINGET SOURCE")
            argv = [
                winget, "install", "--id", target["package_id"], "--exact",
                "--source", "winget", "--accept-source-agreements",
                "--accept-package-agreements", "--interactive",
            ]
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            self._event(f"VISIBLE INSTALL COMMAND: {subprocess.list2cmdline(argv)}")
            self._require_permission("install.package", f"Install {target['name']} with winget")
            self._require_permission("network.access", f"Download {target['name']} with winget")
            self._require_permission("command.execute", f"Run winget installer for {target['name']}")
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )

            def consume_output() -> None:
                assert process is not None and process.stdout is not None
                for line in process.stdout:
                    output_queue.put(line.rstrip())
                output_queue.put(None)

            threading.Thread(target=consume_output, daemon=True, name="nebix-winget-output").start()
            install_started = False
            deadline = time.monotonic() + 1800
            while process.poll() is None:
                if self._cancel_event.is_set():
                    process.terminate()
                    raise TaskCancelled("Installation stop requested; any already-open vendor installer must be checked on screen.")
                if time.monotonic() >= deadline:
                    process.terminate()
                    raise RuntimeError("The interactive winget installation exceeded the 30-minute timeout.")
                try:
                    line = output_queue.get(timeout=0.5)
                except queue.Empty:
                    self._check_visible_installer_windows(process.pid, target["name"])
                    continue
                if line is None:
                    continue
                lines.append(line)
                self._event(f"INSTALLER: {line[:600]}")
                if not install_started and re.search(
                    r"starting package install|installing package|installer started",
                    line,
                    re.IGNORECASE,
                ):
                    install_started = True
                    self._transition(TaskState.INSTALLING, message=f"RUNNING VISIBLE {target['name'].upper()} INSTALLER")
                self._check_visible_installer_windows(process.pid, target["name"])
            return_code = process.wait()
            tail = "\n".join(lines[-30:])
            if return_code:
                raise RuntimeError(
                    f"winget install exited with code {return_code}. Output: {tail[-2500:]}"
                )
            self._transition(TaskState.VERIFYING, message=f"VERIFYING {target['name'].upper()} INSTALLATION")
            installed = _installed_software(target, authorize_command=self._authorize_command)
            if not installed:
                raise RuntimeError(
                    f"winget exited successfully, but {target['name']} is still not detected. "
                    "The installation was not verified."
                )
            if expected_version and expected_version.casefold() not in installed["version"].casefold():
                self._event(
                    f"Installed version differs from the offered winget version: "
                    f"offered {expected_version}, detected {installed['version']}."
                )
            launch_result = ""
            if target["name"] in {"Android Studio", "Visual Studio Code"}:
                launch_result = " " + self._launch_application(target, installed)
            report = (
                f"{target['name']} installed and verified. Version: {installed['version']}. "
                f"Path: {installed['path']}.{launch_result}"
            )
            self._task.evidence.append(report)
            self._transition(TaskState.COMPLETED, message="COMPLETED", result=report)
            return report
        except TaskCancelled as exc:
            self._cancel_confirmation(str(exc))
            return str(exc)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            if process and process.poll() is None:
                process.terminate()
            current = self.snapshot()["state"]
            if current not in {state.value for state in _TERMINAL_STATES}:
                self._transition(
                    TaskState.FAILED,
                    message=f"INSTALLATION FAILED: {exc}",
                    result=f"{target['name']} installation was not verified: {exc}",
                    error=str(exc),
                )
            return f"Installation failed: {exc}"

    def _check_visible_installer_windows(self, parent_pid: int, product: str) -> None:
        import psutil
        from pywinauto import Desktop

        process_ids = {parent_pid}
        try:
            process_ids.update(
                child.pid for child in psutil.Process(parent_pid).children(recursive=True)
            )
        except psutil.Error as exc:
            self._event(f"Could not enumerate installer child processes: {exc}")
        visible_choice = False
        for window in Desktop(backend="uia").windows(visible_only=True):
            try:
                if window.process_id() not in process_ids:
                    continue
                title = window.window_text().strip()
                if not title:
                    continue
                texts = [
                    control.window_text().strip()
                    for control in window.descendants(control_type="Text")
                ]
                choice_text = " | ".join(text for text in texts if text)[:800]
                visible_choice = True
                already_waiting = self.snapshot()["state"] == TaskState.WAITING_FOR_USER.value
                if not already_waiting:
                    self._transition(
                        TaskState.WAITING_FOR_USER,
                        message=(
                            f"WAITING FOR YOU IN THE {product.upper()} INSTALLER: "
                            f"{title}. {choice_text}"
                        ),
                    )
                if choice_text and not already_waiting:
                    self._event(f"INSTALLER CHOICES SHOWN: {choice_text}")
            except (AttributeError, OSError, RuntimeError) as exc:
                self._event(f"Installer window changed while being inspected: {exc}")
        if not visible_choice and self.snapshot()["state"] == TaskState.WAITING_FOR_USER.value:
            self._transition(TaskState.INSTALLING, message="INSTALLER WINDOW CLOSED; CONTINUING VERIFICATION")

    def _prepare_repair(
        self,
        root: Path,
        scan: dict[str, Any],
        request: str,
        sources: list[dict[str, str]],
        commands: dict[str, list[dict[str, Any]]],
    ) -> str:
        try:
            self._transition(
                TaskState.EXECUTING,
                message=f"ANALYZING {len(sources)} RELEVANT SOURCE FILE(S)",
            )
            self._check_cancelled()
            self._require_permission("network.access", "Send selected project source to the configured AI provider")
            patch = _generate_patch(request, sources)
            source_paths = {item["file"] for item in sources}
            if any(item["file"] not in source_paths for item in patch):
                raise RuntimeError("The patch references a file that was not included in the reviewed source set.")
            preview = self._patch_preview(root, patch)
            if not preview:
                raise RuntimeError("The proposed patch did not change any project file.")
            if self._request_confirmation is None:
                raise RuntimeError("The HUD confirmation service became unavailable.")
            self._transition(
                TaskState.WAITING_FOR_CONFIRMATION,
                message="WAITING FOR REVIEW AND APPROVAL OF THE EXACT PATCH",
            )
            self._event(preview[:12000])
            approved = self._request_confirmation(
                "Apply reviewed project patch",
                (
                    f"Request: {request[:240]}. Exact patch preview is in the Activity log. "
                    "NEBIX will back up each changed file outside the project, apply only this patch, "
                    "validate syntax, then run the project test command. "
                    "Project code may execute during requested verification."
                ),
                lambda: self._apply_and_verify(root, scan, request, patch, commands),
                on_cancel=lambda: self._cancel_confirmation("The reviewed source patch was declined or expired."),
            )
            with self._lock:
                self._task.result = str(approved)
                self._task.updated_at = time.time()
            if not str(approved).startswith("[CONFIRMATION_PENDING]"):
                self._transition(
                    TaskState.BLOCKED,
                    message="BLOCKED: the exact patch could not be presented for approval.",
                    result=str(approved),
                    error=str(approved),
                )
            return str(approved)
        except TaskCancelled as exc:
            self._cancel_confirmation(str(exc))
            return str(exc)
        except (OSError, RuntimeError, ValueError) as exc:
            current = self.snapshot()["state"]
            if current not in {state.value for state in _TERMINAL_STATES}:
                self._transition(
                    TaskState.FAILED,
                    message=f"FAILED: {exc}",
                    result=f"No code change was applied: {exc}",
                    error=str(exc),
                )
            return f"Patch preparation failed: {exc}"

    @staticmethod
    def _patch_preview(root: Path, patch: list[dict[str, str]]) -> str:
        import difflib

        previews: list[str] = []
        for item in patch:
            target = (root / item["file"]).resolve(strict=True)
            if not target.is_file() or not target.is_relative_to(root.resolve()):
                raise RuntimeError(f"Patch target is outside the project or is not a file: {item['file']}")
            original = target.read_text(encoding="utf-8-sig")
            if original.count(item["search"]) != 1:
                raise RuntimeError(
                    f"Patch context in {item['file']} must match exactly once; it matched {original.count(item['search'])} times."
                )
            updated = original.replace(item["search"], item["replace"], 1)
            previews.extend(difflib.unified_diff(
                original.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{item['file']}",
                tofile=f"b/{item['file']}",
                lineterm="",
            ))
        return "\n".join(previews)

    def _apply_and_verify(
        self,
        root: Path,
        scan: dict[str, Any],
        request: str,
        patch: list[dict[str, str]],
        commands: dict[str, list[dict[str, Any]]],
    ) -> str:
        task_id = self.snapshot()["task_id"]
        self._require_permission("patch.edit", "Apply the reviewed project patch")
        self._require_permission("patch.restore", "Restore original files if patch verification fails")
        backup_dir = _backup_root(task_id)
        changed: dict[Path, tuple[bytes, bool, str]] = {}
        try:
            self._check_cancelled()
            self._transition(TaskState.EXECUTING, message="CREATING FILE BACKUPS")
            backup_dir.mkdir(parents=True, exist_ok=True)
            preview_files: dict[Path, str] = {}
            for item in patch:
                target = (root / item["file"]).resolve(strict=True)
                if not target.is_relative_to(root.resolve()) or target.is_symlink():
                    raise RuntimeError(f"Refusing to modify a path outside the selected project: {item['file']}")
                if item["file"] not in scan["source_files"]:
                    raise RuntimeError(f"Refusing to modify an unscanned source file: {item['file']}")
                raw = target.read_bytes()
                had_bom = raw.startswith(b"\xef\xbb\xbf")
                original = raw.decode("utf-8-sig")
                if original.count(item["search"]) != 1:
                    raise RuntimeError(
                        f"Patch context in {item['file']} no longer matches exactly once; the file may have changed."
                    )
                current_text = preview_files.get(target, original)
                if current_text.count(item["search"]) != 1:
                    raise RuntimeError(
                        f"Patch context in {item['file']} must match exactly once after earlier changes."
                    )
                updated = current_text.replace(item["search"], item["replace"], 1)
                if target not in preview_files:
                    changed[target] = (raw, had_bom, item["file"])
                    backup_path = backup_dir / item["file"]
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup_path)
                    if backup_path.read_bytes() != raw:
                        raise OSError(f"Recovery backup did not match the original file: {item['file']}")
                preview_files[target] = updated
            for target, updated in preview_files.items():
                before, had_bom, _ = changed[target]
                newline = "\r\n" if b"\r\n" in before else "\n"
                serialized = updated.replace("\r\n", "\n").replace("\n", newline)
                encoded = serialized.encode("utf-8")
                if had_bom:
                    encoded = b"\xef\xbb\xbf" + encoded
                temporary = target.with_name(f".{target.name}.{task_id}.tmp")
                self._require_permission("patch.edit", f"Write reviewed patch to {target.name}")
                temporary.write_bytes(encoded)
                temporary.replace(target)
            with self._lock:
                self._task.changed_files = [item[2] for item in changed.values()]
                self._task.evidence.append(f"Backups saved at {backup_dir}.")
            self._event(f"BACKUP VERIFIED {backup_dir}")
            if sys.platform == "win32":
                self._open_editor_for_changes(root, list(changed))
            self._transition(
                TaskState.VERIFYING,
                message="VERIFYING SAVED SOURCE FILES",
            )
            for target, (_, _, relative) in changed.items():
                _validate_source(
                    target,
                    target.read_text(encoding="utf-8-sig"),
                    authorize_command=self._authorize_command,
                )
                self._event(f"SYNTAX VALIDATED {relative}")
            self._transition(TaskState.TESTING, message="RUNNING PROJECT TESTS")
            outcome = self._run_project_commands(root, commands, request)
            with self._lock:
                self._task.commands = outcome["commands"]
                self._task.evidence.extend(outcome["evidence"])
            if outcome["failed"]:
                return self._repair_after_test_failure(
                    root, scan, request, changed, commands, outcome
                )
            if not outcome["verified"]:
                message = (
                    f"Patch was applied and syntax-checked, with recoverable backup at {backup_dir}, "
                    "but no project-defined test/build command was available to verify behavior."
                )
                self._transition(
                    TaskState.BLOCKED,
                    message="BLOCKED: no runnable project verification command.",
                    result=message,
                    error="No project test/build script was detected for the selected project.",
                )
                return message
            self._transition(TaskState.VERIFYING, message="VERIFYING REQUESTED CHANGE")
            report = (
                f"Applied the reviewed patch to {', '.join(self._task.changed_files)}. "
                f"Project test command passed. Backup: {backup_dir}."
            )
            self._task.evidence.append("Approved patch applied; syntax checks and configured verification passed.")
            self._transition(TaskState.COMPLETED, message="COMPLETED", result=report)
            return report
        except TaskCancelled as exc:
            try:
                self._restore_changed(changed)
            except OSError as rollback_error:
                message = f"Cancellation requested, but restoring the original files failed: {rollback_error}"
                self._transition(TaskState.FAILED, message=message, result=message, error=str(rollback_error))
                return message
            self._cancel_confirmation(str(exc))
            return str(exc)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            try:
                self._restore_changed(changed)
            except OSError as rollback_error:
                message = f"Verification failed ({exc}); restoring original files also failed: {rollback_error}"
                current = self.snapshot()["state"]
                if current not in {state.value for state in _TERMINAL_STATES}:
                    self._transition(
                        TaskState.FAILED,
                        message=f"FAILED: {message}",
                        result=message,
                        error=str(rollback_error),
                    )
                return message
            report = f"Verification failed ({exc}); original files were restored."
            current = self.snapshot()["state"]
            if current not in {state.value for state in _TERMINAL_STATES}:
                self._transition(
                    TaskState.FAILED,
                    message=f"FAILED: {report}",
                    result=report,
                    error=str(exc),
                )
            return report

    def _restore_changed(self, changed: dict[Path, tuple[bytes, bool, str]]) -> None:
        for target, (original, _, _) in changed.items():
            self._require_permission("patch.restore", f"Restore original file {target.name}")
            temporary = target.with_name(f".{target.name}.nebix-restore.tmp")
            temporary.write_bytes(original)
            temporary.replace(target)

    def _run_project_commands(
        self,
        root: Path,
        commands: dict[str, list[dict[str, Any]]],
        request: str,
    ) -> dict[str, Any]:
        wants_build = any(word in _normalize(request) for word in (
            "build", "compile", "assemble", "gradle", "बिल्ड",
        ))
        selected = list(commands["test"])
        if wants_build:
            selected.extend(commands["build"])
        if not selected:
            return {
                "commands": [],
                "evidence": ["No project-configured test/build command was detected."],
                "verified": False,
                "failed": False,
            }
        results: list[dict[str, Any]] = []
        evidence: list[str] = []
        for spec in selected:
            self._check_cancelled()
            argv = list(spec["argv"])
            command = self._windows_command(argv)
            self._event(f"RUNNING {spec['label']}: {subprocess.list2cmdline(argv)}")
            self._require_permission("command.execute", f"Run project command: {spec['label']}")
            process = subprocess.Popen(
                command,
                cwd=str(root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + 600
            while process.poll() is None:
                if self._cancel_event.wait(0.2):
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise TaskCancelled("Project verification was cancelled.")
                if time.monotonic() >= deadline:
                    process.kill()
                    process.communicate()
                    raise RuntimeError(f"{spec['label']} exceeded the 10-minute timeout.")
            stdout, stderr = process.communicate()
            result = {
                "phase": "build" if spec in commands["build"] else "test",
                "label": spec["label"],
                "argv": argv,
                "exit_code": process.returncode,
                "stdout": stdout[-10000:],
                "stderr": stderr[-10000:],
            }
            results.append(result)
            output = "\n".join(part for part in (stdout, stderr) if part).strip()
            evidence.append(
                f"{spec['label']} exit code {process.returncode}; "
                f"output: {_redact_source(output)[-2500:] or '(no output)'}"
            )
            self._event(
                f"{'BUILD/TEST PASSED' if process.returncode == 0 else 'BUILD/TEST FAILED'} "
                f"{spec['label']} (exit {process.returncode})"
            )
            if process.returncode:
                break
        return {
            "commands": results,
            "evidence": evidence,
            "verified": bool(results) and all(item["exit_code"] == 0 for item in results),
            "failed": any(item["exit_code"] != 0 for item in results),
        }

    @staticmethod
    def _windows_command(argv: list[str]) -> list[str]:
        if os.name == "nt" and argv and Path(argv[0]).suffix.casefold() in {".bat", ".cmd"}:
            return [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/d",
                "/s",
                "/c",
                subprocess.list2cmdline(argv),
            ]
        return argv

    def _open_editor_for_changes(self, root: Path, changed_paths: list[Path]) -> None:
        code = shutil.which("Code.exe")
        if code is None:
            candidate = Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "Code.exe"
            code = str(candidate) if candidate.is_file() else None
        if not code:
            self._event("VS CODE NOT FOUND; applying the approved patch through atomic file writes.")
            return
        first = changed_paths[0]
        relative = first.relative_to(root)
        self._event(f"OPENING VS CODE AT {relative}")
        self._require_permission("command.execute", f"Open VS Code at {relative}")
        subprocess.Popen(
            [code, "--new-window", str(root), "--goto", f"{first}:1"],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _repair_after_test_failure(
        self,
        root: Path,
        scan: dict[str, Any],
        request: str,
        changed: dict[Path, tuple[bytes, bool, str]],
        commands: dict[str, list[dict[str, Any]]],
        outcome: dict[str, Any],
    ) -> str:
        failed = next(
            (item for item in outcome["commands"] if item["exit_code"] != 0),
            None,
        )
        if failed is None or self._request_confirmation is None:
            raise RuntimeError("Project verification failed and no safe recovery workflow is available.")
        rels = {item[2] for item in changed.values()}
        sources = _relevant_sources(
            root,
            scan,
            request,
            None,
            allowed_files=rels,
        )
        failure = _redact_source(
            (failed.get("stdout", "") + "\n" + failed.get("stderr", ""))[-6000:]
        )
        self._transition(
            TaskState.EXECUTING,
            message=f"INSPECTING {failed['label']} FAILURE FOR A SCOPED CORRECTION",
        )
        self._require_permission("network.access", "Send project failure context to the configured AI provider")
        followup = _generate_patch(
            f"{request}\n\nThe approved patch was applied but {failed['label']} failed with exit code {failed['exit_code']}. "
            f"Actual command output:\n{failure}\nCorrect only the failure caused by the changed files.",
            sources,
        )
        if any(item["file"] not in rels for item in followup):
            raise RuntimeError("The follow-up patch attempted to change a file outside the original approved scope.")
        preview = self._patch_preview(root, followup)
        self._event(f"FOLLOW-UP PATCH PREVIEW\n{preview[:8000]}")
        self._transition(TaskState.WAITING_FOR_CONFIRMATION, message="WAITING FOR FOLLOW-UP PATCH APPROVAL")
        result = self._request_confirmation(
            "Approve verification correction",
            (
                f"{failed['label']} failed (exit {failed['exit_code']}). A correction limited to the previously "
                "approved file(s) is shown in Activity. Approve this correction to retry verification."
            ),
            lambda: self._apply_followup(root, changed, followup, commands, request),
            on_cancel=lambda: self._cancel_confirmation(
                "The verification correction was declined or expired; the previously approved changes remain with backup."
            ),
        )
        with self._lock:
            self._task.result = str(result)
        if not str(result).startswith("[CONFIRMATION_PENDING]"):
            self._transition(
                TaskState.BLOCKED,
                message="BLOCKED: follow-up patch was not approved.",
                result=str(result),
                error=str(result),
            )
        return str(result)

    def _apply_followup(
        self,
        root: Path,
        original: dict[Path, tuple[bytes, bool, str]],
        patch: list[dict[str, str]],
        commands: dict[str, list[dict[str, Any]]],
        request: str,
    ) -> str:
        try:
            self._transition(TaskState.EXECUTING, message="APPLYING APPROVED FOLLOW-UP PATCH")
            for item in patch:
                target = (root / item["file"]).resolve(strict=True)
                if target not in original:
                    raise RuntimeError(f"Follow-up patch escaped the approved files: {item['file']}")
                content = target.read_text(encoding="utf-8-sig")
                if content.count(item["search"]) != 1:
                    raise RuntimeError(f"Follow-up patch context in {item['file']} did not match exactly once.")
                self._require_permission("patch.edit", f"Apply follow-up patch to {target.name}")
                self._require_permission("patch.restore", "Restore original files if follow-up verification fails")
                target.write_text(content.replace(item["search"], item["replace"], 1), encoding="utf-8")
                _validate_source(
                    target,
                    target.read_text(encoding="utf-8-sig"),
                    authorize_command=self._authorize_command,
                )
            self._transition(TaskState.TESTING, message="RERUNNING PROJECT TESTS AFTER FOLLOW-UP PATCH")
            outcome = self._run_project_commands(root, commands, request)
            with self._lock:
                self._task.commands = outcome["commands"]
                self._task.evidence.extend(outcome["evidence"])
            if not outcome["verified"]:
                output = "; ".join(outcome["evidence"][-2:])
                raise RuntimeError(
                    "Verification still fails after one scoped follow-up patch; "
                    f"original approved files were restored. {output}"
                )
            backup = _backup_root(self.snapshot()["task_id"])
            report = (
                f"Applied and verified the scoped repair to {', '.join(self._task.changed_files)}. "
                f"Project tests pass. Backup: {backup}."
            )
            self._transition(TaskState.VERIFYING, message="VERIFYING FOLLOW-UP REPAIR")
            self._transition(TaskState.COMPLETED, message="COMPLETED", result=report)
            return report
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            self._restore_changed(original)
            self._transition(
                TaskState.FAILED,
                message=f"FAILED AFTER FOLLOW-UP PATCH: {exc}",
                result=f"Follow-up verification failed; original files were restored. {exc}",
                error=str(exc),
            )
            return str(exc)

    def cancel(self) -> bool:
        with self._lock:
            if self._task.state == TaskState.IDLE or self._task.state in _TERMINAL_STATES:
                return False
            self._cancel_event.set()
            self._task.state = TaskState.CANCELLED
            self._task.updated_at = time.time()
            self._task.result = "Task cancelled by the user."
        self._event(f"[ENGINEERING:{self._task.task_id}] CANCELLED BY USER")
        self._set_ui_state(TaskState.CANCELLED.value, "Engineering task cancelled.")
        return True

    @staticmethod
    def _findings(scan: dict[str, Any]) -> list[str]:
        findings = []
        if scan["diagnostics"]:
            findings.extend(
                f"{item['file']}:{item.get('line') or 1}: {item['message']}"
                for item in scan["diagnostics"]
            )
        if scan["scan_errors"]:
            findings.extend(f"Could not inspect {item}" for item in scan["scan_errors"])
        if scan["truncated"]:
            findings.append(f"Scan capped at {_MAX_FILES} files.")
        return findings

    @staticmethod
    def _scan_report(scan: dict[str, Any]) -> str:
        diagnostics = scan["diagnostics"]
        types = ", ".join(scan["project_types"])
        lines = [
            f"Project scan completed for {scan['path']}.",
            f"Type: {types}. Files: {scan['file_count']} total, {scan['source_file_count']} source.",
            f"Entry points: {', '.join(scan['entrypoints']) or 'none identified'}.",
            f"Dependency/build files: {', '.join(scan['manifests']) or 'none identified'}.",
            f"Tests: {len(scan['test_files'])} candidate test files detected; tests were not executed.",
            f"Bounded static syntax checks run: {scan['syntax_checks']}.",
            f"Available tools on PATH: {', '.join(scan['available_tools']) or 'none detected'}.",
        ]
        if scan["vscode_extension_recommendations"]:
            lines.append(
                "Project-declared VS Code recommendations: "
                + ", ".join(scan["vscode_extension_recommendations"])
                + "."
            )
            if scan.get("vscode_extension_missing") is not None:
                lines.append(
                    "Missing VS Code recommendations: "
                    + (", ".join(scan["vscode_extension_missing"]) or "none")
                    + "."
                )
        if diagnostics:
            lines.append(f"Static diagnostics ({len(diagnostics)}):")
            lines.extend(f"- {item['file']}:{item.get('line') or 1}: {item['message']}" for item in diagnostics)
        else:
            lines.append("No Python-source or recognized JSON-manifest syntax errors were found.")
        if scan["scan_errors"]:
            lines.append(f"Some files could not be read: {len(scan['scan_errors'])}.")
        if scan["truncated"]:
            lines.append(f"Inventory was capped at {_MAX_FILES} files.")
        if scan["syntax_checks_truncated"]:
            lines.append(
                f"Static checks were capped at {_MAX_SYNTAX_FILES} files or "
                f"{_MAX_SYNTAX_BYTES // (1024 * 1024)} MiB."
            )
        lines.append("No project files were modified; no tests, installers, or project commands were run.")
        return "\n".join(lines)

    @staticmethod
    def _diagnostic_report(scan: dict[str, Any]) -> str:
        if not scan["diagnostics"]:
            return (
                f"I scanned {scan['path']} and found no supported static syntax diagnostics "
                "in Python source or recognized JSON files. I have not established why the "
                "reported behavior fails, and I did not edit files or run project code."
            )
        detail = "\n".join(
            f"- {item['file']}:{item.get('line') or 1}: {item['message']}"
            for item in scan["diagnostics"]
        )
        return (
            f"I scanned {scan['path']} and found these static diagnostics:\n{detail}\n"
            "I did not edit files. The edit/patch confirmation-and-apply workflow is not "
            "implemented yet, so this task is BLOCKED before modification."
        )

    def _open_ide(self, project_path: str, intent: str) -> dict[str, Any]:
        root = Path(project_path)
        if intent == "open_vscode":
            candidates = [
                shutil.which("Code.exe"),
                str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe"),
                r"C:\Program Files\Microsoft VS Code\Code.exe",
                r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
            ]
            app_name = "Visual Studio Code"
        else:
            candidates = [
                shutil.which("studio64.exe"),
                r"C:\Program Files\Android\Android Studio\bin\studio64.exe",
                str(Path.home() / "AppData/Local/Programs/Android Studio/bin/studio64.exe"),
            ]
            app_name = "Android Studio"

        executable = next(
            (
                Path(candidate)
                for candidate in candidates
                if candidate and Path(candidate).is_file()
            ),
            None,
        )
        if executable is None:
            return {
                "ok": False,
                "message": f"{app_name} was not found in the supported install locations; nothing was downloaded or installed.",
            }
        self._require_permission("command.execute", f"Open {app_name} at {root}")
        process = subprocess.Popen(
            [str(executable), str(root)],
            cwd=str(root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        expected_app = (
            ("android studio",)
            if intent == "open_android_studio"
            else ("visual studio code", "vscode")
        )
        deadline = time.monotonic() + 10.0
        title = ""
        while time.monotonic() < deadline:
            title = EngineeringAgent._foreground_window_title()
            lowered_title = title.casefold()
            if root.name.casefold() in lowered_title and any(
                token in lowered_title for token in expected_app
            ):
                return {
                    "ok": True,
                    "verified": True,
                    "message": f"{app_name} project window is visible: {title}",
                    "pid": process.pid,
                    "executable": str(executable),
                    "window_title": title,
                }
            if process.poll() is not None and process.returncode not in (0, None):
                break
            time.sleep(0.5)

        if process.poll() is not None and process.returncode not in (0, None):
            return {
                "ok": False,
                "message": f"{app_name} exited during launch with code {process.returncode}.",
            }
        return {
            "ok": True,
            "verified": False,
            "message": (
                f"{app_name} launch was requested (PID {process.pid}), but the visible "
                f"window title {title!r} did not confirm that the project opened."
            ),
            "pid": process.pid,
            "executable": str(executable),
            "window_title": title,
        }

    @staticmethod
    def _foreground_window_title() -> str:
        if os.name != "nt":
            return ""
        try:
            import ctypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
            user32.GetWindowTextLengthW.restype = ctypes.c_int
            user32.GetWindowTextW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_int,
            ]
            user32.GetWindowTextW.restype = ctypes.c_int
            window = user32.GetForegroundWindow()
            if not window:
                return ""
            length = user32.GetWindowTextLengthW(window)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(window, title, len(title))
            return title.value
        except (AttributeError, OSError, ValueError):
            return ""

    @staticmethod
    def _is_status_question(text: str) -> bool:
        normalized = _normalize(text)
        return any(phrase in normalized for phrase in (
            "what are you doing", "which file are you editing", "what error did you find",
            "what did you find", "what remains", "did the build pass",
            "where is the error", "which file has the problem",
            "which file has a problem",
            "तिमी के गर्दै", "के गर्दैछौ",
        ))

    def _status_answer(self, question: str) -> str:
        state = self.snapshot()
        if self._is_file_question(_normalize(question)) and not state["current_file"]:
            return "I am not editing a file. The current engineering workflow only inventories and diagnoses supported static errors; it does not change project files."
        if state["state"] == TaskState.IDLE.value:
            return "No engineering task is currently running."
        task_state = state["state"].replace("_", " ").lower()
        response = f"The current engineering task is {task_state}."
        if state["project_path"]:
            response += f" Project: {state['project_path']}."
        if state["current_file"]:
            response += f" Current file: {state['current_file']}."
        if state["findings"]:
            response += f" Findings: {'; '.join(state['findings'][:5])}."
        if state["error"]:
            response += f" Blocker/error: {state['error']}"
        elif state["result"]:
            response += f" Latest result: {state['result']}"
        return response

    @staticmethod
    def _is_file_question(text: str) -> bool:
        return any(phrase in text for phrase in (
            "which file are you editing",
            "which file are you changing",
            "कुन file",
            "कुन फाइल",
        ))

    def _response(self, ok: bool) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "intent": "ENGINEERING_TASK",
            "ok": ok,
            "message": snapshot["result"],
            "state": snapshot,
        }
