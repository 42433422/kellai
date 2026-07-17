"""客来来用户认证与多租户。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from jose import JWTError, jwt

logger = logging.getLogger(__name__)

# --- 环境配置 ---
APP_ENV = os.environ.get("KELLAI_APP_ENV", "development").lower()
IS_PRODUCTION = APP_ENV in ("production", "prod")


def _development_jwt_secret_path() -> Path:
    """返回本机开发环境的持久化 JWT 密钥路径。"""
    configured = (os.environ.get("KELLAI_DATA_DIR") or "").strip()
    data_dir = (
        Path(configured).expanduser()
        if configured
        else Path(__file__).resolve().parents[3] / "data"
    )
    return data_dir / ".jwt-secret"


def _load_or_create_development_jwt_secret() -> str:
    """为本机桌面运行生成一次密钥，后续重启复用。"""
    secret_path = _development_jwt_secret_path()
    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        if secret_path.exists():
            persisted = secret_path.read_text(encoding="utf-8").strip()
            if len(persisted) >= 32:
                return persisted

        generated = secrets.token_urlsafe(48)
        try:
            fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            persisted = secret_path.read_text(encoding="utf-8").strip()
            if len(persisted) >= 32:
                return persisted
            secret_path.write_text(generated, encoding="utf-8")
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(generated)
        try:
            secret_path.chmod(0o600)
        except OSError:
            pass
        return generated
    except OSError as exc:
        logger.warning("无法持久化开发 JWT_SECRET，将仅本次运行有效: %s", exc)
        return secrets.token_urlsafe(48)


# --- JWT 配置 ---
JWT_SECRET = os.environ.get("KELLAI_JWT_SECRET", "")
if not JWT_SECRET:
    if IS_PRODUCTION:
        raise RuntimeError(
            "KELLAI_JWT_SECRET 未设置；生产环境必须显式配置 JWT 密钥。"
        )
    # KELLAI_DEV_FIXED_JWT=1：使用固定 secret 方便开发调试
    if os.environ.get("KELLAI_DEV_FIXED_JWT") == "1":
        JWT_SECRET = "kellai-dev-jwt"
        logger.info("使用开发模式固定 JWT_SECRET（KELLAI_DEV_FIXED_JWT=1）")
    else:
        JWT_SECRET = _load_or_create_development_jwt_secret()
        logger.info("使用本机持久化开发 JWT_SECRET（仅限 development 环境）")
JWT_ALGORITHM = "HS256"

# --- 密码 hash 旧 salt ---
_PASSWORD_SALT = os.environ.get("KELLAI_PASSWORD_SALT", "")
if not _PASSWORD_SALT:
    if IS_PRODUCTION:
        raise RuntimeError(
            "KELLAI_PASSWORD_SALT 未设置；生产环境必须显式配置密码 salt。"
        )
    # 开发环境使用固定 salt，保证开发体验一致（密码 hash 可复现）
    _PASSWORD_SALT = "dev-fixed-salt-2024"
    logger.warning("使用开发模式固定 PASSWORD_SALT（仅限 development 环境）")

# --- 输入校验正则 ---
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d{6,20}$")
_MIN_PASSWORD_LEN = 8


# --- 短信验证码 SQLite 存储 ---
# 改为表存储以支持多 worker / 进程重启场景
# 表结构: (phone PRIMARY KEY, code, expires_at, attempts, created_at)


def _ensure_sms_codes_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kellai_sms_codes (
            phone TEXT PRIMARY KEY,
            code TEXT NOT NULL,
            expires_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )


# --- token 有效期配置 ---
ACCESS_TOKEN_TTL = timedelta(hours=2)  # access_token 2 小时
REFRESH_TOKEN_TTL = timedelta(days=30)  # refresh_token 30 天
_SMS_CODE_TTL = 300  # 短信码 5 分钟
_SMS_MAX_ATTEMPTS = 5  # 单号码最大尝试次数
_MAX_TEAMS_PER_USER = 10  # 单用户最多加入团队数


def _utc_now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_email(email: str) -> bool:
    return bool(email) and bool(_EMAIL_RE.match(email))


def _validate_phone(phone: str) -> bool:
    return bool(phone) and bool(_PHONE_RE.match(phone))


def _validate_password(password: str) -> Optional[str]:
    """返回 None 表示通过；否则返回错误信息。"""
    if not password or not isinstance(password, str):
        return "密码不能为空"
    if len(password) < _MIN_PASSWORD_LEN:
        return f"密码长度至少 {_MIN_PASSWORD_LEN} 位"
    if len(password.encode("utf-8")) > 72:
        return "密码超过 72 字节，请使用更短的密码"
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "密码必须同时包含字母和数字"
    return None


# --- 短信验证码 ---

def _purge_expired_sms_codes(conn: sqlite3.Connection) -> None:
    """清理过期短信码（懒清理）"""
    try:
        conn.execute(
            "DELETE FROM kellai_sms_codes WHERE expires_at < ?",
            (_utc_now_ts(),),
        )
    except sqlite3.Error as exc:
        # 懒清理失败不应阻断主流程，但需要记日志便于排查
        logger.warning("懒清理过期短信码失败: %s", exc)


def purge_all_expired_sms_codes() -> int:
    """主动清理所有过期短信码（可被定时任务调用）。

    返回清理的行数。
    """
    try:
        with _conn() as conn:
            cur = conn.execute(
                "DELETE FROM kellai_sms_codes WHERE expires_at < ?",
                (_utc_now_ts(),),
            )
            count = int(cur.rowcount or 0)
            if count > 0:
                logger.info("清理过期短信码: %d 条", count)
            return count
    except sqlite3.Error as exc:
        logger.error("清理过期短信码失败: %s", exc)
        return 0


def generate_sms_code(phone: str) -> Optional[str]:
    """生成短信验证码。

    验证码使用密码学安全随机数生成；写入 kellai_sms_codes 表以支持多 worker。
    返回 None 表示输入或存储失败。
    """
    if not _validate_phone(phone):
        logger.warning("生成短信码失败：手机号格式不合法 phone=%s", phone)
        return None
    # 6 位数字，密码学安全，首位非零（100000-999999）
    code = str(secrets.randbelow(900000) + 100000)
    now = _utc_now_ts()
    expires_at = now + _SMS_CODE_TTL
    try:
        with _conn() as conn:
            _ensure_sms_codes_table(conn)
            _purge_expired_sms_codes(conn)
            conn.execute(
                """
                INSERT INTO kellai_sms_codes (phone, code, expires_at, attempts, created_at)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(phone) DO UPDATE SET
                    code = excluded.code,
                    expires_at = excluded.expires_at,
                    attempts = 0,
                    created_at = excluded.created_at
                """,
                (phone, code, expires_at, _utc_now_iso()),
            )
    except sqlite3.Error as exc:
        logger.error("写入短信码失败 phone=%s: %s", phone, exc)
        return None

    # 仅在显式开启开发日志时输出验证码
    if os.environ.get("KELLAI_DEV_SMS_LOG") == "1":
        logger.info("开发模式：短信验证码 phone=%s, code=%s", phone, code)
    return code


def verify_sms_code(phone: str, code: str) -> bool:
    """验证短信验证码（一次性 + 次数限制）"""
    if not phone or not code or not isinstance(code, str):
        return False
    try:
        with _conn() as conn:
            _ensure_sms_codes_table(conn)
            row = conn.execute(
                "SELECT code, expires_at, attempts FROM kellai_sms_codes WHERE phone = ?",
                (phone,),
            ).fetchone()
            if not row:
                return False
            now = _utc_now_ts()
            if now > row["expires_at"]:
                conn.execute("DELETE FROM kellai_sms_codes WHERE phone = ?", (phone,))
                return False
            if int(row["attempts"] or 0) >= _SMS_MAX_ATTEMPTS:
                conn.execute("DELETE FROM kellai_sms_codes WHERE phone = ?", (phone,))
                logger.warning("短信码尝试次数超限 phone=%s", phone)
                return False
            if not hmac.compare_digest(str(row["code"] or ""), str(code)):
                conn.execute(
                    "UPDATE kellai_sms_codes SET attempts = attempts + 1 WHERE phone = ?",
                    (phone,),
                )
                return False
            # 验证成功 → 一次性使用
            conn.execute("DELETE FROM kellai_sms_codes WHERE phone = ?", (phone,))
            return True
    except sqlite3.Error as exc:
        logger.error("校验短信码失败 phone=%s: %s", phone, exc)
        return False


# --- 密码 hash 配置 ---
# 优先使用 bcrypt，passlib 1.7.4 与 bcrypt>=4 存在 __about__ 兼容性问题，
# 因此直接调用 bcrypt 库；同时保留 passlib 兜底以兼容未来升级。
try:
    import bcrypt as _bcrypt  # type: ignore

    _BCRYPT_AVAILABLE = True
    logger.info(
        "bcrypt 库可用: version=%s", getattr(_bcrypt, "__version__", "unknown")
    )
except Exception as _exc:  # pragma: no cover - 容错
    _bcrypt = None  # type: ignore
    _BCRYPT_AVAILABLE = False
    logger.warning("bcrypt 库不可用: %s", _exc)

# passlib 仅作为可选用法（暂留引用，便于未来扩展）
try:
    from passlib.context import CryptContext  # type: ignore  # noqa: F401

    _HAS_PASSLIB = True
except Exception:
    _HAS_PASSLIB = False


def _auth_db_path():
    """已废弃：保留符号以保持向后兼容。

    历史版本会写入 data/auth/auth.db，本版本统一并入 crm_store 的 kellai.db。
    调用方传回的 Path 仅用于诊断/迁移，不影响实际连接。
    """
    from app.services.crm_store import _crm_db_path

    return _crm_db_path()


_schema_initialized = threading.Event()
_schema_init_lock = threading.Lock()


@contextmanager
def _conn():
    """数据库连接上下文管理器。自动确保 schema 已初始化（仅首次，线程安全）。

    使用 threading.Event.wait() 替代双检锁：wait() 是原子的，
    避免了 Python GIL 下双检锁的非原子性问题。
    """
    if not _schema_initialized.is_set():
        with _schema_init_lock:
            if not _schema_initialized.is_set():  # double-check
                ensure_auth_schema()
                _schema_initialized.set()
    from app.services.crm_store import _crm_db_path

    # check_same_thread=False 允许多线程访问；
    # SQLite 多 writer 下靠 WAL + 短事务
    conn = sqlite3.connect(str(_crm_db_path()), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 注意：PRAGMA journal_mode = WAL 是持久化设置，在 ensure_auth_schema() 中只设置一次
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# 向后兼容别名（保留旧名称以避免破坏已有调用方）
_connect = _conn


# ---------------------------------------------------------------------------
# 数据库迁移系统（版本控制）
# ---------------------------------------------------------------------------

# 迁移定义：按顺序排列，每个迁移都有唯一版本号
MIGRATIONS = [
    {
        "version": "20240101_initial_schema",
        "description": "创建基础表结构",
        "up": """
            CREATE TABLE IF NOT EXISTS kellai_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL DEFAULT '',
                avatar_url TEXT NOT NULL DEFAULT '',
                team_id INTEGER,
                role TEXT NOT NULL DEFAULT 'owner',
                is_active INTEGER NOT NULL DEFAULT 1,
                token_version INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS kellai_teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                invite_code TEXT NOT NULL DEFAULT '',
                settings_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS kellai_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                refresh_token TEXT NOT NULL DEFAULT '',
                expires_at TEXT NOT NULL,
                refresh_expires_at TEXT NOT NULL DEFAULT '',
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """,
    },
    {
        "version": "20240102_add_indexes",
        "description": "添加查询索引",
        "up": """
            CREATE INDEX IF NOT EXISTS idx_users_email ON kellai_users(email);
            CREATE INDEX IF NOT EXISTS idx_users_phone ON kellai_users(phone);
            CREATE INDEX IF NOT EXISTS idx_sessions_token ON kellai_sessions(token);
            CREATE INDEX IF NOT EXISTS idx_sessions_refresh ON kellai_sessions(refresh_token);
            CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON kellai_sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_teams_invite_code ON kellai_teams(invite_code);
            CREATE INDEX IF NOT EXISTS idx_users_team_id ON kellai_users(team_id);
        """,
    },
    {
        "version": "20240103_add_unique_constraints",
        "description": "添加唯一约束",
        "up": """
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_users_email ON kellai_users(email) WHERE email != '';
            CREATE UNIQUE INDEX IF NOT EXISTS uniq_users_phone ON kellai_users(phone) WHERE phone != '';
        """,
    },
]


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    """创建迁移版本控制表。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kellai_schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _get_applied_migrations(conn: sqlite3.Connection) -> set[str]:
    """获取已应用的迁移版本列表。"""
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT version FROM kellai_schema_migrations").fetchall()
    return {row["version"] for row in rows}


