"""AI and ML endpoints for smart category suggestion and feedback."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.category_suggestion import (
    CategoryFeedbackRequest,
    CategoryFeedbackResponse,
    CategorySuggestionRequest,
    CategorySuggestionResponse,
)
from app.services.category_suggestion_service import (
    record_feedback,
    suggest_category,
)

router = APIRouter()


@router.post(
    "/category-suggestion",
    response_model=CategorySuggestionResponse,
    status_code=status.HTTP_200_OK,
    summary="Suggest expense category",
    description=(
        "Suggests an expense category for a given description and optional merchant "
        "using a 3-layer pipeline (user history -> local ML classifier -> Groq LLM fallback)."
    ),
)
async def suggest_category_endpoint(
    request: CategorySuggestionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CategorySuggestionResponse:
    """Endpoint POST /api/v1/ai/category-suggestion."""
    suggestion_data = await suggest_category(
        db=db,
        user_id=current_user.id,
        req=request,
    )
    return CategorySuggestionResponse(data=suggestion_data)


@router.post(
    "/category-suggestion/feedback",
    response_model=CategoryFeedbackResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit category suggestion feedback",
    description=(
        "Records user confirmation or manual category override. Persists the feedback "
        "and updates the user's historical profile for future personalization."
    ),
)
async def feedback_endpoint(
    request: CategoryFeedbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CategoryFeedbackResponse:
    """Endpoint POST /api/v1/ai/category-suggestion/feedback."""
    feedback_data = await record_feedback(
        db=db,
        user_id=current_user.id,
        feedback_req=request,
    )
    return CategoryFeedbackResponse(data=feedback_data)


# Alias routes for client compatibility with /suggestions
@router.post(
    "/suggestions",
    response_model=CategorySuggestionResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def suggest_category_alias(
    request: CategorySuggestionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CategorySuggestionResponse:
    return await suggest_category_endpoint(request, current_user, db)


@router.post(
    "/suggestions/feedback",
    response_model=CategoryFeedbackResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def feedback_alias(
    request: CategoryFeedbackRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CategoryFeedbackResponse:
    return await feedback_endpoint(request, current_user, db)

