"""Authenticated credential encryption; the operating-system keyring owns the key."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.services.tenant_context import base_data_root, current_team_id


class VaultUnavailable(RuntimeError):
    """The vault is locked, unavailable, or contains an invalid credential."""


_LOCK = threading.RLock()
_NATIVE_BACKENDS = {
    "keyring.backends.macOS", "keyring.backends.Windows",
    "keyring.backends.SecretService", "keyring.backends.kwallet",
}


def _cipher(*, create: bool, owner_id: int = 0) -> Fernet:
    # Headless deployments explicitly inject a randomly generated Fernet key.
    # Never derive a key from a password, JWT secret, hostname or channel secret.
    supplied = os.environ.get("KELLAI_VAULT_KEY", "").strip()
    with _LOCK:
        if not supplied:
            try:
                import keyring
                from keyring.backends.chainer import ChainerBackend
                backend = keyring.get_keyring()
                candidates = backend.backends if isinstance(backend, ChainerBackend) else [backend]
                backend = next((candidate for candidate in candidates
                                if type(candidate).__module__ in _NATIVE_BACKENDS and candidate.priority > 0), None)
                if backend is None:
                    raise VaultUnavailable("系统安全凭据库不可用，请配置受保护的 KELLAI_VAULT_KEY")
                identity = hashlib.sha256(f"{base_data_root()}:{owner_id}".encode()).hexdigest()
                supplied = backend.get_password("xcmax.kellai.vault", identity) or ""
                if not supplied and create:
                    supplied = Fernet.generate_key().decode("ascii")
                    backend.set_password("xcmax.kellai.vault", identity, supplied)
                    if backend.get_password("xcmax.kellai.vault", identity) != supplied:
                        raise VaultUnavailable("系统凭据库未能持久保存主密钥")
            except VaultUnavailable:
                raise
            except Exception as exc:
                raise VaultUnavailable("无法访问系统安全凭据库") from exc
        if not supplied:
            raise VaultUnavailable("凭据库主密钥不存在，禁止创建新密钥覆盖现有凭据")
        try:
            return Fernet(supplied.encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise VaultUnavailable("凭据库主密钥格式无效") from exc


def encrypt(payload: dict[str, Any], *, owner_id: int, connection_id: str,
            purpose: str = "connection", create_key: bool = False) -> str:
    document = {"v": 1, "owner_id": int(owner_id), "connection_id": connection_id,
                "purpose": purpose, "payload": payload}
    data = json.dumps(document, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")
    return _cipher(create=create_key, owner_id=owner_id).encrypt(data).decode("ascii")


def decrypt(value: str, *, owner_id: int, connection_id: str,
            purpose: str = "connection") -> dict[str, Any]:
    try:
        document = json.loads(_cipher(create=False, owner_id=owner_id).decrypt(value.encode("ascii")))
        if (document.get("v"), document.get("owner_id"), document.get("connection_id"),
                document.get("purpose")) != (1, int(owner_id), connection_id, purpose):
            raise VaultUnavailable("凭据归属校验失败")
        payload = document["payload"]
        if not isinstance(payload, dict):
            raise VaultUnavailable("凭据格式无效")
        return payload
    except VaultUnavailable:
        raise
    except (InvalidToken, ValueError, UnicodeError, KeyError, AttributeError) as exc:
        raise VaultUnavailable("凭据无法解密或已被篡改") from exc


def status() -> dict[str, Any]:
    try:
        _cipher(create=False, owner_id=current_team_id())
        return {"available": True, "backend": "managed_key" if os.environ.get("KELLAI_VAULT_KEY")
                else "system_keyring"}
    except VaultUnavailable:
        return {"available": False, "backend": "locked"}
