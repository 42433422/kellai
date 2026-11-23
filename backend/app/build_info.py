"""Read packaged provenance; environment variables cannot rewrite its identity."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys


def load_build_info(version: str) -> dict:
    if not getattr(sys, "frozen", False):
        return {"schema_version": 1, "channel": "source", "source_sha": None,
                "source_tree": None, "version": version}
    value = json.loads(Path(__file__).with_name("build-info.json").read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("version") != version or value.get("channel") != "candidate"
            or any(not isinstance(value.get(key), str) or not re.fullmatch(r"[0-9a-f]{40}", value[key])
                   for key in ("source_sha", "source_tree"))
            or set(value) != {"schema_version", "source_sha", "source_tree", "version", "platform", "architecture", "channel"}):
        raise RuntimeError("Packaged backend build identity is missing or invalid")
    return value
