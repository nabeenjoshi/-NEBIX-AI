# security_gate.py
# NEBIX Security Controller

import json
import os
import sys
import subprocess
from pathlib import Path

import psutil

BASE_DIR = Path(__file__).resolve().parent
MAIN_FILE = BASE_DIR / "main.py"
PID_FILE = BASE_DIR / "nebix.pid"


class SecurityGate:
    def __init__(self):
        self.nebix_process = None

    def _save_pid(self, process):
        tracked_process = psutil.Process(process.pid)
        payload = {
            "pid": process.pid,
            "create_time": tracked_process.create_time(),
        }
        temp_file = PID_FILE.with_name(f"{PID_FILE.name}.{process.pid}.tmp")
        try:
            temp_file.write_text(json.dumps(payload), encoding="utf-8")
            temp_file.replace(PID_FILE)
        finally:
            temp_file.unlink(missing_ok=True)

    def _remove_pid(self):
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass

    def _get_tracked_process(self):
        try:
            stored = PID_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None

        try:
            record = json.loads(stored)
            if isinstance(record, dict):
                pid = record.get("pid")
                expected_create_time = record.get("create_time")
            else:
                pid = record
                expected_create_time = None
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                raise ValueError("invalid PID")
            if expected_create_time is not None and (
                isinstance(expected_create_time, bool)
                or not isinstance(expected_create_time, (int, float))
            ):
                raise ValueError("invalid process creation time")
        except (json.JSONDecodeError, TypeError, ValueError):
            print("[SECURITY] Invalid PID file; no process will be stopped.")
            return None

        try:
            process = psutil.Process(pid)
            command_line = process.cmdline()
            create_time = process.create_time()
        except psutil.Error:
            return None

        if expected_create_time is not None and abs(
            create_time - expected_create_time
        ) > 0.01:
            return None

        expected_script = MAIN_FILE.resolve()
        for argument in command_line[1:]:
            try:
                if Path(argument).resolve() == expected_script:
                    return process
            except (OSError, RuntimeError, ValueError):
                continue
        return None

    def activate(self):
        if not MAIN_FILE.exists():
            print("[SECURITY] main.py not found.")
            return False

        if PID_FILE.exists():
            if self._get_tracked_process() is not None:
                print("[SECURITY] NEBIX already ACTIVE.")
                return True
            self._remove_pid()

        print("[SECURITY] Activating NEBIX...")

        env = os.environ.copy()
        env["NEBIX_SECURITY_TOKEN"] = "ACTIVE"

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW

        self.nebix_process = subprocess.Popen(
            [sys.executable, str(MAIN_FILE)],
            cwd=str(BASE_DIR),
            env=env,
            creationflags=creation_flags,
        )

        try:
            self._save_pid(self.nebix_process)
        except OSError:
            self.nebix_process.terminate()
            self.nebix_process.wait(timeout=5)
            self.nebix_process = None
            raise

        print(f"[SECURITY] NEBIX ACTIVE. PID={self.nebix_process.pid}")
        return True

    def power_cut(self):
        print("[SECURITY] NEBIX POWER CUT.")
        process = self._get_tracked_process()
        if process is None:
            self._remove_pid()
            print("[SECURITY] No verified NEBIX process found; nothing was stopped.")
            return False

        try:
            process.terminate()
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        except psutil.NoSuchProcess:
            pass
        except psutil.Error as error:
            print(f"[SECURITY] Stop error for verified NEBIX process: {error}")
            return False

        self.nebix_process = None
        self._remove_pid()

        print(f"[SECURITY] NEBIX process stopped. PID={process.pid}")
        print("[SECURITY] NEBIX LOCKED.")
        print("[SECURITY] Laptop is still running.")

        return True


def main():
    gate = SecurityGate()

    if len(sys.argv) < 2:
        print("NEBIX SECURITY GATE")
        print()
        print("Commands:")
        print("  activate")
        print("  power-cut")
        print("  status")
        return

    command = sys.argv[1].lstrip("-").lower().strip()

    if command == "activate":
        gate.activate()

    elif command in ("power-cut", "powercut"):
        gate.power_cut()

    elif command == "status":
        if PID_FILE.exists():
            print("[SECURITY] STATUS: ACTIVE")
            print("[SECURITY] PID:", PID_FILE.read_text().strip())
        else:
            print("[SECURITY] STATUS: LOCKED")

    else:
        print("[SECURITY] Unknown command.")


if __name__ == "__main__":
    main()