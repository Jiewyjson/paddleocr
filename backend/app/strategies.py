"""OCR adapters. Model imports and construction happen only when selected."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

import numpy as np

from .config import Settings

StrategyName = Literal["fast", "balanced", "accurate", "document"]
STRATEGY_NAMES = ("fast", "balanced", "accurate", "document")
OCR_PRESETS = {
    "fast": ("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec"),
    "balanced": ("PP-OCRv5_mobile_det", "PP-OCRv5_server_rec"),
    "accurate": ("PP-OCRv5_server_det", "PP-OCRv5_server_rec"),
}


@dataclass(frozen=True)
class StrategyResult:
    text: str
    markdown: str
    blocks: list[dict[str, Any]]


class OcrStrategy(Protocol):  # pylint: disable=too-few-public-methods  # Single predict interface.
    def predict(self, image: np.ndarray) -> StrategyResult: ...


class PaddleOcrStrategy:  # pylint: disable=too-few-public-methods  # Single predict interface.
    def __init__(self, settings: Settings, name: str) -> None:
        from paddleocr import PaddleOCR

        detection, recognition = OCR_PRESETS[name]
        self._pipeline = PaddleOCR(
            text_detection_model_name=detection,
            text_recognition_model_name=recognition,
            device=settings.device,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

    def predict(self, image: np.ndarray) -> StrategyResult:
        results = list(self._pipeline.predict(image))
        if not results:
            raise RuntimeError("The OCR pipeline returned no result")
        payload = results[0].json
        raw = payload.get("res", payload)
        texts = raw.get("rec_texts", [])
        boxes = raw.get("rec_boxes", [])
        blocks = [
            {"label": "text", "bbox": np.asarray(box).tolist(), "content": str(text)}
            for text, box in zip(texts, boxes, strict=True)
            if str(text).strip()
        ]
        text = "\n".join(block["content"].strip() for block in blocks)
        return StrategyResult(text=text, markdown=text, blocks=blocks)


class PaddleVlStrategy:  # pylint: disable=too-few-public-methods  # Single predict interface.
    def __init__(self, settings: Settings) -> None:
        from paddleocr import PaddleOCRVL

        self._settings = settings
        self._pipeline = PaddleOCRVL(
            pipeline_version=settings.pipeline_version,
            device=settings.device,
            vl_rec_backend=settings.vl_backend,
            vl_rec_server_url=settings.vl_server_url,
            vl_rec_api_model_name=settings.vl_api_model_name,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_layout_detection=settings.use_layout_detection,
        )

    def predict(self, image: np.ndarray) -> StrategyResult:
        kwargs: dict[str, Any] = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_layout_detection": self._settings.use_layout_detection,
            "format_block_content": True,
        }
        if self._settings.max_new_tokens is not None:
            kwargs["max_new_tokens"] = self._settings.max_new_tokens
        # Consume lazy results under OcrEngine's lock, including serialization.
        results = list(self._pipeline.predict(image, **kwargs))
        if not results:
            raise RuntimeError("The OCR pipeline returned no result")
        result = results[0]
        markdown = str(result.markdown.get("markdown_texts", "")).strip()
        payload = result.json
        raw = payload.get("res", payload)
        blocks = [
            {
                "label": block.get("block_label", "unknown"),
                "bbox": np.asarray(block.get("block_bbox", [])).tolist(),
                "content": block.get("block_content", ""),
            }
            for block in raw.get("parsing_res_list", [])
            if isinstance(block, dict)
        ]
        text = "\n".join(
            str(block["content"]).strip() for block in blocks if str(block["content"]).strip()
        )
        return StrategyResult(text=text or markdown, markdown=markdown, blocks=blocks)


def create_strategy(settings: Settings, name: str) -> OcrStrategy:
    if name == "document":
        return PaddleVlStrategy(settings)
    return PaddleOcrStrategy(settings, name)
