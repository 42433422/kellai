"""客来来 FastAPI 入口。"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router

# --- 日志基础配置 ---
logging.basicConfig(
    level=os.environ.get("KELLAI_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("kellai")

# --- 配置验证 ---
def _validate_configuration() -> None:
    """验证关键配置项，生产环境强制要求安全配置。"""
    from app.services.auth import JWT_SECRET, _PASSWORD_SALT
    
    app_env = os.environ.get("KELLAI_APP_ENV", "development").lower()
    is_production = app_env in ("production", "prod")
    strict_auth = os.environ.get("KELLAI_STRICT_AUTH", "0") == "1"
    
    # 生产环境关键配置检查
    if is_production:
        errors = []
        
        # 1. JWT_SECRET 必须配置
        if JWT_SECRET == "kellai-dev-secret-change-in-production-2026":
            errors.append("KELLAI_JWT_SECRET 未设置 - 生产环境必须使用自定义的强密钥")
        
        # 2. PASSWORD_SALT 必须配置（如果还在使用旧版的话）
        if _PASSWORD_SALT == "kellai_default_salt_2026":
            logger.warning("⚠️  生产环境建议设置 KELLAI_PASSWORD_SALT（虽然主要使用 bcrypt）")
        
        # 3. 建议启用严格认证模式
        if not strict_auth:
            logger.warning("⚠️  生产环境建议设置 KELLAI_STRICT_AUTH=1 以启用强制 token 验证")
        
        if errors:
            logger.critical("=" * 60)
            logger.critical("❌  生产环境配置验证失败，必须修复以下问题：")
            for err in errors:
                logger.critical(f"   - {err}")
            logger.critical("=" * 60)
            # 在生产环境，配置错误应该导致启动失败
            sys.exit(1)
    else:
        # 开发环境友好提示
        if JWT_SECRET == "kellai-dev-secret-change-in-production-2026":
            logger.warning("⚠️  当前使用默认 JWT_SECRET，仅适用于开发环境")
        if not strict_auth:
            logger.warning("⚠️  当前处于软认证模式，未携带 token 的请求也会被放行（仅开发环境）")

# --- 运行模式：KELLAI_STRICT_AUTH=1 时强制 token 验证（生产环境） ---
_STRICT_AUTH = os.environ.get("KELLAI_STRICT_AUTH", "0") == "1"

# --- 执行配置验证 ---
_validate_configuration()


# --- 默认配置 ---

DEFAULT_CORS_ORIGINS: list[str] = [
    "tauri://localhost",
    "tauri://127.0.0.1",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:8790",
    "http://127.0.0.1:8790",
]


def _load_cors_origins() -> list[str]:
    """从 KELLAI_CORS_ORIGINS 读取白名单（逗号分隔），回退到默认"""
    raw = (os.environ.get("KELLAI_CORS_ORIGINS") or "").strip()
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or list(DEFAULT_CORS_ORIGINS)


def _ensure_data_dir() -> None:
    if not os.environ.get("KELLAI_DATA_DIR"):
        repo_data = Path(__file__).resolve().parents[2] / "data"
        os.environ.setdefault("KELLAI_DATA_DIR", str(repo_data))


def _bootstrap_auth() -> None:
    """启动时：建表 + 迁移密码 hash + 版本化迁移"""
    try:
        from app.services.auth import ensure_auth_schema, migrate_password_hashes

        migration_result = ensure_auth_schema()
        if migration_result:
            applied_count = len(migration_result.get("applied", []))
            skipped_count = len(migration_result.get("skipped", []))
            failed_count = len(migration_result.get("failed", []))
            if applied_count > 0:
                logger.info(f"✅ 成功应用 {applied_count} 个数据库迁移")
            if skipped_count > 0:
                logger.debug(f"跳过 {skipped_count} 个已应用的迁移")
            if failed_count > 0:
                logger.error(f"❌ {failed_count} 个迁移失败")
        
        # 密码 hash 迁移
        result = migrate_password_hashes()
        logger.info("auth 启动完成: %s", result)
    except Exception as exc:  # pragma: no cover - 启动时尽力而为
        logger.warning("auth 启动引导失败: %s", exc)


# --- 全局错误处理 ---


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """统一 HTTPException 返回 {success, error, code}"""
    detail = exc.detail
    if isinstance(detail, dict):
        msg = str(detail.get("message") or detail.get("error") or detail)
    else:
        msg = str(detail) if detail is not None else "请求失败"
    payload = {"success": False, "error": msg, "code": exc.status_code}
    headers = getattr(exc, "headers", None)
    return JSONResponse(status_code=exc.status_code, content=payload, headers=headers)


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求参数验证失败：返回 details 列表"""
    errors = exc.errors() if hasattr(exc, "errors") else []
    # 将每个错误转为简洁的 dict
    details: list[dict] = []
    for err in errors:
        try:
            details.append(
                {
                    "loc": list(err.get("loc", []) or []),
                    "msg": err.get("msg", ""),
                    "type": err.get("type", ""),
                }
            )
        except Exception:
            details.append({"msg": str(err)})
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": "参数验证失败",
            "details": details,
            "code": 422,
        },
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理：避免堆栈暴露给客户端"""
    logger.exception("未处理异常: %s %s -> %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "服务内部错误", "code": 500},
    )


# --- 软认证 + 请求日志中间件 ---


# 软认证白名单（不强制 token，也不打印警告）
_SOFT_AUTH_WHITELIST: set[str] = {
    "/health",
    "/api/kellai/status",
    "/api/kellai/landing/sync",
    "/docs",
    "/openapi.json",
    "/redoc",
}


def _get_client_ip(request: Request) -> str:
    """获取客户端真实 IP（支持 X-Forwarded-For 反向代理）"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _extract_bearer(request: Request) -> str:
    """从 Authorization 头提取 Bearer token，未带则返回空串"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return ""


async def _request_log_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable],
):
    """软认证 + 请求日志中间件

    - 软认证：解析 Authorization 头，把用户信息挂到 request.state.user
      - 路径在白名单内：不强制要求 token
      - 路径不在白名单：未带 token 时打印警告，但仍允许访问（过渡方案）
    - 记录 method / path / status / duration_ms / user_id
    """
    start = time.perf_counter()
    path = request.url.path
    user_id: object = "-"
    user_info: dict | None = None

    token = _extract_bearer(request)
    if token:
        try:
            from app.services.auth import verify_token

            info = verify_token(token)
            if info and "id" in info:
                user_info = info
                user_id = info["id"]
            else:
                # token 无效
                if path not in _SOFT_AUTH_WHITELIST:
                    if _STRICT_AUTH:
                        return JSONResponse(
                            status_code=401,
                            content={"success": False, "error": "token 无效或已过期", "code": 401},
                        )
                    logger.warning("soft-auth: 无效 token 放行 path=%s", path)
        except Exception as exc:  # pragma: no cover - 解析失败不影响主流程
            logger.debug("软认证解析异常: %s", exc)
    else:
        if path not in _SOFT_AUTH_WHITELIST:
            if _STRICT_AUTH:
                return JSONResponse(
                    status_code=401,
                    content={"success": False, "error": "未提供认证 token", "code": 401},
                )
            # 软认证：未带 token 警告但仍放行（演示阶段）
            logger.warning("soft-auth: 未带 token 访问受保护接口 path=%s（演示模式放行）", path)

    # 把 user 挂到 request.state，便于路由层依赖读取
    request.state.user = user_info
    request.state.user_id = user_id

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        logger.warning(
            "request exception: %s %s duration=%.2fms user_id=%s err=%s",
            request.method,
            path,
            duration_ms,
            user_id,
            exc,
        )
        raise

    duration_ms = (time.perf_counter() - start) * 1000.0
    logger.info(
        "request %s %s status=%s duration=%.2fms user_id=%s",
        request.method,
        path,
        status_code,
        duration_ms,
        user_id,
    )
    return response


# --- 应用工厂 ---


def create_app() -> FastAPI:
    _ensure_data_dir()
    _bootstrap_auth()

    app = FastAPI(title="客来来", version="0.1.0", description="商机流水线 · 独立于 XCAGI")

    # CORS：白名单
    origins = _load_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 全局异常处理
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    # 请求日志中间件（通过 BaseHTTPMiddleware 注入）
    @app.middleware("http")
    async def _log_middleware(request: Request, call_next):  # type: ignore[no-redef]
        return await _request_log_middleware(request, call_next)

    # 路由
    app.include_router(router)

    @app.get("/health")
    def health():
        return {"ok": True, "product": "客来来"}

    return app


app = create_app()


def run() -> None:
    import uvicorn

    port = int(os.environ.get("KELLAI_PORT", "8790"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)


if __name__ == "__main__":
    run()
