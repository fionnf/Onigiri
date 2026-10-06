"""The single account follows the environment, and production refuses placeholders."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from onigiri import main
from onigiri.config import settings
from onigiri.models import Recipe, User
from onigiri.security import verify_password


async def owner(db) -> User:
    return await db.scalar(select(User))


async def test_first_boot_creates_the_owner(db) -> None:
    await main.ensure_owner()
    user = await owner(db)
    assert user.email == settings.owner_email
    assert verify_password(settings.owner_password, user.password_hash)


async def test_changing_the_password_takes_effect(db, monkeypatch) -> None:
    await main.ensure_owner()
    monkeypatch.setattr(settings, "owner_password", "a-brand-new-password")
    await main.ensure_owner()
    db.expire_all()
    user = await owner(db)
    assert verify_password("a-brand-new-password", user.password_hash)
    assert not verify_password("test-password", user.password_hash)


async def test_changing_the_email_keeps_the_recipes(db, monkeypatch) -> None:
    await main.ensure_owner()
    user = await owner(db)
    db.add(Recipe(user_id=user.id, title="Kept soup"))
    await db.commit()

    monkeypatch.setattr(settings, "owner_email", "new@test.local")
    await main.ensure_owner()
    db.expire_all()

    assert await db.scalar(select(func.count()).select_from(User)) == 1
    renamed = await owner(db)
    assert renamed.email == "new@test.local"
    assert renamed.id == user.id
    assert await db.scalar(select(Recipe.title).where(Recipe.user_id == renamed.id)) == (
        "Kept soup"
    )


async def test_signing_in_with_a_changed_password(app_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "owner_password", "rotated-password-123")
    await main.ensure_owner()
    resp = await app_client.post(
        "/api/auth/login",
        json={"email": settings.owner_email, "password": "rotated-password-123"},
    )
    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("secret", "password", "problem"),
    [
        ("dev-insecure-secret-change-me", "a-good-password", "SECRET_KEY"),
        ("short", "a-good-password", "SECRET_KEY"),
        ("x" * 48, "changeme", "OWNER_PASSWORD"),
    ],
)
def test_production_refuses_placeholders(monkeypatch, secret, password, problem) -> None:
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "secret_key", secret)
    monkeypatch.setattr(settings, "owner_password", password)
    with pytest.raises(RuntimeError, match=problem):
        main.check_production_settings()


def test_production_accepts_real_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "prod")
    monkeypatch.setattr(settings, "secret_key", "x" * 48)
    monkeypatch.setattr(settings, "owner_password", "a-good-password")
    main.check_production_settings()


def test_development_allows_placeholders(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "dev")
    monkeypatch.setattr(settings, "secret_key", "dev-insecure-secret-change-me")
    main.check_production_settings()
