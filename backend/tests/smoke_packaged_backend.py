"""Exercise the real packaged entry without connecting or sending to any provider."""
from __future__ import annotations

import json
import argparse
import hashlib
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--expected-build-info", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    expected = json.loads((args.expected_build_info or binary.parent / "build-info.json").read_text(encoding="utf-8"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="kellai-packaged-smoke-") as data_dir:
        env = {**os.environ, "KELLAI_DATA_DIR": data_dir, "KELLAI_WORKSPACE_ID": "1",
               "KELLAI_PORT": str(port), "KELLAI_CHANNEL_WORKER_ENABLED": "0",
               "KELLAI_PARENT_PID": str(os.getpid())}
        process = subprocess.Popen([str(binary)], env=env, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError(f"Packaged backend exited: {process.returncode}")
                try:
                    with urllib.request.urlopen(base + "/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.25)
            else:
                raise RuntimeError("Packaged backend did not start")
            assert health["service"] == "kellai-account-tool"
            assert health["protocol_version"] == 2
            assert health["build_info"] == expected, "Running backend differs from packaged source identity"
            # Exercise parent-liveness monitoring on every native CI runner.
            time.sleep(1.1)
            assert process.poll() is None, "Parent watchdog stopped a live desktop session"
            try:
                urllib.request.urlopen(base + "/api/kellai/accounts", timeout=2)
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
            else:
                raise AssertionError("Unauthenticated account access was accepted")
            with binary.open("rb") as stream:
                binary_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
            evidence = {"status": "PASS", "build_info": expected,
                        "binary_sha256": binary_sha256,
                        "health_identity_matches": True, "unauthenticated_accounts_status": 401,
                        "parent_watchdog_alive": True}
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(evidence, sort_keys=True))
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
