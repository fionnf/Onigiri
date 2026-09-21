"""arq worker entry point. Used when JOB_BACKEND=arq."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from arq.connections import RedisSettings

from onigiri.config import settings
from onigiri.pipeline.run import run_job

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("onigiri.worker")


async def run_ingest_job(ctx: dict[str, Any], job_id: str) -> None:
    await run_job(uuid.UUID(job_id))


async def startup(ctx: dict[str, Any]) -> None:
    log.info("worker ready")


async def shutdown(ctx: dict[str, Any]) -> None:
    from onigiri.db import engine

    await engine.dispose()


class WorkerSettings:
    functions = [run_ingest_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 2
    job_timeout = 1800
    keep_result = 3600
