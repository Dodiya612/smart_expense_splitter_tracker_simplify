import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.database import engine
from app.services import notifications
from tests import notification_fakes


@pytest.fixture
async def client():
    """Async test client fixture for invoking FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def dispose_engine_between_tests():
    """Ensure SQLAlchemy connection pool does not leak connections across pytest-asyncio event loops."""
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def fake_notification_store(monkeypatch):
    """Keep fake-session tests off the database: notifications go to an in-memory store."""
    notification_fakes.clear_emitted_notifications()
    monkeypatch.setattr(notifications, "_persist", notification_fakes.fake_persist)
    # The fake sessions cannot answer the SQL membership query: None means "use the loaded
    # group.members snapshot". The real query is exercised in tests/test_notifications_pg.py.
    monkeypatch.setattr(notifications, "active_member_roles", notification_fakes.no_database_membership)
    yield
    notification_fakes.clear_emitted_notifications()
