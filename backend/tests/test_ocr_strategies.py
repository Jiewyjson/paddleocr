import asyncio
import io
import threading
import time
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.config import Settings
from backend.app.engine import OcrEngine
from backend.app.main import create_app
from backend.app.strategies import PaddleOcrStrategy, PaddleVlStrategy, StrategyResult


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings.from_env()
        self.image = np.zeros((32, 32, 3), dtype=np.uint8)

    def test_lazy_cache_reuse_and_lru_eviction(self):
        with patch('backend.app.engine.create_strategy') as factory:
            factory.side_effect = lambda settings, name: SimpleNamespace(
                predict=lambda image: StrategyResult(name, name, []))
            engine = OcrEngine(replace(self.settings, default_strategy='balanced'))
            self.assertFalse(engine.is_loaded)
            self.assertEqual(asyncio.run(engine.infer(self.image)).strategy, 'balanced')
            for name in ['fast', 'balanced', 'accurate', 'fast']:
                asyncio.run(engine.infer(self.image, name))
            self.assertEqual([c.args[1] for c in factory.call_args_list],
                             ['balanced', 'fast', 'accurate', 'fast'])
            self.assertEqual(len(engine._strategies), 2)

    def test_failed_initialization_can_retry(self):
        with patch('backend.app.engine.create_strategy') as factory:
            factory.side_effect = [RuntimeError('load failed'), SimpleNamespace(
                predict=lambda image: StrategyResult('', '', []))]
            engine = OcrEngine(self.settings)
            with self.assertRaises(RuntimeError):
                asyncio.run(engine.infer(self.image))
            self.assertFalse(engine.is_loaded)
            asyncio.run(engine.infer(self.image))
            self.assertTrue(engine.is_loaded)

    def test_concurrent_requests_are_serialized(self):
        active = 0
        peak = 0
        guard = threading.Lock()
        def predict(image):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with guard:
                active -= 1
            return StrategyResult('', '', [])
        with patch('backend.app.engine.create_strategy', return_value=SimpleNamespace(predict=predict)):
            engine = OcrEngine(self.settings)
            async def run():
                await asyncio.gather(*(engine.infer(self.image, n) for n in ['fast', 'balanced', 'document']))
            asyncio.run(run())
        self.assertEqual(peak, 1)

    def test_paddle_normalizes_numpy_boxes_and_empty_text(self):
        strategy = PaddleOcrStrategy.__new__(PaddleOcrStrategy)
        raw = {'res': {'rec_texts': ['中文', 'English'],
                       'rec_boxes': np.array([[1, 2, 10, 20], [2, 22, 30, 31]])}}
        strategy._pipeline = SimpleNamespace(predict=lambda image: iter([SimpleNamespace(json=raw)]))
        result = strategy.predict(self.image)
        self.assertEqual(result.text, '中文\nEnglish')
        self.assertEqual(result.blocks[0]['bbox'], [1, 2, 10, 20])
        raw['res'] = {'rec_texts': [], 'rec_boxes': []}
        self.assertEqual(strategy.predict(self.image).text, '')

    def test_vl_preserves_markdown_and_token_limit(self):
        strategy = PaddleVlStrategy.__new__(PaddleVlStrategy)
        strategy._settings = replace(self.settings, max_new_tokens=123)
        def predict(image, **kwargs):
            self.assertEqual(kwargs['max_new_tokens'], 123)
            yield SimpleNamespace(markdown={'markdown_texts': '| A |'},
                                  json={'res': {'parsing_res_list': []}})
        strategy._pipeline = SimpleNamespace(predict=predict)
        self.assertEqual(strategy.predict(self.image).text, '| A |')

    def test_api_selects_strategy_and_rejects_unknown_without_loading(self):
        payload = io.BytesIO()
        Image.new('RGB', (32, 32)).save(payload, format='PNG')
        with patch('backend.app.engine.create_strategy') as factory:
            factory.side_effect = lambda settings, name: SimpleNamespace(
                predict=lambda image: StrategyResult(name, name, []))
            with TestClient(create_app(self.settings)) as client:
                for name in ['fast', 'balanced', 'accurate', 'document']:
                    response = client.post('/v1/ocr?strategy=' + name, content=payload.getvalue(),
                                           headers={'Content-Type': 'image/png'})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()['strategy'], name)
                    self.assertEqual(response.json()['text'], name)
                count = factory.call_count
                for value in ['invalid', '']:
                    self.assertEqual(client.post('/v1/ocr?strategy=' + value).status_code, 422)
                self.assertEqual(factory.call_count, count)
                self.assertEqual(client.get('/v1/healthz').json()['model_loaded'], True)

    def test_invalid_defaults_fail_at_startup(self):
        for config in [replace(self.settings, default_strategy='typo'),
                       replace(self.settings, strategy_cache_size=0)]:
            with self.assertRaises(ValueError):
                OcrEngine(config)


if __name__ == '__main__':
    unittest.main()
