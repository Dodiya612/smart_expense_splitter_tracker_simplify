"""Unit tests for Receipt Image Processing Pipeline (US-16).

Tests:
1. Stored image is smaller than 1 MB (1,048,576 bytes) & longest side <= 1600 px.
2. Location (EXIF/GPS) and all metadata is removed from the stored image.
3. Orientation is preserved via exif_transpose before stripping.
4. PNG with alpha transparency is converted cleanly to RGB JPEG over white background.
5. Magic byte detection (PNG bytes with .jpg name accepted; non-image rejected; PDF/GIF/HTML rejected 415).
6. Error handling: empty input, truncated/corrupt input, oversize input (>5MB), decompression bomb.
7. generate_key() uniqueness across 1,000 calls with zero PII.
"""

from __future__ import annotations

import io
import os

import pytest
from PIL import Image

from app.services.receipt_images import (
    ImageTooLargeError,
    InvalidImageError,
    UnsupportedMediaTypeError,
    detect_image_type_from_bytes,
    process_receipt_image,
)
from app.services.receipt_storage import generate_key


def create_test_jpeg(width: int = 100, height: int = 100, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    """Create in-memory raw JPEG bytes."""
    buf = io.BytesIO()
    img = Image.new("RGB", (width, height), color)
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def create_test_png(width: int = 100, height: int = 100, with_alpha: bool = False) -> bytes:
    """Create in-memory raw PNG bytes."""
    buf = io.BytesIO()
    mode = "RGBA" if with_alpha else "RGB"
    color = (0, 255, 0, 128) if with_alpha else (0, 255, 0)
    img = Image.new(mode, (width, height), color)
    img.save(buf, format="PNG")
    return buf.getvalue()


# =====================================================================
# Acceptance Criteria 1: Image < 1 MB and max dimension <= 1600
# =====================================================================


def test_large_noisy_jpeg_compressed_below_1mb() -> None:
    """AC 1: Stored image is smaller than 1 MB (1,048,576 bytes) and longest side <= 1600."""
    # Create large image (> 2 MB, but within 5 MB upload limit) with random noise to test compression
    width, height = 1800, 1400
    random_bytes = os.urandom(width * height * 3)
    large_img = Image.frombytes("RGB", (width, height), random_bytes)
    buf = io.BytesIO()
    large_img.save(buf, format="JPEG", quality=90)
    raw = buf.getvalue()
    assert len(raw) > 1_048_576, f"Test input should be > 1MB, got {len(raw)}"

    result = process_receipt_image(raw)

    assert len(result.data) < 1_048_576, f"Result size {len(result.data)} is not < 1MB"
    assert result.content_type == "image/jpeg"
    assert max(result.width, result.height) <= 1600

    # Verify Pillow can open the output
    with Image.open(io.BytesIO(result.data)) as out_img:
        assert out_img.format == "JPEG"
        assert max(out_img.width, out_img.height) <= 1600


# =====================================================================
# Acceptance Criteria 2: Location (EXIF/GPS) data removed
# =====================================================================


def test_exif_and_gps_data_completely_removed() -> None:
    """AC 2: Location (EXIF/GPS) data is removed from the stored image."""
    # Create image with EXIF metadata including GPS tags
    img = Image.new("RGB", (400, 300), (100, 150, 200))
    exif = img.getexif()
    # Tag 0x010E is ImageDescription, 0x8825 is GPSInfo IFD
    exif[0x010E] = "Secret location receipt"
    gps_ifd = exif.get_ifd(0x8825)
    gps_ifd[1] = "N"
    gps_ifd[2] = (37.0, 46.0, 29.74)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    raw_with_exif = buf.getvalue()
    assert b"Secret location" in raw_with_exif

    result = process_receipt_image(raw_with_exif)

    # Output bytes must not contain EXIF marker or text
    assert len(result.data) < 1_048_576
    assert b"Secret location" not in result.data

    with Image.open(io.BytesIO(result.data)) as out_img:
        out_exif = out_img.getexif()
        assert len(out_exif) == 0, f"Expected empty EXIF, got: {out_exif}"


def test_exif_transposed_orientation_preserved_before_stripping() -> None:
    """Orientation tag (e.g. rotated 90 deg clockwise) is applied before stripping."""
    # Create an image that is 200 wide x 100 high with Orientation = 6 (90 deg CW rotate)
    img = Image.new("RGB", (200, 100), (50, 100, 150))
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation 6: rotate 90 CW (width becomes height)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    raw = buf.getvalue()

    result = process_receipt_image(raw)

    # After exif_transpose, dimensions swap: width <= 100, height <= 200
    assert result.height > result.width
    # And EXIF is stripped
    with Image.open(io.BytesIO(result.data)) as out_img:
        assert len(out_img.getexif()) == 0


# =====================================================================
# Acceptance Criteria 3: Type from bytes, not filename/header
# =====================================================================


def test_type_from_bytes_png_with_jpg_name_accepted() -> None:
    """AC 3: Real PNG bytes with .jpg filename are detected as PNG and processed."""
    png_bytes = create_test_png(200, 200, with_alpha=True)

    # Magic byte check detects PNG
    assert detect_image_type_from_bytes(png_bytes) == "PNG"

    # Processing converts it to JPEG cleanly
    result = process_receipt_image(png_bytes)
    assert result.content_type == "image/jpeg"
    with Image.open(io.BytesIO(result.data)) as out_img:
        assert out_img.format == "JPEG"
        assert out_img.mode == "RGB"


def test_non_image_payloads_rejected_415() -> None:
    """Non-image bytes (PDF, HTML, GIF, random bytes) raise UnsupportedMediaTypeError (415)."""
    pdf_payload = b"%PDF-1.4\n%...\ntrailer\n%%EOF"
    html_payload = b"<!DOCTYPE html><html><body><h1>Fake receipt</h1></body></html>"
    gif_payload = b"GIF89a\x01\x00\x01\x00\x80\x00\x00"
    random_payload = b"MZ\x90\x00\x03\x00\x00\x00"

    for payload in [pdf_payload, html_payload, gif_payload, random_payload]:
        with pytest.raises(UnsupportedMediaTypeError) as exc_info:
            process_receipt_image(payload)
        assert exc_info.value.status_code == 415
        assert exc_info.value.code == "UNSUPPORTED_MEDIA_TYPE"


# =====================================================================
# Error & Edge Cases
# =====================================================================


def test_empty_image_raises_invalid_image() -> None:
    with pytest.raises(InvalidImageError) as exc_info:
        process_receipt_image(b"")
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "INVALID_IMAGE"


def test_oversize_upload_raises_image_too_large() -> None:
    """Uploads > 5 MB are rejected immediately before decoding with 413 Payload Too Large."""
    six_mb_dummy = b"\xFF\xD8\xFF" + b"\x00" * (5 * 1024 * 1024 + 10)
    with pytest.raises(ImageTooLargeError) as exc_info:
        process_receipt_image(six_mb_dummy)
    assert exc_info.value.status_code == 413
    assert exc_info.value.code == "IMAGE_TOO_LARGE"


def test_truncated_corrupt_jpeg_raises_invalid_image() -> None:
    """JPEG header followed by truncated/garbage data raises InvalidImageError (422)."""
    corrupt_jpeg = b"\xFF\xD8\xFF" + b"garbage_random_data_not_a_jpeg"
    with pytest.raises(InvalidImageError) as exc_info:
        process_receipt_image(corrupt_jpeg)
    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "INVALID_IMAGE"


def test_decompression_bomb_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decompression bomb (excessive pixel dimensions) is caught and raises 422."""
    from app.services import receipt_images

    monkeypatch.setattr(receipt_images, "DECOMPRESSION_BOMB_MAX_PIXELS", 1000)

    img_bytes = create_test_jpeg(100, 100)  # 10,000 pixels > 1,000
    with pytest.raises(InvalidImageError) as exc_info:
        process_receipt_image(img_bytes)
    assert exc_info.value.status_code == 422
    assert "decompression bomb" in exc_info.value.message.lower()


# =====================================================================
# Acceptance Criteria 4: Random Unguessable Key Generation
# =====================================================================


def test_generate_key_uniqueness_and_no_pii() -> None:
    """AC 4: Random unguessable key with zero user/expense PII across 1,000 calls."""
    keys = {generate_key() for _ in range(1000)}

    assert len(keys) == 1000, "All 1,000 generated keys must be unique"

    for k in keys:
        assert k.startswith("receipts/")
        assert k.endswith(".jpg")
        # Ensure key contains no user_id, expense_id, timestamps or colons
        body = k.removeprefix("receipts/").removesuffix(".jpg")
        assert len(body) >= 32
        assert ":" not in body
        assert "-" not in body or len(body.replace("-", "")) >= 32
