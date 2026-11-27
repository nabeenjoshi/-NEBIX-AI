# security_voice.py
# NEBIX Locked Voice Security Controller

import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

import sounddevice as sd
import speech_recognition as sr


BASE_DIR = Path(__file__).resolve().parent
GATE_FILE = BASE_DIR / "security_gate.py"

COMMAND_QUEUE = queue.Queue()


def activate_nebix():
    print("[SECURITY VOICE] NEBIX ACTIVATE detected.")

    subprocess.Popen(
        [sys.executable, str(GATE_FILE), "--activate"],
        cwd=str(BASE_DIR),
    )


def power_cut_nebix():
    print("[SECURITY VOICE] NEBIX POWER CUT detected.")

    subprocess.Popen(
        [sys.executable, str(GATE_FILE), "--power-cut"],
        cwd=str(BASE_DIR),
    )


def process_command(text):
    text = " ".join(re.findall(r"[a-z0-9]+", str(text).casefold()))

    print(f"[SECURITY VOICE] Heard: {text}")

    if text == "nebix activate":
        activate_nebix()

    elif text == "nebix power cut":
        power_cut_nebix()


def listen_voice():
    recognizer = sr.Recognizer()

    while True:
        try:
            print("[SECURITY VOICE] Listening...")

            audio_data = sd.rec(
                int(4 * 16000),
                samplerate=16000,
                channels=1,
                dtype="int16",
            )

            sd.wait()

            # SpeechRecognition needs raw audio data.
            audio = sr.AudioData(
                audio_data.tobytes(),
                16000,
                2,
            )

            try:
                text = recognizer.recognize_google(
                    audio,
                    language="en-US",
                )

                process_command(text)

            except sr.UnknownValueError:
                pass

            except sr.RequestError as error:
                print("[SECURITY VOICE] Recognition error:", error)

        except KeyboardInterrupt:
            print()
            print("[SECURITY VOICE] Controller stopped.")
            break

        except Exception as error:
            print("[SECURITY VOICE] Error:", error)


def main():
    print()
    print("======================================")
    print("       NEBIX VOICE SECURITY")
    print("======================================")
    print("STATUS: LOCKED")
    print()
    print("Say:")
    print("  NEBIX ACTIVATE")
    print("  NEBIX POWER CUT")
    print()
    print("Voice controller started.")
    print()

    listen_voice()


if __name__ == "__main__":
    main()