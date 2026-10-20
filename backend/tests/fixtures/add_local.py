"""Add a real photo to the local accuracy fixtures (gitignored: they stay on this machine).

uv run python -m tests.fixtures.add_local debug-out/uploads/<upload> 2:08:14.0 [--name NAME]

The upload folder is one saved by `watchtiming-dev --save-uploads` (photo.jpg + request.json
with the tap). The time is what the hands show (12-hour, seconds with a decimal), read
carefully off the photo: the reference time isn't the truth, the watch's own error is what we
measure.
"""

import argparse
import json
import shutil
from pathlib import Path

LOCAL = Path(__file__).parent / "local"


def parse_time(text: str) -> tuple[int, int, float]:
    h, m, s = text.split(":")
    return int(h) % 12, int(m), float(s)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("upload", type=Path)
    parser.add_argument("time", help="what the hands show, H:MM:SS.s")
    parser.add_argument("--name", help="default: the upload folder's name")
    args = parser.parse_args()

    request = json.loads((args.upload / "request.json").read_text())
    h, m, s = parse_time(args.time)
    folder = LOCAL / (args.name or args.upload.name)
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.upload / "photo.jpg", folder / "photo.jpg")
    truth = {"tap": [request["tap_x"], request["tap_y"]], "hours": h, "minutes": m, "seconds": s}
    (folder / "truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    print(f"wrote {folder}")


if __name__ == "__main__":
    main()
