#!/usr/bin/env python3

import argparse
import json
import sys
import time
from pathlib import Path

from paddleocr import PaddleOCRVL


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff", ".pdf"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run PaddleOCR-VL on all supported files in a directory."
    )
    parser.add_argument(
        "--sample-dir",
        default="samples",
        help="Directory containing test images or PDFs.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory used to store per-file results and a summary.json file.",
    )
    parser.add_argument(
        "--pipeline-version",
        default="v1.5",
        choices=["v1", "v1.5"],
        help="PaddleOCR-VL pipeline version.",
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help="Inference device, for example cpu or gpu:0.",
    )
    parser.add_argument(
        "--backend",
        default="native",
        choices=[
            "native",
            "vllm-server",
            "sglang-server",
            "fastdeploy-server",
            "mlx-vlm-server",
        ],
        help="VL backend used for recognition.",
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help="Server URL for non-native backends.",
    )
    parser.add_argument(
        "--api-model-name",
        default=None,
        help="Model name passed to the remote VL server backend.",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=None,
        help="Optional generation cap for the VL model.",
    )
    parser.add_argument(
        "--use-doc-orientation-classify",
        action="store_true",
        help="Enable document orientation classification.",
    )
    parser.add_argument(
        "--use-doc-unwarping",
        action="store_true",
        help="Enable document unwarping.",
    )
    parser.add_argument(
        "--disable-layout-detection",
        action="store_true",
        help="Disable layout detection for a comparison run.",
    )
    parser.add_argument(
        "--use-ocr-for-image-block",
        action="store_true",
        help="Run OCR on image blocks.",
    )
    parser.add_argument(
        "--format-block-content",
        action="store_true",
        help="Format output blocks into more readable Markdown.",
    )
    parser.add_argument(
        "--pattern",
        default="*",
        help="Optional glob pattern applied inside sample-dir before suffix filtering.",
    )
    return parser.parse_args()


def collect_inputs(sample_dir: Path, pattern: str):
    if not sample_dir.exists():
        raise FileNotFoundError(
            f"Sample directory does not exist: {sample_dir}. Put test files there first."
        )

    files = []
    for path in sorted(sample_dir.rglob(pattern)):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            files.append(path)
    return files


def build_pipeline(args):
    pipeline_kwargs = {
        "pipeline_version": args.pipeline_version,
        "device": args.device,
        "vl_rec_backend": args.backend,
        "use_doc_orientation_classify": args.use_doc_orientation_classify,
        "use_doc_unwarping": args.use_doc_unwarping,
    }
    if args.server_url:
        pipeline_kwargs["vl_rec_server_url"] = args.server_url
    if args.api_model_name:
        pipeline_kwargs["vl_rec_api_model_name"] = args.api_model_name
    return PaddleOCRVL(**pipeline_kwargs)


def build_predict_kwargs(args):
    predict_kwargs = {}
    if args.use_doc_orientation_classify:
        predict_kwargs["use_doc_orientation_classify"] = True
    if args.use_doc_unwarping:
        predict_kwargs["use_doc_unwarping"] = True
    if args.disable_layout_detection:
        predict_kwargs["use_layout_detection"] = False
    if args.use_ocr_for_image_block:
        predict_kwargs["use_ocr_for_image_block"] = True
    if args.format_block_content:
        predict_kwargs["format_block_content"] = True
    if args.max_new_tokens is not None:
        predict_kwargs["max_new_tokens"] = args.max_new_tokens
    return predict_kwargs


def main():
    args = parse_args()
    sample_dir = Path(args.sample_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = collect_inputs(sample_dir, args.pattern)
    if not inputs:
        print(
            f"No supported files found in {sample_dir}. "
            "Add images or PDFs under samples/ and rerun."
        )
        return 1

    print(f"Found {len(inputs)} input file(s) under {sample_dir}")
    print(f"Writing results to {output_dir}")

    pipeline = build_pipeline(args)
    predict_kwargs = build_predict_kwargs(args)
    summary = []

    for input_path in inputs:
        case_name = input_path.stem
        case_dir = output_dir / case_name
        case_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[{len(summary) + 1}/{len(inputs)}] Processing {input_path.name}")
        started = time.time()
        status = "ok"
        error = None

        try:
            results = pipeline.predict(str(input_path), **predict_kwargs)
            for idx, result in enumerate(results, start=1):
                page_dir = case_dir / f"page_{idx:03d}"
                page_dir.mkdir(parents=True, exist_ok=True)
                result.save_to_json(str(page_dir))
                result.save_to_markdown(str(page_dir))
        except Exception as exc:
            status = "error"
            error = str(exc)
            print(f"  failed: {exc}")

        elapsed = round(time.time() - started, 2)
        print(f"  status: {status} ({elapsed}s)")
        summary.append(
            {
                "input": str(input_path),
                "output_dir": str(case_dir),
                "status": status,
                "elapsed_seconds": elapsed,
                "error": error,
            }
        )

    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "pipeline_version": args.pipeline_version,
                "device": args.device,
                "backend": args.backend,
                "server_url": args.server_url,
                "api_model_name": args.api_model_name,
                "predict_kwargs": predict_kwargs,
                "files": summary,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nSaved summary to {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
