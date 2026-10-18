"""Render every scenario to PNGs plus one labelled contact sheet, for looking at.

uv run python -m tests.synthetic.gallery [-o OUT_DIR]   # default: debug-out/synthetic/
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

from tests.synthetic.render import render
from tests.synthetic.scenarios import SCENARIOS

TILE = 300
COLUMNS = 6
LABEL_HEIGHT = 40


def _label(tile: np.ndarray, *lines: str) -> np.ndarray:
    band = np.full((LABEL_HEIGHT, TILE), 255, np.uint8)
    for i, line in enumerate(lines):
        cv2.putText(band, line, (6, 16 + i * 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 0, 1, cv2.LINE_AA)
    return np.vstack([band, tile])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-o", "--out", type=Path, default=Path("debug-out/synthetic"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    tiles = []
    for name, spec in SCENARIOS.items():
        dial = render(spec)
        cv2.imwrite(str(args.out / f"{name}.png"), dial.image)
        small = cv2.resize(dial.image, (TILE, TILE), interpolation=cv2.INTER_AREA)
        time = f"{spec.hours}:{spec.minutes:02d}:{spec.seconds:04.1f}"
        tiles.append(_label(small, name, time))

    blank = np.full_like(tiles[0], 255)
    tiles += [blank] * (-len(tiles) % COLUMNS)
    rows = [np.hstack(tiles[i : i + COLUMNS]) for i in range(0, len(tiles), COLUMNS)]
    sheet = args.out / "contact_sheet.png"
    cv2.imwrite(str(sheet), np.vstack(rows))
    print(f"wrote {len(SCENARIOS)} dials and {sheet}")


if __name__ == "__main__":
    main()
