#!/usr/bin/env python3
"""
PP-ChatOCRv4 测试脚本
====================
测试 PP-ChatOCRv4-doc pipeline 的各步骤返回结构，以及自定义 prompt (key_list) 的理解能力。

支持三种运行模式：

  模式 A：千帆 API 一键模式（最简单，只需 qianfan_api_key）
    pipeline 自动用百度 ERNIE 处理所有 LLM 步骤（embedding + chat）。

  模式 B：自定义 OpenAI 兼容 LLM（如 Qwen/DashScope）
    分别配置 chat_bot 和 retriever。

  模式 C：仅本地 OCR（--skip-llm）
    只执行 visual_predict，不调用任何 LLM，用于查看 OCR + 布局分析结果。

Usage:

  # 模式 A：千帆 API（推荐先试这个）
  python test_chatocrv4.py \\
    --image samples/paddleocr_vl_demo.png \\
    --qianfan-api-key YOUR_QIANFAN_API_KEY \\
    --keys "驾驶室准乘人数"

  # 模式 B：Qwen/DashScope
  python test_chatocrv4.py \\
    --image samples/paddleocr_vl_demo.png \\
    --llm-api-key sk-xxx \\
    --llm-base-url https://dashscope.aliyuncs.com/compatible-mode/v1 \\
    --llm-model qwen-plus \\
    --keys "合同编号" "签订日期" "总金额"

  # 模式 C：仅本地 OCR
  python test_chatocrv4.py \\
    --image samples/paddleocr_vl_demo.png \\
    --skip-llm

  # 在以上任何模式加 MLLM（多模态大模型直接看图）
  --mllm-base-url http://127.0.0.1:8080/ --mllm-model PP-DocBee2

  # 使用 hf-mirror 加速模型下载（国内推荐）
  HF_ENDPOINT=https://hf-mirror.com python test_chatocrv4.py ...
"""

import argparse
import json
import sys
import time
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Test PP-ChatOCRv4-doc pipeline and inspect output structure.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--image", required=True, help="Input image or PDF path.")
    parser.add_argument(
        "--keys",
        nargs="+",
        default=["驾驶室准乘人数"],
        help="List of keys (fields) to extract. This is the custom prompt.",
    )
    parser.add_argument("--device", default="cpu", help="cpu, gpu:0, etc.")
    parser.add_argument(
        "--output-dir",
        default="output/chatocrv4_test",
        help="Directory to save structured results.",
    )

    # --- 模式 A：千帆一键 ---
    qf_group = parser.add_argument_group("Mode A: Qianfan API (simplest)")
    qf_group.add_argument(
        "--qianfan-api-key",
        default=None,
        help="Qianfan API Key. If provided, pipeline auto-configures ERNIE chat_bot + retriever.",
    )

    # --- 模式 B：自定义 OpenAI 兼容 LLM ---
    llm_group = parser.add_argument_group("Mode B: Custom OpenAI-compatible LLM")
    llm_group.add_argument("--llm-api-key", default=None, help="LLM API key.")
    llm_group.add_argument(
        "--llm-base-url",
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        help="LLM base URL.",
    )
    llm_group.add_argument("--llm-model", default="qwen-plus", help="LLM model name.")

    # --- MLLM（可选，任何模式都能加） ---
    mllm_group = parser.add_argument_group("MLLM (optional, for vision)")
    mllm_group.add_argument("--mllm-base-url", default=None, help="MLLM server URL.")
    mllm_group.add_argument("--mllm-model", default="PP-DocBee2", help="MLLM model.")
    mllm_group.add_argument("--mllm-api-key", default=None, help="MLLM API key.")

    # --- 控制 ---
    ctrl_group = parser.add_argument_group("Control")
    ctrl_group.add_argument(
        "--skip-llm", action="store_true", help="Only run visual_predict (local OCR)."
    )
    ctrl_group.add_argument(
        "--skip-mllm", action="store_true", help="Skip MLLM step."
    )
    return parser.parse_args()


