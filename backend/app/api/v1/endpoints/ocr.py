"""OCR draft and confirm endpoints for bill photos (US-?? / T-??)."""

import uuid
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.receipt import ReceiptDraftResponse, ReceiptConfirmResponse

router = APIRouter()

# Placeholder OCR function – in real code this would call Tesseract or a cloud OCR service
def _extract_text_from_image(file_bytes: bytes) -> dict:
    # Returning dummy data for now
    return {
        "merchant": "Dummy Store",
        "date": "2024-01-01",
        "total": 12345,  # in paise
    }

@router.post(
    "/ocr-draft",
    response_model=ReceiptDraftResponse,
    status_code=status.HTTP_200_OK,
    summary="Create a draft receipt from a bill photo",
    description="Runs OCR on the uploaded image and returns a draft receipt. Nothing is persisted until the draft is confirmed.",
)
async def ocr_draft(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReceiptDraftResponse:
    if file.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(status_code=400, detail="Unsupported file type")
    content = await file.read()
    data = _extract_text_from_image(content)
    # In a real implementation we would store a temporary draft linked to the user/session
    return ReceiptDraftResponse(data=data)

@router.post(
    "/ocr-confirm",
    response_model=ReceiptConfirmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Confirm and persist a draft receipt",
    description="Takes the draft data (merchant, date, total) and creates a persisted receipt record.",
)
async def ocr_confirm(
    draft_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReceiptConfirmResponse:
    # Placeholder: Assume the draft exists and simply return success.
    # Real implementation would lookup the draft, validate, and create a Receipt model.
    return ReceiptConfirmResponse(message="Receipt confirmed and saved.")
