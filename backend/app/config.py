from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _as_positive_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _as_origins(value: str) -> tuple[str, ...]:
    origins = tuple(origin.strip().rstrip("/") for origin in value.split(",") if origin.strip())
    if not origins:
        raise ValueError("OCR_ALLOWED_ORIGINS must contain at least one origin")
    return origins


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. Keep all data limits deliberately small for crop OCR."""

    allowed_origins: tuple[str, ...]
    max_image_bytes: int
    max_image_pixels: int
    min_crop_edge: int
    pipeline_version: str
    vl_backend: str
    vl_server_url: str
    vl_api_model_name: str
    device: str
    use_layout_detection: bool
    max_new_tokens: int | None
    default_strategy: str = "document"
    strategy_cache_size: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        max_new_tokens = os.getenv("OCR_MAX_NEW_TOKENS", "").strip()
        parsed_max_new_tokens = int(max_new_tokens) if max_new_tokens else None
        if parsed_max_new_tokens is not None and parsed_max_new_tokens <= 0:
            raise ValueError("OCR_MAX_NEW_TOKENS must be greater than zero when set")

        default_mlx_model_path = Path.home() / ".paddlex" / "official_models" / "PaddleOCR-VL-1.5"
        vl_api_model_name = os.getenv("OCR_VL_API_MODEL_NAME", str(default_mlx_model_path)).strip()
        if vl_api_model_name.startswith("~"):
            vl_api_model_name = str(Path(vl_api_model_name).expanduser())

        return cls(
            allowed_origins=_as_origins(
                os.getenv(
                    "OCR_ALLOWED_ORIGINS",
                    "http://localhost:4321,http://127.0.0.1:4321",
                )
            ),
            max_image_bytes=_as_positive_int("OCR_MAX_IMAGE_BYTES", 10 * 1024 * 1024),
            max_image_pixels=_as_positive_int("OCR_MAX_IMAGE_PIXELS", 16_000_000),
            min_crop_edge=_as_positive_int("OCR_MIN_CROP_EDGE", 24),
            pipeline_version=os.getenv("OCR_PIPELINE_VERSION", "v1.5"),
            vl_backend=os.getenv("OCR_VL_BACKEND", "mlx-vlm-server"),
            vl_server_url=os.getenv("OCR_VL_SERVER_URL", "http://127.0.0.1:8111/"),
            vl_api_model_name=vl_api_model_name,
            device=os.getenv("OCR_DEVICE", "cpu"),
            use_layout_detection=_as_bool("OCR_USE_LAYOUT_DETECTION", False),
            max_new_tokens=parsed_max_new_tokens,
            default_strategy=os.getenv("OCR_DEFAULT_STRATEGY", "document"),
            strategy_cache_size=_as_positive_int("OCR_STRATEGY_CACHE_SIZE", 2),
        )
