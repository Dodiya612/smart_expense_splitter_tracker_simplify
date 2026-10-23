"""Health check response schema."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness health check response model."""

    status: str = Field(
        default="ok",
        description="Overall service health status.",
        examples=["ok"],
    )
    environment: str = Field(
        ...,
        description="Current running environment (development, staging, production).",
        examples=["development"],
    )
    version: str = Field(
        ...,
        description="Service semantic version string.",
        examples=["0.1.0"],
    )
    timestamp: str = Field(
        ...,
        description="ISO 8601 UTC timestamp of the health inspection.",
        examples=["2026-10-23T10:00:00.000000+00:00"],
    )
