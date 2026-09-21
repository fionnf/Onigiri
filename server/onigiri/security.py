"""Password hashing and signed session cookies for the single owner account."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.config import settings
from onigiri.db import get_db
from onigiri.models import User

SESSION_COOKIE = "onigiri_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 90  # 90 days

_hasher = PasswordHasher()
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="onigiri-session")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def make_session_token(user_id: uuid.UUID) -> str:
    return _serializer.dumps({"uid": str(user_id), "iat": datetime.now(UTC).isoformat()})


def read_session_token(token: str) -> uuid.UUID | None:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return uuid.UUID(data["uid"])
    except (BadSignature, SignatureExpired, KeyError, ValueError, TypeError):
        return None


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    user_id = read_session_token(token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown account")
    return user