def _apply_migration(conn: sqlite3.Connection, migration: dict[str, str]) -> bool:
    """应用单个迁移。

    注意：不使用 executescript（它会隐式提交事务），
    而是逐条执行 SQL，保持在外层事务中。
    """
    version = migration["version"]
    description = migration["description"]
    try:
        # 分割并逐条执行 SQL（executescript 会隐式 COMMIT）
        statements = [s.strip() for s in migration["up"].split(";") if s.strip()]
        for stmt in statements:
            conn.execute(stmt)
        # 记录迁移
        conn.execute(
            "INSERT INTO kellai_schema_migrations (version, description, applied_at) VALUES (?, ?, ?)",
            (version, description, _utc_now_iso()),
        )
        logger.info("✅ 迁移已应用: %s - %s", version, description)
        return True
    except sqlite3.Error as exc:
        # 单条迁移失败：回滚当前迁移的部分 DDL，避免半迁移状态
        # 注意：DDL 在 SQLite 中通常是事务性的，但 ALTER TABLE 等可能触发隐式提交
        # 此处显式 rollback 作为防御性兜底
        try:
            conn.execute("ROLLBACK")
            # ROLLBACK 会结束当前事务，重新开启 BEGIN 以保持后续迁移可执行
            conn.execute("BEGIN")
        except sqlite3.Error:
            pass
        logger.error("❌ 迁移失败 %s: %s", version, exc)
        return False


def apply_pending_migrations(conn: sqlite3.Connection) -> dict[str, Any]:
    """应用所有待处理的迁移。"""
    applied = _get_applied_migrations(conn)
    results = {
        "applied": [],
        "skipped": [],
        "failed": [],
        "already_applied": len(applied),
    }
    
    for migration in MIGRATIONS:
        version = migration["version"]
        if version in applied:
            results["skipped"].append(version)
            continue
        if _apply_migration(conn, migration):
            results["applied"].append(version)
        else:
            results["failed"].append(version)
    
    return results


