"""Async SQLAlchemy engine and session helpers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from onigiri.config import settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs() -> dict:
    if settings.environment == "test":
        # A pooled connection outlives the event loop a test ran in, and asyncpg
        # refuses to be used from a different loop.
        return {"poolclass": NullPool}
    return {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}


engine = create_async_engine(settings.database_url, echo=False, **_engine_kwargs())

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, committed on success."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Standalone session for workers and scripts."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
