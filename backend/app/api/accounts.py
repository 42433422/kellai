"""Local account wallet. Public responses never include credential values."""
from __future__ import annotations

import inspect
import os
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.channels import config_store
from app.channels.registry import ChannelRegistry
from app.services import credential_vault, oauth_client

router = APIRouter(prefix="/api/kellai/accounts", tags=["accounts"])


class CreateAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_type: str = Field(min_length=1, max_length=32)
    name: str = Field(default="", max_length=100)
    auth_type: str = "credentials"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class UpdateAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=100)
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    expected_version: int = Field(gt=0)


def _actor(request: Request, *, manage: bool = False):
    from app.services.messaging import request_actor
    return request_actor(request, manage=manage)


def _editable_config(config: dict[str, Any] | None, account: dict | None = None):
    if config is None:
        return None
    saved = account["config"] if account else {}
    editable = dict(config)
    for key, value in config.items():
        if key.startswith("oauth_") or key in {"external_account_id", "account_name"}:
            # The editor may echo public metadata and masks, but only a verified
            # provider callback/refresh may install authorization or its identity.
            if key not in saved or value != saved[key]:
                raise HTTPException(400, "账号授权与身份字段只能由平台授权流程更新")
            editable.pop(key)
    return editable


@contextmanager
def _errors():
    try:
        yield
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(404, "账号连接不存在") from exc
    except config_store.ConnectionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except config_store.ConnectionUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    except credential_vault.VaultUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, "账号访问被拒绝") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "账号配置或授权请求无效") from exc


@router.get("")
def list_accounts(request: Request):
    _actor(request)
    with _errors():
        return {"success": True, "data": config_store.list_connections()}


@router.post("")
def create_account(body: CreateAccount, request: Request):
    _actor(request, manage=True)
    with _errors():
        kind = config_store._canonical(body.channel_type)
        channel = next((row for row in ChannelRegistry().list_channels() if row["channel_type"] == kind), None)
        if channel is None:
            raise HTTPException(400, "不支持的渠道类型")
        if body.auth_type not in channel["auth_types"]:
            raise HTTPException(400, "该渠道不支持所选账号授权方式")
        item = config_store.create_connection(kind, _editable_config(body.config), name=body.name,
                                               auth_type=body.auth_type, enabled=body.enabled)
        return {"success": True, "data": item}


@router.get("/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(request: Request):
    if any(len(request.query_params.getlist(key)) != 1 for key in ("state", "code")):
        return HTMLResponse("<h1>授权未完成</h1><p>请返回客来来重新连接账号。</p>", status_code=400,
                            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    try:
        state, code = request.query_params["state"], request.query_params["code"]
        if state.startswith("d."):
            from app.services.douyin_channel import complete_oauth
            await complete_oauth(state=state, code=code)
        else:
            await oauth_client.complete(state=state, code=code)
    except Exception:
        return HTMLResponse("<h1>授权未完成</h1><p>授权已过期、被拒绝或账号不匹配，请返回客来来重新连接。</p>",
                            status_code=400, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return HTMLResponse("<h1>账号已连接</h1><p>请关闭此页，返回客来来刷新账号列表。</p>",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/{connection_id}")
def get_account(connection_id: str, request: Request):
    _actor(request)
    with _errors():
        return {"success": True, "data": config_store.get_connection(connection_id)}


@router.patch("/{connection_id}")
async def update_account(connection_id: str, body: UpdateAccount, request: Request):
    _actor(request, manage=True)
    with _errors():
        fields = body.model_dump(exclude_unset=True)
        if fields.get("config") is not None:
            fields["config"] = _editable_config(fields["config"], config_store.get_connection(connection_id))
        item = config_store.update_connection(connection_id, **fields)
        await ChannelRegistry().invalidate(connection_id=connection_id)
        return {"success": True, "data": item}


@router.delete("/{connection_id}")
async def delete_account(connection_id: str, request: Request):
    _actor(request, manage=True)
    with _errors():
        item = config_store.get_connection(connection_id)
        result = {"deleted": True}
        if item["status"] == "deleted":
            return {"success": True, "data": result}
        if item["channel_type"] in {"oauth2", "douyin"}:
            result.update(await oauth_client.disconnect(connection_id))
        config_store.delete_connection(connection_id)
        await ChannelRegistry().invalidate(connection_id=connection_id)
        return {"success": True, "data": result}


@router.post("/{connection_id}/test")
async def test_account(connection_id: str, request: Request):
    _actor(request, manage=True)
    with _errors():
        item = config_store.get_connection(connection_id)
        tested_version = item["version"]
        if item["auth_type"] == "browser":
            result = {"connected": False, "verification_level": "blocked",
                      "message": "尚未绑定可验证的浏览器执行器"}
        else:
            adapter = ChannelRegistry().get(item["channel_type"], connection_id=connection_id)
            try:
                checked = await adapter.test_connection()
                tested_version = checked.get("config_version", tested_version)
                verified = bool(checked.get("connected"))
                result = {"connected": verified,
                          "verification_level": "authenticated" if verified else "configured",
                          "message": "账号鉴权通过" if verified else "连接检查未通过，请核对配置和服务商权限"}
            except Exception:
                result = {"connected": False, "verification_level": "configured",
                          "message": "连接检查未通过，请核对配置和服务商权限"}
        # Testing may legitimately refresh an OAuth token; persist against the current
        # version only if the original config did not otherwise change.
        current = config_store.get_connection(connection_id)
        if current["version"] != tested_version:
            raise config_store.ConnectionConflict("测试期间账号配置发生变化，请重新测试")
        account = config_store.update_connection(connection_id, connected=result["connected"],
                                                 expected_version=current["version"])
        if result["connected"] and not account["connected"]:
            raise config_store.ConnectionConflict("验证期间账号授权发生变化，请重新连接")
        result["account"] = account
        await ChannelRegistry().invalidate(connection_id=connection_id)
        return {"success": True, "data": result}


@router.post("/{connection_id}/oauth/start")
async def start_oauth(connection_id: str, request: Request):
    _actor(request, manage=True)
    with _errors():
        redirect_uri = os.environ.get("KELLAI_OAUTH_CALLBACK_URL", "").strip()
        if not redirect_uri:
            redirect_uri = str(request.base_url).rstrip("/") + oauth_client.CALLBACK_PATH
        redirect_uri = oauth_client.validate_callback_url(redirect_uri)
        item = config_store.get_connection(connection_id)
        if item["channel_type"] == "douyin":
            from app.services.douyin_channel import create_oauth_url
            result = create_oauth_url(connection_id, redirect_uri)
            if inspect.isawaitable(result):
                result = await result
        else:
            result = await oauth_client.start(connection_id, redirect_uri)
        return {"success": True, "data": result}


@router.post("/{connection_id}/disconnect")
async def disconnect_account(connection_id: str, request: Request):
    _actor(request, manage=True)
    with _errors():
        item = config_store.get_connection(connection_id)
        if item["channel_type"] in {"oauth2", "douyin"}:
            result = await oauth_client.disconnect(connection_id)
        else:
            config_store.update_connection(connection_id, enabled=False, connected=False, status="revoked",
                                             expected_version=item["version"])
            result = {"local_disabled": True, "provider_revoked": False}
        await ChannelRegistry().invalidate(connection_id=connection_id)
        return {"success": True, "data": result}
