"""Receipt Image Processing Pipeline (US-16).

Pure-python, DB-free, FastAPI-free module for:
- 5 MB upload size enforcement
- Byte-level magic signature detection (JPEG & PNG only)
- Pillow integrity validation and decompression bomb prevention
- EXIF orientation transposition and complete metadata stripping
- Alpha flattening onto white background and conversion to RGB JPEG
- Progressive quality reduction and downscaling guaranteeing strictly < 1 MB output
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Constants per US-16 specifications
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 5 MB upload cap (5,242,880 bytes)
MAX_STORED_SIZE = 1 * 1024 * 1024  # 1 MB stored cap (1,048,576 bytes)
MAX_INITIAL_LONGEST_SIDE = 1600  # Target longest side
MIN_PRESERVED_LONGEST_SIDE = 800  # Readability floor
DECOMPRESSION_BOMB_MAX_PIXELS = 40_000_000  # 40 MP guard

# Magic byte signatures
JPEG_MAGIC = b"\xFF\xD8\xFF"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class ReceiptImageError(Exception):
    """Base exception for receipt image processing errors."""

    def __init__(self, message: str, code: str = "INVALID_IMAGE", status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


class UnsupportedMediaTypeError(ReceiptImageError):
    """Raised when the uploaded file is not a supported image format (JPEG/PNG)."""

    def __init__(self, message: str = "Unsupported media type. Only JPEG and PNG images are allowed.") -> None:
        super().__init__(message=message, code="UNSUPPORTED_MEDIA_TYPE", status_code=415)


class InvalidImageError(ReceiptImageError):
    """Raised when image bytes are empty, corrupt, or trigger decompression bomb warnings."""

    def __init__(self, message: str = "Invalid or corrupted image data.") -> None:
        super().__init__(message=message, code="INVALID_IMAGE", status_code=422)


class ImageTooLargeError(ReceiptImageError):
    """Raised when an uploaded or compressed image exceeds allowable byte limits."""

    def __init__(self, message: str = "Image exceeds maximum allowed size.") -> None:
        super().__init__(message=message, code="IMAGE_TOO_LARGE", status_code=413)


@dataclass(frozen=True)
class ProcessedImage:
    """Immutable result of receipt image normalization and compression."""

    data: bytes
    content_type: str
    width: int
    height: int


def detect_image_type_from_bytes(raw: bytes) -> str:
    """Determine file type strictly from file magic bytes, ignoring filename/Content-Type.

    Returns:
        'JPEG' or 'PNG' if matched.
    Raises:
        UnsupportedMediaTypeError: If magic bytes do not match JPEG or PNG.
    """
    if raw.startswith(JPEG_MAGIC):
        return "JPEG"
    elif raw.startswith(PNG_MAGIC):
        return "PNG"
    else:
        raise UnsupportedMediaTypeError(
            "Unsupported file type. File header does not match JPEG or PNG magic bytes."
        )


def process_receipt_image(raw: bytes) -> ProcessedImage:
    """Process, normalize, strip metadata from, and shrink a receipt image strictly below 1 MB.

    Pipeline steps:
    1. Check byte length: reject empty input and input > 5 MB.
    2. Check magic signature: only JPEG and PNG allowed.
    3. Decode with Pillow verify() + reopen to detect corrupt images or decompression bombs.
    4. Apply ImageOps.exif_transpose so orientation is preserved.
    5. Strip all metadata (EXIF, GPS, ICC profile, text chunks) by re-encoding.
    6. Flatten transparency (if any) over a white background and convert to RGB.
    7. Limit longest side to 1600 px initially.
    8. Progressively compress/downscale until file size is strictly < 1,048,576 bytes.
    9. Return ProcessedImage with image/jpeg bytes.
    """
    # 1. Size bounds check before decoding
    if not raw or len(raw) == 0:
        raise InvalidImageError("Uploaded image file is empty.")

    if len(raw) > MAX_UPLOAD_SIZE:
        raise ImageTooLargeError(
            f"Uploaded image of {len(raw)} bytes exceeds the 5 MB upload limit."
        )

    # 2. Magic byte check
    detect_image_type_from_bytes(raw)

    # 3. Decode & integrity check with Pillow
    try:
        # Verify first using lazy header inspection for decompression bombs
        with Image.open(io.BytesIO(raw)) as test_img:
            if test_img.width * test_img.height > DECOMPRESSION_BOMB_MAX_PIXELS:
                raise InvalidImageError(
                    "Image exceeds maximum allowable pixel dimensions (decompression bomb protection)."
                )
            test_img.verify()

        # Reopen for actual processing (verify closes/invalidates the file pointer)
        img = Image.open(io.BytesIO(raw))
        if img.width * img.height > DECOMPRESSION_BOMB_MAX_PIXELS:
            img.close()
            raise InvalidImageError(
                "Image exceeds maximum allowable pixel dimensions (decompression bomb protection)."
            )
        img.load()  # Force loading image pixels
    except ReceiptImageError:
        raise
    except Image.DecompressionBombError as exc:
        raise InvalidImageError(
            "Image exceeds maximum allowable pixel dimensions (decompression bomb protection)."
        ) from exc
    except Exception as exc:
        raise InvalidImageError(f"Corrupted or unreadable image data: {exc}") from exc

    try:
        # 4. Apply exif_transpose FIRST to preserve human orientation
        try:
            transposed = ImageOps.exif_transpose(img)
            if transposed is not None:
                img = transposed
        except Exception:  # noqa: BLE001, S110
            # If transpose fails on malformed EXIF, proceed with original pixels
            pass

        # 5 & 6. Flatten transparency onto white background and convert to RGB
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            img_rgba = img.convert("RGBA")
            bg = Image.new("RGB", img_rgba.size, (255, 255, 255))
            # Alpha channel is 4th band (index 3)
            bg.paste(img_rgba, mask=img_rgba.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # 7. Initial scale: limit longest side to 1600 px
        width, height = img.size
        longest_side = max(width, height)
        if longest_side > MAX_INITIAL_LONGEST_SIDE:
            scale = MAX_INITIAL_LONGEST_SIDE / float(longest_side)
            new_w = max(1, int(width * scale))
            new_h = max(1, int(height * scale))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        # 8. Progressive compression loop strictly < 1 MB
        quality = 85
        iteration = 0
        max_iterations = 12

        while iteration < max_iterations:
            buf = io.BytesIO()
            # Re-encode clean JPEG: NO exif, icc_profile, xmp, or comments passed
            img.save(
                buf,
                format="JPEG",
                quality=quality,
                optimize=True,
            )
            out_bytes = buf.getvalue()

            if len(out_bytes) < MAX_STORED_SIZE:
                return ProcessedImage(
                    data=out_bytes,
                    content_type="image/jpeg",
                    width=img.width,
                    height=img.height,
                )

            # Step down quality first
            if quality > 50:
                quality -= 5
            else:
                # If quality is at 50 and still >= 1 MB, downscale dimensions by 15%
                new_w = max(1, int(img.width * 0.85))
                new_h = max(1, int(img.height * 0.85))
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                quality = 75  # Reset quality slightly for the smaller dimensions

            iteration += 1

        # If loop exhausts without reaching < 1 MB
        raise ImageTooLargeError("Image could not be compressed below 1 MB limit.")

    finally:
        img.close()
