# PaddleOCR-VL test harness

This directory contains a small local test setup for trying PaddleOCR-VL on a batch of sample images.

## Quick start

Activate the existing virtual environment:

```bash
cd /Users/wyjson/dev/paddleocr
source .venv/bin/activate
```

If you reinstall the environment and hit the PaddleOCR-VL scalar conversion error again, reapply the local compatibility patch:

```bash
python scripts/apply_paddleocr_vl_compat_patch.py
```

Put test images into `samples/`, then run:

```bash
python scripts/run_paddleocr_vl_batch.py
```

Or use the wrapper that reapplies the local compat patch automatically:

```bash
./scripts/run_paddleocr_vl.sh
```

Results are written under `output/`.

## Useful examples

Native backend:

```bash
python scripts/run_paddleocr_vl_batch.py \
  --sample-dir samples \
  --output-dir output/native \
  --device cpu
```

MLX-VLM server backend on Apple Silicon:

```bash
./scripts/start_mlx_vlm_server.sh
```

Then in another terminal:

```bash
python scripts/run_paddleocr_vl_batch.py \
  --sample-dir samples \
  --output-dir output/mlx \
  --backend mlx-vlm-server \
  --server-url http://127.0.0.1:8111/ \
  --api-model-name PaddlePaddle/PaddleOCR-VL-1.5 \
  --device cpu
```

Try a stronger document preprocessing setup:

```bash
python scripts/run_paddleocr_vl_batch.py \
  --use-doc-orientation-classify \
  --use-doc-unwarping \
  --format-block-content \
  --use-ocr-for-image-block
```
