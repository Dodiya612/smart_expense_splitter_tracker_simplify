"""OCR.space Cloud Service Client (US-16 / T-47).

Provides an asynchronous client to scan bill images via the OCR.space API with
strict timeouts, error recovery, and graceful failure.
"""

from __future__ import annotations

import json
import logging
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    from app.core.config import settings
except ImportError:
    settings = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

OCR_SPACE_URL = "https://api.ocr.space/parse/image"


async def extract_text_ocr_space(
    image_bytes: bytes,
    api_key: str | None = None,
    timeout_seconds: float | None = None,
    client: Any | None = None,
) -> str | None:
    """Send image to OCR.space API and extract raw parsed text.

    Args:
        image_bytes: JPEG or PNG raw bytes of the receipt bill.
        api_key: OCR.space API key. If omitted, uses settings.OCR_SPACE_API_KEY.
        timeout_seconds: Timeout for external HTTP call. If omitted, uses settings.OCR_SPACE_TIMEOUT_SECONDS.
        client: Optional pre-configured httpx.AsyncClient (useful for dependency injection in tests).

    Returns:
        The extracted raw text string, or None if the request failed, timed out, or returned an error.
    """
    key = api_key or (getattr(settings, "OCR_SPACE_API_KEY", None) if settings else None) or "helloworld"
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else (getattr(settings, "OCR_SPACE_TIMEOUT_SECONDS", 8.0) if settings else 8.0)
    )

    # When httpx is available or a custom client is provided
    if client is not None or httpx is not None:
        data: dict[str, Any] = {
            "apikey": key,
            "language": "eng",
            "isOverlayRequired": False,
            "detectOrientation": True,
            "scale": True,
            "isTable": True,
        }
        files = {
            "file": ("receipt.jpg", image_bytes, "image/jpeg"),
        }

        own_client = client is None
        http_client = client or httpx.AsyncClient(timeout=timeout)

        try:
            response = await http_client.post(OCR_SPACE_URL, data=data, files=files)
            if response.status_code != 200:
                logger.warning(
                    "OCR.space request returned non-200 status %d: %s",
                    response.status_code,
                    response.text[:200],
                )
                return None

            result_json = response.json()
            if result_json.get("IsErroredOnProcessing"):
                err_msg = result_json.get("ErrorMessage") or result_json.get("ErrorDetails")
                logger.warning("OCR.space reported processing error: %s", err_msg)
                return None

            parsed_results = result_json.get("ParsedResults", [])
            if not parsed_results:
                logger.warning("OCR.space returned empty ParsedResults")
                return None

            parsed_text = parsed_results[0].get("ParsedText", "")
            return parsed_text.strip() if parsed_text else None

        except httpx.TimeoutException as exc:
            logger.warning("OCR.space request timed out after %.1f seconds: %s", timeout, exc)
            return None
        except Exception as exc:
            logger.warning("OCR.space external call failed: %s", exc)
            return None
        finally:
            if own_client:
                await http_client.aclose()

    # Fallback to standard library urllib in environments where httpx is not installed
    import asyncio
    import urllib.request

    def _sync_urllib_call() -> str | None:
        boundary = "----WebKitFormBoundaryCoinsciousOcr"
        body_parts = []
        fields = {
            "apikey": key,
            "language": "eng",
            "isOverlayRequired": "false",
            "detectOrientation": "true",
            "scale": "true",
            "isTable": "true",
        }
        for k, v in fields.items():
            body_parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"receipt.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode("utf-8")
        )
        body_parts.append(image_bytes)
        body_parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        payload = b"".join(body_parts)

        req = urllib.request.Request(
            OCR_SPACE_URL,
            data=payload,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "Coinscious-ReceiptOCR/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data_resp = json.loads(resp.read().decode("utf-8"))
                results = data_resp.get("ParsedResults", [])
                if results and results[0].get("ParsedText"):
                    return results[0]["ParsedText"].strip()
                return None
        except Exception as exc:
            logger.warning("urllib OCR.space call failed: %s", exc)
            return None

    return await asyncio.to_thread(_sync_urllib_call)
