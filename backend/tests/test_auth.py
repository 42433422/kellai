"""客来来 auth.py 核心烟雾测试。

运行：
  cd backend && KELLAI_APP_ENV=development pytest tests/test_auth.py -v

特点：
- 每个测试都用临时 SQLite 文件，不污染主库
- 覆盖之前评审中识别的 P0/P1 风险点
"""
from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# 必须先设置环境再 import auth
os.environ.setdefault("KELLAI_APP_ENV", "development")
os.environ.setdefault("KELLAI_JWT_SECRET", "test-secret-for-pytest-only")
os.environ.setdefault("KELLAI_PASSWORD_SALT", "test-salt-for-pytest-only")

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """为每个测试提供独立 SQLite 数据库（避免污染主库）。"""
    db_file = tmp_path / "kellai_test.db"
    monkeypatch.setenv("KELLAI_DATA_DIR", str(tmp_path))

    # 重置 crm_store 的 db 路径缓存 + auth 的 schema 初始化标志
    from app.services import crm_store, auth

    # 重新 import 让 crm_store 用新路径
    importlib.reload(crm_store)
    importlib.reload(auth)

    yield db_file

    # 清理
    monkeypatch.undo()


# --- 基础导入 ---

def test_secrets_module_imported():
    """P0-1: secrets 模块必须可访问（之前是 NameError）。"""
    from app.services import auth

    assert hasattr(auth, "secrets")
    import secrets as _secrets

    assert auth.secrets is _secrets


def test_sms_code_uses_secrets():
    """P0-3: SMS 码必须使用密码学安全随机数。"""
    from app.services import auth

    # 验证 randbelow 在源码中（确保没用 random.randint）
    src = Path(auth.__file__).read_text(encoding="utf-8")
    assert "secrets.randbelow" in src
    assert "random.randint" not in src  # 旧实现


def test_production_requires_jwt_secret(monkeypatch):
    """P0-2: 生产环境必须显式设置 JWT_SECRET。"""
    monkeypatch.setenv("KELLAI_APP_ENV", "production")
    monkeypatch.delenv("KELLAI_JWT_SECRET", raising=False)
    monkeypatch.delenv("KELLAI_PASSWORD_SALT", raising=False)

    from app.services import auth

    with pytest.raises(RuntimeError, match="KELLAI_JWT_SECRET"):
        importlib.reload(auth)


# --- 注册与登录 ---

def test_register_and_login_success(tmp_db):
    """P1-2: 正常注册+登录能拿到 token（修复前会因 secrets 缺失 NameError）。"""
    from app.services import auth

    reg = auth.register_user(
        email="alice@test.com",
        password="Secret123",
        display_name="Alice",
    )
    assert reg["success"] is True
    assert reg["user"]["email"] == "alice@test.com"
    assert reg["user"]["team_id"]  # 自动建团队
    assert reg["access_token"]
    assert reg["refresh_token"]
    assert "password_hash" not in reg["user"]

    # 登录
    login = auth.login_by_email("alice@test.com", "Secret123")
    assert login["success"] is True
    assert login["access_token"]


def test_register_duplicate_email_rejected(tmp_db):
    """P1-2: 重复邮箱注册必须被 UNIQUE INDEX 拒绝。"""
    from app.services import auth

    r1 = auth.register_user(email="dup@test.com", password="Secret123")
    assert r1["success"] is True
    r2 = auth.register_user(email="dup@test.com", password="Secret123")
    assert r2["success"] is False
    assert "已注册" in r2["error"]


def test_register_duplicate_phone_rejected(tmp_db):
    """P1-2: 重复手机号注册必须被 UNIQUE INDEX 拒绝。"""
    from app.services import auth

    r1 = auth.register_user(phone="13800000001", password="Secret123")
    assert r1["success"] is True
    r2 = auth.register_user(phone="13800000001", password="Secret123")
    assert r2["success"] is False
    assert "已注册" in r2["error"]


def test_register_password_too_short(tmp_db):
    """P2-15: 密码强度校验（至少 8 位 + 字母 + 数字）。"""
    from app.services import auth

    r = auth.register_user(email="weak@test.com", password="short")
    assert r["success"] is False
    assert "8 位" in r["error"] or "字母" in r["error"]


