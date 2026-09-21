"""The Onigiri HTTP application."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from onigiri.config import settings
from onigiri.db import engine, session_scope
from onigiri.models import Profile, User
from onigiri.routers import auth, ingest, library, media, profile, recipes
from onigiri.security import hash_password

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("onigiri")

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


async def ensure_owner() -> None:
    """Create the single account from the environment on first boot."""
    email = settings.owner_email.strip().lower()
    async with session_scope() as db:
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(settings.owner_password))
            db.add(user)
            await db.flush()
            db.add(Profile(user_id=user.id))
            log.info("created the owner account for %s", email)
        elif not await db.scalar(select(Profile).where(Profile.user_id == user.id)):
            db.add(Profile(user_id=user.id))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select 1"))
        await ensure_owner()
    except Exception as exc:
        log.error("startup checks failed: %s", exc)
    yield
    await engine.dispose()


app = FastAPI(
    title="Onigiri",
    description="A personal recipe bank that captures from Instagram, the web and photos.",
    version="0.1.0",
    lifespan=lifespan,
)

if settings.environment == "dev":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def same_origin_guard(request: Request, call_next):
    """Reject cross-site state changes. The session cookie is SameSite=Lax, and the
    share target is handled inside the service worker, so nothing legitimate is
    cross-origin."""
    if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin:
            allowed = {settings.base_url.rstrip("/")}
            if settings.environment == "dev":
                allowed |= {"http://localhost:5173", "http://127.0.0.1:5173"}
            allowed.add(f"{request.url.scheme}://{request.headers.get('host', '')}")
            if origin.rstrip("/") not in allowed:
                return JSONResponse(
                    {"detail": "Cross-site requests are not allowed."},
                    status_code=status.HTTP_403_FORBIDDEN,
                )
    return await call_next(request)


app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(ingest.router)
app.include_router(recipes.router)
app.include_router(library.router)
app.include_router(media.router)


@app.get("/api/health")
async def health() -> dict[str, object]:
    checks: dict[str, object] = {"app": "ok"}
    try:
        async with engine.begin() as conn:
            await conn.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
    checks["extraction"] = "configured" if settings.openai_api_key else "no OPENAI_API_KEY"
    checks["instagram"] = "configured" if settings.apify_token else "no APIFY_TOKEN"
    checks["storage"] = "s3" if settings.use_s3 else "local disk"
    checks["jobs"] = settings.job_backend
    return checks


@app.exception_handler(404)
async def spa_fallback(request: Request, exc: HTTPException) -> object:
    """Serve the single-page app for client-side routes, but never for the API."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=404)
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse(
        {"detail": "The web app is not built. Run `pnpm build` in web/."}, status_code=404
    )


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")
