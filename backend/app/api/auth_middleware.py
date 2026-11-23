"""Authenticated local operator dependency; XCMAX gateway uses its own grant."""
from typing import Annotated

from fastapi import Depends, HTTPException, Request


def current_user(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="请从 XCMAX 打开账号工具")
    return user


CurrentUser = Annotated[dict, Depends(current_user)]
