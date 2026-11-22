"""Local Tesseract OCR Engine Fallback (US-16 / T-47).

Provides offline Optical Character Recognition fallback when OCR.space fails or times out.
Applies image preprocessing (grayscale, contrast normalization) and enforces strict timeouts.
"""

from __future__ import annotations

import asyncio
import io
import logging
import shutil
import subprocess
import tempfile
from typing import Any

try:
    from PIL import Image, ImageEnhance, ImageFilter
except ImportError:
    Image = None  # type: ignore[assignment]
    ImageEnhance = None  # type: ignore[assignment]
    ImageFilter = None  # type: ignore[assignment]

try:
    from app.core.config import settings
except ImportError:
    settings = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def preprocess_receipt_image(image_bytes: bytes) -> Any:
    """Prepare raw receipt image bytes for optimal OCR accuracy.

    Converts to grayscale, enhances contrast, and cleans noise if PIL is available.
    """
    if Image is None:
        return None

    img = Image.open(io.BytesIO(image_bytes))

    # Convert to grayscale
    if img.mode != "L":
        img = img.convert("L")

    # Increase contrast for better text binarization
    if ImageEnhance is not None:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.8)

    # Optional sharpening filter
    if ImageFilter is not None:
        img = img.filter(ImageFilter.SHARPEN)
    return img


def _run_tesseract_sync(
    image_bytes: bytes,
    timeout_seconds: float,
    tesseract_cmd: str | None = None,
) -> str | None:
    """Synchronous execution of Tesseract using pytesseract or direct binary CLI."""
    # 1. Try pytesseract if available in the python environment
    try:
        import pytesseract  # type: ignore[import-untyped]

        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        elif settings and getattr(settings, "TESSERACT_CMD", None):
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

        preprocessed = preprocess_receipt_image(image_bytes)
        target = preprocessed if preprocessed is not None else io.BytesIO(image_bytes)
        text = pytesseract.image_to_string(target, timeout=timeout_seconds)
        return text.strip() if text else None
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("pytesseract execution failed: %s", exc)
        return None

    # 2. Fall back to calling the tesseract system binary directly
    bin_path = (
        tesseract_cmd
        or (getattr(settings, "TESSERACT_CMD", None) if settings else None)
        or shutil.which("tesseract")
        or "/usr/local/bin/tesseract"
        or "/opt/homebrew/bin/tesseract"
    )

    if not bin_path or not shutil.which(bin_path):
        logger.info("Tesseract binary not installed on system; skipping local OCR.")
        return None

    try:
        preprocessed = preprocess_receipt_image(image_bytes)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
            if preprocessed is not None:
                preprocessed.save(tmp.name, format="PNG")
            else:
                tmp.write(image_bytes)
                tmp.flush()

            result = subprocess.run(
                [bin_path, tmp.name, "stdout", "--oem", "1", "-l", "eng"],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
            logger.warning("Tesseract binary returned code %d: %s", result.returncode, result.stderr)
            return None
    except subprocess.TimeoutExpired:
        logger.warning("Tesseract process timed out after %.1f seconds", timeout_seconds)
        return None
    except Exception as exc:
        logger.warning("Direct tesseract CLI execution failed: %s", exc)
        return None


async def extract_text_tesseract(
    image_bytes: bytes,
    timeout_seconds: float | None = None,
    tesseract_cmd: str | None = None,
) -> str | None:
    """Asynchronously run Tesseract fallback on the image bytes.

    Args:
        image_bytes: Raw JPEG or PNG bytes.
        timeout_seconds: Strict timeout in seconds (defaults to settings.TESSERACT_TIMEOUT_SECONDS).
        tesseract_cmd: Optional path to tesseract binary.

    Returns:
        The extracted raw text string, or None if failed, timed out, or unavailable.
    """
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else (getattr(settings, "TESSERACT_TIMEOUT_SECONDS", 5.0) if settings else 5.0)
    )

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_run_tesseract_sync, image_bytes, timeout, tesseract_cmd),
            timeout=timeout + 0.5,
        )
    except TimeoutError:
        logger.warning("extract_text_tesseract task timed out after %.1f seconds", timeout)
        return None
    except Exception as exc:
        logger.warning("extract_text_tesseract failed: %s", exc)
        return None