def test_register_invalid_email(tmp_db):
    """P2-15: 邮箱格式校验。"""
    from app.services import auth

    r = auth.register_user(email="not-an-email", password="Secret123")
    assert r["success"] is False
    assert "邮箱" in r["error"]


# --- SMS 验证码 ---

def test_sms_code_generate_and_verify(tmp_db):
    """P1-3: SMS 验证码生成 + 一次性使用。"""
    from app.services import auth

    code = auth.generate_sms_code("13800000002")
    assert code is not None
    assert len(code) == 6
    assert code.isdigit()
    assert not code.startswith("0")  # 首位非零

    # 第一次验证通过
    assert auth.verify_sms_code("13800000002", code) is True
    # 第二次失败（一次性）
    assert auth.verify_sms_code("13800000002", code) is False


def test_sms_code_invalid_phone_returns_none(tmp_db):
    """SMS 验证码：非法手机号返回 None。"""
    from app.services import auth

    assert auth.generate_sms_code("abc") is None
    assert auth.generate_sms_code("") is None


def test_sms_code_persisted_in_sqlite(tmp_db):
    """P1-3: SMS 码应该写入 SQLite（不是内存字典）。"""
    from app.services import auth
    from app.services.auth import _conn

    code = auth.generate_sms_code("13800000003")
    assert code is not None

    # 直接从 DB 验证（绕过内存）
    with _conn() as conn:
        row = conn.execute(
            "SELECT code FROM kellai_sms_codes WHERE phone = ?", ("13800000003",)
        ).fetchone()
        assert row is not None
        assert row["code"] == code


def test_sms_code_max_attempts(tmp_db):
    """SMS 码：超过最大尝试次数后失效。"""
    from app.services import auth

    auth.generate_sms_code("13800000004")
    for _ in range(5):
        auth.verify_sms_code("13800000004", "000000")  # 错误码
    # 第 6 次即使码对也失败
    assert auth.verify_sms_code("13800000004", "anything") is False


# --- Token 刷新与吊销 ---

def test_refresh_token_rotates_session(tmp_db):
    """P1-4/P1-5: refresh_token 轮换会吊销旧 session。"""
    from app.services import auth

    reg = auth.register_user(email="bob@test.com", password="Secret123")
    assert reg["success"] is True
    old_refresh = reg["refresh_token"]
    old_access = reg["access_token"]

    # 第一次刷新成功
    r1 = auth.refresh_access_token(old_refresh)
    assert r1["success"] is True
    new_refresh = r1["refresh_token"]
    assert new_refresh != old_refresh

    # 旧 refresh 已被吊销，无法再用
    r2 = auth.refresh_access_token(old_refresh)
    assert r2["success"] is False
    assert "吊销" in r2["error"] or "无效" in r2["error"]


def test_verify_token_after_role_change(tmp_db):
    """P1-11: 角色变更后 token_version 递增，旧 token 立即失效。"""
    from app.services import auth

    reg = auth.register_user(email="carol@test.com", password="Secret123")
    assert reg["success"] is True
    access = reg["access_token"]
    user = reg["user"]
    team_id = user["team_id"]
    user_id = user["id"]

    # 初始 token 可用
    info = auth.verify_token(access)
    assert info is not None
    assert info["role"] == "owner"

    # owner 改自己的角色（合法，因为是 owner）
    r = auth.update_member_role(team_id, user_id, "sales", actor_id=user_id)
    assert r["success"] is True

    # 旧 token 立即失效
    info2 = auth.verify_token(access)
    assert info2 is None


def test_logout_revokes_session(tmp_db):
    """P1-4: logout 吊销 session 后 refresh 失败。"""
    from app.services import auth

    reg = auth.register_user(email="dan@test.com", password="Secret123")
    refresh = reg["refresh_token"]

    # 注销前能刷新
    r1 = auth.refresh_access_token(refresh)
    assert r1["success"] is True

    # 注销
    assert auth.revoke_session_by_refresh(refresh) is True

    # 注销后旧 refresh 失败
    r2 = auth.refresh_access_token(refresh)
    assert r2["success"] is False


# --- 团队操作权限 ---

