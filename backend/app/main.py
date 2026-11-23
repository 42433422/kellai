"""Local XCMAX account and channel tool. Business decisions belong to the host."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.services.auth import LOCAL_ORIGINS, require_local_request, verify_token, workspace_id
from app.services.tenant_context import bind_request_tenant, reset_request_tenant
from app.build_info import load_build_info

logger = logging.getLogger("kellai")
# Provider URLs may contain API keys (for example Telegram bot tokens).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
class _AccessPathOnly(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn access records contain the request target at argument 2.
        # OAuth authorization codes and state must never enter persistent logs.
        if isinstance(record.args, tuple) and len(record.args) == 5 and isinstance(record.args[2], str):
            values = list(record.args)
            values[2] = values[2].split("?", 1)[0]
            record.args = tuple(values)
        return True


logging.getLogger("uvicorn.access").addFilter(_AccessPathOnly())
DEFAULT_CORS_ORIGINS = sorted(LOCAL_ORIGINS)


def _load_cors_origins() -> list[str]:
    # Public callbacks do not need CORS. Keep operator requests on known local
    # origins even if an old SaaS deployment still sets a wildcard env value.
    return list(DEFAULT_CORS_ORIGINS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.channels import ChannelRegistry
    from app.services.channel_worker import run
    from app.services.message_store import ensure_messages_schema
    workspace_id()  # Ambiguous legacy ownership must fail before any worker.
    ensure_messages_schema()
    stop = asyncio.Event()
    worker = (asyncio.create_task(run(stop))
              if os.environ.get("KELLAI_CHANNEL_WORKER_ENABLED", "1").strip() != "0" else None)
    try:
        yield
    finally:
        stop.set()
        try:
            if worker is not None:
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
        finally:
            await ChannelRegistry().close_all()


try:
    APP_VERSION = version("kellai")
except PackageNotFoundError:
    APP_VERSION = "0+source"

BUILD_INFO = load_build_info(APP_VERSION)

app = FastAPI(title="客来来账号与通道工具", version=APP_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=_load_cors_origins(),
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Authorization", "Content-Type", "X-Kellai-Desktop-Handoff", "X-Kellai-Local-Pairing"])


@app.middleware("http")
async def authenticate(request: Request, call_next):
    path = request.url.path
    public = path in {"/health", "/api/kellai/status"}
    handoff = path == "/api/kellai/auth/xcmax-desktop"
    gateway = path.startswith("/api/kellai/integrations/xcmax/") and (
        path.endswith(("/channels", "/contacts", "/grant-status")) or "/contacts/" in path or "/messages/" in path)
    callback = bool(re.fullmatch(r"/api/kellai/webhook/[a-z0-9_]+/[1-9][0-9]*/[A-Za-z0-9_-]+", path))
    oauth_callback = request.method == "GET" and path == "/api/kellai/accounts/oauth/callback"
    request.state.user = None
    tokens = bind_request_tenant(None)
    try:
        if request.method != "OPTIONS" and not (public or callback or oauth_callback):
            require_local_request(request)
            if not (handoff or gateway):
                authorization = request.headers.get("authorization", "")
                token = authorization[7:] if authorization.startswith("Bearer ") else ""
                user = verify_token(token)
                if user is None:
                    return JSONResponse(status_code=401, content={"success": False, "error": "请从 XCMAX 重新打开账号工具"})
                reset_request_tenant(tokens)
                tokens = bind_request_tenant(user)
                request.state.user = user
        return await call_next(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content=_http_error_content(exc))
    finally:
        reset_request_tenant(tokens)


def _http_error_content(exc: HTTPException) -> dict:
    if isinstance(exc.detail, dict):
        return {"success": False, "error": str(exc.detail.get("message") or "操作被拒绝"), "detail": exc.detail}
    return {"success": False, "error": str(exc.detail)}


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=_http_error_content(exc))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"success": False, "error": "参数无效",
        "details": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logger.error("工具请求失败: %s %s (%s)", request.method, request.url.path, type(exc).__name__)
    return JSONResponse(status_code=500, content={"success": False, "error": "工具请求未完成，请检查本地配置"})


@app.get("/health")
def health():
    return {"status": "ok", "service": "kellai-account-tool", "protocol_version": 2,
            "build_info": BUILD_INFO}


from app.api.routes import router
from app.api.xcmax_channels import router as xcmax_router
from app.api.channel_gateway import router as callback_router
from app.api.accounts import router as accounts_router
app.include_router(router)
app.include_router(xcmax_router)
app.include_router(callback_router)
app.include_router(accounts_router)


def run() -> None:
    import uvicorn
    uvicorn.run("app.main:app", host=os.environ.get("KELLAI_HOST", "127.0.0.1"),
                port=int(os.environ.get("KELLAI_PORT", "8793")))
