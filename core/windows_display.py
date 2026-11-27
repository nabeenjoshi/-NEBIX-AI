"""Windows virtual desktop coordinates and per-thread DPI awareness."""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import platform
from typing import Iterator


_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79


@contextmanager
def per_monitor_dpi_awareness() -> Iterator[bool]:
    """Temporarily use physical per-monitor pixels on the current Windows thread."""
    restore = None
    if platform.system() == "Windows":
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            set_context = user32.SetThreadDpiAwarenessContext
            set_context.argtypes = [ctypes.c_void_p]
            set_context.restype = ctypes.c_void_p
            previous = set_context(_DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
            if previous:
                restore = lambda: set_context(previous)
        except (AttributeError, OSError):
            restore = None
    try:
        yield restore is not None or platform.system() != "Windows"
    finally:
        if restore is not None:
            restore()


def virtual_screen_bounds() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) for the current virtual desktop."""
    if platform.system() == "Windows":
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        bounds = (
            user32.GetSystemMetrics(_SM_XVIRTUALSCREEN),
            user32.GetSystemMetrics(_SM_YVIRTUALSCREEN),
            user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN),
            user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN),
        )
        if bounds[2] <= 0 or bounds[3] <= 0:
            raise RuntimeError("Windows did not report usable virtual desktop bounds.")
        return bounds

    import pyautogui

    width, height = pyautogui.size()
    return 0, 0, int(width), int(height)


def image_point_to_desktop(
    x: int,
    y: int,
    image_size: tuple[int, int],
    bounds: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Map a pixel in a resized virtual-screen image to desktop coordinates."""
    image_width, image_height = (int(image_size[0]), int(image_size[1]))
    left, top, desktop_width, desktop_height = (int(value) for value in bounds)
    x, y = int(x), int(y)
    if image_width <= 0 or image_height <= 0 or desktop_width <= 0 or desktop_height <= 0:
        raise ValueError("Image and desktop dimensions must be positive.")
    if not (0 <= x < image_width and 0 <= y < image_height):
        raise ValueError("Image coordinates are outside the captured frame.")

    scaled_x = round(x * (desktop_width - 1) / max(1, image_width - 1))
    scaled_y = round(y * (desktop_height - 1) / max(1, image_height - 1))
    return left + scaled_x, top + scaled_y
