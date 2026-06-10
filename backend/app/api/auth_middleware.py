"""JWT 认证中间件。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from typing import Annotated


def get_current_user(request: Request) -> dict:
    """从请求头获取当前用户。Authorization: Bearer <token>"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth[7:]
    from app.services.auth import verify_token
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期")
    return user


def require_role(*roles: str):
    """角色权限装饰器"""
    def _checker(current_user: Annotated[dict, Depends(get_current_user)]) -> dict:
        if current_user.get("role") not in roles and current_user.get("role") != "owner":
            raise HTTPException(status_code=403, detail="权限不足")
        return current_user
    return _checker


CurrentUser = Annotated[dict, Depends(get_current_user)]