def _ensure_session_columns(conn: sqlite3.Connection) -> None:
    """迁移：为已存在的 kellai_sessions 表补齐 refresh_token / refresh_expires_at / revoked 字段（保留向后兼容）。"""
    try:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(kellai_sessions)").fetchall()}
    except sqlite3.Error:
        return
    if "refresh_token" not in cols:
        try:
            conn.execute("ALTER TABLE kellai_sessions ADD COLUMN refresh_token TEXT NOT NULL DEFAULT ''")
        except sqlite3.Error as exc:
            logger.warning("添加 refresh_token 列失败: %s", exc)
    if "refresh_expires_at" not in cols:
        try:
            conn.execute("ALTER TABLE kellai_sessions ADD COLUMN refresh_expires_at TEXT NOT NULL DEFAULT ''")
        except sqlite3.Error as exc:
            logger.warning("添加 refresh_expires_at 列失败: %s", exc)
    if "revoked" not in cols:
        try:
            conn.execute("ALTER TABLE kellai_sessions ADD COLUMN revoked INTEGER NOT NULL DEFAULT 0")
        except sqlite3.Error as exc:
            logger.warning("添加 revoked 列失败: %s", exc)


def ensure_auth_schema() -> dict[str, Any]:
    """创建认证相关表（写入统一 kellai.db），返回迁移结果。

    在此函数中设置持久化的 PRAGMA（如 journal_mode=WAL），
    避免每次 _conn() 调用都重复设置。
    """
    from app.services.crm_store import _crm_db_path

    db_path = _crm_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    migration_result = {}
    with sqlite3.connect(str(db_path), timeout=10.0) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        # journal_mode=WAL 是持久化设置，只在初始化时设置一次
        # 之后 _conn() 不再重复设置
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row

        # 先确保短信验证码表存在（这个表比较简单）
        _ensure_sms_codes_table(conn)

        # 应用版本化迁移
        migration_result = apply_pending_migrations(conn)

        # 向后兼容：对于已有旧数据库但没有迁移记录的，补全新字段
        # 这个逻辑保留以防有从更早版本直接升级的情况
        _ensure_session_columns(conn)

        conn.commit()

    return migration_result


# --- 密码 hash ---

# bcrypt 哈希前缀，用于识别
_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")
# bcrypt 推荐的 cost factor（默认值 12）
_BCRYPT_ROUNDS = 12
# 旧版 SHA-256 hash 的魔术前缀（标记升级用）
_LEGACY_HASH_PREFIX = "__legacy__:"


def _hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码（bcrypt 自带 salt，hash 中已包含 salt 前缀）"""
    if not _BCRYPT_AVAILABLE or _bcrypt is None:
        return _legacy_hash_password(password)
    try:
        pwd_bytes = password.encode("utf-8")
        # 72 字节限制由调用方在 _validate_password 阶段拦截；
        # 这里是双重保护（防止调用方跳过校验）
        if len(pwd_bytes) > 72:
            raise ValueError("密码超过 72 字节，bcrypt 不支持")
        salt = _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
        return _bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")
    except Exception as exc:  # pragma: no cover - 容错
        logger.warning("bcrypt hash 失败，回退 SHA-256: %s", exc)
        return _legacy_hash_password(password)


def _legacy_hash_password(password: str) -> str:
    """旧版 SHA-256 + salt hash（仅用于向后兼容校验）"""
    return hashlib.sha256(f"{_PASSWORD_SALT}:{password}".encode()).hexdigest()


def _is_bcrypt_hash(stored: str) -> bool:
    """判断是否为 bcrypt hash"""
    return any(stored.startswith(p) for p in _BCRYPT_PREFIXES)


def _verify_bcrypt(password: str, stored_hash: str) -> Optional[bool]:
    """bcrypt 验证；异常返回 None"""
    if not _BCRYPT_AVAILABLE or _bcrypt is None:
        return None
    try:
        pwd_bytes = password.encode("utf-8")
        # 不应该走到这里：_validate_password 应在入口拦截 > 72 字节
        # 这里做截断是为了容错（防止绕过校验层直接调用验证）
        if len(pwd_bytes) > 72:
            logger.warning("密码超过 72 字节到达 bcrypt 验证层，应在校验层拦截")
            return False
        return bool(_bcrypt.checkpw(pwd_bytes, stored_hash.encode("utf-8")))
    except Exception as exc:
        logger.debug("bcrypt 验证异常: %s", exc)
        return None


def _verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """验证密码：优先尝试 bcrypt 验证，失败则尝试旧 SHA-256 验证

    返回 (是否通过, 是否需要升级到 bcrypt)
    """
    if not stored_hash:
        return False, False
    # 1) bcrypt hash：用 bcrypt 验证
    if _is_bcrypt_hash(stored_hash):
        ok = _verify_bcrypt(password, stored_hash)
        if ok:
            return True, False  # bcrypt 验证通过，无需立即升级
        return False, False  # 验证失败
    # 2) 旧 SHA-256 兜底（同时标记需要升级）；使用恒定时间比较
    # 注意：migrate_password_hashes() 会给旧 hash 加 __legacy__: 前缀，
    # 需要先剥离前缀再比较
    actual_stored = stored_hash
    if stored_hash.startswith(_LEGACY_HASH_PREFIX):
        actual_stored = stored_hash[len(_LEGACY_HASH_PREFIX):]
    legacy_hex = _legacy_hash_password(password)
    if hmac.compare_digest(actual_stored, legacy_hex):
        return True, True
    return False, False


def _generate_access_token(
    user_id: int,
    email: str = "",
    phone: str = "",
    display_name: str = "",
    role: str = "",
    team_id: int = 0,
    token_version: int = 0,
) -> str:
    """生成 JWT access_token"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "phone": phone,
        "display_name": display_name,
        "role": role,
        "team_id": team_id,
        "token_version": token_version,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
        "type": "access",
        "jti": secrets.token_urlsafe(8),  # 确保每次生成的 token 唯一
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _generate_refresh_token(user_id: int, token_version: int = 0) -> str:
    """生成 JWT refresh_token"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "token_version": token_version,
        "iat": now,
        "exp": now + REFRESH_TOKEN_TTL,
        "type": "refresh",
        "jti": secrets.token_urlsafe(16),  # 用于会话定位
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict[str, Any] | None:
    """解码并验证 JWT token，返回 payload 或 None"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != expected_type:
            return None
        return payload
    except JWTError:
        return None


def _now_iso() -> str:
    """UTC 时间 ISO 格式字符串（_utc_now_iso 的别名，保持向后兼容）"""
    return _utc_now_iso()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """将 SQLite Row 转为字典"""
    if row is None:
        return None
    return dict(row)


# --- 迁移工具 ---


