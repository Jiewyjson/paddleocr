#!/usr/bin/env python3

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_SITE_PACKAGES = PROJECT_ROOT / ".venv" / "lib" / "python3.11" / "site-packages"


PATCHES = [
    {
        "path": VENV_SITE_PACKAGES
        / "paddlex"
        / "inference"
        / "models"
        / "doc_vlm"
        / "processors"
        / "paddleocr_vl"
        / "_paddleocr_vl.py",
        "needle": """        if not isinstance(text, list):\n            text = [text]\n\n        if image_grid_thw is not None:\n""",
        "replacement": """        if not isinstance(text, list):\n            text = [text]\n\n        def _to_python_int(value):\n            if isinstance(value, paddle.Tensor):\n                return int(value.numpy().reshape(-1)[0])\n            return int(value)\n\n        if image_grid_thw is not None:\n""",
    },
    {
        "path": VENV_SITE_PACKAGES
        / "paddlex"
        / "inference"
        / "models"
        / "doc_vlm"
        / "processors"
        / "paddleocr_vl"
        / "_paddleocr_vl.py",
        "needle": """                        * int(\n                            image_grid_thw[index].prod()\n                            // self.image_processor.merge_size\n                            // self.image_processor.merge_size\n                        ),\n""",
        "replacement": """                        * _to_python_int(\n                            image_grid_thw[index].prod()\n                            // self.image_processor.merge_size\n                            // self.image_processor.merge_size\n                        ),\n""",
    },
    {
        "path": VENV_SITE_PACKAGES
        / "paddlex"
        / "inference"
        / "models"
        / "doc_vlm"
        / "processors"
        / "paddleocr_vl"
        / "_paddleocr_vl.py",
        "needle": """                        * (\n                            video_grid_thw[index].prod()\n                            // self.image_processor.merge_size\n                            // self.image_processor.merge_size\n                        ),\n""",
        "replacement": """                        * _to_python_int(\n                            video_grid_thw[index].prod()\n                            // self.image_processor.merge_size\n                            // self.image_processor.merge_size\n                        ),\n""",
    },
    {
        "path": VENV_SITE_PACKAGES
        / "paddlex"
        / "inference"
        / "models"
        / "doc_vlm"
        / "modeling"
        / "paddleocr_vl"
        / "_projector.py",
        "needle": """import paddle\nimport paddle.nn as nn\n\n\nclass GELUActivation(nn.Layer):\n""",
        "replacement": """import paddle\nimport paddle.nn as nn\n\n\ndef _to_python_int(value):\n    if isinstance(value, paddle.Tensor):\n        return int(value.numpy().reshape(-1)[0])\n    return int(value)\n\n\nclass GELUActivation(nn.Layer):\n""",
    },
    {
        "path": VENV_SITE_PACKAGES
        / "paddlex"
        / "inference"
        / "models"
        / "doc_vlm"
        / "modeling"
        / "paddleocr_vl"
        / "_projector.py",
        "needle": """                    t=int(t),\n                    h=int(h // m1),\n                    p1=int(m1),\n                    w=int(w // m2),\n                    p2=int(m2),\n""",
        "replacement": """                    t=_to_python_int(t),\n                    h=_to_python_int(h // m1),\n                    p1=_to_python_int(m1),\n                    w=_to_python_int(w // m2),\n                    p2=_to_python_int(m2),\n""",
    },
]


def apply_patch(path: Path, needle: str, replacement: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return False
    if needle not in text:
        raise RuntimeError(f"Patch target not found in {path}")
    path.write_text(text.replace(needle, replacement), encoding="utf-8")
    return True


def main() -> int:
    changed = 0
    for patch in PATCHES:
        changed += int(apply_patch(patch["path"], patch["needle"], patch["replacement"]))
    print(f"Applied {changed} patch step(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
