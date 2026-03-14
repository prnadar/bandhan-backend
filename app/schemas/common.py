"""
Shared schema building blocks.
"""
import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard envelope for every API response."""

    success: bool
    data: T | None = None
    error: str | None = None
    message: str | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    success: bool = True
    data: list[T]
    total: int
    page: int
    limit: int
    has_next: bool

    @classmethod
    def create(
        cls, items: list[T], total: int, page: int, limit: int
    ) -> "PaginatedResponse[T]":
        return cls(
            data=items,
            total=total,
            page=page,
            limit=limit,
            has_next=(page * limit) < total,
        )


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TimestampedSchema(BaseSchema):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