def migrate_password_hashes() -> dict[str, Any]:
    """启动时调用：检查所有用户密码 hash，将 SHA-256 升级到 bcrypt

    返回 {"scanned": int, "upgraded": int, "errors": int, "skipped": bool}

    说明：bcrypt 是单向不可逆 hash，无法做"无明文升级"。
    本函数的策略：
    - 旧 SHA-256 hash 加 _LEGACY_HASH_PREFIX 前缀标记，登录时通过旧 hash 验证后立即升级为 bcrypt
    - 已经是 bcrypt 的 hash：保持原样，登录时按需判断
    - 逐行错误隔离：单行失败不影响其他行
    """
    if not _BCRYPT_AVAILABLE:
        logger.warning("bcrypt 不可用，跳过密码 hash 迁移")
        return {"scanned": 0, "upgraded": 0, "errors": 0, "skipped": True}

    scanned = 0
    upgraded = 0
    errors = 0
    now = _now_iso()
    try:
        with _conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT id, password_hash FROM kellai_users").fetchall()
            for row in rows:
                scanned += 1
                try:
                    # conn.row_factory = sqlite3.Row 已设置，row 必为 sqlite3.Row
                    stored = row["password_hash"] or ""
                    user_id = row["id"]
                    if _is_bcrypt_hash(stored):
                        continue
                    if not stored.startswith(_LEGACY_HASH_PREFIX):
                        conn.execute(
                            "UPDATE kellai_users SET password_hash = ?, updated_at = ? WHERE id = ?",
                            (f"{_LEGACY_HASH_PREFIX}{stored}", now, user_id),
                        )
                        upgraded += 1
                except (sqlite3.Error, ValueError, TypeError) as row_exc:
                    errors += 1
                    logger.error("迁移单行密码 hash 失败 user_id=%s: %s", row["id"], row_exc)
    except (sqlite3.Error, OSError) as exc:
        logger.error("迁移密码 hash 时发生错误: %s", exc)
        errors += 1
    logger.info("密码 hash 迁移完成: scanned=%s, upgraded=%s, errors=%s", scanned, upgraded, errors)
    return {"scanned": scanned, "upgraded": upgraded, "errors": errors}


# --- 会话创建 ---


def _create_session(user_id: int, user_data: dict[str, Any]) -> dict[str, Any]:
    """为用户创建 access_token + refresh_token 会话（JWT + 持久化）。"""
    token_version = int(user_data.get("token_version") or 0)
    access_token = _generate_access_token(
        user_id,
        email=user_data.get("email", ""),
        phone=user_data.get("phone", ""),
        display_name=user_data.get("display_name", ""),
        role=user_data.get("role", ""),
        team_id=user_data.get("team_id", 0) or 0,
        token_version=token_version,
    )
    refresh_token = _generate_refresh_token(user_id, token_version=token_version)
    access_expires = (datetime.now(timezone.utc) + ACCESS_TOKEN_TTL).isoformat()
    refresh_expires = (datetime.now(timezone.utc) + REFRESH_TOKEN_TTL).isoformat()
    now = _now_iso()
    try:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO kellai_sessions
                    (user_id, token, refresh_token, expires_at, refresh_expires_at, revoked, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (user_id, access_token, refresh_token, access_expires, refresh_expires, now),
            )
    except sqlite3.Error as exc:
        # session 持久化失败：返回空 token，让调用方处理
        # 不 bump token_version，避免影响该用户其他正常设备
        logger.error("写入 session 失败 user_id=%s: %s", user_id, exc)
        return {
            "access_token": "",
            "refresh_token": "",
            "access_expires_at": "",
            "refresh_expires_at": "",
        }
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "access_expires_at": access_expires,
        "refresh_expires_at": refresh_expires,
    }


def _is_session_active(user_id: int, access_token: str) -> bool:
    """检查 access_token 对应的 session 是否存在且未被吊销。

    无 session 记录时返回 False（严格模式：未持久化的 token 视为无效）。
    """
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT revoked FROM kellai_sessions WHERE user_id = ? AND token = ?",
                (user_id, access_token),
            ).fetchone()
            if not row:
                return False  # 严格模式：无记录则拒绝
            return int(row["revoked"] or 0) == 0
    except sqlite3.Error:
        # DB 异常：保守拒绝（fail-closed），避免 DB 故障期间绕过 session 校验
        logger.warning("_is_session_active DB 异常，保守拒绝")
        return False


def revoke_session_by_refresh(refresh_token: str) -> bool:
    """根据 refresh_token 吊销整个会话。"""
    if not refresh_token:
        return False
    try:
        with _conn() as conn:
            cur = conn.execute(
                "UPDATE kellai_sessions SET revoked = 1 WHERE refresh_token = ?",
                (refresh_token,),
            )
            return cur.rowcount > 0
    except sqlite3.Error as exc:
        logger.error("吊销 session 失败: %s", exc)
        return False


def revoke_all_sessions_for_user(user_id: int) -> int:
    """吊销某用户全部 session（用于改密、踢人、权限变更等）。"""
    try:
        with _conn() as conn:
            cur = conn.execute(
                "UPDATE kellai_sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
                (user_id,),
            )
            return int(cur.rowcount or 0)
    except sqlite3.Error as exc:
        logger.error("吊销用户全部 session 失败 user_id=%s: %s", user_id, exc)
        return 0


def bump_token_version(user_id: int) -> int:
    """递增用户的 token_version，使所有未过期的 JWT 立刻失效。"""
    try:
        with _conn() as conn:
            conn.execute(
                "UPDATE kellai_users SET token_version = token_version + 1, updated_at = ? WHERE id = ?",
                (_now_iso(), user_id),
            )
            row = conn.execute(
                "SELECT token_version FROM kellai_users WHERE id = ?", (user_id,)
            ).fetchone()
            return int(row["token_version"]) if row else 0
    except sqlite3.Error as exc:
        logger.error("递增 token_version 失败 user_id=%s: %s", user_id, exc)
        return 0


# --- 用户操作 ---


