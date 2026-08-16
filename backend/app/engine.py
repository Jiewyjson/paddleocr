from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import Settings


@dataclass(frozen=True)
class OcrResult:
    text: str
    markdown: str
    blocks: list[dict[str, Any]]
    elapsed_ms: int


class OcrEngine:
    """A single, lazy PaddleOCR-VL pipeline.

    MLX-VLM inference is intentionally serialized. It keeps GPU memory predictable on
    the Mac and makes the API's behaviour clear for this small single-user MVP.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pipeline: Any | None = None
        self._prediction_lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._pipeline is not None

    async def infer(self, bgr_image: np.ndarray) -> OcrResult:
        return await asyncio.to_thread(self._infer_sync, bgr_image)

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        # Import lazily so /v1/healthz works immediately and so a missing model
        # produces a request error rather than preventing the API from starting.
        from paddleocr import PaddleOCRVL

        self._pipeline = PaddleOCRVL(
            pipeline_version=self._settings.pipeline_version,
            device=self._settings.device,
            vl_rec_backend=self._settings.vl_backend,
            vl_rec_server_url=self._settings.vl_server_url,
            vl_rec_api_model_name=self._settings.vl_api_model_name,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_layout_detection=self._settings.use_layout_detection,
        )
        return self._pipeline

    def _infer_sync(self, bgr_image: np.ndarray) -> OcrResult:
        started = time.perf_counter()

        with self._prediction_lock:
            pipeline = self._get_pipeline()
            predict_kwargs: dict[str, Any] = {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_layout_detection": self._settings.use_layout_detection,
                "format_block_content": True,
            }
            if self._settings.max_new_tokens is not None:
                predict_kwargs["max_new_tokens"] = self._settings.max_new_tokens
            results = pipeline.predict(bgr_image, **predict_kwargs)

        if not results:
            raise RuntimeError("The OCR pipeline returned no result")

        result = results[0]
        markdown_payload = result.markdown
        markdown = str(markdown_payload.get("markdown_texts", "")).strip()

        json_payload = result.json
        raw_result = json_payload.get("res", json_payload)
        raw_blocks = raw_result.get("parsing_res_list", [])
        blocks = [
            {
                "label": block.get("block_label", "unknown"),
                "bbox": block.get("block_bbox", []),
                "content": block.get("block_content", ""),
            }
            for block in raw_blocks
            if isinstance(block, dict)
        ]
        text = "\n".join(
            str(block["content"]).strip() for block in blocks if str(block["content"]).strip()
        ).strip()

        return OcrResult(
            text=text or markdown,
            markdown=markdown,
            blocks=blocks,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
        )
