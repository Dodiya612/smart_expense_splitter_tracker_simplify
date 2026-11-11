import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import engine
from app.main import app


@pytest.fixture
async def client():
    """Async test client fixture for invoking FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture(autouse=True)
def dispose_engine_between_tests(request):
    """Ensure SQLAlchemy connection pool does not leak connections across pytest-asyncio event loops."""
    yield
    if request.node.get_closest_marker("anyio") or request.node.get_closest_marker(
        "asyncio"
    ):
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.run_until_complete(engine.dispose())
        except Exception:  # noqa: BLE001, S110
            pass
