from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from app.api.deps import current_user
from app.core.config import get_settings
from app.core.security import create_token, hash_password, verify_password
from app.core.utils import new_id, utcnow
from app.database.mongo import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=60)


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {"id": user["_id"], "username": user["username"], "display_name": user.get("display_name"),
            "is_demo": bool(user.get("is_demo")), "workspaces": user.get("workspaces", ["default"]),
            "clock_offset_seconds": user.get("clock_offset_seconds", 0)}


@router.post("/register")
async def register(body: Credentials) -> dict[str, Any]:
    if not get_settings().allow_signup:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up is disabled on this deployment")
    user = {"_id": new_id("usr"), "username": body.username.lower(), "display_name": body.display_name or body.username,
            "password_hash": hash_password(body.password), "is_demo": False, "workspaces": ["default"],
            "memory_version": 0, "clock_offset_seconds": 0, "created_at": utcnow()}
    try:
        await get_db().users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status.HTTP_409_CONFLICT, "That username is taken")
    return {"token": create_token(user["_id"]), "user": public_user(user)}


@router.post("/login")
async def login(body: Credentials) -> dict[str, Any]:
    user = await get_db().users.find_one({"username": body.username.lower()})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    return {"token": create_token(user["_id"]), "user": public_user(user)}


@router.get("/me")
async def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return public_user(user)
