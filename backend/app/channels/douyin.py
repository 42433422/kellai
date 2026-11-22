"""Official enterprise.im transport. No SaaS relay or desktop-coordinate sender."""
from __future__ import annotations

import json

import httpx

from app.channels.base import ChannelAdapter, UnifiedMessage
from app.channels.http_client import checked_json, send_error
from app.services.douyin_channel import DOUYIN_API_BASE, access_context
from app.services.tenant_context import current_team_id


class DouyinAdapter(ChannelAdapter):
    channel_type = "douyin"

    async def send_message(self, contact_id: str, content: str, **kwargs) -> dict:
        if not contact_id or not content.strip() or contact_id.startswith(("group:", "anonymous:")):
            return send_error("官方私信需要明确的用户 open_id 与文本", definitely_not_sent=True)
        try:
            auth = await access_context(current_team_id())
        except Exception:
            return send_error("账号未完成 enterprise.im 授权，请重新连接", definitely_not_sent=True)
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
                response = await client.post(DOUYIN_API_BASE + "/enterprise/im/message/send/",
                    params={"open_id": auth["open_id"]}, headers={"access-token": auth["access_token"]},
                    json={"message_type": "text", "to_user_id": contact_id,
                          "content": json.dumps({"text": content}, ensure_ascii=False)})
            body = checked_json(response)
            data = body.get("data") or {}
            if str(data.get("error_code")) != "0":
                return send_error("抖音拒绝此私信请求", definitely_not_sent="error_code" in data)
            identifier = str(data.get("server_msg_id") or data.get("message_id") or "")
            if not identifier:
                return send_error("抖音未返回消息编号，发送结果待确认")
            return {"success": True, "message_id": identifier, "delivery_state": "accepted",
                    "open_id": auth["open_id"], "error": ""}
        except Exception:
            return send_error("抖音发送结果未知，请读取原请求回执")

    async def receive_messages(self, since: str = "", limit: int = 50) -> list[UnifiedMessage]:
        from app.services.message_store import list_inbox
        return [UnifiedMessage(id=row["id"], customer_id=0, connection_id=row["connection_id"],
            channel_type="douyin", contact_id=row["contact_id"], contact_name=row["contact_name"],
            direction=row["direction"], content=row["content"], content_type=row["content_type"],
            metadata=row["metadata"], created_at=row["received_at"])
            for row in list_inbox("douyin", limit=limit) if not since or row["received_at"] > since]

    async def get_contacts(self, keyword: str = "", limit: int = 80) -> list[dict]:
        from app.channels.config_store import current_connection_id
        from app.services.message_store import list_contacts
        return [row for row in list_contacts(connection_id=current_connection_id(required=True), limit=limit)
                if not keyword or keyword in row["contact_name"]]

    async def test_connection(self, **kwargs) -> dict:
        auth = await access_context(current_team_id())
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = await client.post(DOUYIN_API_BASE + "/oauth/userinfo/",
                json={"open_id": auth["open_id"], "access_token": auth["access_token"]},
                headers={"access-token": auth["access_token"]})
        data = checked_json(response).get("data") or {}
        valid = str(data.get("error_code")) == "0" and str(data.get("open_id") or "") == auth["open_id"]
        from app.channels.config_store import current_connection_id, get_connection
        current = get_connection(current_connection_id(required=True))
        return {"connected": valid, "verification_level": "authenticated" if valid else "blocked",
                "config_version": current["version"],
                "message": "官方账号身份读取成功" if valid else "账号身份读取失败"}
