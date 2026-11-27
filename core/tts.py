from __future__ import annotations

import threading
import time
from collections.abc import Callable

from core.paths import load_api_config_raw


class WindowsSapiTTS:
    def __init__(self, on_state: Callable[[str, str], None]) -> None:
        self._on_state = on_state
        self._request_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._cancel: threading.Event | None = None

    def speak(self, text: str, voice_name: str = "") -> dict:
        phrase = str(text or "")
        if not phrase.strip():
            return {"ok": False, "error": "There is no response to speak."}

        with self._request_lock:
            previous = self._worker
            previous_cancel = self._cancel
            if previous and previous.is_alive():
                if previous_cancel:
                    previous_cancel.set()
                previous.join(timeout=2)
                if previous.is_alive():
                    return {
                        "ok": False,
                        "error": "The previous speech is still stopping; try again shortly.",
                    }

            cancel = threading.Event()
            worker = threading.Thread(
                target=self._speak,
                args=(phrase, str(voice_name or ""), cancel),
                name="NEBIX-Windows-TTS",
                daemon=True,
            )
            self._cancel = cancel
            self._worker = worker
            worker.start()

        return {"ok": True, "accepted": True}

    def stop(self) -> dict:
        with self._request_lock:
            worker = self._worker
            cancel = self._cancel
            if not worker or not worker.is_alive():
                return {"ok": True, "stopped": False}
            if cancel:
                cancel.set()
            worker.join(timeout=2)
            if worker.is_alive():
                return {"ok": False, "error": "Speech playback has not stopped yet."}
        return {"ok": True, "stopped": True}

    def _speak(self, text: str, voice_name: str, cancel: threading.Event) -> None:
        import pythoncom

        pythoncom.CoInitialize()
        try:
            import win32com.client

            voice = win32com.client.Dispatch("SAPI.SpVoice")
            output_name = str(load_api_config_raw().get("output_device") or "").strip()
            output = self._find_token(voice.GetAudioOutputs(), output_name)
            using_default_output = bool(output_name and output is None)
            if output is not None:
                voice.AudioOutput = output
            output_description = self._description(voice.AudioOutput)

            selected_voice = self._find_token(voice.GetVoices(), voice_name)
            if selected_voice is not None:
                voice.Voice = selected_voice

            if cancel.is_set():
                return

            voice.Speak(text, 1)
            deadline = time.monotonic() + 2
            while not cancel.is_set() and voice.Status.RunningState != 2:
                if voice.WaitUntilDone(50):
                    raise RuntimeError("The Windows speech engine did not start audio playback.")
                if time.monotonic() >= deadline:
                    raise RuntimeError("The Windows speech engine did not start audio playback.")

            if cancel.is_set():
                voice.Speak("", 3)
                voice.WaitUntilDone(1000)
                self._on_state("STANDBY", "Speech playback stopped.")
                return

            output_message = output_description or "Windows default output"
            if using_default_output:
                output_message += " (configured device unavailable; using Windows default)"
            self._on_state("SPEAKING", f"Speaking through {output_message}.")

            while not cancel.is_set():
                if voice.WaitUntilDone(100):
                    break

            if cancel.is_set():
                voice.Speak("", 3)
                voice.WaitUntilDone(1000)
                self._on_state("STANDBY", "Speech playback stopped.")
            else:
                self._on_state("STANDBY", "Speech playback finished.")
        except Exception as exc:
            if cancel.is_set():
                self._on_state("STANDBY", "Speech playback stopped.")
            else:
                message = str(exc).strip() or type(exc).__name__
                self._on_state("ERROR", f"Speech output failed: {message[:300]}")
        finally:
            pythoncom.CoUninitialize()

    @staticmethod
    def _find_token(tokens, requested_name: str):
        requested = requested_name.casefold().strip()
        if not requested:
            return None
        for index in range(tokens.Count):
            token = tokens.Item(index)
            if WindowsSapiTTS._description(token).casefold() == requested:
                return token
        return None

    @staticmethod
    def _description(token) -> str:
        try:
            return str(token.GetDescription() or "").strip()
        except Exception:
            return ""
