"""PyInstaller entry point for the self-contained desktop backend."""

from __future__ import annotations

import os
import threading
import time


def _watch_parent_process() -> None:
    """Stop the frozen backend if the desktop parent disappears unexpectedly."""
    raw_parent_pid = os.environ.get("KELLAI_PARENT_PID", "").strip()
    if not raw_parent_pid:
        return
    try:
        parent_pid = int(raw_parent_pid)
    except ValueError:
        return

    def watch() -> None:
        if os.name == "nt":
            # os.kill(pid, 0) terminates a process on Windows. Wait on a
            # SYNCHRONIZE-only handle instead; it cannot modify the parent.
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x00100000, False, parent_pid)
            if not handle:
                if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: PID has exited.
                    os._exit(0)
                return
            try:
                while True:
                    result = kernel.WaitForSingleObject(handle, 1000)
                    if result == 0:  # WAIT_OBJECT_0: the actual parent handle exited.
                        os._exit(0)
                    if result != 258:  # WAIT_TIMEOUT is the only live-parent result.
                        return
            finally:
                kernel.CloseHandle(handle)
        while True:
            time.sleep(1.0)
            try:
                os.kill(parent_pid, 0)
            except ProcessLookupError:
                os._exit(0)
            except PermissionError:
                continue

    threading.Thread(target=watch, name="kellai-parent-watchdog", daemon=True).start()


def main() -> None:
    os.environ.setdefault("KELLAI_PORT", "8793")
    _watch_parent_process()

    from app.main import run

    run()


if __name__ == "__main__":
    main()
