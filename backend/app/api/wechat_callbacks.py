"""Tenant-bound public callbacks; provider authentication replaces user login."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from app.services import wechat_ingress

router = APIRouter(prefix="/api/kellai", tags=["channel-callbacks"])
logger = logging.getLogger(__name__)


async def _body(request: Request) -> bytes:
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > wechat_ingress.MAX_CALLBACK_BYTES:
            raise wechat_ingress.WechatIngressError("回调正文超过大小限制", 413)
        chunks.append(chunk)
    return b"".join(chunks)


async def _wechat(request: Request, background: BackgroundTasks, team_id: int) -> PlainTextResponse:
    try:
        config = wechat_ingress.wechat_config(team_id)
        query = request.query_params
        if query.get("encrypt_type") or query.get("msg_signature"):
            raise wechat_ingress.WechatIngressError("微信公众号 AES 回调尚未启用，请配置明文回调模式", 400)
        wechat_ingress.verify_wechat_signature(
            signature=query.get("signature", ""), timestamp=query.get("timestamp", ""),
            nonce=query.get("nonce", ""), token=config["token"],
        )
        if request.method == "GET":
            echo = query.get("echostr", "")
            if not echo:
                raise wechat_ingress.WechatIngressError("微信回调验证缺少 echostr")
            return PlainTextResponse(echo)
        body = wechat_ingress.parse_xml(await _body(request))
        if body.get("Encrypt"):
            raise wechat_ingress.WechatIngressError("微信公众号 AES 回调尚未启用", 400)
        if config["original_id"] and body.get("ToUserName") != config["original_id"]:
            raise wechat_ingress.WechatIngressError("微信回调帐号不属于此团队", 403)
        wechat_ingress.persist_callback(channel_type="wechat", team_id=team_id, body=body)
    except wechat_ingress.WechatIngressError as exc:
        return PlainTextResponse(str(exc), status_code=exc.status_code)
    except Exception:
        logger.exception("微信回调尚未持久化: team=%s", team_id)
        return PlainTextResponse("回调持久化暂不可用，请重试", status_code=503)
    # Acknowledge only after the durable inbox commits. CRM/queue projection is
    # independent of the provider's short response deadline and can be retried.
    background.add_task(wechat_ingress.sync_persisted_callback, team_id=team_id, channel_type="wechat")
    return PlainTextResponse("success")


@router.api_route("/webhook/wechat/{team_id}", methods=["GET", "POST"])
async def wechat_team_callback(request: Request, background_tasks: BackgroundTasks, team_id: int):
    return await _wechat(request, background_tasks, team_id)


@router.get("/webhook/wechat")
async def wechat_webhook_verify(request: Request, background_tasks: BackgroundTasks):
    try:
        team_id = wechat_ingress.legacy_wechat_team()
    except wechat_ingress.WechatIngressError as exc:
        return PlainTextResponse(str(exc), status_code=exc.status_code)
    return await _wechat(request, background_tasks, team_id)


@router.post("/webhook/wechat")
async def wechat_webhook_receive(request: Request, background_tasks: BackgroundTasks):
    return await wechat_webhook_verify(request, background_tasks)


@router.api_route("/webhook/wework", methods=["GET", "POST"])
async def wecom_webhook_receive(
    request: Request, background_tasks: BackgroundTasks,
    msg_signature: str = "", timestamp: str = "", nonce: str = "", echostr: str = "",
):
    from app.services import wework_suite

    try:
        if not msg_signature or not timestamp or not nonce:
            raise wechat_ingress.WechatIngressError("企业微信回调签名参数不完整", 403)
        if request.method == "GET":
            if not echostr:
                raise wechat_ingress.WechatIngressError("企业微信验证缺少 echostr")
            wework_suite.verify_signature(msg_signature, timestamp, nonce, echostr)
            return PlainTextResponse(wework_suite.decrypt_callback(echostr, validate_suite_id=False))
        outer = wechat_ingress.parse_xml(await _body(request))
        encrypted = str(outer.get("Encrypt") or "")
        if not encrypted:
            raise wechat_ingress.WechatIngressError("企业微信回调缺少 Encrypt")
        wework_suite.verify_signature(msg_signature, timestamp, nonce, encrypted)
        plaintext = wework_suite.decrypt_callback(encrypted, validate_suite_id=False)
        body = wechat_ingress.parse_xml(plaintext.encode("utf-8"))
        # Only this verified plaintext corporation ID is an authority. Ignore
        # any team_id or corporation fields in the outer untrusted envelope.
        authorization = wework_suite.resolve_callback_authorization(str(body.get("ToUserName") or ""))
        expected_agent = str(authorization.get("agent_id") or "")
        agent_id = str(body.get("AgentID") or "")
        if expected_agent and (agent_id or body.get("MsgType") != "event") and agent_id != expected_agent:
            raise wechat_ingress.WechatIngressError("企业微信回调应用与授权不一致", 403)
        team_id = int(authorization["team_id"])
        wechat_ingress.persist_callback(channel_type="wework", team_id=team_id, body=body)
    except wechat_ingress.WechatIngressError as exc:
        return PlainTextResponse(str(exc), status_code=exc.status_code)
    except wework_suite.WeWorkSuiteError as exc:
        return PlainTextResponse(str(exc), status_code=403)
    except Exception:
        logger.exception("企业微信回调尚未持久化")
        return PlainTextResponse("回调持久化暂不可用，请重试", status_code=503)
    background_tasks.add_task(wechat_ingress.sync_persisted_callback, team_id=team_id, channel_type="wework")
    return PlainTextResponse("success")
