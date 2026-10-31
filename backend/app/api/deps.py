"""Authentication and workspace authorisation dependencies."""
from __future__ import annotations

import re
from typing import Any

from fastapi import Depends, Header, HTTPException, status

from app.core.security import verify_token
from app.database.mongo import get_db

_WS = re.compile(r"^[a-z0-9_-]{1,32}$")


async def user_from_token(token: str | None) -> dict[str, Any]:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue")
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired - sign in again")
    user = await get_db().users.find_one({"_id": user_id})
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found")
    return user


async def current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = authorization.split(" ", 1)[1] if authorization and authorization.lower().startswith("bearer ") else None
    return await user_from_token(token)


def check_workspace(user: dict[str, Any], workspace_id: str) -> str:
    if not _WS.match(workspace_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid workspace id")
    if workspace_id not in user.get("workspaces", ["default"]):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this workspace")
    return workspace_id


async def current_scope(user: dict[str, Any] = Depends(current_user),
                        x_workspace_id: str = Header(default="default")) -> tuple[dict[str, Any], str]:
    return user, check_workspace(user, x_workspace_id)
