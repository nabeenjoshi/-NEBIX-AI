"""Temporary, click-through Windows overlay for active NEBIX control."""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

_WS_POPUP = 0x80000000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_HWND_TOPMOST = wintypes.HWND(-1)
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_SW_SHOWNOACTIVATE = 4
_LWA_COLORKEY = 0x00000001
_LWA_ALPHA = 0x00000002
_WM_PAINT = 0x000F
_WM_CLOSE = 0x0010
_WM_DESTROY = 0x0002
_WM_TIMER = 0x0113
_PM_REMOVE = 0x0001
_PS_SOLID = 0
_TRANSPARENT = 1
_COLOR_KEY = 0x00030201
_CLASS_NAME = "NEBIX.DesktopControlIndicator"


_POINT = wintypes.POINT


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD), ("pt", _POINT),
    ]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
    ]


class _DesktopIndicator:
    """Owns one native overlay window and leaves the user's cursor settings alone."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._startup_ok = False
        self._startup_error = ""
        self._hwnd = None
        self._window_proc = _WNDPROC(self._dispatch)
        self._user32 = None
        self._gdi32 = None
        self._width = self._height = 0
        self._last_cursor_point: tuple[int, int] | None = None

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return True
        self._ready.clear()
        self._stopping.clear()
        self._startup_ok = False
        self._startup_error = ""
        self._thread = threading.Thread(
            target=self._run, name="NEBIX-Desktop-Indicator", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(1.5) or not self._startup_ok:
            self.stop()
            return False
        return True

    def stop(self) -> None:
        self._stopping.set()
        if self._hwnd and self._user32:
            self._user32.PostMessageW(self._hwnd, _WM_CLOSE, 0, 0)
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._thread = None
        self._hwnd = None

    def _run(self) -> None:
        from core.windows_display import per_monitor_dpi_awareness

        with per_monitor_dpi_awareness():
            self._run_dpi_aware()

    def _run_dpi_aware(self) -> None:
        try:
            # Keep these function objects separate from libraries already held
            # by PyAutoGUI; changing a shared ctypes prototype can break input.
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            user32, gdi32 = self._user32, self._gdi32
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32.GetSystemMetrics.argtypes = [ctypes.c_int]
            user32.GetSystemMetrics.restype = ctypes.c_int
            user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
            user32.RegisterClassW.restype = wintypes.ATOM
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.SetLayeredWindowAttributes.argtypes = [
                wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD,
            ]
            user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.UpdateWindow.argtypes = [wintypes.HWND]
            user32.UpdateWindow.restype = wintypes.BOOL
            user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
            user32.SetTimer.restype = ctypes.c_size_t
            user32.GetMessageW.argtypes = [ctypes.POINTER(_MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user32.GetMessageW.restype = ctypes.c_int
            user32.TranslateMessage.argtypes = [ctypes.POINTER(_MSG)]
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(_MSG)]
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            ]
            user32.DefWindowProcW.restype = ctypes.c_ssize_t
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostQuitMessage.argtypes = [ctypes.c_int]
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL
            user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT), wintypes.BOOL]
            user32.InvalidateRect.restype = wintypes.BOOL
            user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
            user32.KillTimer.restype = wintypes.BOOL
            user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
            user32.BeginPaint.restype = wintypes.HDC
            user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(_PAINTSTRUCT)]
            user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
            user32.FillRect.restype = ctypes.c_int
            user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(_POINT)]
            user32.ScreenToClient.restype = wintypes.BOOL
            gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
            gdi32.CreatePen.restype = wintypes.HPEN
            gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
            gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
            gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
            gdi32.SelectObject.restype = wintypes.HGDIOBJ
            gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
            gdi32.DeleteObject.restype = wintypes.BOOL
            gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
            gdi32.GetStockObject.argtypes = [ctypes.c_int]
            gdi32.GetStockObject.restype = wintypes.HGDIOBJ
            gdi32.Rectangle.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
            gdi32.Ellipse.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
            gdi32.Polygon.argtypes = [wintypes.HDC, ctypes.POINTER(_POINT), ctypes.c_int]

            left = user32.GetSystemMetrics(76)
            top = user32.GetSystemMetrics(77)
            self._width = max(1, user32.GetSystemMetrics(78))
            self._height = max(1, user32.GetSystemMetrics(79))
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
            kernel32.GetLastError.restype = wintypes.DWORD
            hinstance = kernel32.GetModuleHandleW(None)
            wc = _WNDCLASSW()
            wc.lpfnWndProc = self._window_proc
            wc.hInstance = hinstance
            wc.lpszClassName = _CLASS_NAME
            atom = user32.RegisterClassW(ctypes.byref(wc))
            if not atom and kernel32.GetLastError() != 1410:
                raise ctypes.WinError()
            hwnd = user32.CreateWindowExW(
                _WS_EX_TRANSPARENT | _WS_EX_TOOLWINDOW | _WS_EX_LAYERED | _WS_EX_NOACTIVATE,
                _CLASS_NAME, "", _WS_POPUP, left, top, self._width, self._height,
                None, None, hinstance, None,
            )
            if not hwnd:
                raise ctypes.WinError()
            self._hwnd = hwnd
            if self._stopping.is_set():
                user32.DestroyWindow(hwnd)
                self._hwnd = None
                self._ready.set()
                return
            if not user32.SetLayeredWindowAttributes(
                hwnd, _COLOR_KEY, 225, _LWA_COLORKEY | _LWA_ALPHA
            ):
                raise ctypes.WinError()
            if not user32.SetWindowPos(
                hwnd, _HWND_TOPMOST, left, top, self._width, self._height,
                _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
            ):
                raise ctypes.WinError()
            user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
            user32.SetTimer(hwnd, 1, 60, None)
            user32.UpdateWindow(hwnd)
            self._startup_ok = True
            self._ready.set()

            msg = _MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            try:
                if self._hwnd and self._user32:
                    self._user32.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None
            self._startup_ok = False
            self._startup_error = f"{type(exc).__name__}: {exc}"
            self._ready.set()
        finally:
            self._hwnd = None

    def _dispatch(self, hwnd, message, wparam, lparam):
        user32 = self._user32
        gdi32 = self._gdi32
        if message == _WM_TIMER:
            if self._stopping.is_set():
                user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0)
            else:
                point = _POINT()
                if user32.GetCursorPos(ctypes.byref(point)) and user32.ScreenToClient(hwnd, ctypes.byref(point)):
                    current = (point.x, point.y)
                    previous = self._last_cursor_point
                    if current != previous:
                        points = [current] + ([previous] if previous else [])
                        dirty = wintypes.RECT(
                            min(p[0] for p in points) - 12,
                            min(p[1] for p in points) - 12,
                            max(p[0] for p in points) + 32,
                            max(p[1] for p in points) + 38,
                        )
                        user32.InvalidateRect(hwnd, ctypes.byref(dirty), False)
                        self._last_cursor_point = current
            return 0
        if message == _WM_PAINT:
            ps = _PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            if hdc:
                background = gdi32.CreateSolidBrush(_COLOR_KEY)
                old_brush = gdi32.SelectObject(hdc, background)
                user32.FillRect(hdc, ctypes.byref(ps.rcPaint), background)
                gdi32.SetBkMode(hdc, _TRANSPARENT)
                for color, thickness, inset in (
                    (0x005C3008, 26, 13),
                    (0x009A5907, 15, 9),
                    (0x00C97C08, 7, 5),
                    (0x00FFD769, 2, 2),
                ):
                    pen = gdi32.CreatePen(_PS_SOLID, thickness, color)
                    old_pen = gdi32.SelectObject(hdc, pen)
                    gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # NULL_BRUSH
                    gdi32.Rectangle(
                        hdc, inset, inset,
                        self._width - inset, self._height - inset,
                    )
                    gdi32.SelectObject(hdc, old_pen)
                    gdi32.DeleteObject(pen)

                point = _POINT()
                if user32.GetCursorPos(ctypes.byref(point)) and user32.ScreenToClient(hwnd, ctypes.byref(point)):
                    x, y = point.x, point.y
                    pen = gdi32.CreatePen(_PS_SOLID, 3, 0x00FFD863)
                    brush = gdi32.CreateSolidBrush(0x00351B07)
                    old_pen = gdi32.SelectObject(hdc, pen)
                    old_cursor_brush = gdi32.SelectObject(hdc, brush)
                    cursor_points = (_POINT * 7)(
                        _POINT(x, y), _POINT(x + 2, y + 23), _POINT(x + 8, y + 17),
                        _POINT(x + 13, y + 28), _POINT(x + 18, y + 26),
                        _POINT(x + 13, y + 15), _POINT(x + 23, y + 15),
                    )
                    gdi32.Polygon(hdc, cursor_points, len(cursor_points))
                    gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
                    gdi32.Ellipse(hdc, x - 8, y - 8, x + 8, y + 8)
                    gdi32.SelectObject(hdc, old_cursor_brush)
                    gdi32.SelectObject(hdc, old_pen)
                    gdi32.DeleteObject(brush)
                    gdi32.DeleteObject(pen)
                gdi32.SelectObject(hdc, old_brush)
                gdi32.DeleteObject(background)
                user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0
        if message == _WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if message == _WM_DESTROY:
            user32.KillTimer(hwnd, 1)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)


_CONTROL_INDICATOR = _DesktopIndicator()


def start_desktop_indicator() -> bool:
    """Show a temporary click-through overlay without changing system settings."""
    return _CONTROL_INDICATOR.start()


def stop_desktop_indicator() -> None:
    """Remove the overlay and wait briefly for its native window thread to exit."""
    _CONTROL_INDICATOR.stop()