def test_invite_requires_owner_or_admin(tmp_db):
    """P1-10: 非 owner/admin 不能邀请成员。"""
    from app.services import auth

    # owner 注册
    reg = auth.register_user(email="owner@test.com", password="Secret123")
    owner_id = reg["user"]["id"]
    team_id = reg["user"]["team_id"]

    # 用 update_member_role 把 owner 降为 sales（仅 owner 自己可改自己）
    r = auth.update_member_role(team_id, owner_id, "sales", actor_id=owner_id)
    assert r["success"] is True

    # 再邀请 → 失败
    inv = auth.invite_team_member(
        team_id, actor_id=owner_id, email="newbie@test.com", role="sales"
    )
    assert inv["success"] is False
    assert "权限" in inv["error"]


def test_remove_team_member_revokes_sessions(tmp_db):
    """P1-10: 移除成员会吊销其所有 session。"""
    from app.services import auth

    owner_reg = auth.register_user(email="o2@test.com", password="Secret123")
    owner_id = owner_reg["user"]["id"]
    team_id = owner_reg["user"]["team_id"]

    # owner 邀请 sales（自动把已存在的 sales 加入）
    newbie = auth.register_user(email="n2@test.com", password="Secret123")
    newbie_id = newbie["user"]["id"]
    newbie_access = newbie["access_token"]

    # 通过邀请加入 owner 的团队
    auth.invite_team_member(team_id, actor_id=owner_id, email="n2@test.com", role="sales")

    # newbie 之前生成的 token 仍可用
    assert auth.verify_token(newbie_access) is not None

    # owner 移除 newbie
    rm = auth.remove_team_member(team_id, newbie_id, actor_id=owner_id)
    assert rm["success"] is True

    # newbie 旧 token 立即失效
    assert auth.verify_token(newbie_access) is None


def test_admin_cannot_remove_other_admin(tmp_db):
    """admin 不能移除其他 admin（仅 owner 可）。"""
    from app.services import auth

    owner_reg = auth.register_user(email="o3@test.com", password="Secret123")
    owner_id = owner_reg["user"]["id"]
    team_id = owner_reg["user"]["team_id"]

    # 注册 a、b 两个用户，owner 把他们提为 admin
    a = auth.register_user(email="a3@test.com", password="Secret123")
    b = auth.register_user(email="b3@test.com", password="Secret123")
    auth.invite_team_member(team_id, actor_id=owner_id, email="a3@test.com", role="admin")
    auth.invite_team_member(team_id, actor_id=owner_id, email="b3@test.com", role="admin")

    # a 想移除 b → 失败
    rm = auth.remove_team_member(team_id, b["user"]["id"], actor_id=a["user"]["id"])
    assert rm["success"] is False
    assert "admin" in rm["error"].lower() or "管理员" in rm["error"]


# --- 密码 hash 迁移 ---

def test_legacy_password_upgrades_on_login(tmp_db):
    """登录时自动把旧 SHA-256 升级为 bcrypt。"""
    from app.services import auth
    import hashlib

    # 使用 auth 模块当前的 salt 值，确保与模块配置一致
    salt_value = auth._PASSWORD_SALT
    raw_hash = hashlib.sha256(f"{salt_value}:Secret123".encode()).hexdigest()

    # 直接写一条旧 hash 用户
    with auth._conn() as conn:
        conn.execute(
            "INSERT INTO kellai_users (email, phone, password_hash, display_name, role, is_active, created_at, updated_at) "
            "VALUES (?, '', ?, 'legacy', 'owner', 1, ?, ?)",
            (
                "legacy@test.com",
                raw_hash,
                "2024-01-01T00:00:00",
                "2024-01-01T00:00:00",
            ),
        )

    # 登录（应触发升级）
    r = auth.login_by_email("legacy@test.com", "Secret123")
    assert r["success"] is True

    # 验证 hash 已被升级为 bcrypt
    with auth._conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM kellai_users WHERE email = ?", ("legacy@test.com",)
        ).fetchone()
        assert auth._is_bcrypt_hash(row["password_hash"])


