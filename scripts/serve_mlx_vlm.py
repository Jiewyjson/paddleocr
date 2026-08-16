#!/usr/bin/env python3
"""Run mlx-vlm's FastAPI app without its development reloader."""

from __future__ import annotations

import argparse

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8111, type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    # mlx_vlm.server's own CLI enables reload=True. That is useful for package
    # development but creates a reloader parent process and adds latency here.
    uvicorn.run("mlx_vlm.server:app", host=args.host, port=args.port, reload=False, workers=1)


if __name__ == "__main__":
    main()
