"""One durable local database; existing message and receipt data stays in place."""

from pathlib import Path

from app.services.tenant_context import base_data_root


def database_path() -> Path:
    root = base_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root / "kellai.db"
