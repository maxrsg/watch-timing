"""Write the pipeline's intermediate images, to look at before changing any thresholds.

    uv run python -m watchtiming.debug <image> [-o OUT_DIR]

Images go to `debug-out/<image name>/` by default, numbered in pipeline order. As stages are
added (dial ellipse, rectification, polar unwrap, hand profiles), they add their images to
`debug_stages`.
"""

import argparse
import sys
from pathlib import Path

import cv2

from watchtiming.dial import GrayImage, preprocess
from watchtiming.imaging import InvalidImageError

Stage = tuple[str, GrayImage]


def debug_stages(data: bytes) -> tuple[list[Stage], list[str]]:
    """Run the pipeline on image bytes; return (named images, info lines). Pure."""
    pre = preprocess(data)
    height, width = pre.gray.shape
    info = [
        f"original (upright): {pre.original_size[0]}×{pre.original_size[1]}",
        f"preprocessed: {width}×{height}, scale {pre.scale:.4f}",
    ]
    return [("01_preprocessed", pre.gray)], info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path)
    parser.add_argument("-o", "--out", type=Path, help="default: debug-out/<image name>/")
    args = parser.parse_args(argv)

    try:
        stages, info = debug_stages(args.image.read_bytes())
    except (OSError, InvalidImageError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    out = args.out or Path("debug-out") / args.image.stem
    out.mkdir(parents=True, exist_ok=True)
    for line in info:
        print(line)
    for name, image in stages:
        path = out / f"{name}.png"
        if not cv2.imwrite(str(path), image):
            print(f"error: could not write {path}", file=sys.stderr)
            return 1
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