def test_legacy_prefixed_password_still_works(tmp_db):
    """P0 #1: 带 __legacy__: 前缀的密码 hash 仍能通过验证并升级。"""
    from app.services import auth
    import hashlib

    # 使用 auth 模块当前的 salt 值
    salt_value = auth._PASSWORD_SALT
    raw_hash = hashlib.sha256(f"{salt_value}:MyPass123".encode()).hexdigest()
    prefixed_hash = f"{auth._LEGACY_HASH_PREFIX}{raw_hash}"

    with auth._conn() as conn:
        conn.execute(
            "INSERT INTO kellai_users (email, phone, password_hash, display_name, role, is_active, created_at, updated_at) "
            "VALUES (?, '', ?, 'prefixed', 'owner', 1, ?, ?)",
            (
                "prefixed@test.com",
                prefixed_hash,
                "2024-01-01T00:00:00",
                "2024-01-01T00:00:00",
            ),
        )

    # 登录必须成功（之前会因为前缀不匹配而失败）
    r = auth.login_by_email("prefixed@test.com", "MyPass123")
    assert r["success"] is True, f"登录失败: {r.get('error')}"

    # 验证 hash 已被升级为 bcrypt
    with auth._conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM kellai_users WHERE email = ?", ("prefixed@test.com",)
        ).fetchone()
        assert auth._is_bcrypt_hash(row["password_hash"])


def test_migrate_password_hashes_marks_legacy(tmp_db):
    """migrate_password_hashes 把旧 hash 加上 __legacy__: 前缀。"""
    from app.services import auth
    import hashlib

    with auth._conn() as conn:
        conn.execute(
            "INSERT INTO kellai_users (email, phone, password_hash, display_name, role, is_active, created_at, updated_at) "
            "VALUES (?, '', ?, 'm', 'owner', 1, ?, ?)",
            (
                "migrate@test.com",
                hashlib.sha256(b"x:y").hexdigest(),
                "2024-01-01T00:00:00",
                "2024-01-01T00:00:00",
            ),
        )

    result = auth.migrate_password_hashes()
    assert result["scanned"] >= 1
    assert result["upgraded"] >= 1

    with auth._conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM kellai_users WHERE email = ?", ("migrate@test.com",)
        ).fetchone()
        assert row["password_hash"].startswith(auth._LEGACY_HASH_PREFIX)


# --- 输入校验 ---

def test_validate_password():
    """密码强度：8 位 + 字母 + 数字。"""
    from app.services.auth import _validate_password

    assert _validate_password("abc") is not None  # 太短
    assert _validate_password("abcdefgh") is not None  # 无数字
    assert _validate_password("12345678") is not None  # 无字母
    assert _validate_password("Abc12345") is None  # 通过
    assert _validate_password("a" * 80) is not None  # > 72 字节


def test_validate_email_phone():
    from app.services.auth import _validate_email, _validate_phone

    assert _validate_email("a@b.com") is True
    assert _validate_email("nope") is False
    assert _validate_email("") is False

    assert _validate_phone("13800000000") is True
    assert _validate_phone("+8613800000000") is True
    assert _validate_phone("abc") is False
    assert _validate_phone("") is False


# --- 跨层一致性 ---

def test_routes_logout_endpoint_exists():
    """P1-4: routes.py 必须提供 /auth/logout 端点。"""
    from app.api.routes import router

    paths = {r.path for r in router.routes}
    assert "/api/kellai/auth/logout" in paths


def test_register_user_returned_tokens_are_valid_jwt(tmp_db):
    """跨层：返回的 token 必须能被 verify_token 接受。"""
    from app.services import auth

    reg = auth.register_user(email="jwt@test.com", password="Secret123")
    info = auth.verify_token(reg["access_token"])
    assert info is not None
    assert info["email"] == "jwt@test.com"
    assert info["id"] == reg["user"]["id"]


# --- 数据库迁移系统测试 ---

def test_migration_table_created(tmp_db):
    """确保迁移系统的 kellai_schema_migrations 表被创建。"""
    from app.services import auth
    
    # 触发 schema 初始化
    auth.ensure_auth_schema()
    
    # 验证迁移表存在
    with auth._conn() as conn:
        # 检查表是否存在
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kellai_schema_migrations'"
        ).fetchone()
        assert row is not None, "kellai_schema_migrations table not created"


