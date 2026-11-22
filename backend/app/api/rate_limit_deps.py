"""FastAPI dependencies that apply the shared rate limiter to routes (T-39).

Both fail closed: if the shared counters are unavailable the request gets HTTP 503.

* ``limit_by_user`` counts per authenticated user. It depends on ``get_current_user`` (cached
  per request), so it runs after authentication and a stranger cannot spend a user's budget.
* ``limit_by_ip`` counts per client address from the trusted header only. When no trusted
  address is available it does nothing (see app/core/rate_limiter.py).
"""

from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import Depends, Request

from app.api.deps import get_current_user
from app.core.rate_limiter import get_client_ip, get_policy, reserve
from app.models.user import User


def limit_by_user(policy_name: str) -> Callable[..., Awaitable[None]]:
    async def dependency(current_user: User = Depends(get_current_user)) -> None:
        await reserve([(get_policy(policy_name), str(current_user.id))])

    return dependency


def limit_by_ip(policy_name: str) -> Callable[..., Awaitable[None]]:
    async def dependency(request: Request) -> None:
        client_ip = get_client_ip(request)
        if client_ip is None:
            return
        await reserve([(get_policy(policy_name), client_ip)])

    return dependency
