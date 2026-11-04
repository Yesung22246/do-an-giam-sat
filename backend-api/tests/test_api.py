import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Ép dùng SQLite in-memory cho toàn bộ bài test
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["JWT_SECRET"] = "test-jwt-secret-key"
os.environ["ADMIN_EMAIL"] = "admin@example.com"
os.environ["ADMIN_PASSWORD"] = "admin-secret-pass"
os.environ["TELEGRAM_LINK_API_KEY"] = "internal-secret-key-tv2-tv5"

from app.database import Base, get_db  # noqa: E402
from app.main import app, seed_initial_data  # noqa: E402

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False
)


async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db

# Giữ lại hàm post gốc để không ảnh hưởng request của chính test client
_original_post = httpx.AsyncClient.post


# Quan trọng: fixture async phải dùng pytest_asyncio.fixture
@pytest_asyncio.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with TestingSessionLocal() as session:
        await seed_initial_data(session)
    yield


@pytest.mark.asyncio
async def test_register_login_and_plan_limits():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reg = await client.post(
            "/auth/register",
            json={"email": "customer@example.com", "password": "password123"},
        )
        assert reg.status_code == 200
        token = reg.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        fast_mon = await client.post(
            "/monitors",
            headers=headers,
            json={
                "name": "Fast Monitor",
                "type": "http",
                "target": "https://example.com",
                "interval_seconds": 30,
            },
        )
        assert fast_mon.status_code == 400

        for i in range(5):
            ok_mon = await client.post(
                "/monitors",
                headers=headers,
                json={
                    "name": f"Monitor {i}",
                    "type": "http",
                    "target": f"https://example{i}.com",
                    "interval_seconds": 60,
                },
            )
            assert ok_mon.status_code == 201

        sixth_mon = await client.post(
            "/monitors",
            headers=headers,
            json={
                "name": "Monitor 6",
                "type": "http",
                "target": "https://example6.com",
                "interval_seconds": 60,
            },
        )
        assert sixth_mon.status_code == 403


@pytest.mark.asyncio
async def test_only_admin_can_list_users_and_change_plan():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reg = await client.post(
            "/auth/register",
            json={"email": "user1@example.com", "password": "password123"},
        )
        user_token = reg.json()["token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        me = (await client.get("/auth/me", headers=user_headers)).json()
        user_id = me["id"]

        self_upgrade = await client.put(
            f"/users/{user_id}/plan",
            headers=user_headers,
            json={"plan_id": 3},
        )
        assert self_upgrade.status_code == 403

        list_denied = await client.get("/users", headers=user_headers)
        assert list_denied.status_code == 403

        admin_login = await client.post(
            "/auth/login",
            json={"email": "admin@example.com", "password": "admin-secret-pass"},
        )
        assert admin_login.status_code == 200, admin_login.text
        admin_headers = {"Authorization": f"Bearer {admin_login.json()['token']}"}

        users_resp = await client.get("/users", headers=admin_headers)
        assert users_resp.status_code == 200
        assert len(users_resp.json()) >= 2

        admin_upgrade = await client.put(
            f"/users/{user_id}/plan",
            headers=admin_headers,
            json={"plan_id": 2},
        )
        assert admin_upgrade.status_code == 200
        assert admin_upgrade.json()["plan_id"] == 2


@pytest.mark.asyncio
async def test_telegram_link_code_endpoint():
    fake_expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    captured = {}

    class FakeResponse:
        status_code = 200
        text = "OK"

        def json(self):
            return {"code": "A1B2C3D4", "expires_at": fake_expires}

        def raise_for_status(self):
            return None

    async def fake_post(self, url, *args, **kwargs):
        headers = kwargs.get("headers") or {}
        if "X-Internal-API-Key" in headers:
            captured["headers"] = headers
            return FakeResponse()
        return await _original_post(self, url, *args, **kwargs)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        reg = await client.post(
            "/auth/register",
            json={"email": "tele@example.com", "password": "password123"},
        )
        assert reg.status_code == 200
        headers = {"Authorization": f"Bearer {reg.json()['token']}"}

        with patch.object(httpx.AsyncClient, "post", new=fake_post):
            resp = await client.post(
                "/notification-channels/telegram/link-code",
                headers=headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "A1B2C3D4"
        assert "/start A1B2C3D4" in data["instruction"]
        assert captured["headers"]["X-Internal-API-Key"] == "internal-secret-key-tv2-tv5"