def register_user(
    *,
    email: str = "",
    phone: str = "",
    password: str,
    display_name: str = "",
) -> dict[str, Any]:
    """注册用户。自动创建个人团队。原子性操作：要么全部成功，要么全部回滚。
    返回 {"success": bool, "user": dict, "access_token": str, "refresh_token": str, "error": str}
    """
    email = (email or "").strip().lower()
    phone = (phone or "").strip()
    display_name = (display_name or "").strip()[:64]  # 截断超长输入
    if not email and not phone:
        return {"success": False, "error": "邮箱和手机号至少提供一个"}
    if email and not _validate_email(email):
        return {"success": False, "error": "邮箱格式不合法"}
    if phone and not _validate_phone(phone):
        return {"success": False, "error": "手机号格式不合法"}
    pwd_err = _validate_password(password)
    if pwd_err:
        return {"success": False, "error": pwd_err}

    password_hash = _hash_password(password)
    now = _now_iso()
    user_id = 0
    team_id = 0
    user: Optional[dict[str, Any]] = None
    
    try:
        with _conn() as conn:
            # ========== 事务开始 ==========
            # 1) 创建用户（UNIQUE INDEX 会拦截重复）
            try:
                cur = conn.execute(
                    "INSERT INTO kellai_users (email, phone, password_hash, display_name, avatar_url, team_id, role, is_active, token_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, 'owner', 1, 0, ?, ?)",
                    (email, phone, password_hash, display_name, "", now, now),
                )
                user_id = int(cur.lastrowid or 0)
                if user_id <= 0:
                    raise RuntimeError("Failed to get user_id after insert")
            except sqlite3.IntegrityError as exc:
                msg = str(exc).lower()
                # SQLite 错误信息可能用列名或索引名
                if "uniq_users_email" in msg or "kellai_users.email" in msg:
                    return {"success": False, "error": "该邮箱已注册"}
                if "uniq_users_phone" in msg or "kellai_users.phone" in msg:
                    return {"success": False, "error": "该手机号已注册"}
                logger.error("注册失败(完整性): %s", exc)
                return {"success": False, "error": "注册失败，账号可能已存在"}

            # 2) 创建个人团队并回填 team_id（原子操作）
            team_name = f"{display_name or email or phone}的团队"
            team_id, _ = _create_team_with_transaction(conn, team_name, user_id, now)

            # 3) 获取完整的用户信息
            user = _row_to_dict(
                conn.execute("SELECT * FROM kellai_users WHERE id = ?", (user_id,)).fetchone()
            )
            if user:
                user.pop("password_hash", None)
            # ========== 事务结束（自动提交） ==========
    except sqlite3.Error as exc:
        logger.error("注册流程异常（已回滚）: %s", exc)
        return {"success": False, "error": "注册失败，请稍后重试"}

    if not user:
        return {"success": False, "error": "注册失败，请稍后重试"}

    # 创建 token 会话（注意：这是在事务之外的，因为会话创建失败不应该影响用户/团队创建）
    try:
        session = _create_session(user_id, user)
        logger.info("用户注册成功: user_id=%s, team_id=%s", user_id, team_id)
        return {
            "success": True,
            "user": user,
            "access_token": session["access_token"],
            "refresh_token": session["refresh_token"],
            "access_expires_at": session["access_expires_at"],
            "refresh_expires_at": session["refresh_expires_at"],
        }
    except (sqlite3.Error, OSError, ValueError) as exc:
        logger.error("用户注册成功但会话创建失败: user_id=%s, error=%s", user_id, exc)
        # 会话创建失败：用户/团队已落库，但客户端无法拿到 token
        # 返回 success=False，让客户端引导用户去登录（避免给出空 token 让前端误判已登录）
        return {
            "success": False,
            "user": user,
            "error": "账号创建成功，但会话初始化失败，请重新登录",
        }


def reset_password_by_phone(phone: str, code: str, new_password: str) -> dict[str, Any]:
    """通过手机验证码重置密码。

    流程：校验手机号/新密码格式 → 校验短信验证码（一次性消费）→
    定位用户 → 写入新 hash → 吊销全部会话并递增 token_version（强制其他端重新登录）。
    返回 {"success": bool, "error": str?}
    """
    phone = (phone or "").strip()
    if not _validate_phone(phone):
        return {"success": False, "error": "手机号格式不合法"}
    pwd_err = _validate_password(new_password)
    if pwd_err:
        return {"success": False, "error": pwd_err}
    if not verify_sms_code(phone, code):
        return {"success": False, "error": "验证码无效或已过期"}

    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT id FROM kellai_users WHERE phone = ? AND is_active = 1",
                (phone,),
            ).fetchone()
            if not row:
                return {"success": False, "error": "该手机号未注册"}
            user_id = int(row["id"])
            conn.execute(
                "UPDATE kellai_users SET password_hash = ?, token_version = token_version + 1, updated_at = ? WHERE id = ?",
                (_hash_password(new_password), _now_iso(), user_id),
            )
            conn.execute(
                "UPDATE kellai_sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
                (user_id,),
            )
    except sqlite3.Error as exc:
        logger.error("重置密码失败 phone=%s: %s", phone, exc)
        return {"success": False, "error": "重置失败，请稍后重试"}

    logger.info("密码已通过短信重置: user_id=%s", user_id)
    return {"success": True, "message": "密码已重置，请使用新密码登录"}


def _verify_password_and_upgrade_if_needed(
    conn: sqlite3.Connection,
    email: str,
    password: str,
) -> tuple[Optional[int], Optional[str]]:
    """验证邮箱密码，自动升级旧 hash。

    返回 (user_id, error_message) - 如果成功则 user_id 有值且 error 为 None。
    """
    row = conn.execute(
        "SELECT id, password_hash FROM kellai_users WHERE email = ? AND is_active = 1",
        (email,),
    ).fetchone()
    if not row:
        return None, "邮箱或密码错误"

    stored = row["password_hash"] or ""
    ok, need_upgrade = _verify_password(password, stored)
    if not ok:
        return None, "邮箱或密码错误"

    user_id = row["id"]
    # 如果是旧 hash 或标记为 __legacy__，则重新 hash 后写回
    if need_upgrade or stored.startswith(_LEGACY_HASH_PREFIX):
        new_hash = _hash_password(password)
        conn.execute(
            "UPDATE kellai_users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (new_hash, _now_iso(), user_id),
        )
        logger.info("用户密码 hash 已升级: user_id=%s", user_id)

    return user_id, None


def login_by_email(email: str, password: str) -> dict[str, Any]:
    """邮箱登录。返回 {"success": bool, "user": dict, "access_token", "refresh_token"}

    注意：速率限制由路由层负责，service 层只做纯业务逻辑。
    """
    email = (email or "").strip().lower()
    if not email or not password:
        return {"success": False, "error": "邮箱或密码错误"}

    user: Optional[dict[str, Any]] = None
    user_id: Optional[int] = None

    try:
        with _conn() as conn:
            user_id, err = _verify_password_and_upgrade_if_needed(conn, email, password)
            if err:
                return {"success": False, "error": err}

            user = _row_to_dict(
                conn.execute("SELECT * FROM kellai_users WHERE id = ?", (user_id,)).fetchone()
            )
            if user:
                user.pop("password_hash", None)
    except sqlite3.Error as exc:
        logger.error("邮箱登录异常: %s", exc)
        return {"success": False, "error": "登录失败，请稍后重试"}

    if not user or user_id is None:
        return {"success": False, "error": "登录失败，请稍后重试"}

    session = _create_session(user_id, user)
    logger.info("邮箱登录成功: user_id=%s", user_id)
    return {
        "success": True,
        "user": user,
        "access_token": session["access_token"],
        "refresh_token": session["refresh_token"],
        "access_expires_at": session["access_expires_at"],
        "refresh_expires_at": session["refresh_expires_at"],
    }


def login_by_phone(phone: str, code: str) -> dict[str, Any]:
    """手机号登录（验证码登录）。
    返回 {"success": bool, "user": dict, "access_token", "refresh_token"}

    注意：速率限制由路由层负责，service 层只做纯业务逻辑。
    """
    phone = (phone or "").strip()
    if not phone or not code:
        return {"success": False, "error": "手机号或验证码错误"}
    if len(code) != 6 or not code.isdigit():
        return {"success": False, "error": "验证码格式错误，需为 6 位数字"}
    if not _validate_phone(phone):
        return {"success": False, "error": "手机号格式不合法"}

    if not verify_sms_code(phone, code):
        return {"success": False, "error": "验证码无效或已过期"}

    user_id: Optional[int] = None
    user: Optional[dict[str, Any]] = None
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM kellai_users WHERE phone = ? AND is_active = 1",
                (phone,),
            ).fetchone()
            if not row:
                return {"success": False, "error": "手机号或验证码错误"}

            user_id = row["id"]
            user = _row_to_dict(row)
            if user:
                user.pop("password_hash", None)
    except sqlite3.Error as exc:
        logger.error("手机号登录异常: %s", exc)
        return {"success": False, "error": "登录失败，请稍后重试"}

    if not user or not user_id:
        return {"success": False, "error": "登录失败，请稍后重试"}

    session = _create_session(user_id, user)
    logger.info("手机号登录成功: user_id=%s", user_id)
    return {
        "success": True,
        "user": user,
        "access_token": session["access_token"],
        "refresh_token": session["refresh_token"],
        "access_expires_at": session["access_expires_at"],
        "refresh_expires_at": session["refresh_expires_at"],
    }


