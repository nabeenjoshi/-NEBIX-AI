"""Windows Excel automation through a dedicated, COM-initialized worker thread."""
from __future__ import annotations

import atexit
import json
import os
import queue
import re
import threading
from pathlib import Path
from typing import Any

_ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".xlsb"}
_FILE_FORMATS = {".xlsx": 51, ".xlsm": 52, ".xls": 56, ".xlsb": 50}
_CELL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)$")
_RANGE_RE = re.compile(r"^(\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)(?::(\$?[A-Za-z]{1,3}\$?[1-9][0-9]*))?$")
_MAX_ROW = 1_048_576
_MAX_COLUMN = 16_384
_INVALID_SHEET_CHARS = set("[]:*?/\\")


def _is_windows() -> bool:
    return os.name == "nt"


def _registered_excel_progid() -> bool:
    if not _is_windows():
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CLSID"):
            return True
    except (ImportError, OSError):
        return False


def _excel_executable_paths() -> list[Path]:
    roots = [
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("PROGRAMW6432", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    paths = []
    for root in filter(None, roots):
        base = Path(root)
        paths.extend((
            base / "Microsoft Office" / "root" / "Office16" / "EXCEL.EXE",
            base / "Microsoft Office" / "Office16" / "EXCEL.EXE",
            base / "Microsoft Office" / "Office15" / "EXCEL.EXE",
            base / "Microsoft Office" / "Office14" / "EXCEL.EXE",
            base / "Microsoft" / "WindowsApps" / "EXCEL.EXE",
        ))
    return paths


def _excel_installed() -> bool:
    return _registered_excel_progid() or any(path.is_file() for path in _excel_executable_paths())


def _installation_message() -> str:
    if not _is_windows():
        return "Microsoft Excel automation is available only on Windows."
    if not _excel_installed():
        return "Microsoft Excel is not detected (no registered Excel.Application ProgID or Excel executable)."
    return "Microsoft Excel is detected; automation will be attempted when an action is run."


def _path(raw: Any, *, must_exist: bool) -> Path:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise ValueError("A valid workbook path is required.")
    result = Path(raw).expanduser().resolve()
    if result.suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise ValueError("Workbook paths must use .xlsx, .xlsm, .xls, or .xlsb.")
    if must_exist and (not result.is_file()):
        raise ValueError(f"Workbook file does not exist: {result}")
    if not must_exist and result.exists() and not result.is_file():
        raise ValueError(f"Save path is not a file: {result}")
    return result


def _column_number(label: str) -> int:
    result = 0
    for character in label.upper():
        result = result * 26 + ord(character) - ord("A") + 1
    return result


def _cell_coordinates(cell: str) -> tuple[int, int]:
    match = _CELL_RE.fullmatch(cell)
    if not match:
        raise ValueError(f"Invalid Excel cell address: {cell!r}")
    column = _column_number(match.group(1))
    row = int(match.group(2))
    if column > _MAX_COLUMN or row > _MAX_ROW:
        raise ValueError(f"Cell address is outside Excel's supported range: {cell!r}")
    return row, column


def _validated_range(address: Any) -> tuple[str, int, int]:
    if not isinstance(address, str):
        raise ValueError("A single-cell or rectangular A1 range is required.")
    match = _RANGE_RE.fullmatch(address.strip())
    if not match:
        raise ValueError(f"Invalid Excel range: {address!r}")
    first_row, first_col = _cell_coordinates(match.group(1).replace("$", ""))
    last_cell = (match.group(2) or match.group(1)).replace("$", "")
    last_row, last_col = _cell_coordinates(last_cell)
    if last_row < first_row or last_col < first_col:
        raise ValueError("Excel ranges must run from the upper-left cell to the lower-right cell.")
    return f"{match.group(1)}:{match.group(2)}" if match.group(2) else match.group(1), (
        last_row - first_row + 1
    ), last_col - first_col + 1


def _matrix(value: Any, rows: int, columns: int, label: str) -> tuple[tuple[Any, ...], ...]:
    if not isinstance(value, list):
        if rows == columns == 1:
            return ((value,),)
        raise ValueError(f"{label} for a multi-cell range must be a two-dimensional array matching the range.")
    if rows == columns == 1 and (not value or not isinstance(value[0], list)):
        if len(value) == 1:
            return ((value[0],),)
    if rows == 1 and value and not isinstance(value[0], list):
        value = [value]
    elif columns == 1 and value and not isinstance(value[0], list):
        value = [[item] for item in value]
    if len(value) != rows or any(not isinstance(row, list) or len(row) != columns for row in value):
        raise ValueError(f"{label} dimensions must exactly match the selected range ({rows} row(s) × {columns} column(s)).")
    return tuple(tuple(row) for row in value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _workbook_key(workbook: Any) -> str:
    try:
        full_name = str(workbook.FullName)
        if full_name:
            return full_name.casefold()
    except Exception:
        pass
    return str(workbook.Name).casefold()


def _resolve_workbook(app: Any, requested: Any = "") -> Any:
    if requested is None:
        requested = ""
    if not isinstance(requested, str):
        raise ValueError("Workbook must be a workbook name or full path.")
    books = app.Workbooks
    if requested.strip():
        wanted = requested.strip().casefold()
        matches = []
        for workbook in books:
            try:
                if wanted in {str(workbook.Name).casefold(), str(workbook.FullName).casefold()}:
                    matches.append(workbook)
            except Exception:
                continue
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"Workbook name is ambiguous; use its full path: {requested}")
        raise ValueError(f"Workbook is not open in Excel: {requested}")
    try:
        workbook = app.ActiveWorkbook
    except Exception:
        workbook = None
    if workbook is None:
        raise ValueError("No active workbook. Open or create a workbook first.")
    return workbook


def _resolve_sheet(workbook: Any, requested: Any = "") -> Any:
    if not isinstance(requested, str):
        raise ValueError("Worksheet must be a worksheet name.")
    sheets = workbook.Worksheets
    if requested.strip():
        wanted = requested.strip().casefold()
        for sheet in sheets:
            if str(sheet.Name).casefold() == wanted:
                return sheet
        raise ValueError(f"Worksheet is not in this workbook: {requested}")
    try:
        sheet = workbook.ActiveSheet
        active_name = str(sheet.Name).casefold()
        if any(str(candidate.Name).casefold() == active_name for candidate in sheets):
            return sheet
    except Exception:
        pass
    if sheets.Count:
        return sheets.Item(1)
    raise ValueError("This workbook has no worksheets.")


def _sheet_name(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ValueError("A worksheet name is required.")
    name = raw.strip()
    if not name or len(name) > 31 or any(char in _INVALID_SHEET_CHARS for char in name):
        raise ValueError("Worksheet names must be 1–31 characters and cannot contain []:*?/\\.")
    if name.startswith("'") or name.endswith("'"):
        raise ValueError("Worksheet names cannot begin or end with an apostrophe.")
    return name


def _find_open_workbook(app: Any, full_path: Path) -> Any | None:
    wanted = str(full_path).casefold()
    for workbook in app.Workbooks:
        try:
            if str(workbook.FullName).casefold() == wanted:
                return workbook
        except Exception:
            continue
    return None


def _verify_saved(path: Path) -> None:
    try:
        if not path.is_file() or path.stat().st_size == 0:
            raise OSError("Excel returned from save but the target file is missing or empty.")
    except OSError as error:
        raise RuntimeError(f"Save could not be verified at {path}: {error}") from error


def _set_workbook_format(workbook: Any, target: Path) -> None:
    extension = target.suffix.lower()
    if extension not in _FILE_FORMATS:
        raise ValueError("Save path must use .xlsx, .xlsm, .xls, or .xlsb.")
    workbook.SaveAs(str(target), FileFormat=_FILE_FORMATS[extension])


def _apply_action(app: Any, request: dict, owned: set[str]) -> str:
    action = str(request.get("action", "")).strip().lower()

    if action == "list_workbooks":
        names = [str(book.Name) for book in app.Workbooks]
        return json.dumps({"workbooks": names}, ensure_ascii=False)
    if action == "create":
        workbook = app.Workbooks.Add()
        owned.add(_workbook_key(workbook))
        return f"Created workbook {workbook.Name}."
    if action == "open":
        target = _path(request.get("path"), must_exist=True)
        workbook = _find_open_workbook(app, target)
        if workbook is None:
            original_security = app.AutomationSecurity
            try:
                app.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
                workbook = app.Workbooks.Open(
                    str(target), UpdateLinks=0, ReadOnly=False, AddToMru=False
                )
            finally:
                app.AutomationSecurity = original_security
            owned.add(_workbook_key(workbook))
        return f"Opened workbook {workbook.Name}."

    if action == "close":
        workbook = _resolve_workbook(app, request.get("workbook", ""))
        key = _workbook_key(workbook)
        is_owned = key in owned
        if not is_owned and request.get("confirm_close") is not True:
            raise PermissionError("This action did not open or create that workbook. Set confirm_close=true to explicitly request closing it.")
        if getattr(workbook, "Saved", True) is not True:
            if request.get("discard_changes") is True:
                pass
            elif request.get("save_changes") is True:
                target = _path(str(workbook.FullName), must_exist=True)
                if request.get("confirm_overwrite") is not True:
                    raise PermissionError("Saving modified workbook data requires confirm_overwrite=true.")
                workbook.Save()
                _verify_saved(target)
            else:
                raise PermissionError("Workbook has unsaved changes. Set save_changes=true with confirm_overwrite=true, or explicitly set discard_changes=true.")
        workbook.Close(SaveChanges=False)
        owned.discard(key)
        return f"Closed workbook {workbook.Name}."

    if action in {"save", "save_as"}:
        workbook = _resolve_workbook(app, request.get("workbook", ""))
        if action == "save":
            target = _path(str(workbook.FullName), must_exist=True)
            if request.get("confirm_overwrite") is not True:
                raise PermissionError("Saving to the workbook's existing file requires confirm_overwrite=true.")
            workbook.Save()
        else:
            target = _path(request.get("path"), must_exist=False)
            replacing_file = target.exists()
            if replacing_file and request.get("confirm_overwrite") is not True:
                raise PermissionError(f"Save target already exists; set confirm_overwrite=true to replace it: {target}")
            previous_alerts = app.DisplayAlerts if replacing_file else None
            try:
                if replacing_file:
                    app.DisplayAlerts = False
                _set_workbook_format(workbook, target)
            finally:
                if replacing_file:
                    app.DisplayAlerts = previous_alerts
            owned.add(_workbook_key(workbook))
        _verify_saved(target)
        return f"Saved workbook to {target} (verified on disk)."

    if action == "list_sheets":
        workbook = _resolve_workbook(app, request.get("workbook", ""))
        return json.dumps({"worksheets": [str(sheet.Name) for sheet in workbook.Worksheets]}, ensure_ascii=False)

    if action in {"inspect", "read_range", "read_formulas", "write_range", "write_formulas", "format"}:
        workbook = _resolve_workbook(app, request.get("workbook", ""))
        sheet = _resolve_sheet(workbook, request.get("sheet", ""))
        if action == "inspect" and not request.get("range"):
            used = sheet.UsedRange
            return json.dumps({
                "workbook": str(workbook.Name),
                "worksheet": str(sheet.Name),
                "used_range": str(used.Address),
                "rows": int(used.Rows.Count),
                "columns": int(used.Columns.Count),
            }, ensure_ascii=False)
        address, rows, columns = _validated_range(request.get("range"))
        selected = sheet.Range(address)
        if action in {"read_range", "read_formulas", "inspect"}:
            member = "Formula" if action == "read_formulas" else "Value2"
            value = getattr(selected, member)
            return json.dumps({
                "workbook": str(workbook.Name),
                "worksheet": str(sheet.Name),
                "range": address,
                "formulas" if member == "Formula" else "values": _json_safe(value),
            }, ensure_ascii=False)
        if action in {"write_range", "write_formulas"}:
            field = "formulas" if action == "write_formulas" else "values"
            if field not in request:
                raise ValueError(f"{field} is required for {action}.")
            matrix = _matrix(request[field], rows, columns, field)
            if action == "write_formulas":
                if any(not isinstance(value, str) or not value.startswith("=") for row in matrix for value in row):
                    raise ValueError("Every formula must be a string beginning with '='.")
                selected.Formula = matrix[0][0] if rows == columns == 1 else matrix
            else:
                if any(isinstance(value, str) and value.startswith("=") for row in matrix for value in row):
                    raise ValueError("Formula-like content must use write_formulas; it cannot be written as ordinary cell data.")
                selected.Value = matrix[0][0] if rows == columns == 1 else matrix
            return f"Wrote {rows} row(s) × {columns} column(s) to {sheet.Name}!{address}."
        formatting = request.get("formatting")
        if not isinstance(formatting, dict) or not formatting:
            raise ValueError("A non-empty formatting object is required.")
        allowed = {"bold", "italic", "number_format", "fill_color", "font_color", "horizontal_alignment"}
        unknown = set(formatting) - allowed
        if unknown:
            raise ValueError(f"Unsupported formatting option(s): {', '.join(sorted(unknown))}")
        font = selected.Font
        if "bold" in formatting:
            if not isinstance(formatting["bold"], bool):
                raise ValueError("bold must be true or false.")
        if "italic" in formatting:
            if not isinstance(formatting["italic"], bool):
                raise ValueError("italic must be true or false.")
        if "number_format" in formatting:
            if not isinstance(formatting["number_format"], str) or len(formatting["number_format"]) > 80:
                raise ValueError("number_format must be a string of at most 80 characters.")
        colors = {}
        for field in ("fill_color", "font_color"):
            if field in formatting:
                color = formatting[field]
                if not isinstance(color, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
                    raise ValueError(f"{field} must be a six-digit #RRGGBB color.")
                red, green, blue = (int(color[i:i + 2], 16) for i in (1, 3, 5))
                colors[field] = red | (green << 8) | (blue << 16)
        alignment = None
        if "horizontal_alignment" in formatting:
            alignments = {"left": -4131, "center": -4108, "right": -4152}
            alignment_name = formatting["horizontal_alignment"]
            if alignment_name not in alignments:
                raise ValueError("horizontal_alignment must be left, center, or right.")
            alignment = alignments[alignment_name]
        if "bold" in formatting:
            font.Bold = formatting["bold"]
        if "italic" in formatting:
            font.Italic = formatting["italic"]
        if "number_format" in formatting:
            selected.NumberFormat = formatting["number_format"]
        if "fill_color" in colors:
            selected.Interior.Color = colors["fill_color"]
        if "font_color" in colors:
            font.Color = colors["font_color"]
        if alignment is not None:
            selected.HorizontalAlignment = alignment
        return f"Formatted {sheet.Name}!{address}."

    if action in {"add_sheet", "rename_sheet"}:
        workbook = _resolve_workbook(app, request.get("workbook", ""))
        name = _sheet_name(request.get("name"))
        if action == "add_sheet":
            if any(str(sheet.Name).casefold() == name.casefold() for sheet in workbook.Worksheets):
                raise ValueError(f"Worksheet already exists: {name}")
            sheet = workbook.Worksheets.Add()
            sheet.Name = name
            return f"Added worksheet {name}."
        sheet = _resolve_sheet(workbook, request.get("sheet", ""))
        current_name = str(sheet.Name).casefold()
        if any(str(candidate.Name).casefold() == name.casefold()
               and str(candidate.Name).casefold() != current_name
               for candidate in workbook.Worksheets):
            raise ValueError(f"Worksheet already exists: {name}")
        sheet.Name = name
        return f"Renamed worksheet to {name}."

    raise ValueError(f"Unknown Excel action: {action or '(empty)'}")


class _ExcelWorker:
    """Owns all Excel COM proxies and uses them only on its initialized thread."""

    def __init__(self) -> None:
        self._requests: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._startup_error: Exception | None = None
        self._thread = threading.Thread(target=self._run, name="NEBIX-Excel-COM", daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run(self) -> None:
        pythoncom = None
        initialized = False
        try:
            import pythoncom as com_module
            pythoncom = com_module
            pythoncom.CoInitialize()
            initialized = True
        except Exception as error:
            self._startup_error = error
        self._ready.set()
        app = None
        owned: set[str] = set()
        while True:
            item = self._requests.get()
            if item is None:
                break
            request, result = item
            try:
                if self._startup_error is not None:
                    raise RuntimeError(f"pywin32 COM initialization failed: {self._startup_error}")
                action = str(request.get("action", "")).strip().lower()
                if action == "attach":
                    if app is None:
                        import win32com.client
                        app = win32com.client.GetActiveObject("Excel.Application")
                    answer = f"Attached to Excel ({app.Workbooks.Count} open workbook(s))."
                else:
                    if app is None:
                        import win32com.client
                        try:
                            app = win32com.client.GetActiveObject("Excel.Application")
                        except Exception:
                            if action not in {"open", "create"}:
                                raise RuntimeError(
                                    "Excel is not running. Attach to an existing instance, or open/create a workbook."
                                )
                            app = win32com.client.DispatchEx("Excel.Application")
                            app.Visible = True
                    answer = _apply_action(app, request, owned)
                result.put((True, answer))
            except Exception as error:
                result.put((False, error))
        app = None
        owned.clear()
        if pythoncom is not None and initialized:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def run(self, request: dict) -> str:
        response: queue.Queue = queue.Queue(maxsize=1)
        self._requests.put((request, response))
        success, value = response.get()
        if success:
            return str(value)
        if isinstance(value, PermissionError):
            return f"Excel action was not performed: {value}"
        if isinstance(value, (ValueError, FileNotFoundError)):
            return f"Excel action could not be performed: {value}"
        return f"Excel automation failed: {value}"

    def shutdown(self) -> None:
        if self._thread.is_alive():
            self._requests.put(None)
            self._thread.join(timeout=2)


_worker: _ExcelWorker | None = None
_worker_lock = threading.Lock()


def _get_worker() -> _ExcelWorker:
    global _worker
    with _worker_lock:
        if _worker is None or not _worker._thread.is_alive():
            _worker = _ExcelWorker()
        return _worker


def _shutdown_worker() -> None:
    global _worker
    with _worker_lock:
        worker, _worker = _worker, None
    if worker is not None:
        worker.shutdown()


atexit.register(_shutdown_worker)


def excel_control(parameters: dict, player=None) -> str:
    """Control installed Microsoft Excel; the handler never substitutes a fake workbook."""
    parameters = parameters or {}
    action = str(parameters.get("action", "")).strip().lower()
    if player is not None:
        try:
            player.write_log(f"[Excel] {action or 'action'}")
        except Exception:
            pass
    if action == "status":
        return _installation_message()
    allowed_actions = set(TOOL["parameters"]["properties"]["action"]["enum"])
    if action not in allowed_actions:
        return f"Excel action could not be performed: unknown action {action or '(empty)'}."
    if not _is_windows():
        return "Excel automation is unavailable: Microsoft Excel COM automation requires Windows."
    return _get_worker().run(parameters)


TOOL = {
    "name": "excel_control",
    "description": (
        "Use natural-language requests to control real Microsoft Excel workbooks on Windows: "
        "attach, create or open workbooks, list workbooks and worksheets, inspect/read/write "
        "cell ranges and formulas, add or rename worksheets, apply basic formatting, save/save-as, "
        "and close workbooks. Excel must be installed. Existing-file saves and save-as overwrites "
        "require confirm_overwrite=true; no workbook is silently overwritten or discarded."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": [
                    "status", "attach", "open", "create", "list_workbooks", "list_sheets",
                    "inspect", "read_range", "read_formulas", "write_range", "write_formulas",
                    "add_sheet", "rename_sheet", "format", "save", "save_as", "close",
                ],
                "description": "Excel operation to perform.",
            },
            "path": {"type": "STRING", "description": "Workbook path for open or save_as."},
            "workbook": {"type": "STRING", "description": "Open workbook name or full path; defaults to active workbook."},
            "sheet": {"type": "STRING", "description": "Worksheet name; defaults to active worksheet."},
            "range": {"type": "STRING", "description": "A single A1 cell or rectangular A1 range."},
            "values": {
                "type": "ARRAY",
                "items": {
                    "anyOf": [
                        {"type": "STRING"},
                        {"type": "NUMBER"},
                        {"type": "INTEGER"},
                        {"type": "BOOLEAN"},
                        {
                            "type": "ARRAY",
                            "items": {
                                "anyOf": [
                                    {"type": "STRING"},
                                    {"type": "NUMBER"},
                                    {"type": "INTEGER"},
                                    {"type": "BOOLEAN"},
                                ]
                            },
                        },
                    ]
                },
                "description": "Single-cell value array or row-major 2-D values matching the selected range exactly.",
            },
            "formulas": {
                "type": "ARRAY",
                "items": {
                    "anyOf": [
                        {"type": "STRING"},
                        {"type": "ARRAY", "items": {"type": "STRING"}},
                    ]
                },
                "description": "Formula string array or 2-D formula array matching the selected range exactly.",
            },
            "name": {"type": "STRING", "description": "New worksheet name."},
            "formatting": {"type": "OBJECT", "description": "Basic formatting: bold, italic, number_format, fill_color/font_color (#RRGGBB), or horizontal_alignment."},
            "confirm_overwrite": {"type": "BOOLEAN", "description": "Explicit confirmation to replace an existing workbook file."},
            "confirm_close": {"type": "BOOLEAN", "description": "Explicit request to close a workbook not opened/created by this action."},
            "save_changes": {"type": "BOOLEAN", "description": "Explicitly save unsaved workbook changes before closing."},
            "discard_changes": {"type": "BOOLEAN", "description": "Explicitly discard unsaved workbook changes when closing."},
        },
        "required": ["action"],
    },
    "handler": excel_control,
}