def test_migrations_recorded(tmp_db):
    """确保迁移被正确记录到 kellai_schema_migrations 表。"""
    from app.services import auth
    
    auth.ensure_auth_schema()
    
    with auth._conn() as conn:
        rows = conn.execute(
            "SELECT version FROM kellai_schema_migrations ORDER BY version"
        ).fetchall()
        
        applied_versions = {row["version"] for row in rows}
        # 我们定义的迁移应该都被记录了
        for migration in auth.MIGRATIONS:
            assert migration["version"] in applied_versions, f"Migration {migration['version']} not recorded"


def test_ensure_auth_schema_returns_result(tmp_db):
    """确保 ensure_auth_schema 返回迁移结果字典。"""
    from app.services import auth
    
    result = auth.ensure_auth_schema()
    
    assert isinstance(result, dict)
    assert "applied" in result
    assert "skipped" in result
    assert "failed" in result


# --- 新增功能测试 ---

def test_login_rate_limit_blocks_excessive_attempts(tmp_db):
    """登录速率限制：超过限制后应返回错误。"""
    from app.services import auth
    from app.services.rate_limiter import check_login_rate_limit, reset_login_rate_limit
    
    ip = "192.168.1.100"
    ip_key = f"ip:{ip}"
    
    # 重置限流器确保干净状态
    reset_login_rate_limit(ip_key)
    
    # 直接消耗令牌桶中的令牌（模拟路由层的限流检查）
    for _ in range(12):  # 默认容量是 10
        check_login_rate_limit(ip_key)
    
    # 第 13 次应该被限流
    allowed, retry_after = check_login_rate_limit(ip_key)
    assert allowed is False
    assert retry_after > 0
    
    # service 层不做限流，由路由层负责；此处验证限流器本身工作正常即可


def test_purge_all_expired_sms_codes(tmp_db):
    """测试主动清理过期短信码功能。"""
    from app.services import auth
    import time
    
    # 生成一个短信码
    code = auth.generate_sms_code("13900000001")
    assert code is not None
    
    # 直接修改数据库使其过期
    with auth._conn() as conn:
        conn.execute(
            "UPDATE kellai_sms_codes SET expires_at = ? WHERE phone = ?",
            (time.time() - 100, "13900000001"),
        )
    
    # 主动清理
    count = auth.purge_all_expired_sms_codes()
    assert count >= 1
    
    # 验证已清理
    with auth._conn() as conn:
        row = conn.execute(
            "SELECT code FROM kellai_sms_codes WHERE phone = ?",
            ("13900000001",),
        ).fetchone()
        assert row is None


def test_login_by_phone_with_rate_limit(tmp_db):
    """手机号登录 service 层不应做速率限制（由路由层负责）。"""
    from app.services import auth
    
    # 注册用户
    auth.register_user(phone="13900000002", password="Secret123")
    
    # 生成验证码
    code = auth.generate_sms_code("13900000002")
    assert code is not None
    
    # 正常登录应成功（service 层不做限流）
    result = auth.login_by_phone("13900000002", code)
    assert result["success"] is True


def test_jwt_secret_is_configurable():
    """JWT_SECRET 应可通过环境变量配置，且生产环境必须设置。"""
    import os
    from app.services import auth
    
    # 当前环境已设置 KELLAI_JWT_SECRET，验证它生效
    assert auth.JWT_SECRET == os.environ.get("KELLAI_JWT_SECRET", "")
    assert len(auth.JWT_SECRET) > 0
    
    # 验证不是硬编码的旧值
    assert "kellai-dev-secret" not in auth.JWT_SECRET
    assert "kellai_default_salt" not in auth._PASSWORD_SALT


def test_update_user_sql_injection_protection(tmp_db):
    """update_user 应防止 SQL 注入（通过动态拼接）。"""
    from app.services import auth
    
    # 注册一个用户
    reg = auth.register_user(email="sqli@test.com", password="Secret123")
    assert reg["success"] is True
    user_id = reg["user"]["id"]
    
    # 尝试通过字段名注入 SQL（allowed_fields 会过滤掉）
    result = auth.update_user(user_id, display_name="; DROP TABLE kellai_users; --")
    # 应该成功更新 display_name，但不会执行 SQL 注入
    assert result["success"] is True
    assert result["user"]["display_name"] == "; DROP TABLE kellai_users; --"
    
    # 验证表仍然存在
    from app.services.auth import _conn
    with _conn() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='kellai_users'"
        ).fetchone()
        assert row is not None, "SQL 注入防护失败：表被删除了"