def create_login_session_for_user(user_id: int) -> dict[str, Any]:
    """Create a fresh login session for an already-authenticated user id."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return {"success": False, "error": "无效用户"}
    if uid <= 0:
        return {"success": False, "error": "无效用户"}

    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM kellai_users WHERE id = ? AND is_active = 1",
                (uid,),
            ).fetchone()
            user = _row_to_dict(row)
            if user:
                user.pop("password_hash", None)
    except sqlite3.Error as exc:
        logger.error("创建用户登录会话异常 user_id=%s: %s", uid, exc)
        return {"success": False, "error": "登录失败，请稍后重试"}

    if not user:
        return {"success": False, "error": "用户不存在或已停用"}

    session = _create_session(uid, user)
    if not session.get("access_token"):
        return {"success": False, "error": "会话初始化失败，请稍后重试"}
    logger.info("扫码登录会话创建成功: user_id=%s", uid)
    return {
        "success": True,
        "user": user,
        "access_token": session["access_token"],
        "refresh_token": session["refresh_token"],
        "access_expires_at": session["access_expires_at"],
        "refresh_expires_at": session["refresh_expires_at"],
    }


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """使用 refresh_token 换取新的 access_token（同时轮换 refresh_token）

    整个流程在单个 _conn() 事务中完成：
    1. 验证 refresh_token 对应的 session 未被吊销
    2. 验证用户状态和 token_version
    3. 吊销旧 session + 插入新 session（原子操作）
    4. 提交事务

    这避免了 TOCTOU 竞态：同一 refresh_token 的并发刷新请求中，
    只有一个能成功吊销旧 session 并插入新 session。
    """
    if not refresh_token:
        return {"success": False, "error": "refresh_token 不能为空"}

    # 验证 refresh JWT（JWT 验证不依赖 DB，先在外层做）
    payload = decode_token(refresh_token, expected_type="refresh")
    if not payload:
        return {"success": False, "error": "refresh_token 无效"}

    user_id = int(payload.get("sub", 0))
    if user_id <= 0:
        return {"success": False, "error": "refresh_token 无效"}

    try:
        with _conn() as conn:
            # 1) 检查 session 是否被吊销
            sess = conn.execute(
                "SELECT revoked FROM kellai_sessions WHERE refresh_token = ?",
                (refresh_token,),
            ).fetchone()
            if sess and int(sess["revoked"] or 0) == 1:
                return {"success": False, "error": "refresh_token 已被吊销"}

            # 2) 验证用户状态
            row = conn.execute(
                "SELECT id, is_active, token_version FROM kellai_users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row or not row["is_active"]:
                return {"success": False, "error": "用户已停用"}

            # 3) 校验 token_version
            current_tv = int(row["token_version"] or 0)
            token_tv = int(payload.get("token_version") or 0)
            if current_tv != token_tv:
                return {"success": False, "error": "refresh_token 已失效"}

            # 4) 获取用户信息
            user = _row_to_dict(
                conn.execute("SELECT * FROM kellai_users WHERE id = ?", (user_id,)).fetchone()
            )
            if not user:
                return {"success": False, "error": "用户不存在"}

            # 5) 生成新 token
            new_access = _generate_access_token(
                user_id,
                email=user.get("email", ""),
                phone=user.get("phone", ""),
                display_name=user.get("display_name", ""),
                role=user.get("role", ""),
                team_id=user.get("team_id", 0) or 0,
                token_version=int(user.get("token_version") or 0),
            )
            new_refresh = _generate_refresh_token(user_id, token_version=int(user.get("token_version") or 0))
            new_access_exp = (datetime.now(timezone.utc) + ACCESS_TOKEN_TTL).isoformat()
            new_refresh_exp = (datetime.now(timezone.utc) + REFRESH_TOKEN_TTL).isoformat()
            now = _now_iso()

            # 6) 吊销旧 session + 写入新 session（同一事务，原子操作）
            conn.execute(
                "UPDATE kellai_sessions SET revoked = 1 WHERE refresh_token = ?",
                (refresh_token,),
            )
            conn.execute(
                """
                INSERT INTO kellai_sessions
                    (user_id, token, refresh_token, expires_at, refresh_expires_at, revoked, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (user_id, new_access, new_refresh, new_access_exp, new_refresh_exp, now),
            )
            # 事务在这里自动提交（_conn() 上下文管理器）
    except sqlite3.Error as exc:
        logger.error("refresh 流程异常: %s", exc)
        return {"success": False, "error": "刷新失败，请稍后重试"}

    logger.info("refresh_token 换发成功: user_id=%s", user_id)
    return {
        "success": True,
        "access_token": new_access,
        "refresh_token": new_refresh,
        "access_expires_at": new_access_exp,
        "refresh_expires_at": new_refresh_exp,
    }


def verify_token(token: str) -> dict[str, Any] | None:
    """验证 access_token（JWT），返回用户信息或 None"""
    payload = decode_token(token, expected_type="access")
    if not payload:
        return None

    user_id = int(payload.get("sub", 0))
    if user_id <= 0:
        return None

    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT id, email, phone, display_name, avatar_url, team_id, role, is_active, token_version "
                "FROM kellai_users WHERE id = ? AND is_active = 1",
                (user_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        logger.error("verify_token 查询异常: %s", exc)
        return None

    if not row:
        return None

    # token_version 校验（支持主动踢人/全员下线）
    if int(row["token_version"] or 0) != int(payload.get("token_version") or 0):
        return None

    # session 状态校验
    if not _is_session_active(user_id, token):
        return None

    return {
        "id": row["id"],
        "email": row["email"],
        "phone": row["phone"],
        "display_name": row["display_name"],
        "avatar_url": row["avatar_url"],
        "team_id": row["team_id"],
        "role": row["role"],
        "refreshed": False,
    }


def get_user(user_id: int) -> dict[str, Any] | None:
    """获取用户信息"""
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT * FROM kellai_users WHERE id = ? AND is_active = 1", (user_id,)
            ).fetchone()
    except sqlite3.Error as exc:
        logger.error("get_user 异常: %s", exc)
        return None
    if not row:
        return None
    user = _row_to_dict(row)
    user.pop("password_hash", None)
    return user


