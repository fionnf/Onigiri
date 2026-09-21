"""Dispatching capture jobs: in-process for a simple deployment, arq when Redis is there."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from onigiri.config import settings
from onigiri.models import IngestJob

log = logging.getLogger(__name__)

_background: set[asyncio.Task] = set()


class JobCapReached(RuntimeError):
    pass


async def check_monthly_cap(db: AsyncSession, user_id: uuid.UUID) -> None:
    since = datetime.now(UTC) - timedelta(days=30)
    count = await db.scalar(
        select(func.count())
        .select_from(IngestJob)
        .where(IngestJob.user_id == user_id, IngestJob.created_at >= since)
    )
    if (count or 0) >= settings.monthly_job_cap:
        raise JobCapReached(
            f"You have run {count} captures in the last 30 days, which is the configured "
            f"cap of {settings.monthly_job_cap}. Raise MONTHLY_JOB_CAP to continue."
        )


async def enqueue(job_id: uuid.UUID) -> None:
    """Hand a job to the worker, or run it in this process when there is no Redis."""
    from onigiri.pipeline.run import run_job_safely

    if settings.job_backend == "arq":
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            await pool.enqueue_job("run_ingest_job", str(job_id))
            await pool.aclose()
            return
        except Exception as exc:
            log.warning("could not reach the job queue (%s); running inline", exc)

    task = asyncio.create_task(run_job_safely(job_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


async def wait_for_background() -> None:
    """Used by tests and by graceful shutdown."""
    if _background:
        await asyncio.gather(*list(_background), return_exceptions=True)
