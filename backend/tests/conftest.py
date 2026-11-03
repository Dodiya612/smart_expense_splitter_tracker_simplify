import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.core.database import engine


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
