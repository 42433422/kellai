"""Provider-authenticated callbacks, each bound to one explicit account."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import struct
import time

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from app.channels import config_store
from app.services.auth import workspace_id
from app.services.tenant_context import tenant_scope
from app.services import wechat_ingress

router = APIRouter(prefix="/api/kellai", tags=["channel-callbacks"])
MAX_BYTES = 1_048_576
logger = logging.getLogger(__name__)


async def _body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise HTTPException(413, "回调正文超过限制")
    return bytes(body)


def _account(team_id: int, connection_id: str, channel_type: str) -> dict:
    if team_id != workspace_id():
        raise HTTPException(403, "回调工作区不匹配")
    try:
        item = config_store.get_connection(connection_id, include_secrets=True)
    except KeyError as exc:
        raise HTTPException(404, "账号连接不存在") from exc
    except config_store.ConnectionUnavailable as exc:
        raise HTTPException(403, "账号连接不可用") from exc
    if item["channel_type"] != channel_type or not item.get("enabled") or item.get("status") == "revoked":
        raise HTTPException(403, "回调账号未启用或渠道不匹配")
    return item


async def _sync(team_id: int, connection_id: str) -> None:
    from app.services.channel_ingest import sync_inbox
    # State is already durable. An exception leaves the inbox for the worker.
    try:
        await sync_inbox(team_id=team_id, connection_id=connection_id)
    except Exception as exc:
        logger.warning("入站消息暂未投影: connection=%s (%s)", connection_id, type(exc).__name__)


@router.post("/webhook/chatwoot/{team_id}/{connection_id}")
async def chatwoot_webhook(team_id: int, connection_id: str, request: Request, background_tasks: BackgroundTasks):
    from app.channels.chatwoot import ChatwootSettings
    from app.services.chatwoot_gateway import WebhookRejected, authenticate, store_event
    raw = await _body(request)
    with tenant_scope(team_id):
        item = _account(team_id, connection_id, "chatwoot")
        with config_store.connection_scope(connection_id):
            settings = ChatwootSettings.load(item)
            try:
                signature = request.headers.get("x-chatwoot-signature", "")
                payload = authenticate(raw, timestamp=request.headers.get("x-chatwoot-timestamp", ""),
                                       signature=signature, settings=settings)
                result = store_event(payload, settings=settings, team_id=team_id,
                                     delivery_id=request.headers.get("x-chatwoot-delivery") or signature)
            except WebhookRejected as exc:
                raise HTTPException(exc.status_code, str(exc)) from exc
    if result.get("kind") in {"inbound", "receipt"}:
        background_tasks.add_task(_sync, team_id, connection_id)
    return result


@router.api_route("/webhook/wechat/{team_id}/{connection_id}", methods=["GET", "POST"])
async def wechat_callback(team_id: int, connection_id: str, request: Request, background_tasks: BackgroundTasks):
    try:
        with tenant_scope(team_id):
            _account(team_id, connection_id, "wechat")
            with config_store.connection_scope(connection_id):
                config = wechat_ingress.wechat_config(team_id)
                query = request.query_params
                if query.get("encrypt_type") or query.get("msg_signature"):
                    raise HTTPException(400, "公众号 AES 回调尚未接入")
                wechat_ingress.verify_wechat_signature(signature=query.get("signature", ""),
                    timestamp=query.get("timestamp", ""), nonce=query.get("nonce", ""), token=config["token"])
                if request.method == "GET":
                    return PlainTextResponse(query.get("echostr", ""))
                body = wechat_ingress.parse_xml(await _body(request))
                if body.get("Encrypt"):
                    raise HTTPException(400, "公众号 AES 回调尚未接入")
                if config["original_id"] and body.get("ToUserName") != config["original_id"]:
                    raise HTTPException(403, "公众号账号身份不匹配")
                wechat_ingress.persist_callback(channel_type="wechat", team_id=team_id, body=body)
    except wechat_ingress.WechatIngressError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    background_tasks.add_task(_sync, team_id, connection_id)
    return PlainTextResponse("success")


def _wecom_decrypt(encrypted: str, config: dict, signature: str, timestamp: str, nonce: str) -> str:
    token = str(config.get("webhook_token") or config.get("token") or "")
    key_text = str(config.get("encoding_aes_key") or "")
    corp_id = str(config.get("corp_id") or "")
    try:
        if not token or len(key_text) != 43 or not corp_id or not nonce or abs(time.time() - int(timestamp)) > 300:
            raise ValueError
        expected = hashlib.sha1("".join(sorted([token, timestamp, nonce, encrypted])).encode()).hexdigest()
        if not signature.isascii() or not hmac.compare_digest(expected, signature):
            raise ValueError
        key = base64.b64decode(key_text + "=", validate=True)
        ciphertext = base64.b64decode(encrypted, validate=True)
        decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(256).unpadder()
        plain = unpadder.update(padded) + unpadder.finalize()
        if len(plain) < 20:
            raise ValueError
        size = struct.unpack("!I", plain[16:20])[0]
        if size <= 0 or 20 + size > len(plain) or plain[20 + size:].decode() != corp_id:
            raise ValueError
        return plain[20:20 + size].decode()
    except (ValueError, UnicodeError, TypeError, struct.error) as exc:
        raise HTTPException(403, "企业微信回调签名或账号身份不匹配") from exc


@router.api_route("/webhook/wework/{team_id}/{connection_id}", methods=["GET", "POST"])
async def wecom_callback(team_id: int, connection_id: str, request: Request, background_tasks: BackgroundTasks):
    with tenant_scope(team_id):
        item = _account(team_id, connection_id, "wework")
        with config_store.connection_scope(connection_id):
            query = request.query_params
            if request.method == "GET":
                encrypted = query.get("echostr", "")
            else:
                try:
                    outer = wechat_ingress.parse_xml(await _body(request))
                except wechat_ingress.WechatIngressError as exc:
                    raise HTTPException(exc.status_code, str(exc)) from exc
                encrypted = str(outer.get("Encrypt") or "")
            plain = _wecom_decrypt(encrypted, item["config"], query.get("msg_signature", ""),
                                   query.get("timestamp", ""), query.get("nonce", ""))
            if request.method == "GET":
                return PlainTextResponse(plain)
            try:
                body = wechat_ingress.parse_xml(plain.encode())
            except wechat_ingress.WechatIngressError as exc:
                raise HTTPException(exc.status_code, str(exc)) from exc
            if body.get("ToUserName") != str(item["config"].get("corp_id") or ""):
                raise HTTPException(403, "企业微信回调企业不匹配")
            agent = str(item["config"].get("agent_id") or "")
            if agent and str(body.get("AgentID") or "") != agent:
                raise HTTPException(403, "企业微信回调应用不匹配")
            wechat_ingress.persist_callback(channel_type="wework", team_id=team_id, body=body)
    background_tasks.add_task(_sync, team_id, connection_id)
    return PlainTextResponse("success")


@router.post("/webhook/douyin/{team_id}/{connection_id}")
async def douyin_callback(team_id: int, connection_id: str, request: Request, background_tasks: BackgroundTasks):
    from app.services.douyin_channel import verify_webhook_signature
    from app.services.message_store import push_inbox
    raw = await _body(request)
    with tenant_scope(team_id):
        item = _account(team_id, connection_id, "douyin")
        with config_store.connection_scope(connection_id):
            try:
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise ValueError
                content = payload.get("content") or {}
                if isinstance(content, str):
                    content = json.loads(content)
                if not isinstance(content, dict):
                    raise ValueError
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, "抖音回调格式无效") from exc
            config = item["config"]
            event = str(payload.get("event") or "")
            signature = request.headers.get("x-douyin-signature", "")
            if event == "verify_webhook":
                # The documented URL challenge can carry an empty client_key.
                # Echoing a bounded scalar is side-effect-free; it never stores a
                # contact, session, token or message, nor proves account ownership.
                challenge = content.get("challenge")
                if type(challenge) not in {str, int} or len(str(challenge)) > 256:
                    raise HTTPException(400, "抖音回调挑战无效")
                if payload.get("client_key") not in {None, "", config.get("client_key")}:
                    raise HTTPException(403, "抖音回调应用不匹配")
                if signature and not verify_webhook_signature(raw, signature):
                    raise HTTPException(403, "抖音回调验签失败")
                return PlainTextResponse(json.dumps({"challenge": challenge}))
            # Provider ownership proof is required before storing any user data.
            if not verify_webhook_signature(raw, signature):
                raise HTTPException(403, "抖音回调验签失败")
            if str(payload.get("client_key") or "") != str(config.get("client_key") or ""):
                raise HTTPException(403, "抖音回调应用不匹配")
            auth = config.get("oauth_token") or {}
            own = str(auth.get("open_id") or "") if isinstance(auth, dict) else ""
            sender, receiver = str(payload.get("from_user_id") or ""), str(payload.get("to_user_id") or "")
            if not own or own not in {sender, receiver}:
                raise HTTPException(403, "抖音回调账号不匹配")
            if event == "unauthorize":
                config_store.update_connection(connection_id, {"oauth_token": {}}, connected=False,
                                               status="requires_reconnect", expected_version=item["version"])
                return {"success": True, "data": {"revoked": True}}
            if event != "receive_msg" or receiver != own:
                return {"success": True, "data": {"ignored": True}}
            if not sender:
                raise HTTPException(400, "抖音回调缺少发送人")
            identifier = str(content.get("server_message_id") or content.get("message_id") or content.get("msg_id")
                             or payload.get("message_id") or request.headers.get("Msg-Id") or "")
            kind = str(content.get("message_type") or "unsupported")
            text = str(content.get("text") or content.get("title") or content.get("resource_url") or "")
            mid = push_inbox("douyin", contact_id=sender, contact_name=sender, direction="inbound",
                content=text, content_type="text" if kind == "text" else "unsupported",
                msg_id="douyin:" + identifier if identifier else None,
                metadata={"owner_open_id": own, "source": "verified_callback", "provider_message_id": identifier,
                          "dedupe_available": bool(identifier), "event": event})
    background_tasks.add_task(_sync, team_id, connection_id)
    return {"success": True, "data": {"message_id": mid, "queued": True}}
