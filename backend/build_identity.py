"""Create public build provenance from the actual clean checkout."""
from __future__ import annotations

import json
from pathlib import Path
import platform
import subprocess
import sys
import tomllib


def write_build_info(root: Path | None = None) -> Path:
    root = root or Path(__file__).resolve().parent.parent

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    if git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("Package builds require a clean committed checkout; commit the intended source first")
    info = {
        "schema_version": 1,
        "source_sha": git("rev-parse", "HEAD"),
        "source_tree": git("rev-parse", "HEAD^{tree}"),
        "version": tomllib.loads((root / "backend" / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
        "platform": sys.platform,
        "architecture": platform.machine(),
        "channel": "candidate",
    }
    target = root / "backend" / "build-info.json"
    target.write_text(json.dumps(info, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return target


if __name__ == "__main__":
    print(write_build_info())
