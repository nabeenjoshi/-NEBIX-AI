from __future__ import annotations

import asyncio
import io
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import numpy as np


@dataclass(frozen=True)
class ScreenFrame:
    data: bytes
    mime_type: str
    signature: np.ndarray


def capture_screen_frame() -> ScreenFrame:
    from actions.screen_processor import _capture_screen
    from PIL import Image

    image_bytes, _ = _capture_screen()
    with Image.open(io.BytesIO(image_bytes)) as source:
        image = source.convert("RGB")
        resampling = getattr(Image, "Resampling", Image)
        image.thumbnail((960, 540), resampling.BILINEAR)
        signature = np.asarray(
            image.convert("L").resize((48, 27), resampling.BILINEAR),
            dtype=np.uint8,
        )
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=58, optimize=False)
    return ScreenFrame(output.getvalue(), "image/jpeg", signature)


class ScreenVisionPipeline:
    """Change-triggered screen capture with a single replaceable newest-frame slot."""

    def __init__(
        self,
        capture: Callable[[], ScreenFrame],
        send: Callable[[bytes, str], Awaitable[None]],
        permission_enabled: Callable[[], bool],
        on_metrics: Callable[[dict], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        run_blocking: Callable[[Callable[[], ScreenFrame]], Awaitable[ScreenFrame]] | None = None,
        interval: float = 0.5,
        change_threshold: float = 5.5,
    ):
        self._capture = capture
        self._send = send
        self._permission_enabled = permission_enabled
        self._on_metrics = on_metrics
        self._on_error = on_error
        self._run_blocking = run_blocking
        self._interval = max(0.25, float(interval))
        self._change_threshold = max(0.0, float(change_threshold))
        self._queue: asyncio.Queue[ScreenFrame] = asyncio.Queue(maxsize=1)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._previous_signature: np.ndarray | None = None
        self._last_metrics_time = 0.0
        self._sent_frames = 0
        self._sent_bytes = 0
        self._last_frame_bytes = 0
        self._error = ""

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def metrics(self) -> dict:
        return {
            "active": self.active,
            "queueDepth": self._queue.qsize(),
            "sentFrames": self._sent_frames,
            "sentBytes": self._sent_bytes,
            "lastFrameBytes": self._last_frame_bytes,
            "cpuPercent": self._cpu_percent(),
            "memoryBytes": self._memory_bytes(),
            "error": self._error,
        }

    @staticmethod
    def _cpu_percent() -> float | None:
        try:
            import psutil

            return round(float(psutil.Process().cpu_percent()), 1)
        except (ImportError, OSError, AttributeError):
            return None

    @staticmethod
    def _memory_bytes() -> int | None:
        try:
            import psutil

            return int(psutil.Process().memory_info().rss)
        except (ImportError, OSError, AttributeError):
            return None

    def _report_metrics(self) -> None:
        if self._on_metrics:
            self._on_metrics(self.metrics)

    async def start(self) -> dict:
        if not self._permission_enabled():
            raise PermissionError(
                "Screen Vision requires Settings → Permissions → Screen observation."
            )
        if self.active:
            return self.metrics
        self._stop_event = asyncio.Event()
        self._previous_signature = None
        self._error = ""
        while not self._queue.empty():
            self._queue.get_nowait()
        self._task = asyncio.create_task(self._run(), name="NEBIX-Screen-Vision")
        self._report_metrics()
        return self.metrics

    async def stop(self) -> dict:
        self._stop_event.set()
        task = self._task
        if task and task is not asyncio.current_task():
            try:
                await asyncio.wait_for(task, timeout=2.0)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._task = None
        while not self._queue.empty():
            self._queue.get_nowait()
        self._report_metrics()
        return self.metrics

    async def _run(self) -> None:
        capture_task = asyncio.create_task(self._capture_loop())
        send_task = asyncio.create_task(self._send_loop())
        try:
            done, pending = await asyncio.wait(
                (capture_task, send_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                task.result()
            self._stop_event.set()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except asyncio.CancelledError:
            self._stop_event.set()
            capture_task.cancel()
            send_task.cancel()
            await asyncio.gather(capture_task, send_task, return_exceptions=True)
            raise
        except Exception as exc:
            self._error = str(exc)
            self._stop_event.set()
            if self._on_error:
                self._on_error(self._error)
        finally:
            self._report_metrics()

    async def _capture_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._permission_enabled():
                self._stop_event.set()
                return
            if self._run_blocking:
                frame = await self._run_blocking(self._capture)
            else:
                frame = self._capture()
            changed = self._previous_signature is None
            if self._previous_signature is not None:
                difference = float(
                    np.mean(
                        np.abs(
                            frame.signature.astype(np.int16)
                            - self._previous_signature.astype(np.int16)
                        )
                    )
                )
                changed = difference >= self._change_threshold
            self._previous_signature = frame.signature.copy()
            if changed:
                if self._queue.full():
                    self._queue.get_nowait()
                self._queue.put_nowait(frame)
            now = time.monotonic()
            if now - self._last_metrics_time >= 2.0:
                self._report_metrics()
                self._last_metrics_time = now
            try:
                await asyncio.wait_for(self._stop_event.wait(), self._interval)
            except asyncio.TimeoutError:
                pass

    async def _send_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                frame = await asyncio.wait_for(self._queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            if self._stop_event.is_set() or not self._permission_enabled():
                self._stop_event.set()
                return
            await self._send(frame.data, frame.mime_type)
            self._sent_frames += 1
            self._last_frame_bytes = len(frame.data)
            self._sent_bytes += self._last_frame_bytes
            self._report_metrics()
