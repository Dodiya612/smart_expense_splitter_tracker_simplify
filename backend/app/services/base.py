"""Base service interface."""

from typing import Any, Optional


class BaseService:
    """Base class for all business logic domain services."""

    def __init__(self, repository: Optional[Any] = None) -> None:
        self.repository = repository
