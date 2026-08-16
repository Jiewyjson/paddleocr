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

## Browser PDF crop OCR MVP

`web/` is an Astro + React + shadcn/ui frontend. It opens a PDF locally with
PDF.js, or a browser-decodable image with the Canvas API, and sends only a
user-selected JPEG crop for OCR. The original PDF/image is never included in
an API request and neither the frontend nor the FastAPI service writes it to
disk. The UI includes a Chinese/English language switch.

`backend/` contains a FastAPI process that accepts a raw image request body;
it deliberately does not use `UploadFile`/multipart parsing, which can spill
large uploads to a temporary file. The image is decoded in RAM, converted to a
NumPy array, and passed to the already configured PaddleOCR-VL MLX server. By
default the API asks MLX-VLM for the local
`~/.paddlex/official_models/PaddleOCR-VL-1.5` directory, rather than a remote
Hugging Face model name.

### Local development

The stack is three processes: MLX-VLM (`:8111`), the crop API (`:8788`), and
the Astro UI (`:4321`). `just` + `process-compose` start them in order, wait
for health checks, and can keep the inference pair running in the background.

Install the runners once:

```bash
brew install just
brew tap f1bonacc1/tap && brew install process-compose
```

Then from the repo root:

```bash
just dev      # foreground: MLX + API + UI (TUI, Ctrl-C stops everything)
just serve    # background: MLX + API only
just web      # UI only, against an already running API
just status
just logs
just attach   # TUI on a detached stack
just stop
```

`just serve` is the usual way to leave this Mac acting as the OCR host.
Open the UI later with `just web`, or use the production Pages site.

The first time you run `just dev` / `just serve`, missing `web/.env` is copied
from `web/.env.example`. That file points the browser at
`http://127.0.0.1:8788/v1/ocr`. In production it is intentionally unset, so
the browser calls the same-origin Pages Function at `/api/ocr` instead.

You can still start each process yourself. The MLX wrapper runs a single
Uvicorn worker without reload (the upstream module launcher enables reload):

```bash
./scripts/start_mlx_vlm_server.sh
bash scripts/start_ocr_api.sh
cd web && pnpm install && pnpm dev
```

### Cloudflare deployment boundary

Protect the Pages hostname with Cloudflare Access. The Pages Function at
`/api/ocr` is executed only after that browser check; it streams the crop to
the Mac API and adds a Cloudflare Access service token held as Pages secrets.
Protect the API hostname with its own Access application. A Tunnel running on
another LAN machine may route to this Mac's fixed LAN IP and port; use either
the Tunnel Dashboard configuration or the local `ingress` YAML (not both) as
described in `infra/cloudflared/config.yml.example` and the deployment guide.
When FastAPI is LAN-reachable, firewall TCP/8788 so only that tunnel host can
connect.

Set these Pages environment values/secrets:

| Name | Type | Value |
| --- | --- | --- |
| `OCR_API_ORIGIN` | plain variable | `https://ocr.<your-domain>` |
| `CF_ACCESS_CLIENT_ID` | encrypted secret | Access service token client ID |
| `CF_ACCESS_CLIENT_SECRET` | encrypted secret | Access service token client secret |

The service-token policy is only for Pages Function → API traffic. Browser
authorization remains the Pages Access policy. Do not expose either service
token value in `PUBLIC_*` variables.

See [the Cloudflare deployment guide](docs/deploy-cloudflare.md) for the exact
Pages, Access, service-token, and Tunnel setup order.

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
  --api-model-name ~/.paddlex/official_models/PaddleOCR-VL-1.5 \
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