def dump_json(obj, label: str, output_dir: Path | None = None):
    """Pretty-print and optionally save a result object."""
    print(f"\n{'='*70}")
    print(f" {label}")
    print(f"{'='*70}")

    if isinstance(obj, (dict, list)):
        text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    else:
        text = str(obj)

    # Truncate very long output for terminal readability
    if len(text) > 5000:
        print(text[:5000])
        print(f"\n  ... (truncated, total {len(text)} chars)")
    else:
        print(text)

    if output_dir:
        filename = label.lower().replace(" ", "_").replace("/", "_") + ".json"
        path = output_dir / filename
        path.write_text(text + "\n", encoding="utf-8")
        print(f"  → saved to {path}")


def run_mode_a_qianfan(args, image_path: Path, output_dir: Path):
    """模式 A：使用千帆 API Key 一键运行全流程。"""
    from paddleocr import PPChatOCRv4Doc

    print("\n" + "=" * 70)
    print(" MODE A: Qianfan API (automatic ERNIE chat + embedding)")
    print("=" * 70)

    # --- Build configs from qianfan_api_key ---
    # NOTE: qianfan_api_key is a CLI-only shortcut. In the Python API,
    # we must manually build retriever_config and chat_bot_config.
    qf_key = args.qianfan_api_key
    retriever_config = {
        "module_name": "retriever",
        "model_name": "embedding-v1",
        "base_url": "https://qianfan.baidubce.com/v2",
        "api_type": "qianfan",
        "api_key": qf_key,
    }
    chat_bot_config = {
        "module_name": "chat_bot",
        "model_name": "ernie-3.5-8k",
        "base_url": "https://qianfan.baidubce.com/v2",
        "api_type": "openai",
        "api_key": qf_key,
    }

    print("\n[1/3] Creating PPChatOCRv4Doc pipeline...")
    t0 = time.time()

    pipeline_kwargs = {
        "device": args.device,
        "retriever_config": retriever_config,
        "chat_bot_config": chat_bot_config,
    }
    if args.mllm_base_url and not args.skip_mllm:
        pipeline_kwargs["mllm_chat_bot_config"] = {
            "module_name": "chat_bot",
            "model_name": "PP-DocBee",
            "base_url": args.mllm_base_url,
            "api_type": "openai",
            "api_key": "fake_key",
        }
    pipeline = PPChatOCRv4Doc(**pipeline_kwargs)
    print(f"  Pipeline created in {time.time() - t0:.1f}s")

    # --- visual_predict ---
    print("\n[2/3] Running visual_predict (OCR + layout analysis)...")
    t0 = time.time()
    visual_predict_res = pipeline.visual_predict(
        input=str(image_path),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_common_ocr=True,
        use_seal_recognition=False,
        use_table_recognition=True,
    )

    visual_info_list = []
    for idx, res in enumerate(visual_predict_res):
        print(f"\n  Page {idx + 1} result keys: {list(res.keys())}")
        visual_info_list.append(res["visual_info"])
        inspect_visual_info(res, idx, output_dir)

    print(f"  visual_predict completed in {time.time() - t0:.1f}s")

    # --- build_vector + chat (all via qianfan) ---
    print(f"\n[3/3] Running build_vector + chat with keys={args.keys}...")
    t0 = time.time()
    try:
        vector_info = pipeline.build_vector(
            visual_info_list, flag_save_bytes_vector=True
        )
        print(f"  build_vector completed in {time.time() - t0:.1f}s")

        # mllm_pred if configured
        mllm_predict_info = None
        if args.mllm_base_url and not args.skip_mllm:
            print("  Running mllm_pred...")
            mllm_res = pipeline.mllm_pred(
                input=str(image_path), key_list=args.keys
            )
            mllm_predict_info = mllm_res.get("mllm_res")
            dump_json(mllm_res, "mllm_predict_result", output_dir)

        t1 = time.time()
        chat_result = pipeline.chat(
            key_list=args.keys,
            visual_info=visual_info_list,
            vector_info=vector_info,
            mllm_predict_info=mllm_predict_info,
        )
        print(f"  chat completed in {time.time() - t1:.1f}s")
        dump_json(chat_result, "chat_result (final extraction)", output_dir)
        print_extraction_results(chat_result)
    except Exception as exc:  # pylint: disable=broad-exception-caught  # Report failures and continue the batch/demo.
        print(f"  Error: {exc}")
        import traceback
        traceback.print_exc()


