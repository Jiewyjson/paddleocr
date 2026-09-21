from __future__ import annotations

import io
import logging
import re
import uuid

import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings
from .engine import OcrEngine


logger = logging.getLogger("crop_ocr")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings.from_env()
    app = FastAPI(  # pylint: disable=redefined-outer-name  # Factory-local ASGI instance.
        title="Local crop OCR API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = runtime_settings
    app.state.engine = OcrEngine(runtime_settings)

    # Production calls arrive from the same-origin Pages Function, so this is
    # primarily for direct local development at http://localhost:4321.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_settings.allowed_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-Id"],
        max_age=600,
    )

    @app.middleware("http")
    async def reject_obviously_large_bodies(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                received_bytes = int(content_length)
            except ValueError:
                return _json_error("Invalid Content-Length", status.HTTP_400_BAD_REQUEST)
            if received_bytes > runtime_settings.max_image_bytes:
                return _json_error(
                    "Crop image exceeds the request size limit",
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
        return await call_next(request)

    @app.get("/v1/healthz")
    async def healthz(request: Request) -> dict[str, object]:
        engine: OcrEngine = request.app.state.engine
        return {"status": "ok", "model_loaded": engine.is_loaded}

    @app.post("/v1/ocr")
    async def ocr(request: Request) -> Response:
        request_id = _request_id(request)
        content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type not in SUPPORTED_IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Send a JPEG, PNG, or WebP crop as the raw request body",
            )

        payload = await request.body()
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Crop image is empty",
            )
        if len(payload) > runtime_settings.max_image_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Crop image exceeds the request size limit",
            )

        bgr_image, width, height = _decode_crop(payload, runtime_settings)
        engine: OcrEngine = request.app.state.engine
        try:
            result = await engine.infer(bgr_image)
        except Exception:
            # Never include image bytes, paths, or model internals in a client error.
            logger.exception("OCR inference failed request_id=%s", request_id)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="OCR inference failed",
            ) from None

        logger.info(
            "OCR completed request_id=%s image=%dx%d elapsed_ms=%d",
            request_id,
            width,
            height,
            result.elapsed_ms,
        )
        return _json_response(
            {
                "request_id": request_id,
                "text": result.text,
                "markdown": result.markdown,
                "blocks": result.blocks,
                "elapsed_ms": result.elapsed_ms,
                "image": {"width": width, "height": height},
            }
        )

    return app


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "")
    return supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid.uuid4().hex


def _decode_crop(payload: bytes, settings: Settings) -> tuple[np.ndarray, int, int]:
    try:
        with Image.open(io.BytesIO(payload)) as source:
            width, height = source.size
            if width < settings.min_crop_edge or height < settings.min_crop_edge:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Crop must be at least {settings.min_crop_edge}px on each side",
                )
            if width * height > settings.max_image_pixels:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Crop image exceeds the pixel limit",
                )
            rgb_image = ImageOps.exif_transpose(source).convert("RGB")
            rgb = np.asarray(rgb_image, dtype=np.uint8)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not decode crop image",
        ) from exc

    # PaddleX's in-memory image reader treats ndarray input as BGR.
    return np.ascontiguousarray(rgb[:, :, ::-1]), width, height


def _json_response(payload: dict[str, object]) -> Response:
    from fastapi.responses import JSONResponse

    return JSONResponse(
        payload,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def _json_error(message: str, status_code: int) -> Response:
    from fastapi.responses import JSONResponse

    return JSONResponse(
        {"detail": message},
        status_code=status_code,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


app = create_app()