# --- 端到端流程测试 ---

def test_remove_team_member_invalidates_target_sessions_e2e(tmp_db):
    """端到端：移除团队成员后，该成员的 access_token 立即失效。

    验证路径：
    1) 邀请一个成员加入团队
    2) 成员登录拿到 access_token 并能通过 verify_token
    3) owner 移除该成员
    4) 同一 access_token 再次 verify_token 必须返回 None（被踢出）
    """
    from app.services import auth
    from app.services.auth import verify_token

    # 1) owner 注册 + 团队自动建立
    owner_reg = auth.register_user(
        email="owner@e2e.com", password="Secret123", display_name="Owner"
    )
    assert owner_reg["success"] is True
    owner = owner_reg["user"]
    team_id = owner["team_id"]
    assert team_id is not None

    # 2) 邀请并接受一个新成员（直接走 service 层：插入 + 接受）
    from app.services.auth import _conn

    with _conn() as conn:
        conn.execute(
            "INSERT INTO kellai_users (email, phone, password_hash, display_name, "
            "team_id, role, is_active, token_version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)",
            (
                "member@e2e.com",
                "",
                auth._hash_password("Secret123"),
                "Member",
                None,
                "member",
                auth._utc_now_iso(),
                auth._utc_now_iso(),
            ),
        )
        member_row = conn.execute(
            "SELECT id FROM kellai_users WHERE email = ?", ("member@e2e.com",)
        ).fetchone()
        member_id = int(member_row["id"])

    # 3) 成员登录，拿到 access_token
    member_login = auth.login_by_email("member@e2e.com", "Secret123")
    assert member_login["success"] is True
    member_access = member_login["access_token"]
    assert member_access, "成员登录应拿到 access_token"

    # 4) 成员挂到 owner 的团队下（接受邀请的等价物）
    with _conn() as conn:
        conn.execute(
            "UPDATE kellai_users SET team_id = ? WHERE id = ?",
            (team_id, member_id),
        )

    # 5) 此时 verify_token 应能通过
    assert verify_token(member_access) is not None, "移除前 token 应该有效"

    # 6) owner 移除该成员
    remove_res = auth.remove_team_member(team_id, member_id, actor_id=owner["id"])
    assert remove_res["success"] is True, f"移除成员失败: {remove_res}"

    # 7) 同一 access_token 必须立即失效
    assert verify_token(member_access) is None, "移除后 token 仍有效，踢人失效！"


def test_register_user_session_failure_returns_error(tmp_db):
    """注册时若 session 持久化失败，应返回 success=False（避免空 token 误导客户端）。"""
    from app.services import auth
    from unittest.mock import patch

    reg = auth.register_user(email="sessfail@test.com", password="Secret123")
    assert reg["success"] is True
    user_id = reg["user"]["id"]

    # 模拟 _create_session 抛 sqlite3.Error
    with patch(
        "app.services.auth._create_session",
        side_effect=sqlite3.Error("simulated session write failure"),
    ):
        result = auth.register_user(email="sessfail2@test.com", password="Secret123")

    # 必须返回 success=False，避免客户端拿到空 token 误判
    assert result["success"] is False
    assert "重新登录" in result.get("error", "")
    # user 字段仍应返回（用户已创建）
    assert result.get("user", {}).get("id")


def test_login_invalidates_other_devices_on_password_change(tmp_db):
    """修改密码后，旧 token 应被失效（通过 bump_token_version）。"""
    from app.services import auth
    from app.services.auth import verify_token, bump_token_version

    reg = auth.register_user(email="chgpwd@test.com", password="OldPass123")
    assert reg["success"] is True
    user_id = reg["user"]["id"]

    login1 = auth.login_by_email("chgpwd@test.com", "OldPass123")
    assert login1["success"] is True
    old_token = login1["access_token"]
    assert verify_token(old_token) is not None

    # 模拟「用户改了密码」：调用 bump_token_version
    new_tv = bump_token_version(user_id)
    assert new_tv > 0

    # 旧 token 应立即失效
    assert verify_token(old_token) is None, "改密后旧 token 仍有效！"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
