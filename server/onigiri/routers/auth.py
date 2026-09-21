"""Sign in and out. One account, so there is no registration flow."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.config import settings
from onigiri.db import get_db
from onigiri.models import User
from onigiri.schemas import LoginRequest, MeResponse
from onigiri.security import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    current_user,
    hash_password,
    make_session_token,
    needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=MeResponse)
async def login(
    body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
) -> MeResponse:
    user = await db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    response.set_cookie(
        SESSION_COOKIE,
        make_session_token(user.id),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return MeResponse(id=user.id, email=user.email)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=MeResponse)
async def me(user: User = Depends(current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email)
