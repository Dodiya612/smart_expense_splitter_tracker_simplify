"""Generic base repository defining consistent data access interface."""

from abc import ABC, abstractmethod
from typing import Any, Generic, List, Optional, TypeVar

ModelType = TypeVar("ModelType")
CreateSchemaType = TypeVar("CreateSchemaType")
UpdateSchemaType = TypeVar("UpdateSchemaType")


class BaseRepository(Generic[ModelType], ABC):
    """Abstract generic repository following the repository pattern."""

    @abstractmethod
    def get(self, id: Any) -> Optional[ModelType]:
        """Retrieve a single entity by its identifier."""
        raise NotImplementedError

    @abstractmethod
    def get_multi(self, skip: int = 0, limit: int = 100) -> List[ModelType]:
        """Retrieve a paginated collection of entities."""
        raise NotImplementedError

    @abstractmethod
    def create(self, obj_in: Any) -> ModelType:
        """Persist a new entity."""
        raise NotImplementedError

    @abstractmethod
    def update(self, id: Any, obj_in: Any) -> Optional[ModelType]:
        """Update an existing entity."""
        raise NotImplementedError

    @abstractmethod
    def remove(self, id: Any) -> Optional[ModelType]:
        """Delete or soft-delete an entity."""
        raise NotImplementedError