def run_mode_b_custom_llm(args, image_path: Path, output_dir: Path):
    """模式 B：使用自定义 OpenAI 兼容 LLM。"""
    from paddleocr import PPChatOCRv4Doc

    print("\n" + "=" * 70)
    print(f" MODE B: Custom LLM ({args.llm_model} @ {args.llm_base_url})")
    print("=" * 70)

    print("\n[1/5] Creating PPChatOCRv4Doc pipeline...")
    t0 = time.time()
    pipeline = PPChatOCRv4Doc(device=args.device)
    print(f"  Pipeline created in {time.time() - t0:.1f}s")

    # --- visual_predict ---
    print("\n[2/5] Running visual_predict...")
    t0 = time.time()
    visual_predict_res = pipeline.visual_predict(
        input=str(image_path),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_common_ocr=True,
        use_seal_recognition=False,
        use_table_recognition=True,
    )
    visual_info_list = []
    for idx, res in enumerate(visual_predict_res):
        visual_info_list.append(res["visual_info"])
        inspect_visual_info(res, idx, output_dir)
    print(f"  visual_predict completed in {time.time() - t0:.1f}s")

    # --- build_vector ---
    retriever_config = {
        "module_name": "retriever",
        "model_name": "text-embedding-v4",
        "base_url": args.llm_base_url,
        "api_type": "openai",
        "api_key": args.llm_api_key,
    }
    print("\n[3/5] Building vector index (RAG)...")
    t0 = time.time()
    vector_info = pipeline.build_vector(
        visual_info_list,
        flag_save_bytes_vector=True,
        retriever_config=retriever_config,
    )
    print(f"  build_vector completed in {time.time() - t0:.1f}s")

    # --- mllm_pred ---
    mllm_predict_info = None
    if args.mllm_base_url and not args.skip_mllm:
        mllm_chat_bot_config = {
            "module_name": "chat_bot",
            "model_name": args.mllm_model,
            "base_url": args.mllm_base_url,
            "api_type": "openai",
            "api_key": args.mllm_api_key or "not-needed",
        }
        print("\n[4/5] Running MLLM prediction...")
        t0 = time.time()
        mllm_res = pipeline.mllm_pred(
            input=str(image_path),
            key_list=args.keys,
            mllm_chat_bot_config=mllm_chat_bot_config,
        )
        mllm_predict_info = mllm_res.get("mllm_res")
        print(f"  mllm_pred completed in {time.time() - t0:.1f}s")
        dump_json(mllm_res, "mllm_predict_result", output_dir)
    else:
        print("\n[4/5] Skipping MLLM")

    # --- chat ---
    chat_bot_config = {
        "module_name": "chat_bot",
        "model_name": args.llm_model,
        "base_url": args.llm_base_url,
        "api_type": "openai",
        "api_key": args.llm_api_key,
    }
    print(f"\n[5/5] Running chat with keys={args.keys}...")
    t0 = time.time()
    try:
        chat_result = pipeline.chat(
            key_list=args.keys,
            visual_info=visual_info_list,
            vector_info=vector_info,
            mllm_predict_info=mllm_predict_info,
            chat_bot_config=chat_bot_config,
            retriever_config=retriever_config,
        )
        print(f"  chat completed in {time.time() - t0:.1f}s")
        dump_json(chat_result, "chat_result (final extraction)", output_dir)
        print_extraction_results(chat_result)
    except Exception as exc:  # pylint: disable=broad-exception-caught  # Report failures and continue the batch/demo.
        print(f"  Error: {exc}")
        import traceback
        traceback.print_exc()


