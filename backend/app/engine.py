from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import Settings
from .strategies import STRATEGY_NAMES, OcrStrategy, create_strategy


@dataclass(frozen=True)
class OcrResult:
    text: str
    markdown: str
    blocks: list[dict[str, Any]]
    elapsed_ms: int
    strategy: str = "document"


class OcrEngine:
    """Serialize inference and lazily cache a bounded number of strategy instances.

    Eviction drops API-side references; the independent MLX server owns its VL
    weights and is not unloaded here. Native runtimes may retain allocations.
    """

    def __init__(self, settings: Settings) -> None:
        if settings.default_strategy not in STRATEGY_NAMES:
            raise ValueError(f"Unknown OCR strategy: {settings.default_strategy}")
        if settings.strategy_cache_size <= 0:
            raise ValueError("strategy_cache_size must be greater than zero")
        self._settings = settings
        self._strategies: OrderedDict[str, OcrStrategy] = OrderedDict()
        self._prediction_lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return bool(self._strategies)

    async def infer(self, bgr_image: np.ndarray, strategy: str | None = None) -> OcrResult:
        name = self._settings.default_strategy if strategy is None else strategy
        if name not in STRATEGY_NAMES:
            raise ValueError(f"Unknown OCR strategy: {name}")
        return await asyncio.to_thread(self._infer_sync, bgr_image, name)

    def _get_strategy(self, name: str) -> OcrStrategy:
        if name in self._strategies:
            self._strategies.move_to_end(name)
            return self._strategies[name]
        # Evict before construction to avoid overlapping all old and new models.
        while len(self._strategies) >= self._settings.strategy_cache_size:
            self._strategies.popitem(last=False)
        strategy = create_strategy(self._settings, name)
        self._strategies[name] = strategy
        return strategy

    def _infer_sync(self, bgr_image: np.ndarray, name: str) -> OcrResult:
        started = time.perf_counter()
        with self._prediction_lock:
            result = self._get_strategy(name).predict(bgr_image)
        return OcrResult(
            text=result.text,
            markdown=result.markdown,
            blocks=result.blocks,
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            strategy=name,
        )
