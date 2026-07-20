"""PyInstaller entry point for the self-contained macOS desktop backend."""

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