def run_mode_c_local_only(args, image_path: Path, output_dir: Path):
    """模式 C：仅本地 OCR。"""
    from paddleocr import PPChatOCRv4Doc

    print("\n" + "=" * 70)
    print(" MODE C: Local OCR only (no LLM)")
    print("=" * 70)

    print("\n[1/2] Creating PPChatOCRv4Doc pipeline...")
    t0 = time.time()
    pipeline = PPChatOCRv4Doc(device=args.device)
    print(f"  Pipeline created in {time.time() - t0:.1f}s")

    print("\n[2/2] Running visual_predict...")
    t0 = time.time()
    visual_predict_res = pipeline.visual_predict(
        input=str(image_path),
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_common_ocr=True,
        use_seal_recognition=False,
        use_table_recognition=True,
    )
    for idx, res in enumerate(visual_predict_res):
        inspect_visual_info(res, idx, output_dir)
    print(f"\n  visual_predict completed in {time.time() - t0:.1f}s")
    print("\n  Done! Use --qianfan-api-key or --llm-api-key to test full pipeline.")


def inspect_visual_info(res: dict, page_idx: int, output_dir: Path):
    """Inspect and print the structure of a single page's visual result."""
    page_label = f"Page {page_idx + 1}"
    print(f"\n  --- {page_label} ---")
    print(f"  Result keys: {list(res.keys())}")

    vi = res.get("visual_info")
    if vi and isinstance(vi, dict):
        print(f"  visual_info keys: {list(vi.keys())}")
        for k, v in vi.items():
            if isinstance(v, list):
                desc = f"list[{len(v)}]"
                if v and isinstance(v[0], dict):
                    desc += f" first_item_keys={list(v[0].keys())}"
                print(f"    {k}: {desc}")
            elif isinstance(v, str) and len(v) > 200:
                print(f"    {k}: str(len={len(v)}) = {v[:80]}...")
            else:
                print(f"    {k}: {type(v).__name__} = {v}")
        dump_json(vi, f"{page_label} visual_info", output_dir)

    lr = res.get("layout_parsing_result")
    if lr:
        print(f"  layout_parsing_result keys: {list(lr.keys()) if isinstance(lr, dict) else type(lr)}")
        dump_json(lr, f"{page_label} layout_parsing_result", output_dir)


def print_extraction_results(chat_result):
    """Display the final extraction results prominently."""
    if isinstance(chat_result, dict) and "chat_res" in chat_result:
        print("\n" + "=" * 70)
        print(" ✅ EXTRACTION RESULTS")
        print("=" * 70)
        for key, value in chat_result["chat_res"].items():
            print(f"  {key}: {value}")
        print()


def main():
    args = parse_args()
    image_path = Path(args.image).expanduser().resolve()
    if not image_path.exists():
        print(f"Error: image not found: {image_path}")
        return 1

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Image:  {image_path}")
    print(f"Keys:   {args.keys}")
    print(f"Device: {args.device}")
    print(f"Output: {output_dir}")

    # --- Import check ---
    try:
        from paddleocr import PPChatOCRv4Doc  # pylint: disable=unused-import  # Verify this optional API is available.
    except ImportError:
        print('\nError: PPChatOCRv4Doc not found. Install: pip install "paddleocr[ie]"')
        return 1

    # --- Determine mode ---
    if args.skip_llm:
        run_mode_c_local_only(args, image_path, output_dir)
    elif args.qianfan_api_key:
        run_mode_a_qianfan(args, image_path, output_dir)
    elif args.llm_api_key:
        run_mode_b_custom_llm(args, image_path, output_dir)
    else:
        print(
            "\nNo LLM configured. Use one of:\n"
            "  --qianfan-api-key KEY   (Mode A: Baidu ERNIE, simplest)\n"
            "  --llm-api-key KEY       (Mode B: custom OpenAI-compatible LLM)\n"
            "  --skip-llm              (Mode C: local OCR only)\n"
        )
        return 1

    print(f"\nAll outputs saved to: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