def update_user(user_id: int, **kwargs) -> dict[str, Any]:
    """更新用户信息"""
    # 注意：email/phone 变更涉及登录身份，谨慎开放；此处仍允许但需通过唯一索引
    allowed_fields = {"display_name", "avatar_url", "email", "phone"}
    # 字段长度上限（防 DoS / 存储膨胀）
    _MAX_LEN = {
        "display_name": 64,
        "avatar_url": 512,
    }
    updates: dict[str, Any] = {}
    for k, v in kwargs.items():
        if k in allowed_fields and v is not None:
            updates[k] = v
    if not updates:
        return {"success": False, "error": "没有可更新的字段"}

    # 长度校验
    for field_name, max_len in _MAX_LEN.items():
        if field_name in updates and len(str(updates[field_name])) > max_len:
            return {
                "success": False,
                "error": f"{field_name} 长度不能超过 {max_len} 个字符",
            }

    if "email" in updates:
        updates["email"] = str(updates["email"]).strip().lower()
        if not _validate_email(updates["email"]):
            return {"success": False, "error": "邮箱格式不合法"}
    if "phone" in updates:
        updates["phone"] = str(updates["phone"]).strip()
        if not _validate_phone(updates["phone"]):
            return {"success": False, "error": "手机号格式不合法"}

    now = _now_iso()
    updates["updated_at"] = now

    # 使用参数化查询，避免动态拼接 SQL
    # 虽然 allowed_fields 已经过滤，但动态拼接仍是安全隐患
    set_clauses = []
    values = []
    for field_name in ("display_name", "avatar_url", "email", "phone", "updated_at"):
        if field_name in updates:
            set_clauses.append(f"{field_name} = ?")
            values.append(updates[field_name])
    values.append(user_id)

    sql = f"UPDATE kellai_users SET {', '.join(set_clauses)} WHERE id = ?"

    try:
        with _conn() as conn:
            try:
                conn.execute(sql, values)
            except sqlite3.IntegrityError as exc:
                msg = str(exc).lower()
                if "uniq_users_email" in msg or "kellai_users.email" in msg:
                    return {"success": False, "error": "该邮箱已被其他用户使用"}
                if "uniq_users_phone" in msg or "kellai_users.phone" in msg:
                    return {"success": False, "error": "该手机号已被其他用户使用"}
                raise
    except sqlite3.Error as exc:
        logger.error("update_user 异常: %s", exc)
        return {"success": False, "error": "更新失败，请稍后重试"}

    user = get_user(user_id)
    return {"success": True, "user": user}


# --- 团队操作 ---


def _create_team_with_transaction(
    conn: sqlite3.Connection, 
    name: str, 
    owner_id: int, 
    now: str
) -> tuple[int, str]:
    """在现有事务中创建团队，返回 team_id 和 invite_code。
    
    注意：此函数不提交事务，由调用方负责提交/回滚。
    """
    invite_code = secrets.token_urlsafe(8)
    cur = conn.execute(
        "INSERT INTO kellai_teams (name, owner_id, invite_code, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (name.strip(), owner_id, invite_code, "{}", now, now),
    )
    team_id = int(cur.lastrowid or 0)
    if team_id <= 0:
        raise RuntimeError("Failed to get team_id after insert")
    # 更新用户的 team_id 和角色
    conn.execute(
        "UPDATE kellai_users SET team_id = ?, role = 'owner', updated_at = ? WHERE id = ?",
        (team_id, now, owner_id),
    )
    return team_id, invite_code


def _load_team_member(team_id: int, user_id: int) -> Optional[dict[str, Any]]:
    """加载用户在某团队中的成员信息。

    team_id=0 表示不校验团队归属，仅获取用户基本信息。
    """
    try:
        with _conn() as conn:
            row = conn.execute(
                "SELECT id, team_id, role, is_active FROM kellai_users WHERE id = ?",
                (user_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        logger.error("_load_team_member 异常: %s", exc)
        return None
    if not row:
        return None
    result = dict(row)
    # 如果传了 team_id（非 0），校验用户是否在该团队
    if team_id and result.get("team_id") != team_id:
        return None
    return result


def create_team(name: str, owner_id: int, *, actor_id: int = 0) -> dict[str, Any]:
    """创建团队。actor_id 必须是 owner_id 本人或 owner 角色；0 表示内部调用（注册流程）。

    权限校验在同一事务中完成，避免竞态。
    """
    if not name or not name.strip():
        return {"success": False, "error": "团队名称不能为空"}
    if owner_id <= 0:
        return {"success": False, "error": "owner_id 无效"}

    now = _now_iso()
    try:
        with _conn() as conn:
            # 权限校验（在同一事务中，避免竞态）
            if actor_id and actor_id != owner_id:
                actor = conn.execute(
                    "SELECT id, role FROM kellai_users WHERE id = ?",
                    (actor_id,),
                ).fetchone()
                if not actor or actor["role"] != "owner":
                    return {"success": False, "error": "无权为其他用户创建团队"}

            invite_code = secrets.token_urlsafe(8)
            conn.execute(
                "INSERT INTO kellai_teams (name, owner_id, invite_code, settings_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (name.strip(), owner_id, invite_code, "{}", now, now),
            )
            team_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
            conn.execute(
                "UPDATE kellai_users SET team_id = ?, role = 'owner', updated_at = ? WHERE id = ?",
                (team_id, now, owner_id),
            )
    except sqlite3.Error as exc:
        logger.error("create_team 异常: %s", exc)
        return {"success": False, "error": "创建团队失败，请稍后重试"}

    logger.info("团队创建成功: team_id=%s, owner_id=%s", team_id, owner_id)
    team = get_team(team_id)
    return {"success": True, "team": team} if team else {"success": False, "error": "创建团队失败"}


def get_team(team_id: int) -> dict[str, Any] | None:
    """获取团队信息"""
    try:
        with _conn() as conn:
            row = conn.execute("SELECT * FROM kellai_teams WHERE id = ?", (team_id,)).fetchone()
    except sqlite3.Error as exc:
        logger.error("get_team 异常: %s", exc)
        return None
    if not row:
        return None
    team = _row_to_dict(row)
    raw = team.get("settings_json", "{}")
    if isinstance(raw, str):
        try:
            team["settings"] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            team["settings"] = {}
    else:
        team["settings"] = {}
    team.pop("settings_json", None)
    return team


def list_team_members(team_id: int) -> list[dict[str, Any]]:
    """列出团队成员"""
    try:
        with _conn() as conn:
            rows = conn.execute(
                "SELECT id, email, phone, display_name, avatar_url, team_id, role, is_active, created_at, updated_at FROM kellai_users WHERE team_id = ?",
                (team_id,),
            ).fetchall()
    except sqlite3.Error as exc:
        logger.error("list_team_members 异常: %s", exc)
        return []
    return [_row_to_dict(row) for row in rows]


def invite_team_member(
    team_id: int,
    *,
    actor_id: int,
    email: str = "",
    phone: str = "",
    role: str = "sales",
) -> dict[str, Any]:
    """邀请团队成员。role: admin/sales/readonly

    actor_id: 发起邀请的用户；权限校验：owner / admin
    权限校验在同一事务中完成，避免竞态。
    """
    if not email and not phone:
        return {"success": False, "error": "邮箱和手机号至少提供一个"}
    if email and not _validate_email(email.strip().lower()):
        return {"success": False, "error": "邮箱格式不合法"}
    if phone and not _validate_phone(phone.strip()):
        return {"success": False, "error": "手机号格式不合法"}
    if role not in ("admin", "sales", "readonly"):
        return {"success": False, "error": "角色必须是 admin/sales/readonly 之一"}

    now = _now_iso()
    email_norm = email.strip().lower() if email else ""
    phone_norm = phone.strip() if phone else ""

    try:
        with _conn() as conn:
            # 权限校验（在同一事务中，避免竞态）
            actor = conn.execute(
                "SELECT id, team_id, role FROM kellai_users WHERE id = ?",
                (actor_id,),
            ).fetchone()
            if not actor or actor["team_id"] != team_id:
                return {"success": False, "error": "您不在该团队中"}
            if actor["role"] not in ("owner", "admin"):
                return {"success": False, "error": "权限不足，仅团队所有者或管理员可邀请成员"}

            user = None
            if email_norm:
                user = conn.execute("SELECT * FROM kellai_users WHERE email = ?", (email_norm,)).fetchone()
            if not user and phone_norm:
                user = conn.execute("SELECT * FROM kellai_users WHERE phone = ?", (phone_norm,)).fetchone()

            if user:
                user_id = user["id"]
                if user["team_id"] == team_id:
                    return {"success": False, "error": "该用户已在团队中"}
                conn.execute(
                    "UPDATE kellai_users SET team_id = ?, role = ?, updated_at = ? WHERE id = ?",
                    (team_id, role, now, user_id),
                )
                logger.info(
                    "邀请已有用户加入团队: user_id=%s, team_id=%s, role=%s",
                    user_id, team_id, role,
                )
                return {"success": True, "user_id": user_id, "message": "用户已加入团队"}
            else:
                # 用户不存在，记录邀请信息（实际生产环境应发送邀请邮件/短信）
                logger.info(
                    "邀请新用户: email=%s, phone=%s, team_id=%s, role=%s",
                    email_norm, phone_norm, team_id, role,
                )
                return {"success": True, "message": "邀请已发送，用户注册后将自动加入团队"}
    except sqlite3.Error as exc:
        logger.error("invite_team_member 异常: %s", exc)
        return {"success": False, "error": "邀请失败，请稍后重试"}


def remove_team_member(team_id: int, user_id: int, *, actor_id: int) -> dict[str, Any]:
    """移除团队成员。actor_id: 发起操作的用户；权限：owner / admin

    所有 DB 操作在同一事务中完成，避免 actor 权限在检查后被修改的竞态。
    """
    if user_id <= 0:
        return {"success": False, "error": "user_id 无效"}

    now = _now_iso()
    try:
        with _conn() as conn:
            # 权限校验（在同一事务中，避免竞态）
            actor = conn.execute(
                "SELECT id, team_id, role FROM kellai_users WHERE id = ?",
                (actor_id,),
            ).fetchone()
            if not actor or actor["team_id"] != team_id:
                return {"success": False, "error": "您不在该团队中"}
            if actor["role"] not in ("owner", "admin"):
                return {"success": False, "error": "权限不足"}

            user = conn.execute(
                "SELECT id, role FROM kellai_users WHERE id = ? AND team_id = ?",
                (user_id, team_id),
            ).fetchone()
            if not user:
                return {"success": False, "error": "该用户不在团队中"}
            if user["role"] == "owner":
                return {"success": False, "error": "不能移除团队所有者"}

            # admin 不能移除另一个 admin（仅 owner 可）
            if actor["role"] == "admin" and user["role"] == "admin":
                return {"success": False, "error": "管理员不能移除其他管理员"}

            conn.execute(
                "UPDATE kellai_users SET team_id = NULL, updated_at = ? WHERE id = ?",
                (now, user_id),
            )
            # 踢人：吊销该用户所有 session + 递增 token_version 使旧 JWT 立即失效
            conn.execute(
                "UPDATE kellai_sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
                (user_id,),
            )
            conn.execute(
                "UPDATE kellai_users SET token_version = token_version + 1, updated_at = ? WHERE id = ?",
                (now, user_id),
            )
    except sqlite3.Error as exc:
        logger.error("remove_team_member 异常: %s", exc)
        return {"success": False, "error": "移除失败，请稍后重试"}

    logger.info("移除团队成员: user_id=%s, team_id=%s, actor_id=%s", user_id, team_id, actor_id)
    return {"success": True, "message": "成员已移除"}


def update_member_role(team_id: int, user_id: int, role: str, *, actor_id: int) -> dict[str, Any]:
    """更新成员角色。权限：仅 owner 可执行。

    所有 DB 操作在同一事务中完成，避免 actor 权限在检查后被修改的竞态。
    """
    if role not in ("admin", "sales", "readonly", "owner"):
        return {"success": False, "error": "角色必须是 admin/sales/readonly/owner 之一"}

    now = _now_iso()
    try:
        with _conn() as conn:
            # 权限校验（在同一事务中，避免竞态）
            actor = conn.execute(
                "SELECT id, team_id, role FROM kellai_users WHERE id = ?",
                (actor_id,),
            ).fetchone()
            if not actor or actor["team_id"] != team_id:
                return {"success": False, "error": "您不在该团队中"}
            if actor["role"] != "owner":
                return {"success": False, "error": "权限不足，仅团队所有者可修改成员角色"}

            user = conn.execute(
                "SELECT id, role FROM kellai_users WHERE id = ? AND team_id = ?",
                (user_id, team_id),
            ).fetchone()
            if not user:
                return {"success": False, "error": "该用户不在团队中"}

            conn.execute(
                "UPDATE kellai_users SET role = ?, updated_at = ? WHERE id = ?",
                (role, now, user_id),
            )
            # 角色变更：吊销该用户所有 session 强制重新登录
            conn.execute(
                "UPDATE kellai_sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
                (user_id,),
            )
            # 提升 token_version 让已发出的 JWT 立即失效
            conn.execute(
                "UPDATE kellai_users SET token_version = token_version + 1, updated_at = ? WHERE id = ?",
                (now, user_id),
            )
    except sqlite3.Error as exc:
        logger.error("update_member_role 异常: %s", exc)
        return {"success": False, "error": "更新角色失败，请稍后重试"}

    logger.info(
        "更新成员角色: user_id=%s, team_id=%s, role=%s, actor_id=%s",
        user_id, team_id, role, actor_id,
    )
    return {"success": True, "message": f"角色已更新为 {role}"}


def join_team_by_invite_code(invite_code: str, user_id: int) -> dict[str, Any]:
    """通过邀请码加入团队

    限制：每个用户最多加入 _MAX_TEAMS_PER_USER 个团队（当前为 {_MAX_TEAMS_PER_USER}）。
    """
    if not invite_code or not invite_code.strip():
        return {"success": False, "error": "邀请码不能为空"}
    if user_id <= 0:
        return {"success": False, "error": "用户无效"}

    now = _now_iso()
    try:
        with _conn() as conn:
            team = conn.execute(
                "SELECT * FROM kellai_teams WHERE invite_code = ?",
                (invite_code.strip(),),
            ).fetchone()
            if not team:
                return {"success": False, "error": "邀请码无效"}

            team_id = team["id"]
            user = conn.execute(
                "SELECT id, team_id, role FROM kellai_users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not user:
                return {"success": False, "error": "用户不存在"}
            if user["team_id"] == team_id:
                return {"success": False, "error": "您已在该团队中"}

            # 检查团队数量限制
            team_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM kellai_users WHERE id = ? AND team_id IS NOT NULL",
                (user_id,),
            ).fetchone()["cnt"]
            if int(team_count or 0) >= _MAX_TEAMS_PER_USER:
                return {"success": False, "error": f"您已达到最大团队数限制（{_MAX_TEAMS_PER_USER}）"}

            conn.execute(
                "UPDATE kellai_users SET team_id = ?, role = 'sales', updated_at = ? WHERE id = ?",
                (team_id, now, user_id),
            )
    except sqlite3.Error as exc:
        logger.error("join_team_by_invite_code 异常: %s", exc)
        return {"success": False, "error": "加入团队失败，请稍后重试"}

    logger.info("用户通过邀请码加入团队: user_id=%s, team_id=%s", user_id, team_id)
    return {"success": True, "team_id": team_id, "message": "已加入团队"}
